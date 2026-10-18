import json
from types import SimpleNamespace


def test_replacement_selection_finishes_paid_and_preserves_replacement_status(monkeypatch):
    import utils.shipping_report_execute as service

    order = SimpleNamespace(
        id=7,
        total=185000,
        paid_amount=0,
        status="استبدال",
        shipping_status="استبدال",
        payment_status="غير مسدد",
        shipping_company_id=None,
    )
    report = SimpleNamespace(
        id=1,
        report_number="WS-TEST",
        is_executed=False,
        order_status_selections=json.dumps({"7": "استبدال"}, ensure_ascii=False),
        orders_data=json.dumps([
            {"id": 7, "total": 185000, "partial_settlement": False}
        ]),
    )
    fake_session = SimpleNamespace(
        add=lambda _value: None,
        commit=lambda: None,
        rollback=lambda: None,
    )
    monkeypatch.setattr(service, "db", SimpleNamespace(session=fake_session))
    monkeypatch.setattr(
        service,
        "Invoice",
        SimpleNamespace(
            query=SimpleNamespace(
                get=lambda invoice_id: order if int(invoice_id) == 7 else None
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_effective_paid_amount_inv",
        lambda invoice: int(invoice.paid_amount or 0),
    )
    monkeypatch.setattr(service, "ensure_stock_for_transition", lambda *a, **k: True)
    monkeypatch.setattr(service, "append_payment_ledger_delta", lambda *a, **k: None)
    monkeypatch.setattr(service, "_invoice_payment_allocations", lambda *a, **k: [])

    def settle(invoice, **_kwargs):
        invoice.shipping_status = "تم التسديد"

    monkeypatch.setattr(service, "ensure_paid_shipping_order_settled", settle)
    monkeypatch.setattr(service, "sync_delivery_expense_for_invoice", lambda *a, **k: None)

    result = service.execute_shipping_report(report)

    assert result.get("success") is True, result
    assert result["replacement_count"] == 1
    assert order.total == 185000
    assert order.paid_amount == 185000
    assert order.payment_status == "مسدد"
    assert order.status == "استبدال"
    assert order.shipping_status == "استبدال"


def test_agent_report_delay_restores_to_each_items_original_branch(monkeypatch):
    import utils.shipping_report_execute as service
    import utils.agent_report_helpers as agent_helpers

    order = SimpleNamespace(
        id=664,
        total=169000,
        paid_amount=0,
        status="جاري الشحن",
        shipping_status="جاري الشحن",
        payment_status="غير مسدد",
        note=None,
    )
    report = SimpleNamespace(
        id=56,
        report_number="AGT-1-20260803-0001",
        is_executed=False,
        order_status_selections=json.dumps({"664": "مؤجل"}, ensure_ascii=False),
        orders_data=json.dumps([{"id": 664}], ensure_ascii=False),
    )
    fake_session = SimpleNamespace(
        add=lambda _value: None,
        commit=lambda: None,
        rollback=lambda: None,
    )
    monkeypatch.setattr(service, "db", SimpleNamespace(session=fake_session))
    monkeypatch.setattr(
        service,
        "Invoice",
        SimpleNamespace(
            query=SimpleNamespace(get=lambda invoice_id: order if int(invoice_id) == 664 else None)
        ),
    )
    monkeypatch.setattr(service, "_effective_paid_amount_inv", lambda _invoice: 0)
    monkeypatch.setattr(service, "append_payment_ledger_delta", lambda *a, **k: None)
    monkeypatch.setattr(service, "sync_delivery_expense_for_invoice", lambda *a, **k: None)
    monkeypatch.setattr(agent_helpers, "extract_agent_id_from_report", lambda _number: 1)
    monkeypatch.setattr(
        agent_helpers,
        "find_blocking_executed_agent_reports_for_order",
        lambda _order_id, _agent_id: [],
    )

    restore_destinations = []
    monkeypatch.setattr(
        service,
        "restore_order_stock_once",
        lambda _order, return_branch_id=None: restore_destinations.append(return_branch_id),
    )

    result = service.execute_shipping_report(report, return_branch_id=2)

    assert result.get("success") is True, result
    assert restore_destinations == [None]
    assert order.status == "تم الطلب"
