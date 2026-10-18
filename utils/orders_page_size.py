"""Orders table page-size configuration stored in SystemSettings.ui_flags."""

from extensions import db
from models.system_settings import SystemSettings


DEFAULT_ORDERS_PAGE_SIZE = 100
MIN_ORDERS_PAGE_SIZE = 1
MAX_ORDERS_PAGE_SIZE = 5000
UI_FLAG = "orders_page_size"


def _validated_page_size(value) -> int:
    if isinstance(value, bool):
        raise ValueError("حجم الصفحة يجب أن يكون رقماً صحيحاً")
    try:
        page_size = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("حجم الصفحة يجب أن يكون رقماً صحيحاً") from None

    if page_size < MIN_ORDERS_PAGE_SIZE or page_size > MAX_ORDERS_PAGE_SIZE:
        raise ValueError(
            f"حجم الصفحة يجب أن يكون بين {MIN_ORDERS_PAGE_SIZE} و{MAX_ORDERS_PAGE_SIZE}"
        )
    return page_size


def get_orders_page_size() -> int:
    """Return the configured page size, falling back safely to 100."""
    try:
        settings = SystemSettings.get_settings()
        value = settings.get_ui_flags().get(UI_FLAG, DEFAULT_ORDERS_PAGE_SIZE)
        return _validated_page_size(value)
    except Exception:
        return DEFAULT_ORDERS_PAGE_SIZE


def save_orders_page_size(value) -> int:
    """Validate and persist the orders table page size."""
    page_size = _validated_page_size(value)
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags[UI_FLAG] = page_size
    settings.set_ui_flags(flags)
    db.session.add(settings)
    db.session.commit()
    return page_size
