"""Time-based fulfillment branch when orders move to «جاري الشحن»."""
from __future__ import annotations

import re
from datetime import datetime, time

from models.branch import Branch
from models.order_item import OrderItem
from utils.branch_sales import reassign_item_fulfillment_branch
from utils.branch_stock_service import BranchStockError, deduct_stock, get_branch_stock, receive_stock
from utils.order_shipping import is_shipping_item
from utils.payment_ledger import BUSINESS_TZ_NAME

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_DEFAULT_DAY_START = "08:00"
_DEFAULT_DAY_END = "17:00"


def _business_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(BUSINESS_TZ_NAME))
    except Exception:
        try:
            import pytz

            return datetime.now(pytz.timezone(BUSINESS_TZ_NAME))
        except Exception:
            return datetime.now()


def _parse_hhmm(value: str | None, default: str) -> time:
    raw = (value or default).strip()
    match = _TIME_RE.match(raw)
    if not match:
        match = _TIME_RE.match(default)
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("وقت غير صالح")
    return time(hour, minute)


def get_shipping_branch_schedule_settings() -> dict:
    try:
        from models.system_settings import SystemSettings

        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags() if settings else {}
    except Exception:
        flags = {}

    day_id = flags.get("shipping_day_branch_id")
    night_id = flags.get("shipping_night_branch_id")
    try:
        day_id = int(day_id) if day_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        day_id = None
    try:
        night_id = int(night_id) if night_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        night_id = None

    return {
        "enabled": bool(flags.get("shipping_branch_schedule_enabled")),
        "day_branch_id": day_id,
        "night_branch_id": night_id,
        "day_start": (flags.get("shipping_day_start") or _DEFAULT_DAY_START).strip(),
        "day_end": (flags.get("shipping_day_end") or _DEFAULT_DAY_END).strip(),
    }


def set_shipping_branch_schedule(
    *,
    enabled: bool,
    day_branch_id: int | None,
    night_branch_id: int | None,
    day_start: str = _DEFAULT_DAY_START,
    day_end: str = _DEFAULT_DAY_END,
) -> None:
    from datetime import datetime as dt

    from extensions import db
    from models.system_settings import SystemSettings

    _parse_hhmm(day_start, _DEFAULT_DAY_START)
    _parse_hhmm(day_end, _DEFAULT_DAY_END)

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags["shipping_branch_schedule_enabled"] = bool(enabled)
    flags["shipping_day_branch_id"] = day_branch_id
    flags["shipping_night_branch_id"] = night_branch_id
    flags["shipping_day_start"] = (day_start or _DEFAULT_DAY_START).strip()
    flags["shipping_day_end"] = (day_end or _DEFAULT_DAY_END).strip()
    settings.set_ui_flags(flags)
    settings.updated_at = dt.utcnow()
    db.session.add(settings)


def resolve_shipping_branch_for_now(now: datetime | None = None) -> int | None:
    cfg = get_shipping_branch_schedule_settings()
    if not cfg["enabled"]:
        return None
    day_id = cfg["day_branch_id"]
    night_id = cfg["night_branch_id"]
    if not day_id or not night_id:
        return None

    current = now or _business_now()
    day_start = _parse_hhmm(cfg["day_start"], _DEFAULT_DAY_START)
    day_end = _parse_hhmm(cfg["day_end"], _DEFAULT_DAY_END)
    current_time = current.time()

    if day_start <= day_end:
        in_day = day_start <= current_time < day_end
    else:
        in_day = current_time >= day_start or current_time < day_end

    return day_id if in_day else night_id


def _reassign_item_to_branch(item: OrderItem, order, target_branch_id: int) -> None:
    target_branch_id = int(target_branch_id)
    qty = int(item.quantity or 0)
    if qty <= 0:
        return

    old_branch_id = item.fulfillment_branch_id or getattr(order, "branch_id", None)
    if old_branch_id and int(old_branch_id) == target_branch_id:
        item.fulfillment_branch_id = target_branch_id
        return

    if item.fulfillment_branch_id:
        reassign_item_fulfillment_branch(item, target_branch_id)
        return

    target_branch = Branch.query.filter_by(id=target_branch_id, is_active=True).first()
    if not target_branch:
        raise BranchStockError("فرع الجدولة غير موجود أو غير نشط")

    available = get_branch_stock(target_branch_id, item.product_id)
    if available < qty:
        product_name = item.product_name or "الصنف"
        raise BranchStockError(
            f"المخزون غير كافٍ في {target_branch.name} لصنف {product_name}. "
            f"المتاح: {available}، المطلوب: {qty}"
        )

    if old_branch_id:
        receive_stock(int(old_branch_id), item.product_id, qty)

    try:
        deduct_stock(target_branch_id, item.product_id, qty)
    except BranchStockError:
        if old_branch_id:
            deduct_stock(int(old_branch_id), item.product_id, qty)
        raise

    item.fulfillment_branch_id = target_branch_id


def apply_shipping_branch_schedule(order, *, previous_status: str | None = None) -> None:
    """
    Reassign fulfillment branch for all line items when entering «جاري الشحن».
    Only runs on first transition from «تم الطلب».
    """
    prev = (previous_status or getattr(order, "status", None) or "").strip()
    if prev != "تم الطلب":
        return

    target_branch_id = resolve_shipping_branch_for_now()
    if not target_branch_id:
        return

    target_branch = Branch.query.filter_by(id=target_branch_id, is_active=True).first()
    if not target_branch:
        raise BranchStockError("فرع الجدولة غير موجود أو غير نشط")

    items = [
        item
        for item in OrderItem.query.filter_by(invoice_id=order.id).all()
        if not is_shipping_item(item)
    ]
    for item in items:
        _reassign_item_to_branch(item, order, target_branch_id)

    order.branch_id = target_branch_id
