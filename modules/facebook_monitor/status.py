"""Message monitoring status. This page never sends replies."""
from __future__ import annotations

from datetime import datetime

NEW_SECONDS = 60
WARNING_SECONDS = 90
LATE_SECONDS = 180

STATUS_LABELS = {
    "NEW": "جديد",
    "WAITING_REPLY": "بانتظار الرد",
    "ANSWERED": "تم الرد",
    "LATE": "متأخر",
    "ORDER_CREATED": "تحول لطلب",
    "CLOSED": "مغلق",
}


def response_tone(seconds: int | None, *, waiting: bool) -> str:
    if seconds is None:
        return "muted"
    if seconds <= WARNING_SECONDS:
        return "success"
    if seconds <= LATE_SECONDS:
        return "warning"
    return "danger" if waiting or seconds > LATE_SECONDS else "warning"


def classify_message(
    *,
    received_at: datetime | None,
    answered_at: datetime | None,
    now: datetime | None = None,
    has_order: bool = False,
    conversation_closed: bool = False,
) -> tuple[str, int | None]:
    """Return (status, response_or_wait_seconds)."""
    now = now or datetime.utcnow()
    if not received_at:
        return "NEW", None
    if answered_at and answered_at >= received_at:
        seconds = max(0, int((answered_at - received_at).total_seconds()))
        if has_order:
            return "ORDER_CREATED", seconds
        if conversation_closed:
            return "CLOSED", seconds
        return "ANSWERED", seconds
    waiting = max(0, int((now - received_at).total_seconds()))
    if has_order:
        return "ORDER_CREATED", waiting
    if waiting <= NEW_SECONDS:
        return "NEW", waiting
    if waiting <= LATE_SECONDS:
        return "WAITING_REPLY", waiting
    return "LATE", waiting
