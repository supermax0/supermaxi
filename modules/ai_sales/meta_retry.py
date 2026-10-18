"""Outbound retry executor for Meta messages in ``retry_scheduled`` state (rate limits, 5xx, network).

Each due message is claimed atomically (``retry_scheduled`` → ``sending``) so two workers can never send it twice.
AI-authored retries respect the FINORA CORE kill switch; human replies are always delivered.
Must run inside a tenant context (``g.tenant``).
"""
from __future__ import annotations

import logging
from datetime import datetime

from extensions import db

from .channels import channel_client, outbound_message_id
from .meta_reliability import due_for_retry, record_send_failure, record_send_success
from .models import AISalesMessage

logger = logging.getLogger(__name__)

META_CHANNELS = ("messenger", "instagram")


def _automation_paused() -> bool:
    from modules.finora_core.killswitch import automation_paused_for_current_tenant

    return automation_paused_for_current_tenant()


def retry_due(now: datetime | None = None, *, limit: int = 20) -> dict[str, int]:
    now = now or datetime.utcnow()
    stats = {"sent": 0, "rescheduled": 0, "failed": 0, "held": 0}
    candidates = (
        AISalesMessage.query.filter(AISalesMessage.status == "retry_scheduled", AISalesMessage.direction == "outbound")
        .order_by(AISalesMessage.created_at.asc(), AISalesMessage.id.asc())
        .limit(limit * 3)
        .all()
    )
    paused = None
    blocked: set[int] = set()  # conversations with an earlier message still waiting: keep send order
    for message in candidates:
        if stats["sent"] + stats["failed"] + stats["rescheduled"] >= limit:
            break
        if message.conversation_id in blocked:
            continue
        if not due_for_retry(message, now):
            blocked.add(message.conversation_id)
            continue
        if message.sender_type == "ai":
            paused = _automation_paused() if paused is None else paused
            if paused:
                stats["held"] += 1
                blocked.add(message.conversation_id)
                continue
        claimed = AISalesMessage.query.filter_by(id=message.id, status="retry_scheduled").update(
            {"status": "sending"}, synchronize_session=False
        )
        db.session.commit()
        if not claimed:
            continue
        db.session.refresh(message)
        conversation = message.conversation
        channel = conversation.channel
        try:
            if message.get_media_metadata().get("core_media"):
                from flask import g
                from modules.finora_core.media import send_stored
                external_id = send_stored(message, str(g.tenant))
            else:
                body = channel_client(channel).send_text(conversation.external_contact_id, message.text_content or "")
                external_id = outbound_message_id(body)
            record_send_success(message, channel, external_id)
            if not conversation.last_business_message_at or message.sent_at > conversation.last_business_message_at:
                conversation.last_business_message_at = message.sent_at
            stats["sent"] += 1
        except Exception as exc:
            failure = record_send_failure(message, channel, exc, now=now)
            stats["rescheduled" if message.status == "retry_scheduled" else "failed"] += 1
            blocked.add(message.conversation_id)
            if message.status == "failed":
                _fail_followers(message)
            logger.warning("meta retry message=%s kind=%s → %s", message.id, failure.kind, message.status)
        db.session.commit()
    return stats


def _fail_followers(message: AISalesMessage) -> None:
    """Later reply parts queued behind a permanently failed part are failed too (never sent out of context)."""
    followers = AISalesMessage.query.filter(
        AISalesMessage.conversation_id == message.conversation_id,
        AISalesMessage.direction == "outbound",
        AISalesMessage.status == "retry_scheduled",
        AISalesMessage.sender_type == message.sender_type,
        AISalesMessage.id > message.id,
    ).all()
    for row in followers:
        row.status = "failed"
        row.failure_code = "previous_part_failed"
        row.failure_message = f"earlier part {message.id} could not be delivered"
