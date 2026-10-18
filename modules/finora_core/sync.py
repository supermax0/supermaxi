"""Turns house-tenant ai_sales activity (written by the webhook / AI worker) into outbox events + audit rows.

Idempotent: every event and audit row carries a dedupe key, so concurrent callers can never duplicate them.
Throttled to one pass per second per process.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from extensions import db
from modules.ai_sales.models import AISalesConversation, AISalesMessage

from . import conversations as convs
from .store import audit, core_session, emit, get_setting, house_slug, house_tag, iso, msg_ref, set_setting, use_house

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_last_run = 0.0
_INTERVAL = 1.0
CURSOR_MSG = "house_cursor_message_id"
CURSOR_DELIVERY = "house_cursor_delivery_at"
CURSOR_CONV = "house_cursor_conversation_at"
AGENT_SIG = "house_agent_signature"
BATCH = 200


def _parse(ts: str | None, fallback: datetime) -> datetime:
    try:
        return datetime.fromisoformat(ts) if ts else fallback
    except ValueError:
        return fallback


_last_maintenance = 0.0
MAINTENANCE_INTERVAL = 5.0


def run_house_maintenance(force: bool = False) -> None:
    """Outbound retries (rate limit / 5xx backoff) + attachment storage catch-up after restarts. Never raises."""
    global _last_maintenance
    if not house_slug():
        return
    now = time.monotonic()
    if not force and now - _last_maintenance < MAINTENANCE_INTERVAL:
        return
    _last_maintenance = now
    try:
        from modules.ai_sales.attachments import store_message_attachments
        from modules.ai_sales.meta_retry import retry_due

        with use_house() as slug:
            stats = retry_due()
            if any(stats.values()):
                logger.info("finora_core outbound retries: %s", stats)
            pending = (
                AISalesMessage.query.filter(
                    AISalesMessage.media_metadata_json.like('%"status": "pending"%'),
                    AISalesMessage.created_at < datetime.utcnow() - timedelta(minutes=1),
                )
                .order_by(AISalesMessage.id.asc())
                .limit(5)
                .all()
            )
            for message in pending:
                if message.conversation is not None:
                    store_message_attachments(message, message.conversation.channel, slug)
            db.session.commit()
    except Exception:
        logger.exception("finora_core house maintenance failed")


def sync_house(force: bool = False) -> int:
    """Returns the number of new events. Never raises into the caller's stream: failures are logged."""
    global _last_run
    if not house_slug():
        return 0
    with _lock:
        now = time.monotonic()
        if not force and now - _last_run < _INTERVAL:
            return 0
        _last_run = now
        try:
            return _sync_once()
        except Exception:
            logger.exception("finora_core house sync failed")
            return 0


def _keys(slug: str) -> tuple[str, str, str, str]:
    """Cursors are per house tenant: switching / re-provisioning the house must never reuse another DB's cursor."""
    import hashlib

    tag = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:16]  # fixed length: fc_settings.key is VARCHAR(60)
    return (f"{CURSOR_MSG}:{tag}", f"{CURSOR_DELIVERY}:{tag}", f"{CURSOR_CONV}:{tag}", f"{AGENT_SIG}:{tag}")


def _sync_once() -> int:
    created = 0
    slug = house_slug() or ""
    k_msg, k_delivery, k_conv, k_agent = _keys(slug)
    with core_session() as s:
        raw_cursor = get_setting(s, k_msg)
        delivery_cursor = _parse(get_setting(s, k_delivery), datetime.utcnow() - timedelta(minutes=5))
        conv_cursor = _parse(get_setting(s, k_conv), datetime.utcnow() - timedelta(minutes=5))
        with use_house():
            last_id = int(db.session.query(db.func.max(AISalesMessage.id)).scalar() or 0)
            if raw_cursor is None or int(raw_cursor) > last_id:
                # First run, or the house DB was recreated / restored (ids restarted below our cursor): anchor at
                # "now" so history is not replayed and new messages are never hidden behind a stale cursor.
                set_setting(s, k_msg, str(last_id), "system")
                s.commit()
                return 0
            cursor = int(raw_cursor)
            new_msgs = (
                AISalesMessage.query.filter(AISalesMessage.id > cursor).order_by(AISalesMessage.id.asc()).limit(BATCH).all()
            )
            touched: set[int] = set()
            for m in new_msgs:
                conv = m.conversation
                if conv is None or convs.channel_of(conv) is None:
                    cursor = m.id
                    continue
                dto = convs.message_dto(m)
                emit(s, "message.received" if m.direction == "inbound" else "message.sent", {"message": dto}, dedupe_key=f"msg:{msg_ref(m.id, iso(m.created_at))}:new")
                name = (conv.contact_name or "عميل")[:150]
                if m.direction == "inbound":
                    channel = "Instagram" if convs.channel_of(conv) == "instagram" else "Facebook"
                    audit(s, actor="customer", actor_type="system", category="messages", action="message.received",
                          title=f"رسالة جديدة من {channel}", customer=name, conversation_ref=str(conv.id),
                          dedupe_key=f"audit:msg:{msg_ref(m.id, iso(m.created_at))}", created_at=m.created_at)
                elif m.sender_type == "ai":
                    audit(s, actor="FINORA CORE", actor_type="ai", category="messages", action="message.sent",
                          title="تم إرسال الرد" if m.status != "failed" else "فشل إرسال الرد", customer=name,
                          conversation_ref=str(conv.id), result="failed" if m.status == "failed" else "ok",
                          dedupe_key=f"audit:msg:{msg_ref(m.id, iso(m.created_at))}", created_at=m.created_at)
                touched.add(conv.id)
                cursor = m.id
                created += 1

            # Delivery receipts on already-known outbound messages.
            receipts = (
                AISalesMessage.query.filter(
                    AISalesMessage.direction == "outbound",
                    db.or_(AISalesMessage.delivered_at > delivery_cursor, AISalesMessage.read_at > delivery_cursor),
                )
                .order_by(AISalesMessage.id.asc())
                .limit(BATCH)
                .all()
            )
            for m in receipts:
                dto = convs.message_dto(m)
                emit(s, "message.sent", {"message": dto}, dedupe_key=f"msg:{msg_ref(m.id, iso(m.created_at))}:{dto['delivery']}")
                stamp = max(t for t in (m.delivered_at, m.read_at) if t)
                delivery_cursor = max(delivery_cursor, stamp)

            # Conversation state changes (takeover, stage, AI work) — including ones with no new message.
            changed = (
                AISalesConversation.query.filter(AISalesConversation.updated_at > conv_cursor)
                .order_by(AISalesConversation.updated_at.asc())
                .limit(BATCH)
                .all()
            )
            rows = [c for c in changed if convs.channel_of(c)]
            for c in changed:
                if c.updated_at:
                    conv_cursor = max(conv_cursor, c.updated_at)
            extra = [cid for cid in touched if cid not in {c.id for c in rows}]
            if extra:
                rows += AISalesConversation.query.filter(AISalesConversation.id.in_(extra)).all()
            from .brain.enrich import enrich_conversations

            for dto in enrich_conversations(s, convs.build_dtos(rows, {})):
                stamp = f"{dto['lastActivityAt']}|{dto['agentState']}|{dto['control']}|{dto['leadStage']}"
                # unreadCount is per operator: clients recompute it via REST on this hint.
                emit(s, "conversation.updated", {"conversation": dto}, dedupe_key=f"conv:{house_tag()}:{dto['id']}:{stamp}"[:160])
                created += 1
            status = convs.agent_status()
        signature = f"{status['state']}:{status['conversationId']}"
        if get_setting(s, k_agent) != signature:  # only real changes become events
            emit(s, "agent.status", {"status": status})
            set_setting(s, k_agent, signature, "system")
        set_setting(s, k_msg, str(cursor), "system")
        set_setting(s, k_delivery, delivery_cursor.isoformat(), "system")
        set_setting(s, k_conv, conv_cursor.isoformat(), "system")
        s.commit()
    return created
