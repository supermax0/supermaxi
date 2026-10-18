"""Real isolated drawer opening/closing, replay, variance and access checks."""
from uuid import uuid4

import pytest
from tests.test_finance_operations import finance, voucher, balance


def opening(f, actual=20_000_000, **extra):
    return f["call"]("cash_shift.open", {"treasury_account_id": f["cash"].id,
        "opening_actual": actual, "name": "وردية اختبار", **extra})


def detail(f, row):
    return f["get"](f"/api/finance/cash-shifts/{row['id']}").get_json()["data"]


def closing(f, row, actual, **extra):
    current = detail(f, row)
    return f["call"]("cash_shift.close", {"id": row["id"], "version": current["version"],
        "preview_token": current["preview"]["token"], "actual": actual, **extra})


def test_shift_counts_posted_movements_and_close_never_posts_money(finance):
    from models.journal_entry import JournalEntry
    from modules.finance.models import FinanceCashShift
    f = finance
    row = opening(f)
    payment = voucher(f, "expense", 100_000, party_name="كهرباء")
    current = detail(f, row)
    assert current["preview"]["expected"] == 19_900_000
    assert current["preview"]["net_movement"] == -100_000
    journals, cash = JournalEntry.query.count(), balance(f)
    result = closing(f, row, 19_900_000)
    assert result["status"] == "closed" and result["variance"] == 0
    assert result["closed_by"] == f["admin"].name
    assert balance(f) == cash and JournalEntry.query.count() == journals
    assert f["db"].session.get(FinanceCashShift, row["id"]).open_account_key is None
    f["call"]("voucher.reverse", {"id": payment["id"], "version": payment["version"], "reason": "تصحيح موثق"})
    frozen = detail(f, row)
    assert frozen["expected"] == 19_900_000 and frozen["actual"] == 19_900_000
    assert frozen["ledger_changed_since_close"] is True
    assert opening(f)["id"] != row["id"]


def test_shared_cash_aliases_cannot_open_two_shifts(finance):
    from models.treasury_account import TreasuryAccount
    from modules.finance.common import FinanceError
    f = finance
    opening(f)
    alias = TreasuryAccount(name="اسم صندوق قديم", account_type="cash", branch_id=f["branch"].id, is_active=True)
    f["db"].session.add(alias); f["db"].session.commit()
    with pytest.raises(FinanceError, match="وردية مفتوحة"):
        f["call"]("cash_shift.open", {"treasury_account_id": alias.id, "opening_actual": 20_000_000, "name": "مكررة"})


def test_print_retains_closing_evidence_after_later_transactions(finance):
    f = finance
    row = opening(f)
    closing(f, row, 19_999_500, reason="عجز عد")
    voucher(f, "expense", 1000, party_name="مصروف بعد الإغلاق")
    html = f["get"](f"/accounts/finance/cash-shifts/{row['id']}/print")
    assert "19,999,500" in html and "عجز عد" in html and "أرقام محفوظة" in html
    assert "20,000,000" in html and "تغيّرت مصادر" in html


def test_opening_and_closing_variances_are_separate_evidence(finance):
    from modules.finance.common import FinanceError
    f = finance
    with pytest.raises(FinanceError, match="الافتتاحي"):
        opening(f, 19_999_000)
    row = opening(f, 19_999_000, reason="عجز سابق تحت المراجعة")
    assert row["opening_variance"] == -1000
    voucher(f, "expense", 2000, party_name="نقل")
    with pytest.raises(FinanceError, match="سبب العجز"):
        closing(f, row, 19_996_500)
    result = closing(f, row, 19_996_500, reason="عجز عد الوردية")
    assert result["expected"] == 19_997_000 and result["variance"] == -500
    assert result["opening_variance"] == -1000
    assert balance(f) == 19_998_000


def test_retry_is_exactly_once_for_open_and_close(finance):
    from modules.finance.models import FinanceCashShift, FinanceAudit
    f = finance
    body = {"treasury_account_id": f["cash"].id, "opening_actual": 20_000_000, "name": "إعادة إرسال"}
    key = uuid4().hex
    row = f["call"]("cash_shift.open", body, key)
    assert row == f["call"]("cash_shift.open", body, key)
    assert FinanceCashShift.query.count() == 1
    current = detail(f, row)
    body = {"id": row["id"], "version": row["version"], "actual": 20_000_000,
        "preview_token": current["preview"]["token"]}
    key = uuid4().hex
    result = f["call"]("cash_shift.close", body, key)
    assert f["call"]("cash_shift.close", body, key) == result
    assert FinanceAudit.query.filter_by(source_type="cash_shift", action="close").count() == 1


def test_duplicate_open_bank_and_stale_preview_are_rejected(finance):
    from modules.finance.common import FinanceError
    f = finance
    with pytest.raises(FinanceError, match="الصندوق النقدي"):
        f["call"]("cash_shift.open", {"treasury_account_id": f["bank"].id, "opening_actual": 0, "name": "بنك"})
    row = opening(f)
    with pytest.raises(FinanceError, match="وردية مفتوحة"):
        opening(f)
    old = detail(f, row)
    voucher(f, "expense", 1000, party_name="نقل")
    with pytest.raises(FinanceError, match="تغيّرت حركات"):
        f["call"]("cash_shift.close", {"id": row["id"], "version": row["version"],
            "preview_token": old["preview"]["token"], "actual": 20_000_000})
    assert detail(f, row)["status"] == "open"
    closing(f, row, 19_999_000)
    with pytest.raises(FinanceError, match="تغيّر السجل"):
        f["call"]("cash_shift.close", {"id": row["id"], "version": 1, "actual": 19_999_000})


@pytest.mark.parametrize("amount", [-1, 1.5, True, "nan", "", None])
def test_invalid_count_cannot_create_shift(finance, amount):
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceCashShift
    with pytest.raises(FinanceError):
        opening(finance, amount)
    assert FinanceCashShift.query.count() == 0


def test_cash_shift_respects_branch_and_permission(finance):
    from flask import g, session
    from models.branch import Branch
    from models.employee import Employee
    from models.role import Role, Permission
    from modules.finance import cash_shifts
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceCashShift
    f = finance
    row = opening(f)
    other = Branch(code="OTHER", name="فرع آخر", is_active=True)
    f["db"].session.add(other); f["db"].session.flush()
    reader = Employee(name="قارئ", username=uuid4().hex, password="test", role="cashier", is_active=True, branch_id=other.id)
    role = Role(name=uuid4().hex)
    role.permissions.append(Permission.query.filter_by(name="finance.view").one())
    reader.roles.append(role)
    f["db"].session.add(reader); f["db"].session.commit()
    with f["app"].test_request_context("/api/finance/cash-shifts"):
        session.update(user_id=reader.id, employee_id=reader.id, role="cashier")
        g.branch = other; g.view_all_branches = False; g.branch_scope_ready = True
        assert cash_shifts.listing({})["items"] == []
        with pytest.raises(FinanceError) as failure:
            cash_shifts.details(row["id"])
        assert failure.value.status == 404
        with pytest.raises(FinanceError) as failure:
            cash_shifts.open_shift({"treasury_account_id": f["cash"].id, "opening_actual": 0, "name": "مرفوض"})
        assert failure.value.status == 403
    assert FinanceCashShift.query.count() == 1


def test_branch_mode_change_requires_review_before_close(finance):
    from flask import g, session
    from modules.finance import cash_shifts
    from modules.finance.common import FinanceError
    f = finance
    row = opening(f)
    with f["app"].test_request_context("/api/finance/cash-shifts"):
        session.update(user_id=f["admin"].id, employee_id=f["admin"].id, role="admin")
        g.branch = f["branch"]; g.view_all_branches = True; g.branch_scope_ready = True
        g.independent_branches_enabled = True
        with pytest.raises(FinanceError, match="تغيّر نمط الصندوق"):
            cash_shifts.details(row["id"])
    assert detail(f, row)["status"] == "open"


def test_bank_receipt_is_not_counted_as_drawer_cash(finance):
    f = finance
    row = opening(f)
    before = detail(f, row)["preview"]
    voucher(f, "capital", 50_000, treasury_account_id=f["bank"].id, party_name="تمويل البنك")
    after = detail(f, row)["preview"]
    assert balance(f, "bank") == 50_000 and balance(f) == 20_000_000
    assert after["token"] == before["token"] and after["expected"] == 20_000_000
    assert closing(f, row, 20_000_000)["variance"] == 0


def test_cached_response_cannot_bypass_new_branch_scope(finance):
    from flask import g, session
    from models.branch import Branch
    from modules.finance import routes
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceCashShift
    f = finance
    body = {"treasury_account_id": f["cash"].id, "opening_actual": 20_000_000, "name": "نطاق متغير"}
    key = uuid4().hex
    row = f["call"]("cash_shift.open", body, key)
    other = Branch(code="REPLAY", name="نطاق آخر", is_active=True)
    f["db"].session.add(other); f["db"].session.commit()
    with f["app"].test_request_context("/api/finance/commands", method="POST",
            json={**body, "operation": "cash_shift.open", "idempotency_key": key}):
        session.update(user_id=f["admin"].id, employee_id=f["admin"].id, role="admin")
        g.branch = other; g.view_all_branches = False; g.branch_scope_ready = True
        with pytest.raises(FinanceError) as failure:
            routes.commands()
        assert failure.value.status == 404
        f["db"].session.rollback()
    assert FinanceCashShift.query.execution_options(skip_branch_scope=True).count() == 1
    assert detail(f, row)["status"] == "open"
