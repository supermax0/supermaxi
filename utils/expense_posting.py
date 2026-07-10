"""Helpers for linking expense rows to treasury movements."""
from __future__ import annotations


def expense_withdraw_marker(expense_id: int) -> str:
    return f"[expense:{int(expense_id)}]"


def build_expense_withdraw_note(expense) -> str:
    note_extra = f" - {expense.note}" if getattr(expense, "note", None) else ""
    marker = expense_withdraw_marker(expense.id)
    return (
        f"مصروف: {expense.title} ({expense.category}) "
        f"بتاريخ {expense.expense_date} {marker}{note_extra}"
    )
