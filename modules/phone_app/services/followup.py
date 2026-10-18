"""Follow-up priority + open-task coalesce helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from extensions import db
from modules.phone_app.models import PhoneFollowupTask
from modules.phone_app.services.call_outcomes import compute_priority, followup_minutes_default


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


TASK_STATUS_RANK = {
    "open": 1,
    "in_progress": 2,
    "overdue": 2,
    "resolved_by_answered_call": 3,
    "completed": 4,
    "cancelled": 4,
}


def can_transition(old: str, new: str) -> bool:
    """Forward-only status transitions; block reopening completed from stale sync."""
    o = TASK_STATUS_RANK.get((old or "").lower(), 0)
    n = TASK_STATUS_RANK.get((new or "").lower(), 0)
    if old in ("completed", "cancelled") and new in ("open", "in_progress", "overdue"):
        return False
    return n >= o or new == old


def find_open_task(
    *,
    employee_id: int,
    phone_normalized: str,
    task_type: str,
    customer_id: int | None = None,
    window_minutes: int = 15,
) -> PhoneFollowupTask | None:
    window_start = _utcnow() - timedelta(minutes=window_minutes)
    q = PhoneFollowupTask.query.filter_by(
        employee_id=employee_id,
        status="open",
        task_type=task_type,
    ).filter(PhoneFollowupTask.created_at >= window_start)
    if customer_id:
        hit = q.filter_by(customer_id=customer_id).order_by(PhoneFollowupTask.id.desc()).first()
        if hit:
            return hit
    if phone_normalized:
        return (
            q.filter(
                (PhoneFollowupTask.phone_normalized == phone_normalized)
                | (PhoneFollowupTask.phone == phone_normalized)
            )
            .order_by(PhoneFollowupTask.id.desc())
            .first()
        )
    return None


def mark_overdue_tasks(employee_id: int | None = None) -> int:
    q = PhoneFollowupTask.query.filter(
        PhoneFollowupTask.status.in_(("open", "in_progress")),
        PhoneFollowupTask.due_at.isnot(None),
        PhoneFollowupTask.due_at < _utcnow(),
    )
    if employee_id:
        q = q.filter_by(employee_id=employee_id)
    n = 0
    for t in q.limit(500).all():
        t.status = "overdue"
        t.updated_at = _utcnow()
        n += 1
    return n


def priority_for_customer(customer, *, attempt_count: int = 1, is_complaint: bool = False, overdue: bool = False) -> str:
    vip = bool(getattr(customer, "vip", False)) if customer else False
    purchases = float(getattr(customer, "total_purchases", 0) or 0) if customer else 0
    open_orders = int(getattr(customer, "open_orders_count", 0) or 0) if customer else 0
    # Heuristic VIP if card fields missing
    if customer is not None and not vip:
        try:
            from modules.phone_app.api.v1.customers import _customer_card

            card = _customer_card(customer)
            vip = bool(card.get("vip"))
            purchases = float(card.get("total_purchases") or 0)
            open_orders = int(card.get("open_orders_count") or 0)
        except Exception:
            pass
    return compute_priority(
        vip=vip,
        high_purchases=purchases >= 1_000_000,
        attempt_count=attempt_count,
        is_complaint=is_complaint,
        has_open_order=open_orders > 0,
        overdue=overdue,
    )


def default_due_at() -> datetime:
    return _utcnow() + timedelta(minutes=followup_minutes_default())
