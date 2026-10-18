"""Phase 2A unit tests: outcomes, flags, follow-up priority, timeline cursor."""

from __future__ import annotations

from datetime import datetime, timedelta

from modules.phone_app.services.call_outcomes import (
    OUTCOMES,
    compute_priority,
    resolve_follow_up_at,
    should_create_followup,
    validate_outcome,
)
from modules.phone_app.services.feature_flags import DEFAULT_FLAGS, get_feature_flags
from modules.phone_app.services.followup import can_transition
from modules.phone_app.services.timeline import paginate_timeline


def test_outcome_enum_complete():
    assert "order_created" in OUTCOMES
    assert "callback_required" in OUTCOMES
    assert "wrong_number" in OUTCOMES


def test_validate_order_created_without_order():
    err = validate_outcome(
        outcome="order_created",
        call_status="ended",
        follow_up_at=None,
        has_linked_order=False,
    )
    assert err == "order_created_without_order"


def test_validate_incompatible_missed():
    err = validate_outcome(
        outcome="interested",
        call_status="missed",
        follow_up_at=None,
        has_linked_order=False,
    )
    assert err == "outcome_incompatible_with_status"


def test_wrong_number_no_followup():
    assert should_create_followup("wrong_number") is False
    assert should_create_followup("callback_required") is True
    assert should_create_followup("complaint") is True


def test_callback_default_follow_up():
    at = resolve_follow_up_at("callback_required", None)
    assert at is not None
    assert at > datetime.utcnow() - timedelta(minutes=1)


def test_priority_urgent_complaint():
    assert compute_priority(is_complaint=True, vip=True, attempt_count=3) in (
        "high",
        "urgent",
    )


def test_task_forward_only():
    assert can_transition("open", "completed") is True
    assert can_transition("completed", "open") is False


def test_default_feature_flags_phase2a():
    flags = get_feature_flags()
    assert flags["phone_timeline_enabled"] is True
    assert flags["phone_call_outcomes_enabled"] is True
    assert flags["phone_advanced_search_enabled"] is True
    assert flags["phone_smart_followup_enabled"] is True
    assert flags["phone_voice_notes_enabled"] is False
    assert DEFAULT_FLAGS["recording"] is False


def test_timeline_pagination_order():
    now = datetime.utcnow()
    events = [
        {
            "id": "call_1",
            "type": "call",
            "occurred_at": now.isoformat() + "Z",
            "title": "a",
            "summary": "a",
            "status": "ended",
            "reference_type": "call",
            "reference_id": 1,
            "metadata": {},
            "_sort_at": now,
            "_sort_id": 1,
        },
        {
            "id": "note_2",
            "type": "note",
            "occurred_at": (now - timedelta(hours=1)).isoformat() + "Z",
            "title": "b",
            "summary": "b",
            "status": "saved",
            "reference_type": "note",
            "reference_id": 2,
            "metadata": {},
            "_sort_at": now - timedelta(hours=1),
            "_sort_id": 2,
        },
    ]
    page = paginate_timeline(events, cursor=None, limit=1)
    assert len(page["items"]) == 1
    assert page["pagination"]["has_more"] is True
    assert page["items"][0]["type"] == "call"
