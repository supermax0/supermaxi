"""Measured net assets versus accounting, with real isolated finance services."""
from uuid import uuid4

import pytest
from utils.business_time import business_today
from tests.test_finance_operations import finance, voucher, balance, review_opening
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment, receipt, returned


def current(f):
    return f["get"]("/api/finance/control/current").get_json()["data"]


def measure(f, *, cash_difference=0, key=None, name="معاينة حقيقية"):
    data = current(f)
    counts = [{"id": row["treasury_account_id"], "actual": row["target"] + (cash_difference if row["treasury_type"] == "cash" else 0),
        "evidence": "عد يدوي / كشف مصرف اختبار"} for row in data["rows"] if "treasury_account_id" in row]
    return f["call"]("control.measure", {"name": name, "reason": "مطابقة المصادر والعد الفعلي", "treasury_counts": counts}, key)


def compare(f, start, end):
    return f["get"](f"/api/finance/control/compare?start={start['id']}&end={end['id']}").get_json()["data"]


def test_owner_funding_draws_and_expense_do_not_confuse_profit(finance):
    from models.journal_entry import JournalEntry
    f = finance
    review_opening(f)
    start = measure(f)
    voucher(f, "capital", 100_000, party_name="تمويل مالك")
    voucher(f, "owner_draw", 20_000, party_name="سحب مالك")
    voucher(f, "expense", 5000, party_name="مصروف الفترة")
    before_cash, before_journals = balance(f), JournalEntry.query.count()
    end = measure(f)
    result = compare(f, start, end)
    assert result["capital"] == 100_000 and result["owner_drawings"] == 20_000
    assert result["net_assets_change"] == 75_000
    assert result["accounting_profit"] == result["derived_profit"] == -5000
    assert result["difference"] == 0 and result["matched"] is True
    assert balance(f) == before_cash and JournalEntry.query.count() == before_journals


def test_physical_cash_gap_is_independent_of_balanced_journal(finance):
    f = finance
    review_opening(f)
    start = measure(f)
    end = measure(f, cash_difference=-500)
    result = compare(f, start, end)
    assert result["accounting_profit"] == 0
    assert result["derived_profit"] == -500 and result["difference"] == -500
    assert result["matched"] is False
    assert balance(f) == 20_000_000


def test_read_does_not_create_treasury_mapping_or_opening_entry(finance):
    from modules.finance.models import FinanceMapping
    from models.journal_entry import JournalEntry
    f = finance
    f["get"]("/api/finance/meta")
    before = FinanceMapping.query.count(), JournalEntry.query.count()
    result = current(f)
    assert (FinanceMapping.query.count(), JournalEntry.query.count()) == before
    assert any(row["current"] is None for row in result["rows"] if "treasury_account_id" in row)
    assert any(row["key"] == "opening" for row in result["coverage_issues"])


def test_measurement_is_retry_safe_and_requires_all_actual_counts(finance):
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceControlSnapshot
    f = finance
    with pytest.raises(FinanceError, match="كل صندوق"):
        f["call"]("control.measure", {"name": "ناقصة", "reason": "اختبار", "treasury_counts": []})
    key = uuid4().hex
    row = measure(f, key=key)
    assert measure(f, key=key) == row
    assert FinanceControlSnapshot.query.count() == 1


def test_changed_old_journal_prevents_false_historical_match(finance):
    from models.journal_entry import JournalEntry
    from modules.finance.common import FinanceError
    f = finance
    review_opening(f)
    start, end = measure(f), measure(f)
    entry = JournalEntry.query.order_by(JournalEntry.id).first()
    assert compare(f, start, end)["matched"] is True
    # Simulate an external database alteration, not an allowed application edit.
    from sqlalchemy import update
    f["db"].session.execute(update(JournalEntry).where(JournalEntry.id == entry.id).values(amount=JournalEntry.amount+1))
    f["db"].session.commit()
    with pytest.raises(FinanceError, match="تغيرت قيود"):
        compare(f, start, end)


def test_company_control_denies_selected_branch_and_cached_replay(finance):
    from flask import g, session
    from modules.finance import control
    from modules.finance.common import FinanceError
    f = finance
    key = uuid4().hex
    data = current(f)
    payload = {"name": "إعادة محاولة محفوظة", "reason": "حدود صلاحية الشركة",
        "treasury_counts": [{"id": row["treasury_account_id"], "actual": row["target"],
            "evidence": "دليل مستقل"} for row in data["rows"] if "treasury_account_id" in row]}
    f["call"]("control.measure", payload, key)
    with f["app"].test_request_context("/api/finance/control/current"):
        session.update(user_id=f["admin"].id, employee_id=f["admin"].id, role="admin")
        g.branch = f["branch"]; g.view_all_branches = False
        with pytest.raises(FinanceError) as failure:
            control.current()
        assert failure.value.status == 403
        from modules.finance.routes import action
        with pytest.raises(FinanceError) as failure:
            action("control.measure", {**payload, "idempotency_key": key})
        assert failure.value.status == 403


def test_accrued_expense_and_later_payment_keep_net_assets_equal_to_profit(finance):
    f = finance
    review_opening(f)
    start = measure(f)
    due = voucher(f, "expense_accrual", 10_000, party_name="مصروف مستحق")
    after_accrual = measure(f)
    result = compare(f, start, after_accrual)
    assert result["accounting_profit"] == result["derived_profit"] == -10_000
    assert result["matched"] is True
    voucher(f, "accrued_expense", 6000, party_name="دفع المستحق", expense_id=due["source_id"])
    after_payment = measure(f)
    result = compare(f, after_accrual, after_payment)
    assert result["derived_profit"] == result["accounting_profit"] == 0 and result["matched"] is True


def test_unchanged_cash_shortage_does_not_become_all_clear(finance):
    f = finance
    review_opening(f)
    result = compare(f, measure(f, cash_difference=-500), measure(f, cash_difference=-500))
    assert result["difference"] == 0 and result["matched"] is False
    assert any(issue["amount"] == -500 for issue in result["coverage_issues"])


def test_count_matching_ledger_does_not_hide_operational_source_gap(finance, monkeypatch):
    from modules.finance import control
    f = finance
    review_opening(f)
    start = measure(f)
    original = control.source_rows
    def changed_source():
        rows = original()
        cash = next(row for row in rows if row.get("treasury_type") == "cash")
        cash["target"] -= 500
        cash["difference"] -= 500
        return rows
    monkeypatch.setattr(control, "source_rows", changed_source)
    end = measure(f, cash_difference=500)
    result = compare(f, start, end)
    assert result["difference"] == 0 and result["matched"] is False
    assert any(issue["amount"] == -500 for issue in result["coverage_issues"])


def test_changed_account_classification_invalidates_saved_comparison(finance):
    from modules.finance import ledger
    from modules.finance.common import FinanceError
    f = finance
    review_opening(f)
    start, end = measure(f), measure(f)
    ledger.account("expense").account_type = "asset"
    f["db"].session.commit()
    with pytest.raises(FinanceError, match="تصنيف حساب"):
        compare(f, start, end)


def test_reversed_accrual_is_not_an_outstanding_liability(finance):
    f = finance
    review_opening(f)
    start = measure(f)
    due = voucher(f, "expense_accrual", 10_000, party_name="مصروف مستحق قابل للعكس")
    f["call"]("voucher.reverse", {"id": due["id"], "version": due["version"], "reason": "عكس إثبات خاطئ"})
    end = measure(f)
    result = compare(f, start, end)
    assert result["derived_profit"] == result["accounting_profit"] == 0
    assert result["matched"] is True


def test_loan_principal_and_accrued_interest_use_independent_liabilities(finance):
    f = finance
    review_opening(f)
    start = measure(f)
    loan = f["call"]("loan.create", {"direction": "borrowed", "party_name": "قرض للمطابقة",
        "principal": 1_000_000, "interest": 100_000, "upfront_fee": 25_000, "instalments": 2,
        "first_due": business_today().isoformat(), "treasury_account_id": f["cash"].id, "branch_id": f["branch"].id})
    loan = f["call"]("loan.fund", {"id": loan["id"], "version": loan["version"]})
    loan = f["call"]("loan.accrue", {"id": loan["id"], "version": loan["version"], "amount": 50_000, "notes": "فائدة مستحقة"})
    accrued = measure(f)
    result = compare(f, start, accrued)
    assert result["derived_profit"] == result["accounting_profit"] == -75_000 and result["matched"]
    f["call"]("loan.pay", {"id": loan["id"], "version": loan["version"], "amount": 550_000,
        "principal": 500_000, "interest": 50_000, "fees": 0})
    result = compare(f, accrued, measure(f))
    assert result["derived_profit"] == result["accounting_profit"] == 0 and result["matched"]


def test_real_fifo_sale_and_full_return_reconcile_wealth(shipment):
    f = shipment
    # Preserve the independent branch mode used by the real order controllers.
    f["get"] = lambda path: f["request"](path)
    def command(operation, values=None, key=None):
        response = f["request"]("/api/finance/commands", {"operation": operation,
            "idempotency_key": key or uuid4().hex, **(values or {})})
        assert response.status_code == 200, response.get_json()
        return response.get_json()["data"]
    f["call"] = command
    # The direct-controller fixture skips app.before_request. Initialize the
    # bank definitions for the newly added branch before reviewing openings.
    f["get"]("/api/finance/meta")
    review_opening(f)
    start = measure(f)
    assert receipt(f).status_code == 200
    paid = f["order_request"]("/orders/payment", {"id": f["order"].id, "payment": "مسدد",
        "payment_allocations": [{"treasury_account_id": f["cash"].id, "amount": 400},
            {"treasury_account_id": f["bank"].id, "amount": 400}]})
    assert paid.status_code == 200, paid.get_json()
    sold = measure(f)
    result = compare(f, start, sold)
    assert result["derived_profit"] == result["accounting_profit"] == 600 and result["matched"]
    assert returned(f).status_code == 200
    result = compare(f, sold, measure(f))
    assert result["derived_profit"] == result["accounting_profit"] == -600 and result["matched"]


def test_fixed_asset_purchase_and_real_depreciation_reconcile_without_cash_debt(finance):
    from models.fixed_asset import FixedAsset
    from utils.fixed_assets_service import post_monthly_depreciation
    f = finance
    review_opening(f)
    start = measure(f)
    categories = f["get"]("/api/finance/meta").get_json()["data"]["asset_categories"]
    voucher(f, "fixed_asset", 1_200_000, asset_name="أصل المطابقة",
        asset_category_id=categories[0]["id"], asset_months=12)
    asset = FixedAsset.query.filter_by(name="أصل المطابقة").one()
    purchased = measure(f)
    result = compare(f, start, purchased)
    assert result["derived_profit"] == result["accounting_profit"] == 0 and result["matched"]
    cash = balance(f)
    with f["app"].test_request_context():
        result = post_monthly_depreciation(asset.purchase_date.year, asset.purchase_date.month,
            user_id=f["admin"].id)
        f["db"].session.commit()
    assert result["total_amount"] == 100_000
    assert balance(f) == cash
    result = compare(f, purchased, measure(f))
    assert result["derived_profit"] == result["accounting_profit"] == -100_000 and result["matched"]
    assert next(row for row in current(f)["rows"] if row["key"] == "expense_payable")["target"] == 0


def test_repeated_bank_names_identify_the_branch_and_account_without_mutation(stock):
    from models.journal_entry import JournalEntry
    f = stock
    f["get"] = lambda path: f["request"](path)
    f["get"]("/api/finance/meta")
    before = JournalEntry.query.count()
    rows = [row for row in current(f)["rows"] if row.get("treasury_type") == "bank"]
    assert len(rows) == 2
    assert len({row["name"] for row in rows}) == 2
    assert all(f"#{row['treasury_account_id']}" in row["name"] for row in rows)
    assert JournalEntry.query.count() == before


def test_constant_duplicate_gl_source_cannot_certify_the_company_balance_sheet(finance, monkeypatch):
    from modules.finance import control
    f = finance
    review_opening(f)
    original = control.source_rows
    def duplicate_mapping():
        rows = original()
        cash = next(row for row in rows if row.get("treasury_type") == "cash")
        # The duplicated source points at the same GL, with no individual gap.
        rows.append({"key": "duplicate_asset", "name": "مصدر مكرر", "type": "asset",
            "target": cash["target"], "current": cash["current"], "difference": 0,
            "account_ids": cash["account_ids"]})
        return rows
    monkeypatch.setattr(control, "source_rows", duplicate_mapping)
    result = compare(f, measure(f), measure(f))
    assert result["difference"] == 0 and result["matched"] is False
    assert any(issue["key"] == "balance_sheet:assets" and issue["amount"] == 20_000_000
        for issue in result["coverage_issues"])
    # Older software stored the same totals without this diagnostic. Read-time
    # checks must protect those snapshots without rewriting their payloads.
    import json
    from modules.finance.models import FinanceControlSnapshot
    from modules.finance.common import dumps
    from sqlalchemy import update
    saved = FinanceControlSnapshot.query.order_by(FinanceControlSnapshot.id).all()
    for row in saved:
        data = json.loads(row.payload)
        data["coverage_issues"] = [issue for issue in data["coverage_issues"] if not issue["key"].startswith("balance_sheet:")]
        f["db"].session.execute(update(FinanceControlSnapshot).where(
            FinanceControlSnapshot.id == row.id).values(payload=dumps(data)))
    f["db"].session.commit()
    payloads = [row.payload for row in saved]
    legacy = compare(f, {"id": saved[0].id}, {"id": saved[1].id})
    assert legacy["matched"] is False
    assert control.serialize(saved[0])["coverage_issues_count"] == 1
    assert [row.payload for row in saved] == payloads


def test_unbalanced_ledger_is_not_certified_even_without_source_drift(finance, monkeypatch):
    from modules.finance import reports
    f = finance
    review_opening(f)
    original = reports.trial_balance
    def unbalanced(args):
        return {**original(args), "balanced": False}
    monkeypatch.setattr(reports, "trial_balance", unbalanced)
    result = compare(f, measure(f), measure(f))
    assert result["difference"] == 0 and result["matched"] is False
    assert any(issue["key"] == "balance_sheet:equation" for issue in result["coverage_issues"])


def test_saved_measurement_is_immutable_at_the_orm_boundary(finance):
    from modules.finance.models import FinanceControlSnapshot
    from modules.finance.common import FinanceError
    f = finance
    result = measure(f)
    row = f["db"].session.get(FinanceControlSnapshot, result["id"])
    original = row.payload
    row.payload = "{}"
    with pytest.raises(FinanceError) as failure:
        f["db"].session.commit()
    assert failure.value.code == "immutable_snapshot"
    f["db"].session.rollback()
    f["db"].session.delete(row)
    with pytest.raises(FinanceError):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert row.payload == original
