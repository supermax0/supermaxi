"""Delivery portal date, amount, authorization and validation regressions."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask, session, g

from tests.test_delivery_agent_report_groups import _fake_model


def test_today_uses_baghdad_day_and_preserves_collectible_snapshot(monkeypatch):
    from routes import delivery_agent as route

    class Clock(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 10, 14, 22)

    def report(row, status="Delivered", executed=False):
        return SimpleNamespace(orders_data=json.dumps([row]), is_executed=executed,
                               order_status_selections=json.dumps({str(row["id"]): status}))

    rows = [
        report({"id": 1, "remaining": 1200, "agent_status_updated_at": "2026-10-14T21:30:00+00:00"}),
        report({"id": 2, "remaining": 900, "agent_status_updated_at": "2026-10-14T20:59:00Z", "executed_at": "2026-10-14T22:00:00Z"}, executed=True),
        report({"id": 3, "remaining": 2000, "executed_at": "2026-10-14T21:59:00Z"}, executed=True),
        report({"id": 4, "remaining": 5000}, executed=True),
        report({"id": 5, "remaining": 4000, "agent_status_updated_at": "2026-10-14T22:00:00Z"}, status="Canceled"),
    ]
    monkeypatch.setattr(route, "datetime", Clock)
    monkeypatch.setattr(route, "ShippingReport", _fake_model(rows, "report_number"))
    result = route._agent_delivery_summary(1)
    assert result == {"delivered_total": 3200, "delivered_count": 2, "awaiting_total": 1200, "undated_count": 1}


def test_execution_date_does_not_fall_back_to_creation(monkeypatch):
    from routes import delivery_agent as route
    reports = [SimpleNamespace(id=1, orders_data='[{"id": 7}]', order_status_selections='{"7":"Delivered"}',
                               created_at=datetime(2026, 10, 1), report_number="AGT-1-OLD")]
    monkeypatch.setattr(route, "ShippingReport", _fake_model(reports, "is_executed", "report_number", "created_at"))
    monkeypatch.setattr(route, "get_report_order_ids", lambda report: [7])
    assert route._build_executed_report_meta(1)[7]["executed_at"] == ""
    reports[0].orders_data = '[{"id":7,"executed_at":"2026-10-14T22:15:00Z"}]'
    assert route._build_executed_report_meta(1)[7]["executed_at"] == "2026-10-15 01:15"


def test_selection_records_utc_time_without_losing_row_fields(monkeypatch):
    import utils.agent_report_helpers as helper
    report = SimpleNamespace(orders_data='[{"id":7,"remaining":1200,"agent_note":"keep"}]', order_status_selections="{}")
    monkeypatch.setattr(helper, "sync_open_report_payment_amounts", lambda report: None)
    monkeypatch.setattr(helper, "get_report_progress", lambda report: {"all_complete": True})
    helper.save_selection_to_report(report, 7, "واصل")
    row = json.loads(report.orders_data)[0]
    assert row["remaining"] == 1200 and row["agent_note"] == "keep"
    assert datetime.fromisoformat(row["agent_status_updated_at"]).utcoffset().total_seconds() == 0
    assert json.loads(report.order_status_selections) == {"7": "Delivered"}
    # A retry of the same result must not move an earlier delivery into today.
    first_recorded = row["agent_status_updated_at"]
    helper.save_selection_to_report(report, 7, "واصل")
    assert json.loads(report.orders_data)[0]["agent_status_updated_at"] == first_recorded


@pytest.mark.parametrize("value", [None, "bad-date", "2020-01-01", "2026-02-30"])
def test_postponement_rejects_invalid_dates_before_touching_orders(monkeypatch, value):
    from routes import delivery_agent as route
    app = Flask(__name__)
    app.secret_key = "test-only"
    query = MagicMock()
    monkeypatch.setattr(route, "Invoice", SimpleNamespace(query=query))
    with app.test_request_context(json={"order_id": 7, "status": "مؤجل", "scheduled_date": value}):
        session["agent_id"] = 1
        response, status = route.update_order_status()
        assert status == 400 and response.get_json()["error"]
        query.get.assert_not_called()


@pytest.mark.parametrize("path,method,payload,allowed", [
    ("/messages/get/2", "GET", None, True),
    ("/messages/get/3", "GET", None, False),
    ("/messages/send", "POST", {"receiver_id":3,"content":"x"}, False),
    ("/messages/send", "POST", {"receiver_id":2,"content":"x"}, True),
    ("/messages/conversations", "GET", None, True),
    ("/messages/channels", "GET", None, False),
])
def test_agent_message_guard_enforces_admin_contacts(monkeypatch, path, method, payload, allowed):
    import routes.messages as messages
    import utils.agent_employee_link as link
    import importlib
    agent_module = importlib.import_module("models.delivery_agent")
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.register_blueprint(messages.messages_bp)
    monkeypatch.setattr(agent_module, "DeliveryAgent", SimpleNamespace(query=SimpleNamespace(get=lambda id: SimpleNamespace(id=id))))
    monkeypatch.setattr(link, "bind_agent_messaging_session", lambda *args: True)
    monkeypatch.setattr(messages, "_agent_chat_contacts", lambda: [SimpleNamespace(id=2)])
    monkeypatch.setattr(messages, "guard_permission", lambda *args, **kwargs: None)
    # Match an actual protected endpoint even when testing a forbidden route.
    with app.test_request_context(path, method=method, json=payload):
        session.update(agent_portal=True, agent_id=1, agent_tenant_slug="test", user_id=99)
        result = messages._messages_permission_guard()
        if allowed:
            assert result is None
            assert g.agent_chat_contact_ids == {2}
        else:
            assert result[1] == 403


def test_map_fallback_contains_city_and_rejects_script_urls():
    from routes.delivery_agent import _agent_map_url
    order = SimpleNamespace(customer=SimpleNamespace(city="بغداد", address="الدورة"), location_url="javascript:alert(1)")
    url = _agent_map_url(order)
    from urllib.parse import parse_qs, urlsplit
    assert url.startswith("https://www.google.com/maps/search/")
    assert parse_qs(urlsplit(url).query)["query"] == ["بغداد الدورة"]


def test_real_agent_update_execution_keeps_financial_snapshot_and_actual_time(monkeypatch):
    import os
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.delivery_agent import DeliveryAgent
    from models.invoice import Invoice
    from models.shipping_report import ShippingReport
    from routes import delivery_agent as route
    from utils.shipping_report_execute import execute_shipping_report

    tenant = f"test_delivery_portal_upgrade_{os.getpid()}"
    monkeypatch.setattr(route, "notify_agent_report_ready", lambda *args: True)
    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        agent = DeliveryAgent(name="Portal Test Agent")
        customer = Customer(name="Portal Test Customer", phone="07700000000")
        db.session.add_all([agent, customer])
        db.session.flush()
        invoice = Invoice(customer_id=customer.id, customer_name=customer.name,
                          delivery_agent_id=agent.id, total=365000, paid_amount=50000,
                          status="تم الطلب", payment_status="جزئي", note="keep delivery instructions")
        db.session.add(invoice)
        db.session.flush()
        report = ShippingReport(report_number=f"AGT-{agent.id}-PORTAL-TEST", shipping_company_name="Portal Test",
                                orders_data=json.dumps([{"id": invoice.id}]), orders_count=1,
                                is_executed=False, created_at=datetime(2020,1,1))
        db.session.add(report)
        from utils.payment_ledger import append_payment_ledger_delta
        append_payment_ledger_delta(invoice.id, 50000)
        db.session.commit()
        from utils.business_time import business_date
        with app.test_request_context(json={"order_id":invoice.id,"report_id":report.id,"status":"مؤجل", "scheduled_date":business_date(datetime.utcnow()).isoformat()}):
            g.tenant = tenant
            session["agent_id"] = agent.id
            assert route.update_order_status().get_json()["success"]
        assert invoice.note == "keep delivery instructions"
        with app.test_request_context(json={"order_id":invoice.id,"report_id":report.id,"status":"واصل"}):
            g.tenant = tenant
            session["agent_id"] = agent.id
            response = route.update_order_status().get_json()
        assert response["success"] is True
        assert response["stats"]["delivered_total"] == 315000
        assert response["stats"]["awaiting_total"] == 315000
        assert invoice.status == "تم الطلب"  # Accountant approval is still required.
        assert invoice.paid_amount == 50000
        assert invoice.scheduled_date is None
        assert invoice.note == "keep delivery instructions"
        result = execute_shipping_report(report)
        assert result.get("success"), result
        row = json.loads(report.orders_data)[0]
        assert row["remaining"] == 315000
        assert datetime.fromisoformat(row["executed_at"]).year != 2020
        assert row["agent_status_updated_at"]
        summary = route._agent_delivery_summary(agent.id)
        assert summary["delivered_total"] == 315000
        assert summary["awaiting_total"] == 0
        meta = route._build_executed_report_meta(agent.id)
        from utils.business_time import business_date
        assert meta[invoice.id]["executed_at"].startswith(str(business_date(datetime.utcnow())))
