"""Record delivery fees as expenses when invoices are paid."""

from __future__ import annotations

from datetime import datetime

from extensions import db
from models.account_transaction import AccountTransaction
from models.expense import Expense
from utils.order_shipping import get_shipping_fee_from_invoice

_DELIVERY_EXPENSE_NOTE_PREFIX = "delivery_fee_invoice:"


def delivery_expense_note(invoice_id: int) -> str:
    return f"{_DELIVERY_EXPENSE_NOTE_PREFIX}{invoice_id}"


def find_delivery_expense(invoice_id: int) -> Expense | None:
    note = delivery_expense_note(invoice_id)
    return Expense.query.filter_by(note=note).first()


def _find_delivery_withdraw_tx(invoice_id: int) -> AccountTransaction | None:
    marker = f"أجور توصيل — فاتورة #{invoice_id}"
    return (
        AccountTransaction.query.filter(
            AccountTransaction.type == "withdraw",
            AccountTransaction.note == marker,
        )
        .order_by(AccountTransaction.id.desc())
        .first()
    )


def remove_delivery_expense_for_invoice(invoice_id: int) -> None:
    expense = find_delivery_expense(invoice_id)
    if expense:
        db.session.delete(expense)
    withdraw_tx = _find_delivery_withdraw_tx(invoice_id)
    if withdraw_tx:
        db.session.delete(withdraw_tx)


def sync_delivery_expense_for_invoice(invoice) -> Expense | None:
    """Create/update or remove delivery expense based on invoice payment state."""
    if invoice is None:
        return None

    invoice_id = int(invoice.id)
    fee = get_shipping_fee_from_invoice(invoice)
    is_paid = (getattr(invoice, "payment_status", None) or "") == "مسدد"

    if not is_paid or fee <= 0:
        remove_delivery_expense_for_invoice(invoice_id)
        return None

    title = f"أجور توصيل — فاتورة #{invoice_id}"
    note = delivery_expense_note(invoice_id)
    expense = find_delivery_expense(invoice_id)
    if expense:
        expense.title = title
        expense.amount = fee
        expense.category = expense.category or "توصيل"
        expense.expense_date = expense.expense_date or datetime.utcnow().date()
    else:
        expense = Expense(
            title=title,
            category="توصيل",
            amount=fee,
            note=note,
            expense_date=datetime.utcnow().date(),
        )
        db.session.add(expense)
        db.session.flush()

        withdraw_tx = AccountTransaction(
            type="withdraw",
            amount=fee,
            note=title,
        )
        db.session.add(withdraw_tx)
    return expense
