"""Balanced GL posting adapter for purchases executed from a daily list."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import inspect

from extensions import db
from models.account import Account
from models.journal_entry import JournalEntry
from models.purchase import Purchase
from utils.accounting_logic import ACCOUNT_CODES


def _account(code: str) -> Account | None:
    return Account.query.filter_by(code=code, is_active=True).first()


def _treasury_gl_account(treasury) -> Account | None:
    if treasury is None:
        return _account(ACCOUNT_CODES["CASH"])
    if bool(getattr(treasury, "is_cash", False)):
        return _account(ACCOUNT_CODES["CASH"])
    code = f"TR-{int(treasury.id)}"
    account = Account.query.filter_by(code=code).first()
    if account:
        return account
    account = Account(
        code=code,
        name=treasury.name,
        name_ar=treasury.name,
        account_type="asset",
        description=f"حساب خزينة مرتبط بـ {treasury.name}",
        is_active=True,
    )
    db.session.add(account)
    db.session.flush()
    return account


def _entry(*, purchase: Purchase, debit: Account, credit: Account, amount: int,
           description: str, employee_id: int | None) -> JournalEntry:
    row = JournalEntry(
        entry_number=f"JE-PL-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:10].upper()}",
        description=description,
        reference_type="purchase_list_purchase",
        reference_id=purchase.id,
        debit_account_id=debit.id,
        credit_account_id=credit.id,
        amount=int(amount),
        entry_date=datetime.utcnow(),
        created_by=employee_id,
    )
    db.session.add(row)
    return row


def post_split_purchase_journals(purchase: Purchase, *, employee_id: int | None = None) -> list[JournalEntry]:
    """Post inventory against each real funding source plus AP outstanding.

    Finora installations without an initialized chart of accounts keep using
    the existing operational ledgers only. Once Inventory and Accounts Payable
    accounts exist, posting is mandatory and any failure rolls back execution.
    """
    bind = db.session.get_bind()
    if "account" not in inspect(bind).get_table_names() or "journal_entry" not in inspect(bind).get_table_names():
        return []
    inventory = _account(ACCOUNT_CODES["INVENTORY"])
    payable = _account(ACCOUNT_CODES["ACCOUNTS_PAYABLE"])
    if not inventory or not payable:
        return []
    existing = JournalEntry.query.filter_by(
        reference_type="purchase_list_purchase", reference_id=purchase.id
    ).first()
    if existing:
        return []

    total = int(purchase.grand_total or purchase.total or 0)
    paid = 0
    created: list[JournalEntry] = []
    for payment in purchase.payments or []:
        amount = max(0, int(payment.amount or 0))
        if amount <= 0:
            continue
        credit = _treasury_gl_account(payment.treasury_account)
        if not credit:
            raise ValueError("حساب دفتر الأستاذ المقابل لحساب الدفع غير مهيأ")
        created.append(_entry(
            purchase=purchase, debit=inventory, credit=credit, amount=amount,
            description=f"شراء {purchase.invoice_no} — {payment.payment_method}",
            employee_id=employee_id,
        ))
        paid += amount
    outstanding = max(0, total - paid)
    if outstanding:
        created.append(_entry(
            purchase=purchase, debit=inventory, credit=payable, amount=outstanding,
            description=f"شراء آجل {purchase.invoice_no}", employee_id=employee_id,
        ))
    if paid > total:
        raise ValueError("دفعات فاتورة الشراء تتجاوز إجماليها")
    db.session.flush()
    return created
