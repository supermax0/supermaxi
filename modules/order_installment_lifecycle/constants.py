# -*- coding: utf-8 -*-
"""Constants for order installment lifecycle (distinct from monthly installments module)."""

SESSION_MODE_KEY = "installment_order_mode"

STATUS_ACTIVE = "ACTIVE"
STATUS_RETURNED = "RETURNED"
STATUS_PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
STATUS_AUTO_SETTLED = "AUTO_SETTLED"
STATUS_MANUALLY_SETTLED = "MANUALLY_SETTLED"
STATUS_CANCELLED = "CANCELLED"
STATUS_EXPIRED = "EXPIRED"

SETTLEABLE_STATUSES = (STATUS_ACTIVE, STATUS_PARTIALLY_RETURNED)

PERM_VIEW = "installment.view"
PERM_MODE_TOGGLE = "installment.mode.toggle"
PERM_CREATE = "installment.create"
PERM_RETURN = "installment.return"
PERM_MANUAL_SETTLE = "installment.manual_settle"
PERM_CANCEL = "installment.cancel"
PERM_OVERRIDE = "installment.override"
PERM_SETTINGS = "installment.settings"

BASIC_PERMISSIONS = (PERM_VIEW, PERM_MODE_TOGGLE, PERM_CREATE, PERM_RETURN)

ALL_PERMISSIONS = (
    (PERM_VIEW, "عرض طلبات الأقساط (دورة الطلب)"),
    (PERM_MODE_TOGGLE, "تفعيل وضع الأقساط (دورة الطلب)"),
    (PERM_CREATE, "إنشاء طلب أقساط (دورة الطلب)"),
    (PERM_RETURN, "ترجيع طلب أقساط (دورة الطلب)"),
    (PERM_MANUAL_SETTLE, "تسديد طلب أقساط يدوياً (دورة الطلب)"),
    (PERM_CANCEL, "إلغاء طلب أقساط (دورة الطلب)"),
    (PERM_OVERRIDE, "تجاوز قيود دورة الأقساط"),
    (PERM_SETTINGS, "إعدادات دورة طلب الأقساط"),
)

DURATION_UNITS = ("days", "hours")

ERROR_PERMISSION_DENIED = "INSTALLMENT_PERMISSION_DENIED"
ERROR_FEATURE_DISABLED = "INSTALLMENT_FEATURE_DISABLED"
ERROR_MODE_REQUIRED = "INSTALLMENT_MODE_REQUIRED"

IDEMPOTENCY_PREFIX = "installment:settlement:"
