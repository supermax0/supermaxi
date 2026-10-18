"""Compound logical entries built from FINORA's existing balanced journal pairs."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import func
from extensions import db
from models.account import Account
from models.journal_entry import JournalEntry
from models.treasury_account import TreasuryAccount
from utils.accounting_logic import get_or_create_account
from utils.financial_period_guard import assert_date_period_open
from .common import FinanceError, get_row, policy, scope, today
from .models import FinanceJournalLink, FinanceMapping


def account(key):
    mapping = db.session.get(FinanceMapping, key)
    if not mapping or not mapping.account.is_active:
        raise FinanceError("ربط الحساب المحاسبي غير مكتمل أو غير فعال؛ راجع إعدادات الحسابات")
    return mapping.account


def treasury(row_id, branch_id=None):
    row = get_row(TreasuryAccount, row_id)
    if not row.is_active or (branch_id and row.branch_id != branch_id):
        raise FinanceError("اختر حساباً فعالاً من نفس فرع العملية")
    return row


def visible_treasuries():
    rows=scope(TreasuryAccount.query,TreasuryAccount).filter_by(is_active=True).order_by(
        TreasuryAccount.is_default.desc(),TreasuryAccount.id).all()
    from utils.branch_mode import independent_branches_enabled
    if independent_branches_enabled():
        return rows
    # The existing shared treasury calculator pools all cash accounts in its
    # canonical cash row. Show that pool once rather than adding it twice.
    cash_seen=False
    result=[]
    for row in rows:
        if row.is_cash:
            if cash_seen:
                continue
            cash_seen=True
        result.append(row)
    return result


def treasury_gl(row):
    from utils.branch_mode import independent_branches_enabled
    if row.is_cash and not independent_branches_enabled():
        from utils.treasury_helpers import get_default_cash_account
        canonical=get_default_cash_account()
        if canonical.id!=row.id:
            return treasury_gl(canonical)
    key = f"treasury:{row.id}"
    mapping = db.session.get(FinanceMapping, key)
    if not mapping:
        from utils.accounting_logic import ACCOUNT_CODES
        code = ACCOUNT_CODES["CASH"] if row.is_cash else ACCOUNT_CODES["BANK"]
        candidate = Account.query.filter_by(code=code).first()
        if candidate and FinanceMapping.query.filter(FinanceMapping.key.like("treasury:%"), FinanceMapping.account_id == candidate.id).first():
            candidate = None
        if not candidate:
            candidate = get_or_create_account(f"TR{row.id}", row.name, "asset", commit=False)
        mapping = FinanceMapping(key=key, account_id=candidate.id)
        db.session.add(mapping)
        db.session.flush()
    return account(key)


def check_funds(row, amount):
    from utils.treasury_calculations import assert_sufficient_balance
    if not policy()["allow_negative"]:
        assert_sufficient_balance(row.id, amount)


def post(voucher, pairs):
    assert_date_period_open(voucher.transaction_date, "ترحيل السند")
    assert_date_period_open(today(), "ترحيل السند")
    if not pairs or any(amount <= 0 or debit.id == credit.id for debit, credit, amount in pairs):
        raise FinanceError("تعذر تكوين قيد مالي متوازن")
    if FinanceJournalLink.query.filter_by(voucher_id=voucher.id).first():
        raise FinanceError("السند مرحّل مسبقاً", "already_posted", 409)
    for debit, credit, amount in pairs:
        entry = JournalEntry(entry_number=f"FV-{voucher.id}-{uuid4().hex[:12]}",
            description=f"{voucher.number} — {voucher.party_name or voucher.notes or voucher.category}",
            reference_type="finance_voucher", reference_id=voucher.id,
            debit_account_id=debit.id, credit_account_id=credit.id, amount=amount,
            entry_date=datetime.combine(voucher.transaction_date, datetime.min.time()), created_by=voucher.approved_by)
        db.session.add(entry)
        db.session.flush()
        db.session.add(FinanceJournalLink(voucher_id=voucher.id, journal_entry_id=entry.id))


def entries(voucher):
    return (JournalEntry.query.join(FinanceJournalLink, FinanceJournalLink.journal_entry_id == JournalEntry.id)
            .filter(FinanceJournalLink.voucher_id == voucher.id).all())


def reverse_pairs(voucher):
    result = entries(voucher)
    if not result:
        raise FinanceError("لا يوجد قيد أصلي صالح للعكس")
    return [(entry.credit_account, entry.debit_account, entry.amount) for entry in result]


def balance(row):
    return int(row.balance)
