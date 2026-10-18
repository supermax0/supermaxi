"""
Treasury balance calculations per account (cash + banks).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time
import threading

from sqlalchemy import func, or_, and_, true

from extensions import db
from models.account_transaction import AccountTransaction
from models.delivery_agent import DeliveryAgent
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.invoice import Invoice
from models.shipping import ShippingCompany
from models.shipping_payment import ShippingPayment
from models.supplier_payment import SupplierPayment
from models.treasury_account import TreasuryAccount
from models.treasury_transfer import TreasuryTransfer
from utils.cash_movement_values import signed_movement_amount
from utils.business_time import business_date, utc_period_filter
from utils.cash_calculations import (
    CANCELED_STATUSES,
    RETURN_STATUSES,
    _cash_affecting_note_filter,
    _effective_paid_amount,
)
from utils.treasury_helpers import account_matches_treasury, get_default_cash_account


# SQLite does not support ``SELECT ... FOR UPDATE``.  The process lock closes
# the check-then-write gap there, while row locks protect PostgreSQL tenants.
_TREASURY_WRITE_LOCK = threading.RLock()


SHIPPING_OPENING_COLLECTION_ACTIONS = (
    "\u0642\u0628\u0636",  # قبض
    "\u0627\u0633\u062a\u0644\u0627\u0645",  # استلام
)
SHIPPING_INVOICE_COLLECTION_ACTIONS = (
    "\u062a\u0633\u062f\u064a\u062f",  # تسديد
    "عكس تسديد",  # signed refund of the original courier collection
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


def _sum_account_transactions(account_id: int, tx_type: str, default_cash_id: int, branch_id: int, include_unassigned: bool) -> int:
    col = AccountTransaction.treasury_account_id
    match = account_matches_treasury(
        col, account_id, default_cash_id,
        branch_column=AccountTransaction.branch_id,
        account_branch_id=branch_id,
        include_unassigned_branch=include_unassigned,
    )
    value = (
        db.session.query(func.sum(AccountTransaction.amount))
        .execution_options(skip_branch_scope=True)
        .filter(
            AccountTransaction.type == tx_type,
            match,
            _cash_affecting_note_filter(AccountTransaction.note),
        )
        .scalar()
        or 0
    )
    return int(value)


def _sum_withdrawals(account_id: int, default_cash_id: int, branch_id: int, include_unassigned: bool) -> int:
    col = AccountTransaction.treasury_account_id
    match = account_matches_treasury(
        col, account_id, default_cash_id,
        branch_column=AccountTransaction.branch_id,
        account_branch_id=branch_id,
        include_unassigned_branch=include_unassigned,
    )
    value = (
        db.session.query(func.sum(AccountTransaction.amount))
        .execution_options(skip_branch_scope=True)
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
        func.lower(SupplierPayment.payment_method).in_(
            ["cash", "bank", "card", "نقدي", "صندوق", "بنك", "بطاقة"]
        ),
    )
    not_linked_sale = SupplierPayment.supplier_sale_id.is_(None)
    not_sale_note = or_(
        SupplierPayment.note.is_(None),
        ~SupplierPayment.note.like("%بيع للمورد%"),
    )
    return and_(not_offset_method, not_linked_sale, not_sale_note)


def _sum_supplier_payments(account_id: int, default_cash_id: int, branch_id: int, include_unassigned: bool) -> int:
    col = SupplierPayment.treasury_account_id
    match = account_matches_treasury(
        col, account_id, default_cash_id,
        branch_column=SupplierPayment.branch_id,
        account_branch_id=branch_id,
        include_unassigned_branch=include_unassigned,
    )
    value = (
        db.session.query(func.sum(SupplierPayment.amount))
        .execution_options(skip_branch_scope=True)
        .filter(match, _cash_affecting_supplier_payment_filter())
        .scalar()
        or 0
    )
    return int(value)


def _sum_shipping_collections(account_id: int, default_cash_id: int, branch_id: int, include_unassigned: bool) -> int:
    col = ShippingPayment.treasury_account_id
    match = account_matches_treasury(
        col, account_id, default_cash_id,
        branch_column=ShippingPayment.branch_id,
        account_branch_id=branch_id,
        include_unassigned_branch=include_unassigned,
    )
    value = (
        db.session.query(func.sum(ShippingPayment.amount))
        .execution_options(skip_branch_scope=True)
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
        .execution_options(skip_branch_scope=True)
        .filter(
            ShippingPayment.invoice_id.isnot(None),
            ShippingPayment.action.in_(SHIPPING_INVOICE_COLLECTION_ACTIONS),
        )
        .distinct()
        .all()
    )
    return [int(row[0]) for row in rows if row[0] is not None]


def _paid_sales_for_account(
    account_id: int,
    default_cash_id: int,
    branch_id: int,
    include_unassigned: bool,
) -> int:
    """Collected invoice revenue assigned to one treasury account.

    Old invoices/ledger rows without an account remain assigned to the default
    cash account. New split-payment ledger rows are assigned explicitly.
    """
    from utils.branch_mode import independent_branches_enabled
    from modules.sales_returns.collections import for_treasury, saved_collections
    undated = saved_collections()
    baseline_ids = [row["invoice_id"] for row in undated]
    baseline_total = sum(row["amount"] for row in for_treasury(account_id, default_cash_id, undated))

    shipping_invoice_ids = _shipping_settled_invoice_ids()
    ledger_query = (
        db.session.query(InvoicePaymentLedger)
        .execution_options(skip_branch_scope=True)
        .filter(InvoicePaymentLedger.amount_delta != 0)
    )
    if shipping_invoice_ids:
        ledger_query = ledger_query.filter(
            ~InvoicePaymentLedger.invoice_id.in_(shipping_invoice_ids)
        )

    ledger_invoice_ids = {
        int(row[0])
        for row in ledger_query.with_entities(
            InvoicePaymentLedger.invoice_id
        ).distinct().all()
    }
    ledger_total = int(
        ledger_query.filter(
            or_(InvoicePaymentLedger.payment_method.is_(None), InvoicePaymentLedger.payment_method != "finance_offset"),
            account_matches_treasury(
                InvoicePaymentLedger.treasury_account_id,
                account_id,
                default_cash_id,
                branch_column=InvoicePaymentLedger.branch_id,
                account_branch_id=branch_id,
                include_unassigned_branch=include_unassigned,
            )
        ).with_entities(
            func.coalesce(func.sum(InvoicePaymentLedger.amount_delta), 0)
        ).scalar()
        or 0
    )

    ledger_total += baseline_total
    if account_id != default_cash_id:
        return ledger_total

    query = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).execution_options(skip_branch_scope=True).filter(
        (
            true()
            if not independent_branches_enabled()
            else or_(Invoice.branch_id == branch_id, and_(include_unassigned, Invoice.branch_id.is_(None)))
        ),
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(RETURN_STATUSES)),
        or_(
            Invoice.payment_status.in_(["مسدد", "جزئي"]),
            Invoice.status == "مسدد",
            and_(Invoice.payment_status.is_(None), Invoice.status == "تم التوصيل"),
        ),
    )
    if shipping_invoice_ids:
        query = query.filter(~Invoice.id.in_(shipping_invoice_ids))
    if ledger_invoice_ids:
        query = query.filter(~Invoice.id.in_(ledger_invoice_ids))
    if baseline_ids:
        query = query.filter(~Invoice.id.in_(baseline_ids))
    paid_invoices = query.all()
    return ledger_total + sum(_effective_paid_amount(inv) for inv in paid_invoices)


def calculate_treasury_balance(account_id: int | None = None) -> int:
    """Calculate balance for a treasury account."""
    if account_id is None:
        default_cash = get_default_cash_account()
        account_id = default_cash.id
    account = TreasuryAccount.query.get(account_id)
    if not account or not account.is_active:
        return 0
    from utils.branch_mode import independent_branches_enabled

    shared_mode = not independent_branches_enabled()
    default_cash = get_default_cash_account(None if shared_mode else account.branch_id)
    from utils.branch_migration import get_default_branch

    company_default = get_default_branch()
    include_unassigned = shared_mode or bool(
        company_default and int(company_default.id) == int(account.branch_id or 0)
    )

    balance = 0
    default_cash_id = default_cash.id

    account_branch_id = None if shared_mode else (int(account.branch_id) if account.branch_id else None)
    balance += _paid_sales_for_account(
        account_id, default_cash_id, account_branch_id, include_unassigned
    )

    balance += _sum_account_transactions(account_id, "deposit", default_cash_id, account_branch_id, include_unassigned)
    balance -= _sum_withdrawals(account_id, default_cash_id, account_branch_id, include_unassigned)
    balance -= _sum_supplier_payments(account_id, default_cash_id, account_branch_id, include_unassigned)
    balance += _sum_shipping_collections(account_id, default_cash_id, account_branch_id, include_unassigned)

    return int(balance)


def calculate_total_liquidity() -> int:
    accounts = list_treasury_accounts()
    from utils.branch_mode import independent_branches_enabled

    if not independent_branches_enabled():
        canonical = {}
        for account in accounts:
            key = ((account.account_type or "bank").strip().lower(), (account.name or "").strip().casefold())
            current = canonical.get(key)
            if current is None or (bool(account.is_default), -int(account.id)) > (
                bool(current.is_default), -int(current.id)
            ):
                canonical[key] = account
        accounts = list(canonical.values())
    return sum(calculate_treasury_balance(acc.id) for acc in accounts)


def assert_sufficient_balance(account_id: int, amount: int) -> None:
    account = TreasuryAccount.query.get(account_id)
    if not account:
        raise InsufficientTreasuryBalance("الحساب", 0, amount)
    balance = calculate_treasury_balance(account_id)
    if balance < amount:
        raise InsufficientTreasuryBalance(account.name, balance, amount)


@contextmanager
def _treasury_branch_scope(branch_id: int):
    """Temporarily calculate one account using its owning branch scope."""
    from flask import g, has_request_context

    if not has_request_context():
        yield
        return

    from models.branch import Branch

    branch = Branch.query.filter_by(id=int(branch_id), is_active=True).first()
    if not branch:
        raise ValueError("فرع حساب المصدر غير موجود أو غير نشط")

    missing = object()
    previous_branch = getattr(g, "branch", missing)
    previous_view_all = getattr(g, "view_all_branches", missing)
    g.branch = branch
    g.view_all_branches = False
    try:
        yield
    finally:
        if previous_branch is missing:
            g.pop("branch", None)
        else:
            g.branch = previous_branch
        if previous_view_all is missing:
            g.pop("view_all_branches", None)
        else:
            g.view_all_branches = previous_view_all


def record_treasury_transfer(
    from_account_id: int,
    to_account_id: int,
    amount: int,
    note: str | None = None,
    *,
    allow_cross_branch: bool = False,
) -> TreasuryTransfer:
    """Transfer funds between treasury accounts."""
    from models.account_transaction import AccountTransaction

    amount = int(amount)
    if amount <= 0:
        raise ValueError("مبلغ التحويل يجب أن يكون أكبر من صفر")
    if from_account_id == to_account_id:
        raise ValueError("لا يمكن التحويل لنفس الحساب")

    with _TREASURY_WRITE_LOCK:
        account_query = TreasuryAccount.query
        if allow_cross_branch:
            account_query = account_query.execution_options(skip_branch_scope=True)
        # Lock in deterministic order so opposite-direction transfers do not
        # deadlock on PostgreSQL.
        accounts = (
            account_query.filter(TreasuryAccount.id.in_([from_account_id, to_account_id]))
            .order_by(TreasuryAccount.id)
            .with_for_update()
            .all()
        )
        account_map = {int(account.id): account for account in accounts}
        from_acc = account_map.get(int(from_account_id))
        to_acc = account_map.get(int(to_account_id))
        if not from_acc or not to_acc or not from_acc.is_active or not to_acc.is_active:
            raise ValueError("حساب التحويل غير صالح")
        if not from_acc.branch_id or not to_acc.branch_id:
            raise ValueError("يجب ربط حسابات التحويل بفروعها أولاً")
        if not allow_cross_branch and int(from_acc.branch_id) != int(to_acc.branch_id):
            raise ValueError("لا يمكن التحويل بين حسابات فروع مختلفة")

        with _treasury_branch_scope(int(from_acc.branch_id)):
            assert_sufficient_balance(from_account_id, amount)

        transfer = TreasuryTransfer(
            branch_id=from_acc.branch_id,
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
                branch_id=from_acc.branch_id,
                type="withdraw",
                amount=amount,
                note=f"تحويل → {to_acc.name}{extra}",
                treasury_account_id=from_account_id,
                treasury_transfer_id=transfer.id,
            )
        )
        db.session.add(
            AccountTransaction(
                branch_id=to_acc.branch_id,
                type="deposit",
                amount=amount,
                note=f"تحويل ← {from_acc.name}{extra}",
                treasury_account_id=to_account_id,
                treasury_transfer_id=transfer.id,
            )
        )
        db.session.commit()
        return transfer


def get_treasury_movements(
    account_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Build movement ledger for one treasury account.

    ``date_from`` and ``date_to`` are optional inclusive filters.  Keeping the
    filtering in SQL is important for reports: a period report should not have
    to load the complete lifetime treasury ledger first.
    """
    if account_id is None:
        account_id = get_default_cash_account().id

    account = TreasuryAccount.query.get(account_id)
    if not account:
        return []

    default_cash = get_default_cash_account(account.branch_id)
    default_cash_id = default_cash.id
    from utils.branch_migration import get_default_branch

    company_default = get_default_branch()
    include_unassigned = bool(
        company_default and int(company_default.id) == int(account.branch_id or 0)
    )
    account_branch_id = int(account.branch_id or 0)
    movements = []
    current_balance = 0

    def _within_period(query, column):
        return query.filter(utc_period_filter(column, date_from, date_to))

    def _movement_datetime(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min)
        return datetime.combine(date.today(), time.min)

    shipping_invoice_ids = set(_shipping_settled_invoice_ids())
    ledger_query = (
        db.session.query(
            InvoicePaymentLedger.id,
            InvoicePaymentLedger.invoice_id,
            InvoicePaymentLedger.amount_delta,
            InvoicePaymentLedger.recorded_at,
            InvoicePaymentLedger.source_module,
            InvoicePaymentLedger.note,
            Invoice.customer_name,
            Invoice.delivery_agent_id,
            DeliveryAgent.name.label("delivery_agent_name"),
        )
        .execution_options(skip_branch_scope=True)
        .join(Invoice, Invoice.id == InvoicePaymentLedger.invoice_id)
        .outerjoin(DeliveryAgent, DeliveryAgent.id == Invoice.delivery_agent_id)
        .filter(
            InvoicePaymentLedger.amount_delta != 0,
            or_(InvoicePaymentLedger.payment_method.is_(None), InvoicePaymentLedger.payment_method != "finance_offset"),
            account_matches_treasury(
                InvoicePaymentLedger.treasury_account_id,
                account_id,
                default_cash_id,
                branch_column=InvoicePaymentLedger.branch_id,
                account_branch_id=account_branch_id,
                include_unassigned_branch=include_unassigned,
            ),
        )
    )
    if shipping_invoice_ids:
        ledger_query = ledger_query.filter(
            ~InvoicePaymentLedger.invoice_id.in_(shipping_invoice_ids)
        )
    ledger_query = _within_period(ledger_query, InvoicePaymentLedger.recorded_at)

    ledger_invoice_ids = {
        int(row[0])
        for row in db.session.query(InvoicePaymentLedger.invoice_id)
        .execution_options(skip_branch_scope=True)
        .distinct()
        .all()
    }
    for entry in ledger_query.order_by(
        InvoicePaymentLedger.recorded_at,
        InvoicePaymentLedger.id,
    ).all():
        amount_delta = int(entry.amount_delta or 0)
        if amount_delta == 0:
            continue
        movement_dt = _movement_datetime(entry.recorded_at)
        movement_type = "cash_in" if amount_delta > 0 else "cash_out"
        movement_amount = abs(amount_delta)
        agent_id = int(entry.delivery_agent_id) if entry.delivery_agent_id else None
        agent_name = (entry.delivery_agent_name or "").strip()
        source_module = (entry.source_module or "").strip()
        is_receipt = source_module.startswith("receipts:")
        receipt_id = None
        if is_receipt:
            try:
                receipt_id = int(source_module.split(":", 1)[1])
            except (TypeError, ValueError):
                receipt_id = None
        if is_receipt and amount_delta > 0:
            reason = "سند قبض"
        elif is_receipt:
            reason = "إلغاء سند قبض"
        elif amount_delta > 0:
            reason = "قبض من مندوب التوصيل" if agent_id else "بيع مباشر"
        else:
            reason = "تعديل تحصيل مندوب" if agent_id else "تعديل تحصيل"
        current_balance += amount_delta
        description = (
            f"{reason} - فاتورة #{entry.invoice_id} - "
            f"{entry.customer_name or ''} - {movement_amount:,} د.ع"
        )
        if is_receipt and entry.note:
            description = f"{entry.note} - فاتورة #{entry.invoice_id} - {entry.customer_name or ''}"
        if agent_name:
            description = (
                f"{reason} - المندوب {agent_name} - فاتورة #{entry.invoice_id} - "
                f"{entry.customer_name or ''} - {movement_amount:,} د.ع"
            )
        movements.append(
            {
                "date": business_date(movement_dt),
                "datetime": movement_dt,
                "type": movement_type,
                "type_ar": "قبض" if amount_delta > 0 else "صرف",
                "reason": reason,
                "amount": movement_amount,
                "balance_after": current_balance,
                "reference_type": "receipt" if receipt_id else "invoice_payment_ledger",
                "reference_id": receipt_id or entry.id,
                "movement_key": f"invoice_payment_ledger:{entry.id}",
                "invoice_id": entry.invoice_id,
                "delivery_agent_id": agent_id,
                "delivery_agent_name": agent_name,
                "shipping_company_id": None,
                "shipping_company_name": "",
                "description": description,
            }
        )

    if account.is_cash and account.is_default:
        from modules.sales_returns.collections import saved_collections
        undated_invoice_ids = [row["invoice_id"] for row in saved_collections()]
        invoice_query = (
            db.session.query(
                Invoice.id,
                Invoice.customer_name,
                Invoice.created_at,
                Invoice.status,
                Invoice.payment_status,
                Invoice.total,
                Invoice.paid_amount,
                Invoice.delivery_agent_id,
                DeliveryAgent.name.label("delivery_agent_name"),
            )
            .execution_options(skip_branch_scope=True)
            .outerjoin(DeliveryAgent, DeliveryAgent.id == Invoice.delivery_agent_id)
            .filter(
                Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
                or_(
                    Invoice.branch_id == account_branch_id,
                    and_(include_unassigned, Invoice.branch_id.is_(None)),
                ),
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
        if undated_invoice_ids:
            invoice_query = invoice_query.filter(~Invoice.id.in_(undated_invoice_ids))
        invoice_query = _within_period(invoice_query, Invoice.created_at)
        paid_invoices = invoice_query.order_by(Invoice.created_at).all()
        for invoice in paid_invoices:
            payment_amount = _effective_paid_amount(invoice)
            if payment_amount <= 0:
                continue
            movement_dt = _movement_datetime(invoice.created_at)
            agent_id = int(invoice.delivery_agent_id) if invoice.delivery_agent_id else None
            agent_name = (invoice.delivery_agent_name or "").strip()
            reason = "قبض من مندوب التوصيل" if agent_id else "بيع مباشر"
            current_balance += payment_amount
            description = (
                f"{reason} - فاتورة #{invoice.id} - "
                f"{invoice.customer_name} - {payment_amount:,} د.ع"
            )
            if agent_name:
                description = (
                    f"{reason} - المندوب {agent_name} - فاتورة #{invoice.id} - "
                    f"{invoice.customer_name} - {payment_amount:,} د.ع"
                )
            movements.append(
                {
                    "date": business_date(movement_dt),
                    "datetime": movement_dt,
                    "type": "cash_in",
                    "type_ar": "قبض",
                    "reason": reason,
                    "amount": payment_amount,
                    "balance_after": current_balance,
                    "reference_type": "invoice",
                    "reference_id": invoice.id,
                    "invoice_id": invoice.id,
                    "delivery_agent_id": agent_id,
                    "delivery_agent_name": agent_name,
                    "shipping_company_id": None,
                    "shipping_company_name": "",
                    "description": description,
                }
            )

    col = AccountTransaction.treasury_account_id
    match = account_matches_treasury(
        col,
        account_id,
        default_cash_id,
        branch_column=AccountTransaction.branch_id,
        account_branch_id=account_branch_id,
        include_unassigned_branch=include_unassigned,
    )
    deposits_query = AccountTransaction.query.execution_options(skip_branch_scope=True).filter(
            AccountTransaction.type == "deposit",
            match,
            _cash_affecting_note_filter(AccountTransaction.note),
    )
    deposits = _within_period(deposits_query, AccountTransaction.created_at).order_by(
        AccountTransaction.created_at
    ).all()
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
                "date": business_date(movement_dt),
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
    sp_match = account_matches_treasury(
        sp_col,
        account_id,
        default_cash_id,
        branch_column=SupplierPayment.branch_id,
        account_branch_id=account_branch_id,
        include_unassigned_branch=include_unassigned,
    )
    supplier_query = SupplierPayment.query.execution_options(skip_branch_scope=True).filter(
        sp_match, _cash_affecting_supplier_payment_filter()
    )
    supplier_payments = _within_period(
        supplier_query, SupplierPayment.created_at
    ).order_by(SupplierPayment.created_at).all()
    for payment in supplier_payments:
        movement_dt = _movement_datetime(payment.created_at)
        current_balance -= payment.amount
        movements.append(
            {
                "date": business_date(movement_dt),
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
    sh_match = account_matches_treasury(
        sh_col,
        account_id,
        default_cash_id,
        branch_column=ShippingPayment.branch_id,
        account_branch_id=account_branch_id,
        include_unassigned_branch=include_unassigned,
    )
    shipping_query = (
        db.session.query(
            ShippingPayment,
            ShippingCompany.name.label("shipping_company_name"),
        )
        .execution_options(skip_branch_scope=True)
        .outerjoin(
            ShippingCompany,
            ShippingCompany.id == ShippingPayment.shipping_company_id,
        )
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
            sh_match,
        )
    )
    shipping_payments = _within_period(
        shipping_query, ShippingPayment.created_at
    ).order_by(ShippingPayment.created_at).all()
    for payment, company_name in shipping_payments:
        movement_dt = _movement_datetime(payment.created_at)
        company_id = int(payment.shipping_company_id) if payment.shipping_company_id else None
        company_label = (company_name or "").strip() or (
            f"شركة #{company_id}" if company_id else "شركة نقل"
        )
        current_balance += payment.amount
        movements.append(
            {
                "date": business_date(movement_dt),
                "datetime": movement_dt,
                "type": "cash_out" if payment.amount < 0 else "cash_in",
                "type_ar": "عكس قبض" if payment.amount < 0 else "قبض",
                "reason": "عكس تحصيل شركة نقل" if payment.amount < 0 else "قبض من شركة نقل",
                "amount": payment.amount,
                "balance_after": current_balance,
                "reference_type": "shipping_payment",
                "reference_id": payment.id,
                "invoice_id": payment.invoice_id,
                "delivery_agent_id": None,
                "delivery_agent_name": "",
                "shipping_company_id": company_id,
                "shipping_company_name": company_label,
                "description": (
                    f"{'عكس تحصيل شركة نقل' if payment.amount < 0 else 'قبض من شركة نقل'} - {company_label} - "
                    f"{payment.amount:,} د.ع - {payment.note or ''}"
                ),
            }
        )

    withdrawals_query = AccountTransaction.query.execution_options(skip_branch_scope=True).filter(
            AccountTransaction.type == "withdraw",
            match,
            _cash_affecting_note_filter(AccountTransaction.note),
    )
    withdrawals = _within_period(
        withdrawals_query, AccountTransaction.created_at
    ).order_by(AccountTransaction.created_at).all()
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
                "date": business_date(movement_dt),
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
        running_balance += signed_movement_amount(movement)
        movement["balance_after"] = running_balance
    return movements
