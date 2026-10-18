"""A later return is attributed to its document date, not the old sale date."""
from datetime import datetime, timedelta
from tests.test_finance_operations import finance, balance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment
from tests.test_sales_return_posting import prepare, body, perform


def test_period_adjustments_restore_old_sale_and_deduct_on_return_date(shipment):
    from modules.sales_returns.reporting import period_adjustments
    from models.journal_entry import JournalEntry
    from utils.inventory_lots import current_lot_inventory_value
    from utils.financial_report_data import get_financial_report_data
    f = shipment
    from utils.payment_ledger import business_today
    today = business_today()
    yesterday = today - timedelta(days=1)
    f["order"].created_at = datetime.combine(yesterday, datetime.min.time())
    f["db"].session.commit()
    prepare(f)
    perform(f, body(f))
    before = balance(f), current_lot_inventory_value(), JournalEntry.query.count()
    old = period_adjustments(yesterday, yesterday)
    new = period_adjustments(today, today)
    whole = period_adjustments(yesterday, today)
    assert (old["revenue"], old["cogs"], old["settled"]) == (400, 100, 400)
    assert old["original_invoice_ids"] == {f["order"].id} and old["returns"] == []
    assert (new["revenue"], new["cogs"], new["settled"]) == (-400, -100, -400)
    assert new["returns"][0]["date"] == today
    assert (whole["revenue"], whole["cogs"], whole["settled"]) == (0, 0, 0)
    old_report = get_financial_report_data("custom", yesterday.isoformat(), yesterday.isoformat())
    new_report = get_financial_report_data("custom", today.isoformat(), today.isoformat())
    whole_report = get_financial_report_data("custom", yesterday.isoformat(), today.isoformat())
    assert (old_report["total_revenue"], old_report["cogs_period"], old_report["net_profit_period"]) == (800, 200, 600)
    assert (new_report["total_revenue"], new_report["cogs_period"], new_report["net_profit_period"]) == (-400, -100, -300)
    assert (whole_report["total_revenue"], whole_report["cogs_period"], whole_report["net_profit_period"]) == (400, 100, 300)
    assert old_report["invoices_count"] == 1 and new_report["invoices_count"] == 0
    assert new_report["return_documents_count"] == 1 and new_report["return_credit_period"] == 400
    assert whole_report["top_products"][0]["qty"] == 1 and whole_report["top_products"][0]["profit"] == 300
    assert whole_report["top_customers"][0]["total"] == 400
    assert whole_report["top_employees"][0]["profit"] == 300
    assert before == (balance(f), current_lot_inventory_value(), JournalEntry.query.count())
    perform(f, body(f))
    old = period_adjustments(yesterday, yesterday)
    assert (old["revenue"], old["cogs"]) == (800, 200)
    new = period_adjustments(today, today)
    assert (new["revenue"], new["cogs"]) == (-800, -200)
    old_report = get_financial_report_data("custom", yesterday.isoformat(), yesterday.isoformat())
    new_report = get_financial_report_data("custom", today.isoformat(), today.isoformat())
    assert old_report["total_revenue"] == 800 and old_report["cogs_period"] == 200
    assert new_report["total_revenue"] == -800 and new_report["cogs_period"] == -200
