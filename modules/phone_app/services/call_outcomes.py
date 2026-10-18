"""Structured call outcome rules for Finora Phone."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

OUTCOMES = frozenset(
    {
        "order_created",
        "interested",
        "callback_required",
        "no_answer",
        "busy",
        "wrong_number",
        "not_interested",
        "complaint",
        "support",
        "price_inquiry",
        "delivery_inquiry",
        "cancelled",
        "other",
    }
)

# Most-used first for After-call UI.
PRIMARY_OUTCOMES = (
    "interested",
    "callback_required",
    "order_created",
    "no_answer",
    "not_interested",
    "complaint",
)

MORE_OUTCOMES = tuple(sorted(OUTCOMES - set(PRIMARY_OUTCOMES)))

# Outcomes allowed per call_status.
_STATUS_ALLOW: dict[str, frozenset[str]] = {
    "missed": frozenset({"no_answer", "callback_required", "wrong_number", "other"}),
    "rejected": frozenset({"no_answer", "busy", "callback_required", "wrong_number", "other"}),
    "failed": frozenset({"no_answer", "busy", "cancelled", "other"}),
    "cancelled": frozenset({"cancelled", "other"}),
    "answered": OUTCOMES,
    "ended": OUTCOMES,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def allowed_outcomes_for_status(call_status: str | None) -> frozenset[str]:
    status = (call_status or "").strip().lower()
    return _STATUS_ALLOW.get(status, OUTCOMES)


def followup_minutes_default() -> int:
    try:
        from models.system_settings import SystemSettings

        row = SystemSettings.query.filter_by(key="phone_missed_followup_minutes").first()
        if row and row.value:
            m = int(str(row.value).strip())
            if m in (5, 15, 30, 60):
                return m
    except Exception:
        pass
    return 30


def validate_outcome(
    *,
    outcome: str,
    call_status: str | None,
    follow_up_at: datetime | None,
    has_linked_order: bool,
    force_missed_skip: bool = False,
) -> str | None:
    """Return error code or None if valid."""
    outcome = (outcome or "").strip().lower()
    if outcome not in OUTCOMES:
        return "invalid_outcome"
    status = (call_status or "").strip().lower()
    # Missed already classified by the system — do not require / force outcome,
    # but if the employee sets one, keep it within the allowed subset.
    if force_missed_skip and status == "missed" and not outcome:
        return None
    if outcome not in allowed_outcomes_for_status(status):
        return "outcome_incompatible_with_status"
    if outcome == "order_created" and not has_linked_order:
        return "order_created_without_order"
    if outcome == "callback_required" and follow_up_at is None:
        # Caller should fill default; treat missing as soft fill, not hard error here.
        pass
    return None


def resolve_follow_up_at(outcome: str, follow_up_at: datetime | None) -> datetime | None:
    if outcome != "callback_required":
        return follow_up_at
    if follow_up_at is not None:
        return follow_up_at
    return _utcnow() + timedelta(minutes=followup_minutes_default())


def should_create_followup(outcome: str) -> bool:
    if outcome == "wrong_number":
        return False
    return outcome in ("callback_required", "complaint")


def compute_priority(
    *,
    vip: bool = False,
    high_purchases: bool = False,
    attempt_count: int = 1,
    is_complaint: bool = False,
    has_open_order: bool = False,
    overdue: bool = False,
) -> str:
    score = 0
    if vip:
        score += 2
    if high_purchases:
        score += 2
    if attempt_count >= 3:
        score += 2
    elif attempt_count >= 2:
        score += 1
    if is_complaint:
        score += 3
    if has_open_order:
        score += 1
    if overdue:
        score += 2
    if score >= 6:
        return "urgent"
    if score >= 4:
        return "high"
    if score >= 2:
        return "normal"
    return "low"


def outcome_catalog() -> dict[str, Any]:
    return {
        "outcomes": sorted(OUTCOMES),
        "primary": list(PRIMARY_OUTCOMES),
        "more": list(MORE_OUTCOMES),
        "by_status": {k: sorted(v) for k, v in _STATUS_ALLOW.items()},
    }
