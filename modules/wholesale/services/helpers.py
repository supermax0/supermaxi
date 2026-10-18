"""Shared helpers for wholesale services."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


class WholesaleError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.code = code


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def resolve_wholesale_treasury_account(raw_id, payment_method: str):
    """Resolve cash/bank methods to one active operational treasury account."""
    from models.treasury_account import TreasuryAccount

    account_id = parse_int(raw_id)
    if account_id > 0:
        account = TreasuryAccount.query.filter_by(id=account_id, is_active=True).first()
        if not account:
            raise WholesaleError("حساب الخزينة المختار غير صالح")
        return account
    method = str(payment_method or "cash").strip().lower()
    if method in {"bank", "card", "بنك", "بطاقة"}:
        account = TreasuryAccount.query.filter_by(account_type="bank", is_active=True).order_by(
            TreasuryAccount.id.asc()
        ).first()
        if not account:
            raise WholesaleError("لا يوجد حساب بنكي فعال لتسجيل الحركة")
        return account
    from utils.treasury_helpers import get_default_cash_account

    return get_default_cash_account()


def parse_date(value: Any, default: date | None = None) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if not text:
        return default or date.today()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return default or date.today()


def normalize_currency(value: Any) -> str:
    cur = str(value or "IQD").strip().upper()
    return cur if cur in ("USD", "IQD") else "IQD"


def to_base_amount(amount: int, currency: str, exchange_rate: float) -> int:
    """Convert document amount to IQD base snapshot."""
    amount = int(amount or 0)
    rate = float(exchange_rate or 1.0)
    if normalize_currency(currency) == "USD":
        return int(round(amount * rate))
    return amount


def next_doc_no(prefix: str, last_no: str | None) -> str:
    today = date.today().strftime("%Y%m%d")
    base = f"{prefix}-{today}-"
    seq = 1
    if last_no and last_no.startswith(base):
        try:
            seq = int(last_no.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{base}{seq:04d}"
