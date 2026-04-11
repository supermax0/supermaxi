"""
قائمة سوداء للزبائن: تطبيع أرقام، عدّ المرتجعات لمجموعة الهاتف، وتلقائي بعد عتبة.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import or_

from extensions import db
from models.customer import Customer
from models.invoice import Invoice

_log = logging.getLogger(__name__)

# «أكثر من طلبين» = أكثر من طلبين مرتجعين = على الأقل 3 مرتجعات
AUTO_BLACKLIST_MIN_RETURNS = 3

AUTO_REASON_AR = "تلقائي: تجاوز عدد المرتجعات المسموح به لهذا الرقم"


def normalize_phone(s: str | None) -> str:
    if not s:
        return ""
    return "".join(ch for ch in str(s) if ch.isdigit())


def customer_ids_for_same_phone(customer: Customer) -> list[int]:
    """معرّفات الزبائن الذين يشاركون نفس رقم الهاتف الأساسي (phone أو phone2)."""
    if not customer:
        return []
    key = (customer.phone or "").strip()
    if not key:
        return [customer.id]
    rows = Customer.query.filter(
        or_(Customer.phone == key, Customer.phone2 == key)
    ).all()
    return [c.id for c in rows if c and c.id]


def count_returned_invoices_for_customer_ids(customer_ids: list[int]) -> int:
    if not customer_ids:
        return 0
    return (
        Invoice.query.filter(
            Invoice.customer_id.in_(customer_ids),
            or_(
                Invoice.status == "راجع",
                Invoice.payment_status == "مرتجع",
            ),
        ).count()
    )


def is_phone_blacklisted_for_new_customer(phone: str | None, phone2: str | None = None) -> bool:
    """هل يطابق رقم (جديد) أي زبون في القائمة السوداء (phone أو phone2)؟"""
    np = normalize_phone(phone)
    n2 = normalize_phone(phone2) if phone2 else ""
    if not np and not n2:
        return False
    for c in Customer.query.filter(Customer.is_blacklisted.is_(True)).all():
        for ex in (normalize_phone(c.phone), normalize_phone(c.phone2)):
            if not ex:
                continue
            if np and np == ex:
                return True
            if n2 and n2 == ex:
                return True
    return False


def blacklist_customers_by_ids(
    customer_ids: list[int],
    reason: str,
    *,
    commit: bool = True,
) -> int:
    """يضبط is_blacklisted لمجموعة معرّفات. يعيد عدد الصفوف المحدثة."""
    if not customer_ids:
        return 0
    now = datetime.utcnow()
    n = 0
    for cid in set(customer_ids):
        c = Customer.query.get(cid)
        if not c:
            continue
        c.is_blacklisted = True
        c.blacklist_reason = (reason or "")[:2000]
        c.blacklisted_at = now
        n += 1
    if commit and n:
        db.session.commit()
    return n


def clear_blacklist_for_customer_ids(customer_ids: list[int], *, commit: bool = True) -> int:
    n = 0
    for cid in set(customer_ids):
        c = Customer.query.get(cid)
        if not c or not c.is_blacklisted:
            continue
        c.is_blacklisted = False
        c.blacklist_reason = None
        c.blacklisted_at = None
        n += 1
    if commit and n:
        db.session.commit()
    return n


def maybe_auto_blacklist_after_return(invoice: Invoice | int) -> None:
    """
    بعد تسجيل طلب كمرتجع: إن وصل عدد المرتجعات لمجموعة الهاتف إلى AUTO_BLACKLIST_MIN_RETURNS فأكثر.
    يقبل كائن الفاتورة أو معرفها (يُعاد التحميل بعد commit).
    """
    try:
        inv = invoice
        if isinstance(invoice, int):
            inv = Invoice.query.get(invoice)
        if not inv or not inv.customer_id:
            return
        cust = inv.customer or Customer.query.get(inv.customer_id)
        if not cust:
            return
        ids = customer_ids_for_same_phone(cust)
        cnt = count_returned_invoices_for_customer_ids(ids)
        if cnt < AUTO_BLACKLIST_MIN_RETURNS:
            return
        to_flag: list[int] = []
        for cid in ids:
            row = Customer.query.get(cid)
            if row and not row.is_blacklisted:
                to_flag.append(cid)
        if not to_flag:
            return
        blacklist_customers_by_ids(to_flag, AUTO_REASON_AR, commit=True)
    except Exception:
        _log.exception(
            "maybe_auto_blacklist_after_return failed for invoice %s",
            getattr(invoice, "id", None) if not isinstance(invoice, int) else invoice,
        )
