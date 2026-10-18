"""Regression tests for showing every open AGT report in the agent portal."""

from types import SimpleNamespace
from unittest.mock import patch


class _FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)

    def get(self, row_id):
        return next((row for row in self.rows if row.id == row_id), None)


class _FakeField:
    def is_(self, value):
        return self

    def like(self, value):
        return self

    def in_(self, value):
        return self

    def desc(self):
        return self


def _fake_model(rows, *field_names):
    attrs = {"query": _FakeQuery(rows)}
    attrs.update({name: _FakeField() for name in field_names})
    return SimpleNamespace(**attrs)


def _report(report_id, number, order_ids):
    return SimpleNamespace(
        id=report_id,
        report_number=number,
        is_executed=False,
        created_at=None,
        order_status_selections=None,
        orders_data="[]",
        order_ids=order_ids,
    )


def test_agent_portal_flattens_all_open_reports_with_report_metadata():
    from routes import delivery_agent as route

    reports = [
        _report(3, "AGT-1-20260801-0001", list(range(1, 11))),
        _report(2, "AGT-1-20260731-0001", list(range(11, 15))),
        _report(1, "AGT-1-20260729-0001", [15, 16]),
    ]
    invoices = [SimpleNamespace(id=order_id) for order_id in range(1, 17)]

    def serialize(order):
        return {
            "id": order.id,
            "remaining": 1000,
            "applied_status": None,
            "pending_accountant": False,
        }

    with (
        patch.object(route, "ShippingReport", _fake_model(reports, "is_executed", "report_number", "created_at", "id")),
        patch.object(route, "Invoice", _fake_model(invoices, "id")),
        patch.object(route, "get_report_order_ids", side_effect=lambda report: report.order_ids),
        patch.object(route, "_serialize_agent_order", side_effect=serialize),
        patch.object(route, "_agent_pending_orders", return_value=[]),
    ):
        orders = route._agent_active_report_orders(1)

    assert len(orders) == 16
    assert [order["report_id"] for order in orders[:10]] == [3] * 10
    assert [order["report_id"] for order in orders[10:14]] == [2] * 4
    assert [order["report_id"] for order in orders[14:]] == [1] * 2
    assert orders[0]["report_orders_count"] == 10
    assert orders[10]["report_orders_count"] == 4
    assert orders[14]["report_orders_count"] == 2


def test_agent_can_access_legacy_report_order_even_if_invoice_link_is_missing():
    from routes import delivery_agent as route

    report = _report(8, "AGT-1-20260731-0001", [101, 102])
    with (
        patch.object(route, "ShippingReport", _fake_model([report], "is_executed", "report_number", "id")),
        patch.object(route, "get_report_order_ids", return_value=[101, 102]),
    ):
        assert route._agent_open_report_for_order(1, 101, 8) is report
        assert route._agent_open_report_for_order(2, 101, 8) is None
        assert route._agent_open_report_for_order(1, 999, 8) is None
