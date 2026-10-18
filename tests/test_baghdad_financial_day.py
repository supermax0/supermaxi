"""UTC storage must be selected and grouped using Baghdad's accounting day."""
from datetime import date, datetime
from tests.test_finance_operations import finance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment
from tests.test_sales_return_posting import prepare, body, perform


def test_treasury_period_includes_local_midnight_and_excludes_next_midnight(finance):
    from models.account_transaction import AccountTransaction
    from utils.treasury_calculations import get_treasury_movements
    f = finance
    times = [datetime(2026, 7, 31, 20, 59, 59), datetime(2026, 7, 31, 21),
        datetime(2026, 8, 1, 20, 59, 59), datetime(2026, 8, 1, 21)]
    rows = [AccountTransaction(type="deposit", amount=amount, treasury_account_id=f["bank"].id,
        branch_id=f["branch"].id, created_at=when, note="اختبار حدود اليوم")
        for amount, when in zip([10, 20, 30, 40], times)]
    f["db"].session.add_all(rows)
    f["db"].session.commit()
    movements = get_treasury_movements(f["bank"].id, date(2026, 8, 1), date(2026, 8, 1))
    assert [row["amount"] for row in movements] == [20, 30]
    assert {row["date"] for row in movements} == {date(2026, 8, 1)}
    assert [row.created_at for row in rows] == times


def test_original_sale_and_return_on_same_utc_day_belong_to_different_baghdad_days(shipment):
    from modules.sales_returns.models import SalesReturn
    from modules.sales_returns.reporting import period_activity
    from utils.financial_report_data import get_financial_report_data
    f = shipment
    f["order"].created_at = datetime(2026, 7, 31, 20, 59, 59)
    f["db"].session.commit()
    prepare(f)
    posted = perform(f, body(f))
    # A controlled historical timestamp in this disposable fixture only.
    f["db"].session.execute(SalesReturn.__table__.update().where(SalesReturn.id == posted["id"]).values(
        created_at=datetime(2026, 7, 31, 21)))
    f["db"].session.commit()
    f["db"].session.expire_all()
    previous = period_activity(date(2026, 7, 31), date(2026, 7, 31))
    current = period_activity(date(2026, 8, 1), date(2026, 8, 1))
    assert sum(row.total for row in previous["invoices"]) == 800
    assert sum(row.total for row in current["invoices"]) == -400
    report = get_financial_report_data("custom", "2026-08-01", "2026-08-01")
    assert report["total_revenue"] == -400 and report["cogs_period"] == -100
    assert report["chart_series"][0]["label"] == "2026-08-01"
    assert report["return_documents"][0]["date"] == "2026-08-01"
