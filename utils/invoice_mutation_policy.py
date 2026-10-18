"""Per-company policy for destructive mutations of collected invoices."""
from __future__ import annotations

from extensions import db
from models.system_settings import SystemSettings
from utils.cash_calculations import _effective_paid_amount


ALLOW_PAID_INVOICE_MUTATIONS_FLAG = "allow_paid_invoice_mutations"


def paid_invoice_mutations_enabled() -> bool:
    """The safety switch is deliberately off for every company by default."""
    try:
        settings = SystemSettings.get_settings()
        return bool(
            settings.get_ui_flags().get(ALLOW_PAID_INVOICE_MUTATIONS_FLAG, False)
        )
    except Exception:
        return False


def set_paid_invoice_mutations_enabled(enabled: bool) -> bool:
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags[ALLOW_PAID_INVOICE_MUTATIONS_FLAG] = bool(enabled)
    settings.set_ui_flags(flags)
    db.session.commit()
    return bool(enabled)


def invoice_has_financial_effect(invoice) -> bool:
    """Treat partial collections as paid for mutation-safety purposes."""
    if invoice is None:
        return False
    payment_status = (getattr(invoice, "payment_status", None) or "").strip()
    status = (getattr(invoice, "status", None) or "").strip()
    return bool(
        _effective_paid_amount(invoice) > 0
        or payment_status in {"جزئي", "مسدد", "مسدد جزئي"}
        or status == "مسدد"
    )


def paid_invoice_mutation_denied(invoice) -> bool:
    return invoice_has_financial_effect(invoice) and not paid_invoice_mutations_enabled()


PAID_INVOICE_MUTATION_DISABLED_MESSAGE = (
    "تعديل أو حذف الفاتورة المسددة غير مفعّل لهذه الشركة. "
    "يمكن للمدير تفعيله من إعدادات النظام."
)
