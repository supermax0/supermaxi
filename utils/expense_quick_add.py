"""Shared quick expense creation (dashboard + settlements facade)."""
from __future__ import annotations

from datetime import date, datetime

from extensions import db
from models.account_transaction import AccountTransaction
from models.expense import Expense
from utils.branch_scope import resolve_write_branch_id
from utils.expense_categories import normalize_category_key
from utils.expense_posting import build_expense_withdraw_note
from utils.treasury_calculations import InsufficientTreasuryBalance, assert_sufficient_balance
from utils.treasury_helpers import resolve_treasury_account_id
from utils.treasury_schema_guard import ensure_treasury_schema


class ExpenseQuickAddError(Exception):
    def __init__(self, message: str, code: str = "expense_error"):
        self.message = message
        self.code = code
        super().__init__(message)


def create_quick_expense(data: dict | None = None, *, commit: bool = True) -> dict:
    """Create an expense and withdraw from treasury immediately.

    ``data`` keys: title, category, amount, note, expense_date, treasury_account_id, branch_id.
    """
    data = data or {}
    from flask import has_request_context

    # Prefer explicit branch for tests / internal callers; otherwise resolve in request.
    if data.get("branch_id") not in (None, "", 0, "0"):
        try:
            branch_id = int(data.get("branch_id"))
        except (TypeError, ValueError):
            branch_id = None
    elif has_request_context():
        branch_id = resolve_write_branch_id(data)
    else:
        branch_id = None

    title = str(data.get("title") or "").strip()
    category_raw = str(data.get("category") or "").strip()
    note = str(data.get("note") or "").strip()
    expense_date = data.get("expense_date")

    if not title:
        raise ExpenseQuickAddError("الرجاء إدخال عنوان المصروف")
    if not category_raw:
        raise ExpenseQuickAddError("الرجاء اختيار فئة المصروف")

    category = normalize_category_key(category_raw) or category_raw

    try:
        amount = int(float(data.get("amount")))
        if amount <= 0:
            raise ExpenseQuickAddError("المبلغ يجب أن يكون أكبر من صفر")
    except ExpenseQuickAddError:
        raise
    except (ValueError, TypeError):
        raise ExpenseQuickAddError("المبلغ غير صحيح")

    try:
        if expense_date:
            expense_date_obj = datetime.strptime(str(expense_date)[:10], "%Y-%m-%d").date()
        else:
            expense_date_obj = date.today()
    except ValueError:
        expense_date_obj = date.today()

    ensure_treasury_schema()
    treasury_account_id = resolve_treasury_account_id(data.get("treasury_account_id"))
    try:
        assert_sufficient_balance(treasury_account_id, amount)
    except InsufficientTreasuryBalance as exc:
        raise ExpenseQuickAddError(str(exc), "insufficient_balance") from exc

    try:
        expense = Expense(
            branch_id=branch_id,
            title=title,
            category=category,
            amount=amount,
            note=note,
            expense_date=expense_date_obj,
            treasury_account_id=treasury_account_id,
            cash_posted=False,
        )
        db.session.add(expense)
        db.session.flush()

        withdraw_tx = AccountTransaction(
            branch_id=branch_id,
            type="withdraw",
            amount=amount,
            note=build_expense_withdraw_note(expense),
            treasury_account_id=treasury_account_id,
        )
        db.session.add(withdraw_tx)
        expense.cash_posted = True

        if commit:
            db.session.commit()
    except ExpenseQuickAddError:
        raise
    except Exception:
        db.session.rollback()
        raise

    return {
        "kind": "expense",
        "id": int(expense.id),
        "amount": amount,
        "title": title,
        "category": category,
        "label": title,
        "detail_url": "/expenses",
        "message": "تم إضافة المصروف بنجاح",
        "subtype": "payroll" if str(note).startswith("payroll:") else None,
    }
