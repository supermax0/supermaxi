"""Supplier balance exchange-rate configuration stored in SystemSettings.ui_flags."""

from decimal import Decimal, InvalidOperation

from extensions import db
from models.system_settings import SystemSettings


DEFAULT_SUPPLIER_EXCHANGE_RATE = Decimal("1350")
MIN_SUPPLIER_EXCHANGE_RATE = Decimal("1")
MAX_SUPPLIER_EXCHANGE_RATE = Decimal("1000000")
UI_FLAG = "supplier_exchange_rate"


def _validated_exchange_rate(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("سعر الصرف يجب أن يكون رقماً أكبر من صفر")

    try:
        rate = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("سعر الصرف يجب أن يكون رقماً صالحاً") from None

    if not rate.is_finite() or rate < MIN_SUPPLIER_EXCHANGE_RATE or rate > MAX_SUPPLIER_EXCHANGE_RATE:
        raise ValueError(
            f"سعر الصرف يجب أن يكون بين {MIN_SUPPLIER_EXCHANGE_RATE:g} "
            f"و{MAX_SUPPLIER_EXCHANGE_RATE:g}"
        )

    return rate


def get_supplier_exchange_rate() -> Decimal:
    """Return the configured IQD-per-USD rate, falling back safely to 1350."""
    try:
        settings = SystemSettings.get_settings()
        value = settings.get_ui_flags().get(UI_FLAG, str(DEFAULT_SUPPLIER_EXCHANGE_RATE))
        return _validated_exchange_rate(value)
    except Exception:
        return DEFAULT_SUPPLIER_EXCHANGE_RATE


def save_supplier_exchange_rate(value) -> Decimal:
    """Validate and persist the supplier balance exchange rate."""
    rate = _validated_exchange_rate(value)
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags[UI_FLAG] = str(rate)
    settings.set_ui_flags(flags)
    db.session.add(settings)
    db.session.commit()
    return rate
