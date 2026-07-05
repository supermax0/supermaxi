"""
توحيد حالات الطلب/الدفع — حالة الراجع الموحّدة: «راجع» فقط.
"""

from __future__ import annotations

import logging
from typing import Optional, Iterable

_log = logging.getLogger(__name__)

# الحالة الموحّدة للراجع (كتابة وعرض)
RETURN_STATUS = "راجع"

# قيم قديمة تُعامل كراجع عند القراءة ثم تُحوَّل تلقائياً
RETURN_STATUS_LEGACY: set[str] = {"مرتجع", "راجعة", "راجعه"}

# كل القيم التي تُعد «راجع» عند البحث في قاعدة البيانات
RETURN_STATUSES: set[str] = {RETURN_STATUS} | RETURN_STATUS_LEGACY

CANCELED_STATUSES: set[str] = {"ملغي"}
PENDING_STATUSES: set[str] = {"تم الطلب", "جاري الشحن"}
COMPLETED_STATUSES: set[str] = {"تم التوصيل", "مسدد"}

_RETURN_STATUS_UNIFIED_BINDS: set[str] = set()


def normalize_status(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(str(value).strip().split())


def is_return_status_value(value: Optional[str]) -> bool:
    return normalize_status(value) in RETURN_STATUSES


def display_return_status(value: Optional[str]) -> str:
    """عرض موحّد: أي قيمة راجع قديمة تُعرض كـ «راجع»."""
    if is_return_status_value(value):
        return RETURN_STATUS
    return normalize_status(value)


def is_canceled(status: Optional[str] = None, payment_status: Optional[str] = None) -> bool:
    s = normalize_status(status)
    p = normalize_status(payment_status)
    return (s in CANCELED_STATUSES) or (p in CANCELED_STATUSES)


def is_returned(status: Optional[str] = None, payment_status: Optional[str] = None) -> bool:
    return is_return_status_value(status) or is_return_status_value(payment_status)


def is_completed(status: Optional[str] = None, payment_status: Optional[str] = None) -> bool:
    s = normalize_status(status)
    p = normalize_status(payment_status)
    if p == "مسدد":
        return True
    return s in COMPLETED_STATUSES


def allowed_for_financials(status: Optional[str] = None, payment_status: Optional[str] = None) -> bool:
    if is_canceled(status, payment_status):
        return False
    if is_returned(status, payment_status):
        return False
    return True


def any_in(value: Optional[str], candidates: Iterable[str]) -> bool:
    v = normalize_status(value)
    return v in set(candidates)


def invoice_returned_condition(invoice_model):
    """شرط SQLAlchemy: الطلب راجع (يشمل القيم القديمة)."""
    from sqlalchemy import or_

    legacy = list(RETURN_STATUSES)
    return or_(
        invoice_model.status.in_(legacy),
        invoice_model.payment_status.in_(legacy),
    )


_DELIVERED_STATUS_NORMALIZED_BINDS: set[str] = set()


def ensure_delivered_status_normalized() -> None:
    """تحويل الطلبات القديمة: status=مسدد + payment=مسدد → status=تم التوصيل."""
    bind_key = "default"
    try:
        from flask import g

        bind_key = str(getattr(g, "tenant", None) or "core")
    except Exception:
        pass

    if bind_key in _DELIVERED_STATUS_NORMALIZED_BINDS:
        return

    try:
        from extensions import db
        from sqlalchemy import text

        result = db.session.execute(
            text(
                "UPDATE invoice SET status = :new_status "
                "WHERE status = :old_status AND payment_status = :paid"
            ),
            {
                "new_status": "تم التوصيل",
                "old_status": "مسدد",
                "paid": "مسدد",
            },
        )
        updated = int(result.rowcount or 0)
        if updated:
            db.session.commit()
            _log.info("ensure_delivered_status_normalized: updated %s orders", updated)
        _DELIVERED_STATUS_NORMALIZED_BINDS.add(bind_key)
    except Exception:
        _log.exception("ensure_delivered_status_normalized failed")
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass


def ensure_return_status_unified() -> None:
    """تحويل القيم القديمة (مرتجع/راجعة) إلى «راجع» مرة واحدة لكل قاعدة."""
    bind_key = "default"
    try:
        from flask import g

        bind_key = str(getattr(g, "tenant", None) or "core")
    except Exception:
        pass

    if bind_key in _RETURN_STATUS_UNIFIED_BINDS:
        return

    try:
        from extensions import db
        from models.invoice import Invoice

        legacy = list(RETURN_STATUS_LEGACY)
        if legacy:
            db.session.query(Invoice).filter(Invoice.status.in_(legacy)).update(
                {"status": RETURN_STATUS}, synchronize_session=False
            )
            db.session.query(Invoice).filter(Invoice.payment_status.in_(legacy)).update(
                {"payment_status": RETURN_STATUS}, synchronize_session=False
            )
            db.session.commit()
        _RETURN_STATUS_UNIFIED_BINDS.add(bind_key)
    except Exception:
        _log.exception("ensure_return_status_unified failed")
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass
