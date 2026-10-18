"""Shared helpers for the receipts module."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


class ReceiptError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.code = code


SOURCE_CUSTOMER = "customer"
SOURCE_COURIER = "courier"
SOURCE_SHIPPING = "shipping_company"

SOURCE_LABELS = {
    SOURCE_CUSTOMER: "عميل",
    SOURCE_COURIER: "مندوب توصيل",
    SOURCE_SHIPPING: "شركة نقل",
}

STATUS_ACTIVE = "معتمد"
STATUS_CANCELLED = "ملغى"

ALLOC_OLDEST = "oldest_first"
ALLOC_MANUAL = "manual"
ALLOC_ON_ACCOUNT = "on_account"

PAYMENT_METHODS = [
    ("cash", "نقدي"),
    ("bank", "تحويل مصرفي"),
    ("card", "بطاقة"),
    ("zaincash", "زين كاش"),
    ("fastpay", "FastPay"),
    ("qi", "Qi"),
    ("other", "أخرى"),
]


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


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


def resolve_treasury_account(raw_id, payment_method: str):
    from models.treasury_account import TreasuryAccount
    from utils.treasury_helpers import get_default_cash_account

    account_id = parse_int(raw_id)
    method = str(payment_method or "cash").strip().lower()
    bank_methods = {"bank", "card", "transfer", "تحويل", "بطاقة", "zaincash", "fastpay", "qi"}
    if account_id > 0:
        account = TreasuryAccount.query.filter_by(id=account_id, is_active=True).first()
        if not account:
            raise ReceiptError("حساب الخزينة المختار غير صالح")
        account_type = (account.account_type or "cash").strip().lower()
        if method == "cash" and account_type != "cash":
            raise ReceiptError("الدفع النقدي يجب أن يدخل إلى حساب صندوق نقدي")
        if method in bank_methods and account_type != "bank":
            raise ReceiptError("طريقة الدفع الإلكترونية/المصرفية يجب أن تدخل إلى حساب بنكي")
        return account

    if method in bank_methods:
        account = (
            TreasuryAccount.query.filter_by(account_type="bank", is_active=True)
            .order_by(TreasuryAccount.id.asc())
            .first()
        )
        if account:
            return account
    return get_default_cash_account()


def invoice_remaining(inv) -> int:
    return max(0, int(inv.total or 0) - int(inv.paid_amount or 0))


def set_payment_status(inv) -> None:
    total = int(inv.total or 0)
    paid = int(inv.paid_amount or 0)
    if paid <= 0:
        inv.payment_status = "غير مسدد"
    elif total > 0 and paid >= total:
        inv.paid_amount = total
        inv.payment_status = "مسدد"
    else:
        inv.payment_status = "جزئي"


def next_receipt_number() -> str:
    from models.receipt import Receipt

    year = datetime.utcnow().year
    prefix = f"RC-{year}-"
    last = (
        Receipt.query.filter(Receipt.receipt_number.like(f"{prefix}%"))
        .order_by(Receipt.id.desc())
        .first()
    )
    seq = 1
    if last and last.receipt_number:
        try:
            seq = int(str(last.receipt_number).rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = (last.id or 0) + 1
    return f"{prefix}{seq:06d}"
