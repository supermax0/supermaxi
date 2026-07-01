"""Shared helpers for treasury account selection and resolution."""
from __future__ import annotations

from models.treasury_account import TreasuryAccount


def get_default_cash_account() -> TreasuryAccount:
    from utils.treasury_schema_guard import ensure_treasury_schema

    ensure_treasury_schema()
    cash = (
        TreasuryAccount.query.filter_by(account_type="cash", is_default=True, is_active=True)
        .order_by(TreasuryAccount.id.asc())
        .first()
    )
    if cash:
        return cash
    cash = TreasuryAccount(
        name="الصندوق",
        account_type="cash",
        is_default=True,
        is_active=True,
    )
    from extensions import db

    db.session.add(cash)
    db.session.commit()
    return cash


def resolve_treasury_account_id(raw_value) -> int:
    """Resolve form/API value to a valid treasury account id (default cash)."""
    default_id = get_default_cash_account().id
    if raw_value is None or str(raw_value).strip() == "":
        return default_id
    try:
        account_id = int(raw_value)
    except (TypeError, ValueError):
        return default_id
    account = TreasuryAccount.query.filter_by(id=account_id, is_active=True).first()
    return account.id if account else default_id


def treasury_choices_for_form(include_cash: bool = True, banks_only: bool = False):
    """Return active treasury accounts for form dropdowns."""
    from utils.treasury_schema_guard import ensure_treasury_schema

    ensure_treasury_schema()
    query = TreasuryAccount.query.filter_by(is_active=True).order_by(
        TreasuryAccount.is_default.desc(),
        TreasuryAccount.account_type.asc(),
        TreasuryAccount.name.asc(),
    )
    if banks_only:
        query = query.filter(TreasuryAccount.account_type == "bank")
    elif not include_cash:
        query = query.filter(TreasuryAccount.account_type != "cash")
    return query.all()


def account_matches_treasury(column, account_id: int, default_cash_id: int):
    """SQLAlchemy filter: row belongs to treasury account (NULL = default cash)."""
    from sqlalchemy import or_

    if account_id == default_cash_id:
        return or_(column.is_(None), column == account_id)
    return column == account_id
