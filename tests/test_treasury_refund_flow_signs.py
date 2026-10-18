"""Courier refunds are outgoing even when the legacy row keeps a negative amount."""
from datetime import datetime, timedelta
from tests.test_finance_operations import finance, balance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment, returned
from tests.test_sales_return_posting import prepare, context


def test_courier_refund_running_balance_and_statement_sign_match_actual_bank(shipment):
    from utils.treasury_calculations import get_treasury_movements
    from modules.finance.reconciliation import movements
    f = shipment
    prepare(f)
    assert returned(f).status_code == 200
    rows = get_treasury_movements(f["bank"].id)
    refund = next(row for row in rows if row["type"] == "cash_out")
    assert refund["amount"] == -400  # Existing display/API contract remains signed.
    assert refund["balance_after"] == balance(f, "bank") == 0
    statement = context(f, lambda: movements(f["bank"]))
    assert [row["amount"] for row in statement] == [400, -400]


def test_cash_and_financial_report_count_courier_refund_as_positive_outflow(shipment):
    from utils.cash_calculations import get_cash_summary
    from utils.financial_report_data import get_financial_report_data
    f = shipment
    prepare(f)
    assert returned(f).status_code == 200
    cash = context(f, get_cash_summary)
    assert cash["total_out"] == 400 and cash["current_balance"] == 20_000_000
    today = datetime.utcnow().date()
    report = context(f, lambda: get_financial_report_data("custom", (today-timedelta(days=1)).isoformat(), (today+timedelta(days=1)).isoformat()))
    assert report["cash_inflow"] == 20_000_800 and report["cash_outflow"] == 800
    assert report["net_cash_flow"] == 20_000_000
    from types import SimpleNamespace
    from utils.daily_closing_service import _cash_data
    from utils.daily_report_data import _cash_summary_for_day
    from utils.payment_ledger import business_today
    daily = SimpleNamespace(branch_id=f["branch"].id, opening_cash=0,
        adjustments=[], actual_closing_cash=None)
    closing = context(f, lambda: _cash_data(daily, datetime.min, datetime.max))
    assert closing["total_out"] == 400 and closing["expected"] == 20_000_000
    summary = context(f, lambda: _cash_summary_for_day(business_today()))
    assert summary["cash_out"] == 400 and summary["closing_balance"] == 20_000_000
    assert sum(row["amount"] for row in summary["cash_out_by_reason"]) == 400
