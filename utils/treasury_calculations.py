"""
Treasury balance calculations per account (cash + banks).
"""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import func, or_, and_

from extensions import db
from models.account_transaction import AccountTransaction
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.invoice import Invoice
from models.shipping_payment import ShippingPayment
from models.supplier_payment import SupplierPayment
from models.treasury_account import TreasuryAccount
from models.treasury_transfer import TreasuryTransfer
from utils.cash_calculations import (
    CANCELED_STATUSES,
    RETURN_STATUSES,
    _cash_affecting_note_filter,
    _effective_paid_amount,
)
from utils.treasury_helpers import account_matches_treasury, get_default_cash_account


SHIPPING_OPENING_COLLECTION_ACTIONS = (
    "\u0642\u0628\u0636",  # قبض
    "\u0627\u0633\u062a\u0644\u0627\u0645",  # استلام
)
SHIPPING_INVOICE_COLLECTION_ACTIONS = (
    "\u062a\u0633\u062f\u064a\u062f",  # تسديد
)


class InsufficientTreasuryBalance(Exception):
    def __init__(self, account_name: str, balance: int, amount: int):
        self.account_name = account_name
        self.balance = balance
        self.amount = amount
        super().__init__(
            f"رصيد {account_name} غير كافٍ. المتاح: {balance:,} د.ع والمطلوب: {amount:,} د.ع"
        )


def list_treasury_accounts(active_only: bool = True):
    from utils.treasury_schema_guard import ensure_treasury_schema

    ensure_treasury_schema()
    query = TreasuryAccount.query.order_by(
        TreasuryAccount.is_default.desc(),
        TreasuryAccount.account_type.asc(),
        TreasuryAccount.name.asc(),
    )
    if active_only:
        query = query.filter_by(is_active=True)
    return query.all()


def _sum_account_transactions(account_id: int, tx_type: str, default_cash_id: int) -> int:
    col = AccountTransaction.treasury_account_id
    match = account_matches_treasury(col, account_id, default_cash_id)
    value = (
        db.session.query(func.sum(AccountTransaction.amount))
        .filter(
            AccountTransaction.type == tx_type,
            match,
            _cash_affecting_note_filter(AccountTransaction.note),
        )
        .scalar()
        or 0
    )
    return int(value)


def _sum_withdrawals(account_id: int, default_cash_id: int) -> int:
    col = AccountTransaction.treasury_account_id
    match = account_matches_treasury(col, account_id, default_cash_id)
    value = (
        db.session.query(func.sum(AccountTransaction.amount))
        .filter(
            AccountTransaction.type == "withdraw",
            match,
            _cash_affecting_note_filter(AccountTransaction.note),
        )
        .scalar()
        or 0
    )
    return int(value)


def _cash_affecting_supplier_payment_filter():
    """
    دفعات المورد التي تؤثر على الصندوق فعلياً.
    تسوية «بيع للمورد» (offset) لا تخرج نقداً — تُخصم من حساب المورد فقط.
    """
    not_offset_method = or_(
        SupplierPayment.payment_method.is_(None),
        SupplierPayment.payment_method == "cash",
    )
    not_linked_sale = SupplierPayment.supplier_sale_id.is_(None)
    not_sale_note = or_(
        SupplierPayment.note.is_(None),
        ~SupplierPayment.note.like("%بيع للمورد%"),
    )
    return and_(not_offset_method, not_linked_sale, not_sale_note)


def _sum_supplier_payments(account_id: int, default_cash_id: int) -> int:
    col = SupplierPayment.treasury_account_id
    match = account_matches_treasury(col, account_id, default_cash_id)
    value = (
        db.session.query(func.sum(SupplierPayment.amount))
        .filter(match, _cash_affecting_supplier_payment_filter())
        .scalar()
        or 0
    )
    return int(value)


def _sum_shipping_collections(account_id: int, default_cash_id: int) -> int:
    col = ShippingPayment.treasury_account_id
    match = account_matches_treasury(col, account_id, default_cash_id)
    value = (
        db.session.query(func.sum(ShippingPayment.amount))
        .filter(
            or_(
                and_(
                    ShippingPayment.invoice_id.is_(None),
                    ShippingPayment.action.in_(SHIPPING_OPENING_COLLECTION_ACTIONS),
                ),
                and_(
                    ShippingPayment.invoice_id.isnot(None),
                    ShippingPayment.action.in_(SHIPPING_INVOICE_COLLECTION_ACTIONS),
                ),
            ),
            match,
        )
        .scalar()
        or 0
    )
    return int(value)


def _shipping_settled_invoice_ids() -> list[int]:
    rows = (
        db.session.query(ShippingPayment.invoice_id)
        .filter(
            ShippingPayment.invoice_id.isnot(None),
            ShippingPayment.action.in_(SHIPPING_INVOICE_COLLECTION_ACTIONS),
        )
        .distinct()
        .all()
    )
    return [int(row[0]) for row in rows if row[0] is not None]


def _paid_sales_for_default_cash() -> int:
    query = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(RETURN_STATUSES)),
        or_(
            Invoice.payment_status.in_(["مسدد", "جزئي"]),
            Invoice.status == "مسدد",
            and_(Invoice.payment_status.is_(None), Invoice.status == "تم التوصيل"),
        ),
    )
    shipping_invoice_ids = _shipping_settled_invoice_ids()
    if shipping_invoice_ids:
        query = query.filter(~Invoice.id.in_(shipping_invoice_ids))
    paid_invoices = query.all()
    return sum(_effective_paid_amount(inv) for inv in paid_invoices)


def calculate_treasury_balance(account_id: int | None = None) -> int:
    """Calculate balance for a treasury account."""
    default_cash = get_default_cash_account()
    if account_id is None:
        account_id = default_cash.id

    account = TreasuryAccount.query.get(account_id)
    if not account or not account.is_active:
        return 0

    balance = 0
    default_cash_id = default_cash.id

    if account.is_cash and account.is_default:
        balance += _paid_sales_for_default_cash()

    balance += _sum_account_transactions(account_id, "deposit", default_cash_id)
    balance -= _sum_withdrawals(account_id, default_cash_id)
    balance -= _sum_supplier_payments(account_id, default_cash_id)
    balance += _sum_shipping_collections(account_id, default_cash_id)

    return int(balance)


def calculate_total_liquidity() -> int:
    return sum(calculate_treasury_balance(acc.id) for acc in list_treasury_accounts())


def assert_sufficient_balance(account_id: int, amount: int) -> None:
    account = TreasuryAccount.query.get(account_id)
    if not account:
        raise InsufficientTreasuryBalance("الحساب", 0, amount)
    balance = calculate_treasury_balance(account_id)
    if balance < amount:
        raise InsufficientTreasuryBalance(account.name, balance, amount)


def record_treasury_transfer(
    from_account_id: int,
    to_account_id: int,
    amount: int,
    note: str | None = None,
) -> TreasuryTransfer:
    """Transfer funds between treasury accounts."""
    from models.account_transaction import AccountTransaction

    amount = int(amount)
    if amount <= 0:
        raise ValueError("مبلغ التحويل يجب أن يكون أكبر من صفر")
    if from_account_id == to_account_id:
        raise ValueError("لا يمكن التحويل لنفس الحساب")

    from_acc = TreasuryAccount.query.get(from_account_id)
    to_acc = TreasuryAccount.query.get(to_account_id)
    if not from_acc or not to_acc or not from_acc.is_active or not to_acc.is_active:
        raise ValueError("حساب التحويل غير صالح")

    assert_sufficient_balance(from_account_id, amount)

    transfer = TreasuryTransfer(
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        amount=amount,
        note=(note or "").strip() or None,
    )
    db.session.add(transfer)
    db.session.flush()

    extra = f" - {note}" if note else ""
    db.session.add(
        AccountTransaction(
            type="withdraw",
            amount=amount,
            note=f"تحويل → {to_acc.name}{extra}",
            treasury_account_id=from_account_id,
            treasury_transfer_id=transfer.id,
        )
    )
    db.session.add(
        AccountTransaction(
            type="deposit",
            amount=amount,
            note=f"تحويل ← {from_acc.name}{extra}",
            treasury_account_id=to_account_id,
            treasury_transfer_id=transfer.id,
        )
    )
    db.session.commit()
    return transfer


def get_treasury_movements(account_id: int | None = None):
    """Build movement ledger for one treasury account."""
    default_cash = get_default_cash_account()
    if account_id is None:
        account_id = default_cash.id

    account = TreasuryAccount.query.get(account_id)
    if not account:
        return []

    default_cash_id = default_cash.id
    movements = []
    current_balance = 0

    def _movement_datetime(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min)
        return datetime.combine(date.today(), time.min)

    if account.is_cash and account.is_default:
        shipping_invoice_ids = set(_shipping_settled_invoice_ids())
        ledger_query = (
            db.session.query(
                InvoicePaymentLedger.id,
                InvoicePaymentLedger.invoice_id,
                InvoicePaymentLedger.amount_delta,
                InvoicePaymentLedger.recorded_at,
                Invoice.customer_name,
            )
            .join(Invoice, Invoice.id == InvoicePaymentLedger.invoice_id)
            .filter(InvoicePaymentLedger.amount_delta != 0)
        )
        if shipping_invoice_ids:
            ledger_query = ledger_query.filter(~InvoicePaymentLedger.invoice_id.in_(shipping_invoice_ids))

        ledger_invoice_ids = set()
        for entry in ledger_query.order_by(InvoicePaymentLedger.recorded_at, InvoicePaymentLedger.id).all():
            amount_delta = int(entry.amount_delta or 0)
            if amount_delta == 0:
                continue
            ledger_invoice_ids.add(int(entry.invoice_id))
            movement_dt = _movement_datetime(entry.recorded_at)
            movement_type = "cash_in" if amount_delta > 0 else "cash_out"
            movement_amount = abs(amount_delta)
            reason = "بيع / تحصيل" if amount_delta > 0 else "تعديل تحصيل"
            current_balance += amount_delta
            movements.append(
                {
                    "date": movement_dt.date(),
                    "datetime": movement_dt,
                    "type": movement_type,
                    "type_ar": "قبض" if amount_delta > 0 else "صرف",
                    "reason": reason,
                    "amount": movement_amount,
                    "balance_after": current_balance,
                    "reference_type": "invoice_payment_ledger",
                    "reference_id": entry.id,
                    "description": (
                        f"{reason} - فاتورة #{entry.invoice_id} - "
                        f"{entry.customer_name or ''} - {movement_amount:,} د.ع"
                    ),
                }
            )

        invoice_query = (
            db.session.query(
                Invoice.id,
                Invoice.customer_name,
                Invoice.created_at,
                Invoice.status,
                Invoice.payment_status,
                Invoice.total,
                Invoice.paid_amount,
            ).filter(
                Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
                or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(RETURN_STATUSES)),
                or_(
                    Invoice.payment_status.in_(["مسدد", "جزئي"]),
                    Invoice.status == "مسدد",
                    and_(Invoice.payment_status.is_(None), Invoice.status == "تم التوصيل"),
                ),
            )
        )
        if shipping_invoice_ids:
            invoice_query = invoice_query.filter(~Invoice.id.in_(shipping_invoice_ids))
        if ledger_invoice_ids:
            invoice_query = invoice_query.filter(~Invoice.id.in_(ledger_invoice_ids))
        paid_invoices = invoice_query.order_by(Invoice.created_at).all()
        for invoice in paid_invoices:
            payment_amount = _effective_paid_amount(invoice)
            if payment_amount <= 0:
                continue
            movement_dt = _movement_datetime(invoice.created_at)
            current_balance += payment_amount
            movements.append(
                {
                    "date": movement_dt.date(),
                    "datetime": movement_dt,
                    "type": "cash_in",
                    "type_ar": "قبض",
                    "reason": "بيع / تحصيل",
                    "amount": payment_amount,
                    "balance_after": current_balance,
                    "reference_type": "invoice",
                    "reference_id": invoice.id,
                    "description": (
                        f"بيع / تحصيل - فاتورة #{invoice.id} - "
                        f"{invoice.customer_name} - {payment_amount:,} د.ع"
                    ),
                }
            )

    col = AccountTransaction.treasury_account_id
    match = account_matches_treasury(col, account_id, default_cash_id)
    deposits = (
        AccountTransaction.query.filter(
            AccountTransaction.type == "deposit",
            match,
            _cash_affecting_note_filter(AccountTransaction.note),
        )
        .order_by(AccountTransaction.created_at)
        .all()
    )
    for tx in deposits:
        movement_dt = _movement_datetime(tx.created_at)
        current_balance += tx.amount
        reason = "إيداع"
        if tx.note and tx.note.startswith("صندوق -"):
            reason = "قبض (صندوق)"
        elif tx.note and "إلغاء مصروف" in tx.note:
            reason = "استرجاع/إلغاء مصروف"
        elif tx.note and "تحويل ←" in tx.note:
            reason = "تحويل وارد"
        movements.append(
            {
                "date": movement_dt.date(),
                "datetime": movement_dt,
                "type": "cash_in",
                "type_ar": "قبض",
                "reason": reason,
                "amount": tx.amount,
                "balance_after": current_balance,
                "reference_type": "account_transaction",
                "reference_id": tx.id,
                "description": tx.note or f"إيداع - {tx.amount:,} د.ع",
            }
        )

    sp_col = SupplierPayment.treasury_account_id
    sp_match = account_matches_treasury(sp_col, account_id, default_cash_id)
    supplier_payments = (
        SupplierPayment.query.filter(sp_match, _cash_affecting_supplier_payment_filter())
        .order_by(SupplierPayment.created_at)
        .all()
    )
    for payment in supplier_payments:
        movement_dt = _movement_datetime(payment.created_at)
        current_balance -= payment.amount
        movements.append(
            {
                "date": movement_dt.date(),
                "datetime": movement_dt,
                "type": "cash_out",
                "type_ar": "صرف",
                "reason": "دفع مورد",
                "amount": payment.amount,
                "balance_after": current_balance,
                "reference_type": "supplier_payment",
                "reference_id": payment.id,
                "description": (
                    f"دفع مورد #{payment.supplier_id} - {payment.amount:,} د.ع - "
                    f"{payment.note or ''}"
                ),
            }
        )

    sh_col = ShippingPayment.treasury_account_id
    sh_match = account_matches_treasury(sh_col, account_id, default_cash_id)
    shipping_payments = (
        ShippingPayment.query.filter(
            or_(
                and_(
                    ShippingPayment.invoice_id.is_(None),
                    ShippingPayment.action.in_(SHIPPING_OPENING_COLLECTION_ACTIONS),
                ),
                and_(
                    ShippingPayment.invoice_id.isnot(None),
                    ShippingPayment.action.in_(SHIPPING_INVOICE_COLLECTION_ACTIONS),
                ),
            ),
            sh_match,
        )
        .order_by(ShippingPayment.created_at)
        .all()
    )
    for payment in shipping_payments:
        movement_dt = _movement_datetime(payment.created_at)
        current_balance += payment.amount
        movements.append(
            {
                "date": movement_dt.date(),
                "datetime": movement_dt,
                "type": "cash_in",
                "type_ar": "قبض",
                "reason": "قبض من شركة نقل",
                "amount": payment.amount,
                "balance_after": current_balance,
                "reference_type": "shipping_payment",
                "reference_id": payment.id,
                "description": (
                    f"قبض من شركة نقل #{payment.shipping_company_id} - "
                    f"{payment.amount:,} د.ع - {payment.note or ''}"
                ),
            }
        )

    withdrawals = (
        AccountTransaction.query.filter(
            AccountTransaction.type == "withdraw",
            match,
            _cash_affecting_note_filter(AccountTransaction.note),
        )
        .order_by(AccountTransaction.created_at)
        .all()
    )
    for tx in withdrawals:
        movement_dt = _movement_datetime(tx.created_at)
        current_balance -= tx.amount
        reason = "صرف"
        if tx.note:
            if "شراء أصل" in tx.note:
                reason = "شراء أصل"
            elif "صندوق - شراء نقدي" in tx.note or "شراء نقدي" in tx.note or "دفعة شراء" in tx.note:
                reason = "شراء"
            elif "مصروف" in tx.note:
                reason = "مصروف"
            elif "تحويل →" in tx.note:
                reason = "تحويل صادر"
            elif "سحب" in tx.note or "رأس مال" in tx.note:
                reason = "سحب مالك"
        else:
            reason = "سحب مالك"
        movements.append(
            {
                "date": movement_dt.date(),
                "datetime": movement_dt,
                "type": "cash_out",
                "type_ar": "صرف",
                "reason": reason,
                "amount": tx.amount,
                "balance_after": current_balance,
                "reference_type": "account_transaction",
                "reference_id": tx.id,
                "description": tx.note or f"صرف - {tx.amount:,} د.ع",
            }
        )

    movements.sort(key=lambda x: (x.get("datetime") or datetime.combine(x["date"], time.min), x.get("reference_type", ""), x.get("reference_id", 0)))
    running_balance = 0
    for movement in movements:
        amount = int(movement.get("amount") or 0)
        if movement.get("type") == "cash_in":
            running_balance += amount
        else:
            running_balance -= amount
        movement["balance_after"] = running_balance
    return movements
