"""Read/write façade over the house tenant's ai_sales conversations, mapped to the desktop wire contract
(desktop/finora_core/src/data/schemas.ts). Must be called inside ``store.use_house()``."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_

from extensions import db
from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation, AISalesMessage

from modules.ai_sales.attachments import label_for as attachment_label
from modules.ai_sales.attachments import public_view as public_attachments

from .store import iso

CHANNEL_TYPES = {"instagram": "instagram", "messenger": "facebook", "telegram": "telegram"}
CORE_CHANNEL_TYPES = tuple(CHANNEL_TYPES)

STAGE_MAP = {
    "new": "new",
    "interested": "engaged",
    "product_selection": "engaged",
    "collecting_order_data": "proposal",
    "waiting_confirmation": "proposal",
    "won": "account_created",
    "lost": "lost",
}

DELIVERY_MAP = {
    "queued": "sending",
    "processing": "sending",
    "sending": "sending",
    "retry_scheduled": "sending",  # rate limit / 5xx: queued for retry, never shown as sent
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
}

MEDIA_LABELS = {
    "image": "[صورة]",
    "audio": "[رسالة صوتية]",
    "voice": "[رسالة صوتية]",
    "video": "[فيديو]",
    "file": "[ملف]",
    "sticker": "[ملصق]",
    "unsupported": "[مرفق غير مدعوم]",
}

WORKING_STATUSES = ("processing",)


def channel_of(conv: AISalesConversation) -> str | None:
    return CHANNEL_TYPES.get(str(conv.channel.channel_type or "").lower()) if conv.channel else None


def lead_stage(conv: AISalesConversation) -> str:
    if conv.status == "waiting_employee":
        return "needs_human"
    return STAGE_MAP.get(str(conv.sales_stage or "new"), "engaged")


def control(conv: AISalesConversation) -> str:
    if conv.human_takeover:
        return "human"
    paused = conv.ai_paused_until and conv.ai_paused_until > datetime.utcnow()
    if not conv.ai_enabled or paused:
        return "paused"
    return "ai"


def _attachments(m: AISalesMessage) -> list[dict[str, Any]]:
    try:
        return list((m.get_media_metadata() or {}).get("attachments") or [])
    except (ValueError, TypeError):
        return []


def message_text(m: AISalesMessage) -> str:
    text = (m.text_content or m.transcription or "").strip()
    if text:
        return text
    label = attachment_label(_attachments(m))
    return label or MEDIA_LABELS.get(str(m.message_type or ""), "[رسالة]")


def message_dto(m: AISalesMessage) -> dict[str, Any]:
    items = _attachments(m)
    attachments = public_attachments(items)
    for row, item in zip(attachments, items):
        row["durationSeconds"] = item.get("duration_seconds")
        analysis = item.get("analysis")
        if isinstance(analysis, dict):
            row["analysis"] = {key: analysis[key] for key in ("status", "summary", "details", "needsHuman", "model", "provider", "frameTimes", "error", "at") if key in analysis}
    if m.direction == "inbound":
        sender, author, delivery = "customer", None, None
    elif m.sender_type == "ai":
        sender, author = "core", "Finora Core"
        delivery = _delivery(m)
    elif m.sender_type == "system":
        sender, author, delivery = "system", None, None
    else:
        sender, author = "human", "فريق FINORA"
        delivery = _delivery(m)
    return {
        "id": str(m.id),
        "conversationId": str(m.conversation_id),
        "sender": sender,
        "authorName": author,
        "text": message_text(m),
        "at": iso(m.created_at),
        "delivery": delivery,
        # Safe view only: kind / mime / name / size / status. Never Meta CDN URLs or storage paths.
        "attachments": attachments,
    }


def _delivery(m: AISalesMessage) -> str:
    status = str(m.status or "")
    if status == "failed":
        return "failed"
    if status in {"queued", "processing", "sending", "retry_scheduled"}:
        return "sending"
    if m.read_at:
        return "read"
    if m.delivered_at:
        return "delivered"
    # "sent" only when the provider accepted it; an unknown status is never claimed as sent.
    return DELIVERY_MAP.get(status, "sending")


def _last_activity(conv: AISalesConversation) -> datetime:
    stamps = [t for t in (conv.last_customer_message_at, conv.last_business_message_at) if t]
    return max(stamps) if stamps else conv.started_at


def _safe_avatar(url: str | None) -> str | None:
    return url if url and url.startswith("https://") and len(url) <= 800 else None


def conversation_dto(
    conv: AISalesConversation,
    *,
    last: AISalesMessage | None,
    unread: int,
    working: bool,
) -> dict[str, Any]:
    ctl = control(conv)
    if working:
        agent_state = "thinking"
    elif last is not None and last.direction == "outbound":
        agent_state = "waiting_customer"
    else:
        agent_state = "idle"
    activity = _last_activity(conv)
    return {
        "id": str(conv.id),
        "customerId": f"c{conv.customer_id}" if conv.customer_id else f"x{conv.id}",
        "customerName": (conv.contact_name or conv.external_phone or "عميل").strip()[:150] or "عميل",
        "avatarUrl": _safe_avatar(conv.contact_profile_picture_url),
        "channel": channel_of(conv) or "facebook",
        "lastMessageText": message_text(last) if last else "",
        "lastMessageAt": iso(last.created_at if last else activity),
        "lastActivityAt": iso(activity),
        "unreadCount": unread,
        "control": ctl,
        "assignedTo": "فريق FINORA" if ctl == "human" else None,
        "leadStage": lead_stage(conv),
        "agentState": agent_state,
        "archived": conv.status == "closed",
        "escalated": conv.status == "waiting_employee",
        "pendingApprovals": 0,
    }


def _core_channel_filter():
    return AISalesConversation.channel_account_id.in_(
        db.session.query(AISalesChannelAccount.id).filter(AISalesChannelAccount.channel_type.in_(CORE_CHANNEL_TYPES))
    )


def get_conversation(conversation_id: int) -> AISalesConversation | None:
    return (
        AISalesConversation.query.filter(AISalesConversation.id == conversation_id).filter(_core_channel_filter()).first()
    )


def build_dtos(rows: list[AISalesConversation], read_map: dict[str, int]) -> list[dict[str, Any]]:
    """Batch-load last message, unread counts and working state for a page (no N+1)."""
    if not rows:
        return []
    ids = [r.id for r in rows]
    last_ids = dict(
        db.session.query(AISalesMessage.conversation_id, func.max(AISalesMessage.id))
        .filter(AISalesMessage.conversation_id.in_(ids))
        .group_by(AISalesMessage.conversation_id)
        .all()
    )
    last_rows = {m.conversation_id: m for m in AISalesMessage.query.filter(AISalesMessage.id.in_(list(last_ids.values()))).all()} if last_ids else {}
    min_read = min((read_map.get(str(i), 0) for i in ids), default=0)
    inbound = (
        db.session.query(AISalesMessage.conversation_id, AISalesMessage.id)
        .filter(
            AISalesMessage.conversation_id.in_(ids),
            AISalesMessage.direction == "inbound",
            AISalesMessage.id > min_read,
        )
        .all()
    )
    unread: dict[int, int] = {}
    for conv_id, msg_id in inbound:
        if msg_id > read_map.get(str(conv_id), 0):
            unread[conv_id] = unread.get(conv_id, 0) + 1
    working = {
        cid
        for (cid,) in db.session.query(AISalesMessage.conversation_id)
        .filter(AISalesMessage.conversation_id.in_(ids), AISalesMessage.status.in_(WORKING_STATUSES))
        .distinct()
        .all()
    }
    return [
        conversation_dto(r, last=last_rows.get(r.id), unread=unread.get(r.id, 0), working=r.id in working) for r in rows
    ]


def list_conversations(
    *,
    channel: str,
    filter_: str,
    search: str,
    limit: int,
    offset: int,
    read_map: dict[str, int],
) -> tuple[list[dict[str, Any]], int | None]:
    q = AISalesConversation.query.filter(_core_channel_filter()).filter(AISalesConversation.status != "closed")
    if channel in CHANNEL_TYPES.values():
        wanted = [k for k, v in CHANNEL_TYPES.items() if v == channel]
        q = q.filter(
            AISalesConversation.channel_account_id.in_(
                db.session.query(AISalesChannelAccount.id).filter(AISalesChannelAccount.channel_type.in_(wanted))
            )
        )
    if filter_ == "ai_active":
        q = q.filter(AISalesConversation.human_takeover.is_(False), AISalesConversation.ai_enabled.is_(True))
    elif filter_ == "human":
        q = q.filter(AISalesConversation.human_takeover.is_(True))
    elif filter_ == "qualified":
        q = q.filter(AISalesConversation.sales_stage.in_([k for k, v in STAGE_MAP.items() if v == "qualified"] or ["__none__"]))
    elif filter_ in ("needs_approval", "onboarding"):
        return [], None  # approvals / onboarding arrive in later phases; never fake matches
    needle = search.strip()
    if needle:
        like = f"%{needle[:100]}%"
        q = q.filter(
            or_(
                AISalesConversation.contact_name.ilike(like),
                AISalesConversation.external_phone.ilike(like),
                AISalesConversation.id.in_(
                    db.session.query(AISalesMessage.conversation_id).filter(AISalesMessage.text_content.ilike(like))
                ),
            )
        )
    customer_at, business_at = AISalesConversation.last_customer_message_at, AISalesConversation.last_business_message_at
    # Latest real message time; started_at only when the thread has no messages at all (mirrors _last_activity).
    activity = func.coalesce(
        func.max(func.coalesce(customer_at, business_at), func.coalesce(business_at, customer_at)),
        AISalesConversation.started_at,
    )
    q = q.order_by(activity.desc(), AISalesConversation.id.desc())
    if filter_ == "unread":
        # Unread depends on per-operator markers stored in the Core DB; filter after mapping, bounded scan.
        dtos = [d for d in build_dtos(q.limit(500).all(), read_map) if d["unreadCount"] > 0]
        return dtos[offset : offset + limit], (offset + limit if len(dtos) > offset + limit else None)
    rows = q.offset(offset).limit(limit + 1).all()
    more = len(rows) > limit
    return build_dtos(rows[:limit], read_map), (offset + limit if more else None)


def list_messages(conversation_id: int, *, before: int | None, limit: int) -> list[dict[str, Any]]:
    """Ordered by provider event time (``created_at`` = Meta timestamp) so delayed / out-of-order webhook deliveries
    appear where they happened; id breaks ties."""
    q = AISalesMessage.query.filter(AISalesMessage.conversation_id == conversation_id)
    if before:
        q = q.filter(AISalesMessage.id < before)
    rows = q.order_by(AISalesMessage.created_at.desc(), AISalesMessage.id.desc()).limit(limit).all()
    return [message_dto(m) for m in reversed(rows)]


def latest_message_id(conversation_id: int) -> int:
    return int(
        db.session.query(func.max(AISalesMessage.id)).filter(AISalesMessage.conversation_id == conversation_id).scalar()
        or 0
    )


HEALTH_MAP = {
    "connected": "connected",
    "ready": "connected",
    "active": "connected",
    "verified": "connected",
    "auth_expired": "token_expired",
    "token_invalid": "token_expired",
    "permission_missing": "permission_missing",
    "comments_only": "permission_missing",  # pages_messaging not granted
    "webhook_invalid": "webhook_invalid",
}
# Worst state wins: one broken page must never hide behind a healthy one.
HEALTH_SEVERITY = ["webhook_invalid", "token_expired", "permission_missing", "disconnected", "connected"]


def _channel_state(row: AISalesChannelAccount, parent: AISalesChannelAccount | None) -> str:
    if not row.is_active:
        return "disconnected"
    if parent is not None and parent.connection_status == "webhook_invalid":
        return "webhook_invalid"
    return HEALTH_MAP.get(str(row.connection_status or ""), "disconnected")


def channel_health() -> dict[str, str]:
    """Per platform: connected | token_expired | permission_missing | webhook_invalid | disconnected."""
    rows = AISalesChannelAccount.query.filter(AISalesChannelAccount.channel_type.in_(CORE_CHANNEL_TYPES)).all()
    parent_ids = [r.parent_channel_id for r in rows if r.parent_channel_id] or [0]
    parents = {p.id: p for p in AISalesChannelAccount.query.filter(AISalesChannelAccount.id.in_(parent_ids)).all()}
    seen: dict[str, list[str]] = {name: [] for name in CHANNEL_TYPES.values()}
    for row in rows:
        if row.channel_type == "telegram" and not row.is_active:
            continue  # archived bots retain their conversations without masking the active bot's health
        seen[CHANNEL_TYPES[row.channel_type]].append(_channel_state(row, parents.get(row.parent_channel_id)))
    return {key: (min(states, key=HEALTH_SEVERITY.index) if states else "disconnected") for key, states in seen.items()}


def agent_status() -> dict[str, Any]:
    """Derived execution status: a claimed inbound message means FINORA CORE is working on that thread."""
    row = (
        AISalesMessage.query.filter(AISalesMessage.direction == "inbound", AISalesMessage.status.in_(WORKING_STATUSES))
        .order_by(AISalesMessage.id.desc())
        .first()
    )
    if row is None or row.conversation is None:
        return {"state": "idle", "label": None, "conversationId": None, "channel": None}
    return {"state": "thinking", "label": None, "conversationId": str(row.conversation_id), "channel": channel_of(row.conversation)}


def conversation_count() -> int:
    return AISalesConversation.query.filter(_core_channel_filter()).count()
