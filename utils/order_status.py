"""
توحيد حالات الطلب/الدفع (Status Standardization) بدون تغيير بنية قاعدة البيانات.

الهدف:
- توحيد منطق التعامل مع الحالات المتكررة (راجع/راجعة/راجعه/مرتجع/ملغي...).
- توفير دوال مساعدة آمنة للاستخدام داخل routes والـ utils.
"""

from __future__ import annotations

from typing import Optional, Iterable


# حالات الإلغاء والمرتجع (تم توحيدها حسب طلب المستخدم)
CANCELED_STATUSES: set[str] = {"مرتجع"}
RETURN_STATUSES: set[str] = {"مرتجع"}

# حالات الطلب “غير مكتمل”
PENDING_STATUSES: set[str] = {"تم الطلب", "جاري الشحن"}

# حالات الإكمال (حسب النظام الحالي)
COMPLETED_STATUSES: set[str] = {"تم التوصيل", "مسدد"}


def normalize_status(value: Optional[str]) -> str:
    """Normalize Arabic status strings: trim and collapse spaces."""
    if not value:
        return ""
    # توحيد الفراغات
    return " ".join(str(value).strip().split())


def is_canceled(status: Optional[str] = None, payment_status: Optional[str] = None) -> bool:
    s = normalize_status(status)
    p = normalize_status(payment_status)
    return (s in CANCELED_STATUSES) or (p in CANCELED_STATUSES)


def is_returned(status: Optional[str] = None, payment_status: Optional[str] = None) -> bool:
    s = normalize_status(status)
    p = normalize_status(payment_status)
    return (p == "مرتجع") or (s in RETURN_STATUSES)


def is_completed(status: Optional[str] = None, payment_status: Optional[str] = None) -> bool:
    s = normalize_status(status)
    p = normalize_status(payment_status)
    # في النظام الحالي: مسدد = مكتمل، وأحياناً تم التوصيل + مسدد
    if p == "مسدد":
        return True
    return s in COMPLETED_STATUSES


def allowed_for_financials(status: Optional[str] = None, payment_status: Optional[str] = None) -> bool:
    """هل يدخل في حسابات الإيراد/الربح؟ نستبعد الملغي والمرتجع."""
    if is_canceled(status, payment_status):
        return False
    if is_returned(status, payment_status):
        return False
    return True


def any_in(value: Optional[str], candidates: Iterable[str]) -> bool:
    v = normalize_status(value)
    return v in set(candidates)

