"""Profit must retain Baghdad day boundaries and dated return evidence."""
from datetime import date, datetime, time, timedelta

import pytest

from tests.test_reports_v2 import ctx, TENANT  # noqa: F401
from tests.test_finance_operations import finance  # noqa: F401
from tests.test_desktop_stock_operations import stock  # noqa: F401
from tests.test_desktop_order_returns_shipping import shipment  # noqa: F401


def test_report_includes_baghdad_midnight_and_excludes_next_day(ctx):
    from flask import g
    from extensions import db
    from models.invoice import Invoice
    from services.reports_service import ReportFilters, sales_totals, sales_series, sales_breakdown

    day = date(2026, 10, 20)
    filters = ReportFilters("custom", day, day)
    with ctx["app"].app_context():
        g.tenant = TENANT
        invoice = db.session.get(Invoice, ctx["ids"]["credit_sale"])
        try:
            for stamp, expected in ((datetime(2026, 10, 19, 20, 59, 59), 0),
                                    (datetime(2026, 10, 19, 21), 300000),
                                    (datetime(2026, 10, 20, 20, 59, 59), 300000),
                                    (datetime(2026, 10, 20, 21), 0)):
                invoice.created_at = stamp
                db.session.flush()
                assert sales_totals(filters, day, day)["net"] == expected
                assert sales_series(filters, "day") == [{"key": day.isoformat(), "amount": expected}]
                assert sum(r["amount"] for r in sales_breakdown(filters, "day")) == expected
        finally:
            db.session.rollback()


@pytest.mark.parametrize("return_count", [1, 2])
def test_dated_returns_match_statement_rows_charts_and_scopes(shipment, monkeypatch, return_count):
    from tests.test_sales_return_posting import prepare, body, perform
    from services import reports_service as rs
    from utils.financial_report_data import get_financial_report_data
    from utils.payment_ledger import business_today

    monkeypatch.setattr(rs, "can_view", lambda section: True)
    f = shipment
    today = business_today()
    yesterday = today - timedelta(days=1)
    f["order"].created_at = datetime.combine(yesterday, time(9))
    f["db"].session.commit()
    prepare(f)
    for _ in range(return_count):
        perform(f, body(f))
    for start, end in ((yesterday, yesterday), (today, today), (yesterday, today)):
        filters = rs.ReportFilters("custom", start, end)
        statement = rs.profit_and_loss(filters, start, end)
        native = get_financial_report_data("custom", start.isoformat(), end.isoformat())
        assert (statement["net_revenue"], statement["cogs"], statement["net_profit"]) == (
            native["total_revenue"], native["cogs_period"], native["net_profit_period"])
        report = rs.sales_report(filters, 1, 100, "day")
        assert sum(row["total"] for row in report["rows"]) == statement["net_revenue"]
        assert all(row["id"] == f["order"].id for row in report["rows"])
        assert len({row["event_id"] for row in report["rows"]}) == len(report["rows"])
        assert sum(row["amount"] for row in rs.sales_series(filters, "day")) == statement["net_revenue"]
        for grouping in ("day", "week", "month", "employee", "branch", "customer", "payment", "product", "category"):
            assert sum(row["amount"] for row in rs.sales_breakdown(filters, grouping)) == statement["net_revenue"]
        products = rs.top_products(filters, start, end)
        assert sum(row["cogs"] for row in products) == statement["cogs"]
        assert sum(row["profit"] for row in rs.employees_table(filters)) == statement["gross_profit"]
        if statement["net_revenue"] <= 0:
            assert rs.profit_report(filters, "day")["margins"] == {"gross_margin_pct": None, "net_margin_pct": None}
    for scope in ({"branch_id": f["destination"].id}, {"employee_id": 999999}):
        filters = rs.ReportFilters("custom", yesterday, today, **scope)
        assert rs.sales_totals(filters, yesterday, today)["net"] == 0
        assert rs.cogs_total(filters, yesterday, today) == 0
        assert rs.returns_total(filters, yesterday, today)["amount"] == 0


def test_baghdad_expense_clock_and_default_report_day(monkeypatch):
    from routes import expenses
    from utils import business_time, date_periods

    class Clock(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 10, 20, 21, 30)

    monkeypatch.setattr(business_time, "datetime", Clock)
    assert business_time.business_now() == datetime(2026, 10, 21, 0, 30)
    assert date_periods.get_period_dates("today") == (date(2026, 10, 21), date(2026, 10, 21))
    assert expenses._is_expense_due(date(2026, 10, 20), time(22)) is True
    assert expenses._is_expense_due(date(2026, 10, 21), time(1)) is False


@pytest.mark.parametrize("stamp, expected", [
    (datetime(2026, 10, 19, 21), "2026-10-20 12:00 ص"),
    (datetime(2026, 10, 20, 9), "2026-10-20 12:00 م"),
    (datetime(2026, 10, 20, 16, 30), "2026-10-20 07:30 م"),
])
def test_exports_use_baghdad_arabic_12_hour_clock(stamp, expected):
    from utils.business_time import display_datetime
    from services.reports_export import _display_date
    assert display_datetime(stamp) == expected
    assert _display_date(stamp.isoformat()) == expected
    assert _display_date("2026-10-20") == "2026-10-20"
