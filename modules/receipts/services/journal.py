"""Journal posting for receipts (single Debit/Credit pair)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_

from extensions import db
from models.account import Account
from models.journal_entry import JournalEntry


def _find_account(parts: list[str]) -> Account | None:
    for part in parts:
        acc = Account.query.filter(Account.name.contains(part)).first()
        if acc:
            return acc
    return None


def _next_entry_number(prefix: str = "JE-RC") -> str:
    last = JournalEntry.query.order_by(JournalEntry.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d')}-{n:05d}"


def _cash_account_for_treasury(treasury) -> Account | None:
    """Resolve the GL cash/bank account that matches the selected treasury."""
    from modules.finance.source_sync import enabled
    if treasury is not None and enabled(db.session):
        from modules.finance.ledger import treasury_gl
        return treasury_gl(treasury)
    account_type = (getattr(treasury, "account_type", None) or "cash").strip().lower()
    treasury_name = (getattr(treasury, "name", None) or "").strip()
    if treasury_name:
        exact = Account.query.filter(
            or_(Account.name == treasury_name, Account.name_ar == treasury_name)
        ).first()
        if exact:
            return exact
    if account_type == "bank":
        return _find_account(["بنك", "مصرف", "Bank"])
    return _find_account(["صندوق", "نقدية", "Cash"])


def _receivable_account():
    from modules.finance.source_sync import enabled
    if enabled(db.session):
        from modules.finance.ledger import account
        return account("receivable")
    return _find_account(["عملاء", "ذمم", "مدينون", "Receivable"])


def post_receipt_journal(
    *,
    amount: int,
    receipt_id: int,
    treasury=None,
    doc_no: str | None = None,
    entry_date: datetime | None = None,
    employee_id: int | None = None,
) -> JournalEntry | None:
    if amount <= 0:
        return None
    cash = _cash_account_for_treasury(treasury)
    ar = _receivable_account()
    if not cash or not ar or cash.id == ar.id:
        return None
    entry = JournalEntry(
        entry_number=_next_entry_number(),
        description=f"سند قبض {doc_no or receipt_id}",
        reference_type="receipt",
        reference_id=receipt_id,
        debit_account_id=cash.id,
        credit_account_id=ar.id,
        amount=int(amount),
        entry_date=entry_date or datetime.utcnow(),
        created_by=employee_id,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def reverse_receipt_journal(
    *,
    amount: int,
    receipt_id: int,
    treasury=None,
    doc_no: str | None = None,
    employee_id: int | None = None,
) -> JournalEntry | None:
    """Reverse: Dr AR / Cr Cash."""
    if amount <= 0:
        return None
    original=JournalEntry.query.filter_by(reference_type="receipt",reference_id=receipt_id).order_by(JournalEntry.id).first()
    cash = db.session.get(Account,original.debit_account_id) if original else _cash_account_for_treasury(treasury)
    ar = db.session.get(Account,original.credit_account_id) if original else _receivable_account()
    if not cash or not ar or cash.id == ar.id:
        return None
    entry = JournalEntry(
        entry_number=_next_entry_number("JE-RC-REV"),
        description=f"إلغاء سند قبض {doc_no or receipt_id}",
        reference_type="receipt_cancel",
        reference_id=receipt_id,
        debit_account_id=ar.id,
        credit_account_id=cash.id,
        amount=int(amount),
        entry_date=datetime.utcnow(),
        created_by=employee_id,
    )
    db.session.add(entry)
    db.session.flush()
    return entry
