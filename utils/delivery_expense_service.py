"""Record delivery fees as expenses when invoices are paid."""

from __future__ import annotations

from datetime import datetime

from extensions import db
from models.account_transaction import AccountTransaction
from models.expense import Expense
from models.shipping_payment import ShippingPayment
from utils.order_shipping import get_shipping_fee_from_invoice

_DELIVERY_EXPENSE_NOTE_PREFIX = "delivery_fee_invoice:"
_COURIER_DELIVERY_EXPENSE_NOTE_PREFIX = "courier_delivery_fee:"


def delivery_expense_note(invoice_id: int) -> str:
    return f"{_DELIVERY_EXPENSE_NOTE_PREFIX}{invoice_id}"


def find_delivery_expense(invoice_id: int) -> Expense | None:
    note = delivery_expense_note(invoice_id)
    return Expense.query.filter_by(note=note).first()


def post_courier_delivery_fee(
    invoice_id: int,
    amount: int,
    reference: str,
    treasury_account_id: int | None = None,
) -> Expense | None:
    """Post a current courier fee without rewriting an older invoice fee.

    This is used for statement rows whose collection was already received in a
    previous payment.  The reference makes the posting idempotent when the same
    workspace analysis is retried.
    """
    fee = max(int(amount or 0), 0)
    if fee <= 0:
        return None

    marker = f"{_COURIER_DELIVERY_EXPENSE_NOTE_PREFIX}{reference}"
    title = f"أجور توصيل كشف النقل — فاتورة #{int(invoice_id)}"
    tx_note = f"مصروف: {title} [{marker}]"
    expense = Expense.query.filter_by(note=marker).first()
    withdraw_tx = (
        AccountTransaction.query.filter_by(type="withdraw", note=tx_note)
        .order_by(AccountTransaction.id.desc())
        .first()
    )

    if expense is None:
        expense = Expense(
            title=title,
            category="توصيل",
            amount=fee,
            note=marker,
            expense_date=datetime.utcnow().date(),
            cash_posted=True,
            treasury_account_id=treasury_account_id,
        )
        db.session.add(expense)
    else:
        expense.title = title
        expense.amount = fee
        expense.category = expense.category or "توصيل"
        expense.cash_posted = True
        expense.treasury_account_id = treasury_account_id

    if withdraw_tx is None:
        db.session.add(
            AccountTransaction(
                type="withdraw",
                amount=fee,
                note=tx_note,
                treasury_account_id=treasury_account_id,
            )
        )
    else:
        withdraw_tx.amount = fee
        withdraw_tx.treasury_account_id = treasury_account_id
    return expense


def _find_delivery_withdraw_tx(invoice_id: int) -> AccountTransaction | None:
    marker = f"أجور توصيل — فاتورة #{invoice_id}"
    legacy_marker = f"Ø£Ø¬ÙˆØ± ØªÙˆØµÙŠÙ„ â€” ÙØ§ØªÙˆØ±Ø© #{invoice_id}"
    return (
        AccountTransaction.query.filter(
            AccountTransaction.type == "withdraw",
            AccountTransaction.note.in_([marker, legacy_marker]),
        )
        .order_by(AccountTransaction.id.desc())
        .first()
    )


def _settlement_treasury_account_id(invoice_id: int) -> int | None:
    """Return the account that actually received the courier settlement."""
    payment = (
        ShippingPayment.query.filter_by(invoice_id=invoice_id, action="تسديد")
        .order_by(ShippingPayment.id.desc())
        .first()
    )
    return payment.treasury_account_id if payment else None


def remove_delivery_expense_for_invoice(invoice_id: int) -> None:
    expense = find_delivery_expense(invoice_id)
    if expense:
        db.session.delete(expense)
    withdraw_tx = _find_delivery_withdraw_tx(invoice_id)
    if withdraw_tx:
        db.session.delete(withdraw_tx)


def restore_missing_delivery_fee_withdrawals() -> dict[str, int]:
    """Recreate delivery-fee withdraw rows when their expense rows still exist."""
    expenses = Expense.query.filter(Expense.note.like(f"{_DELIVERY_EXPENSE_NOTE_PREFIX}%")).all()
    restored_count = 0
    restored_total = 0
    changed = False

    for expense in expenses:
        note = expense.note or ""
        raw_invoice_id = note.removeprefix(_DELIVERY_EXPENSE_NOTE_PREFIX)
        try:
            invoice_id = int(raw_invoice_id)
        except (TypeError, ValueError):
            continue

        fee = int(expense.amount or 0)
        if fee <= 0:
            continue

        title = f"أجور توصيل — فاتورة #{invoice_id}"
        if not expense.cash_posted:
            expense.cash_posted = True
            changed = True
        withdraw_tx = _find_delivery_withdraw_tx(invoice_id)
        if withdraw_tx:
            if int(withdraw_tx.amount or 0) != fee:
                withdraw_tx.amount = fee
                changed = True
            if withdraw_tx.note != title:
                withdraw_tx.note = title
                changed = True
            continue

        db.session.add(
            AccountTransaction(
                type="withdraw",
                amount=fee,
                note=title,
                treasury_account_id=expense.treasury_account_id,
            )
        )
        restored_count += 1
        restored_total += fee
        changed = True

    if changed:
        db.session.commit()
    else:
        db.session.flush()

    return {"count": restored_count, "total": restored_total}


def sync_delivery_expense_for_invoice(
    invoice,
    treasury_account_id: int | None = None,
    allow_partial: bool = False,
) -> Expense | None:
    """Create/update or remove delivery expense based on invoice payment state."""
    if invoice is None:
        return None

    invoice_id = int(invoice.id)
    fee = get_shipping_fee_from_invoice(invoice)
    payment_status = (getattr(invoice, "payment_status", None) or "")
    is_paid = payment_status == "مسدد" or (
        allow_partial and payment_status == "جزئي"
    )

    if not is_paid or fee <= 0:
        remove_delivery_expense_for_invoice(invoice_id)
        try:
            from utils.payroll_service import sync_commission_line_for_invoice

            sync_commission_line_for_invoice(invoice)
        except Exception:
            pass
        return None

    title = f"أجور توصيل — فاتورة #{invoice_id}"
    note = delivery_expense_note(invoice_id)
    expense = find_delivery_expense(invoice_id)
    withdraw_tx = _find_delivery_withdraw_tx(invoice_id)
    resolved_treasury_id = treasury_account_id
    if resolved_treasury_id is None:
        resolved_treasury_id = _settlement_treasury_account_id(invoice_id)
    if resolved_treasury_id is None and expense is not None:
        resolved_treasury_id = expense.treasury_account_id
    if resolved_treasury_id is None and withdraw_tx is not None:
        resolved_treasury_id = withdraw_tx.treasury_account_id

    if expense:
        expense.title = title
        expense.amount = fee
        expense.category = expense.category or "توصيل"
        expense.expense_date = expense.expense_date or datetime.utcnow().date()
        expense.cash_posted = True
        expense.treasury_account_id = resolved_treasury_id
    else:
        expense = Expense(
            title=title,
            category="توصيل",
            amount=fee,
            note=note,
            expense_date=datetime.utcnow().date(),
            cash_posted=True,
            treasury_account_id=resolved_treasury_id,
        )
        db.session.add(expense)
        db.session.flush()

    if withdraw_tx:
        withdraw_tx.amount = fee
        withdraw_tx.note = title
        withdraw_tx.treasury_account_id = resolved_treasury_id
    else:
        withdraw_tx = AccountTransaction(
            type="withdraw",
            amount=fee,
            note=title,
            treasury_account_id=resolved_treasury_id,
        )
        db.session.add(withdraw_tx)

    try:
        from utils.payroll_service import sync_commission_line_for_invoice

        sync_commission_line_for_invoice(invoice)
    except Exception:
        pass
    return expense
