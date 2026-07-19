"""UI/API routes and public WhatsApp webhook for Finora Sales AI."""
from __future__ import annotations

import json
import re
import secrets
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, Response, current_app, g, jsonify, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import case, func, or_

from extensions import db
from models.employee import Employee
from models.product import Product
from models.product_color_variant import ProductColorVariant
# Register relationship targets before AI order models trigger mapper setup.
from models.shipping import ShippingCompany  # noqa: F401
from models.delivery_agent import DeliveryAgent  # noqa: F401
from models.user import User  # noqa: F401
from utils.permission_checks import check_permission
from .channels import (
    MetaMessagingClient,
    MetaMessagingClientError,
    WhatsAppClient,
    WhatsAppClientError,
    channel_client,
    external_timestamp,
    extract_meta_system_message_context,
    meta_attachment_details,
    outbound_message_id,
    parse_meta_comment_payload,
    parse_meta_messaging_payload,
    parse_whatsapp_payload,
)
from .engine import (
    dispatch_inbound_async,
    get_or_create_conversation,
    mark_customer_activity,
    pause_conversation_for_human,
    process_inbound_message,
)
from .decision_engine import product_knowledge_score
from .models import (
    AISalesAgentProfile,
    AISalesChannelAccount,
    AISalesCall,
    AISalesConversation,
    AISalesConversationRead,
    AISalesLead,
    AISalesKnowledgeEntry,
    AISalesLearningImport,
    AISalesMessage,
    AISalesProductProfile,
    AISalesReplyExample,
    AISalesSocialComment,
    AISalesSocialPost,
    ProductMediaAsset,
)
from .comments import (
    dispatch_social_comment_async,
    sync_page_posts,
    upsert_social_comment,
    upsert_social_post,
)
from .knowledge import build_learning_template, import_learning_workbook, save_problem_entry
from .learning import capture_employee_reply_example, capture_new_employee_reply_examples
from .schema import ensure_ai_sales_schema
from .security import decrypt_secret, encrypt_secret, verify_meta_signature
from .training import approve_training_feedback, generate_training_reply
from .openai_service import (
    AIServiceError,
    DEFAULT_VOICE_INSTRUCTIONS,
    SUPPORTED_TTS_VOICES,
    create_realtime_client_secret,
    generate_speech_file,
    get_ffmpeg_binary,
    get_openai_api_key,
    get_openai_client,
    is_corrupted_text,
    settings_for_profile,
)


ai_sales_bp = Blueprint("ai_sales", __name__, url_prefix="/ai-sales")
ai_sales_webhook_bp = Blueprint("ai_sales_webhook", __name__, url_prefix="/api/v1/ai-sales")


CHAT_MEDIA_RULES = {
    "image/jpeg": ("image", ".jpg", 5 * 1024 * 1024),
    "image/png": ("image", ".png", 5 * 1024 * 1024),
    "image/webp": ("image", ".webp", 5 * 1024 * 1024),
    "image/gif": ("image", ".gif", 5 * 1024 * 1024),
    "video/mp4": ("video", ".mp4", 16 * 1024 * 1024),
    "video/3gpp": ("video", ".3gp", 16 * 1024 * 1024),
    "video/quicktime": ("video", ".mov", 16 * 1024 * 1024),
    "audio/mpeg": ("audio", ".mp3", 16 * 1024 * 1024),
    "audio/mp4": ("audio", ".m4a", 16 * 1024 * 1024),
    "audio/aac": ("audio", ".aac", 16 * 1024 * 1024),
    "audio/ogg": ("audio", ".ogg", 16 * 1024 * 1024),
    "audio/webm": ("audio", ".webm", 16 * 1024 * 1024),
    "audio/wav": ("audio", ".wav", 16 * 1024 * 1024),
    "audio/x-wav": ("audio", ".wav", 16 * 1024 * 1024),
}


META_AUTH_ERROR_CODES = {102, 190}
META_AUTH_RETRY_DELAY = timedelta(hours=12)
META_TRANSIENT_RETRY_DELAY = timedelta(minutes=1)
META_PENDING_AI_WINDOW = timedelta(hours=12)


def _meta_sync_is_blocked(channel: AISalesChannelAccount, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    return bool(channel.sync_blocked_until and channel.sync_blocked_until > now)


def _record_meta_sync_failure(
    channel: AISalesChannelAccount,
    exc: Exception,
    now: datetime | None = None,
) -> bool:
    """Persist a connector cooldown and return whether credentials must be renewed."""
    now = now or datetime.utcnow()
    meta_code = getattr(exc, "meta_code", None)
    status_code = getattr(exc, "status_code", None)
    auth_expired = meta_code in META_AUTH_ERROR_CODES or status_code == 401
    channel.last_sync_at = now
    channel.last_error = str(exc)[:2000]
    channel.sync_blocked_until = now + (
        META_AUTH_RETRY_DELAY if auth_expired else META_TRANSIENT_RETRY_DELAY
    )
    if auth_expired:
        channel.connection_status = "auth_expired"
    return auth_expired


def _clear_meta_sync_failure(channel: AISalesChannelAccount, *, connected: bool = False) -> None:
    channel.sync_blocked_until = None
    channel.last_error = None
    if connected or channel.connection_status in {"auth_expired", "error"}:
        channel.connection_status = "connected" if connected else "ready"


def _mark_missing_meta_channels_unavailable(
    connector: AISalesChannelAccount,
    imported_channel_ids: list[int],
) -> list[int]:
    """Disable child accounts that are not granted by the connector's current token."""
    imported_ids = {int(channel_id) for channel_id in imported_channel_ids if channel_id}
    missing_ids: list[int] = []
    children = AISalesChannelAccount.query.filter(
        AISalesChannelAccount.parent_channel_id == connector.id,
        AISalesChannelAccount.channel_type.in_(("messenger", "instagram")),
    ).all()
    for child in children:
        if child.connection_status == "removed":
            continue
        if child.id in imported_ids:
            continue
        child.is_active = False
        child.connection_status = "unavailable"
        child.sync_blocked_until = None
        child.last_error = "الصفحة غير موجودة ضمن صلاحيات رمز Meta الحالي. أعد ربطها من الحساب الذي يديرها."
        missing_ids.append(child.id)
    return missing_ids


def _apply_meta_channel_policy(channel: AISalesChannelAccount) -> int:
    """Apply a page routing policy to its open conversations without deleting history."""
    conversations = AISalesConversation.query.filter_by(channel_account_id=channel.id).filter(
        AISalesConversation.status != "closed"
    ).all()
    use_ai = bool(channel.is_active and channel.reply_mode == "ai")
    use_employee = bool(channel.is_active and channel.reply_mode == "employee")
    for conversation in conversations:
        conversation.ai_enabled = use_ai
        conversation.human_takeover = use_employee
        conversation.assigned_employee_id = channel.default_employee_id
        conversation.status = "waiting_employee" if use_employee else "open"
    return len(conversations)


def _employee_channel_ids(employee_id: int | None = None) -> list[int]:
    """Channels explicitly registered to the current employee."""
    employee_id = int(employee_id or session.get("user_id") or 0)
    if not employee_id:
        return []
    return [
        int(channel_id)
        for (channel_id,) in (
            db.session.query(AISalesChannelAccount.id)
            .filter(
                AISalesChannelAccount.default_employee_id == employee_id,
                AISalesChannelAccount.connection_status != "removed",
            )
            .all()
        )
    ]


def _scope_conversations(query):
    if _can_manage():
        return query
    channel_ids = _employee_channel_ids()
    if not channel_ids:
        return query.filter(AISalesConversation.id == -1)
    return query.filter(AISalesConversation.channel_account_id.in_(channel_ids))


def _can_view() -> bool:
    return bool(
        session.get("role") == "admin"
        or check_permission("use_ai_sales")
        or check_permission("manage_ai_sales")
        or _employee_channel_ids()
    )


def _can_manage() -> bool:
    return session.get("role") == "admin" or check_permission("manage_ai_sales")


def _api_guard(manage: bool = False):
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    if (manage and not _can_manage()) or (not manage and not _can_view()):
        return jsonify({"success": False, "error": "لا تملك صلاحية Finora Sales AI"}), 403
    ensure_ai_sales_schema()
    return None


def _conversation_allowed(conversation: AISalesConversation) -> bool:
    if _can_manage():
        return True
    employee_id = int(session.get("user_id") or 0)
    return bool(
        employee_id
        and conversation.channel
        and int(conversation.channel.default_employee_id or 0) == employee_id
        and conversation.channel.connection_status != "removed"
    )


def _knowledge_payload(product: Product, profile: AISalesProductProfile | None) -> dict:
    colors = list(profile.get_colors() if profile else [])
    variant_colors = [
        str(row.color_name or "").strip()
        for row in ProductColorVariant.query.filter_by(product_id=product.id)
        .filter(ProductColorVariant.quantity > 0)
        .order_by(ProductColorVariant.color_name.asc())
        .all()
        if str(row.color_name or "").strip()
    ]
    for color in variant_colors:
        if color not in colors:
            colors.append(color)
    row = {
        "description": product.description or "",
        "selling_points": profile.get_selling_points() if profile else [],
        "ideal_for": profile.get_ideal_for() if profile else [],
        "objection_guidance": profile.get_objections() if profile else {},
        "warranty": profile.warranty_text if profile else "",
        "delivery": profile.delivery_text if profile else "",
        "colors": colors,
        "width_cm": profile.width_cm if profile else None,
        "height_cm": profile.height_cm if profile else None,
        "depth_cm": profile.depth_cm if profile else None,
        "sales_notes": profile.ai_notes if profile else "",
        "image_url": product.image_url or "",
    }
    score = product_knowledge_score(row)
    missing = []
    checks = (
        ("الوصف", row["description"]),
        ("نقاط البيع", row["selling_points"]),
        ("الاستخدام المناسب", row["ideal_for"]),
        ("الضمان", row["warranty"]),
        ("التوصيل", row["delivery"]),
        ("ردود الاعتراضات", row["objection_guidance"]),
        ("صورة المنتج", row["image_url"]),
    )
    for label, value in checks:
        if not value:
            missing.append(label)
    return {
        "product_id": product.id,
        "product_name": product.name or "",
        "marketing_name": profile.marketing_name if profile else "",
        "aliases": profile.get_aliases() if profile else [],
        **row,
        "allow_price": bool(profile.allow_price) if profile else True,
        "allow_recommendation": bool(profile.allow_recommendation) if profile else True,
        "is_active": bool(profile.is_active) if profile else True,
        "knowledge_score": score,
        "missing": missing,
    }


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        source = value
    else:
        source = re.split(r"[\n,،]+", str(value or ""))
    result = []
    for item in source:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result[:50]


def _objection_map(value) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            str(key).strip(): str(answer).strip()
            for key, answer in value.items()
            if str(key).strip() and str(answer).strip()
        }
    result = {}
    for line in str(value or "").splitlines():
        parts = re.split(r"\s*(?:=|:|：)\s*", line.strip(), maxsplit=1)
        if len(parts) == 2 and parts[0] and parts[1]:
            result[parts[0].strip()] = parts[1].strip()
    return result


def _optional_measurement(value) -> float | None:
    text_value = str(value or "").strip().replace("،", ".").replace(",", ".")
    if not text_value:
        return None
    try:
        number = float(text_value)
    except (TypeError, ValueError):
        raise ValueError("الأبعاد يجب أن تكون أرقاماً بالسنتيمتر")
    if number <= 0 or number > 1000:
        raise ValueError("قيمة البعد يجب أن تكون بين 0 و1000 سم")
    return round(number, 2)


def _public_base_url() -> str:
    configured = str(current_app.config.get("BASE_URL") or "").strip().rstrip("/")
    if configured == "https://finora.company":
        configured = "https://www.finora.company"
    if configured:
        return configured
    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",", 1)[0].strip()
    return f"{forwarded_proto}://{request.host}".rstrip("/")


def _capture_employee_learning_safely(message_id: int) -> None:
    try:
        capture_employee_reply_example(message_id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Finora Sales AI continuous learning capture failed message_id=%s", message_id)


def _message_file(message: AISalesMessage) -> Path | None:
    if not message.media_path:
        return None
    target = Path(message.media_path).resolve()
    allowed = (Path(current_app.root_path) / "uploads" / "ai_sales").resolve()
    try:
        target.relative_to(allowed)
    except ValueError:
        return None
    return target if target.is_file() else None


def _transcode_voice(source: Path) -> tuple[Path, str]:
    target = source.with_suffix(".ogg")
    try:
        ffmpeg_binary = get_ffmpeg_binary()
        subprocess.run(
            [
                ffmpeg_binary, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(source), "-vn",
                "-af", (
                    "highpass=f=65,lowpass=f=12000,"
                    "acompressor=threshold=0.125:ratio=2:attack=20:release=180:makeup=1.35,"
                    "loudnorm=I=-16:LRA=7:TP=-1.5"
                ),
                "-codec:a", "libopus", "-b:a", "72k", "-vbr", "on",
                "-compression_level", "10", "-application", "audio",
                "-ar", "48000", "-ac", "1", "-f", "ogg", str(target),
            ],
            check=True,
            timeout=90,
            capture_output=True,
        )
    except (AIServiceError, OSError, subprocess.SubprocessError) as exc:
        target.unlink(missing_ok=True)
        raise ValueError("تعذر تجهيز التسجيل الصوتي للإرسال") from exc
    source.unlink(missing_ok=True)
    return target, "audio/ogg"


def _channel_webhook_url(channel: AISalesChannelAccount, tenant_slug: str, base: str | None = None) -> str:
    base = base or _public_base_url()
    webhook_type = "meta" if channel.channel_type == "meta" else "whatsapp"
    if channel.channel_type in {"messenger", "instagram"} and channel.parent_channel_id:
        parent = AISalesChannelAccount.query.get(channel.parent_channel_id)
        if parent:
            channel = parent
            webhook_type = "meta"
    return f"{base}/api/v1/ai-sales/webhooks/{webhook_type}/{tenant_slug}/{channel.webhook_key}"


@ai_sales_bp.before_request
def _setup_ai_sales_ui():
    if session.get("user_id"):
        ensure_ai_sales_schema()


@ai_sales_bp.route("/")
def root():
    return redirect(url_for("ai_sales.inbox"))


@ai_sales_bp.route("/inbox")
def inbox():
    if not session.get("user_id"):
        return redirect("/")
    if not _can_view():
        return redirect("/pos"), 403
    return render_template(
        "ai_sales/inbox.html",
        can_manage=_can_manage(),
        assigned_page_count=len(_employee_channel_ids()) if not _can_manage() else 0,
    )


@ai_sales_bp.route("/comments")
def comments_page():
    if not session.get("user_id"):
        return redirect("/")
    if not _can_view():
        return redirect("/pos"), 403
    return render_template("ai_sales/comments.html", can_manage=_can_manage())


def _visible_comment_channels():
    query = AISalesChannelAccount.query.filter(
        AISalesChannelAccount.channel_type == "messenger",
        AISalesChannelAccount.connection_status != "removed",
    )
    if not _can_manage():
        channel_ids = _employee_channel_ids()
        query = query.filter(AISalesChannelAccount.id.in_(channel_ids or [-1]))
    return query


@ai_sales_bp.route("/api/comments/posts")
def api_comment_posts():
    denied = _api_guard()
    if denied:
        return denied
    channel_ids = [row.id for row in _visible_comment_channels().all()]
    query = AISalesSocialPost.query.filter(AISalesSocialPost.channel_account_id.in_(channel_ids or [-1]))
    channel_id = int(request.args.get("channel_id") or 0)
    if channel_id:
        query = query.filter(AISalesSocialPost.channel_account_id == channel_id)
    search = str(request.args.get("q") or "").strip()
    if search:
        query = query.filter(or_(
            AISalesSocialPost.message.ilike(f"%{search}%"),
            AISalesSocialPost.story.ilike(f"%{search}%"),
        ))
    rows = query.order_by(
        AISalesSocialPost.published_at.desc(),
        AISalesSocialPost.id.desc(),
    ).limit(min(max(int(request.args.get("limit") or 60), 1), 200)).all()
    result = []
    for post in rows:
        payload = post.to_dict()
        payload["new_comments"] = AISalesSocialComment.query.filter_by(post_id=post.id, status="new").count()
        payload["failed_comments"] = AISalesSocialComment.query.filter_by(post_id=post.id, status="failed").count()
        payload["stored_comments"] = AISalesSocialComment.query.filter_by(post_id=post.id).count()
        result.append(payload)
    channels = [row.to_dict() for row in _visible_comment_channels().order_by(AISalesChannelAccount.name.asc()).all()]
    return jsonify({"success": True, "posts": result, "channels": channels})


@ai_sales_bp.route("/api/comments/posts/<int:post_id>")
def api_comment_post(post_id):
    denied = _api_guard()
    if denied:
        return denied
    post = AISalesSocialPost.query.get_or_404(post_id)
    visible_ids = {row.id for row in _visible_comment_channels().all()}
    if post.channel_account_id not in visible_ids:
        return jsonify({"success": False, "error": "لا تملك صلاحية هذه الصفحة"}), 403
    comments = AISalesSocialComment.query.filter_by(post_id=post.id).order_by(
        AISalesSocialComment.commented_at.desc(),
        AISalesSocialComment.id.desc(),
    ).limit(500).all()
    return jsonify({
        "success": True,
        "post": post.to_dict(),
        "comments": [row.to_dict() for row in comments],
    })


@ai_sales_bp.route("/api/comments/sync", methods=["POST"])
def api_sync_comments():
    denied = _api_guard()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    channel_id = int(data.get("channel_id") or 0)
    channel = _visible_comment_channels().filter(AISalesChannelAccount.id == channel_id).first_or_404()
    try:
        result = sync_page_posts(channel, post_limit=int(data.get("post_limit") or 30))
        comment_ids = result.pop("new_comment_ids", [])
        if channel.comments_enabled and channel.comments_reply_mode == "ai":
            app = current_app._get_current_object()
            tenant_slug = str(getattr(g, "tenant", "") or "")
            for comment_id in comment_ids:
                dispatch_social_comment_async(app, tenant_slug, comment_id)
        result["queued_comments"] = (
            len(comment_ids)
            if channel.comments_enabled and channel.comments_reply_mode == "ai"
            else 0
        )
        return jsonify({"success": True, **result})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Meta comments sync failed channel_id=%s", channel_id)
        error_text = str(exc)
        if "pages_read_user_content" in error_text or "Page Public Content Access" in error_text:
            error_text = (
                "تطبيق Meta لا يملك صلاحية pages_read_user_content. "
                "أضفها من App Review بصلاحية Advanced Access، ثم حدّث Page Access Token لهذه الصفحة."
            )
        elif "Error validating access token" in error_text or "OAuthException" in error_text:
            error_text = (
                "رمز وصول الصفحة منتهي أو غير صالح. حدّث Page Access Token من إعدادات Meta والصفحات، "
                "ثم أعد جلب المنشورات."
            )
        return jsonify({"success": False, "error": error_text}), 502


@ai_sales_bp.route("/api/comments/<int:comment_id>/reply", methods=["POST"])
def api_reply_comment(comment_id):
    denied = _api_guard()
    if denied:
        return denied
    comment = AISalesSocialComment.query.get_or_404(comment_id)
    visible_ids = {row.id for row in _visible_comment_channels().all()}
    if comment.channel_account_id not in visible_ids:
        return jsonify({"success": False, "error": "لا تملك صلاحية هذه الصفحة"}), 403
    comment.status = "new"
    comment.failure_message = None
    db.session.commit()
    dispatch_social_comment_async(
        current_app._get_current_object(),
        str(getattr(g, "tenant", "") or ""),
        comment.id,
        force=True,
    )
    return jsonify({"success": True, "status": "queued"}), 202


@ai_sales_bp.route("/api/overview")
def api_overview():
    denied = _api_guard()
    if denied:
        return denied
    conversation_scope = _scope_conversations(AISalesConversation.query)
    visible_ids = conversation_scope.with_entities(AISalesConversation.id)
    return jsonify(
        {
            "success": True,
            "overview": {
                "open_conversations": conversation_scope.filter(AISalesConversation.status != "closed").count(),
                "waiting_employee": conversation_scope.filter(AISalesConversation.human_takeover.is_(True)).count(),
                "hot_leads": AISalesLead.query.filter(AISalesLead.temperature == "hot", AISalesLead.conversation_id.in_(visible_ids)).count(),
                "messages_today": AISalesMessage.query.filter(AISalesMessage.conversation_id.in_(visible_ids), AISalesMessage.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)).count(),
            },
        }
    )


@ai_sales_bp.route("/api/conversations")
def api_conversations():
    denied = _api_guard()
    if denied:
        return denied
    status = (request.args.get("status") or "").strip()
    q = _scope_conversations(AISalesConversation.query)
    if status == "human":
        q = q.filter(AISalesConversation.human_takeover.is_(True))
    elif status == "ai":
        q = q.filter(
            AISalesConversation.ai_enabled.is_(True),
            AISalesConversation.human_takeover.is_(False),
            AISalesConversation.status != "closed",
        )
    elif status == "hot":
        q = q.filter(AISalesConversation.lead_temperature == "hot")
    elif status not in {"", "unread"}:
        q = q.filter(AISalesConversation.status == status)
    rows = q.order_by(AISalesConversation.updated_at.desc()).limit(300).all()
    conversation_ids = [row.id for row in rows]
    latest_by_conversation = {}
    unread_by_conversation = {}
    if conversation_ids:
        latest_ids = dict(
            db.session.query(AISalesMessage.conversation_id, func.max(AISalesMessage.id))
            .filter(AISalesMessage.conversation_id.in_(conversation_ids))
            .group_by(AISalesMessage.conversation_id)
            .all()
        )
        if latest_ids:
            latest_by_conversation = {
                message.conversation_id: message
                for message in AISalesMessage.query.filter(AISalesMessage.id.in_(latest_ids.values())).all()
            }
        read_subquery = (
            db.session.query(
                AISalesConversationRead.conversation_id.label("conversation_id"),
                AISalesConversationRead.last_read_message_id.label("last_read_message_id"),
            )
            .filter(AISalesConversationRead.employee_id == session.get("user_id"))
            .subquery()
        )
        outbound_subquery = (
            db.session.query(
                AISalesMessage.conversation_id.label("conversation_id"),
                func.max(AISalesMessage.id).label("last_outbound_message_id"),
            )
            .filter(
                AISalesMessage.conversation_id.in_(conversation_ids),
                AISalesMessage.direction == "outbound",
            )
            .group_by(AISalesMessage.conversation_id)
            .subquery()
        )
        read_cutoff = func.coalesce(read_subquery.c.last_read_message_id, 0)
        reply_cutoff = func.coalesce(outbound_subquery.c.last_outbound_message_id, 0)
        unread_cutoff = case(
            (read_cutoff >= reply_cutoff, read_cutoff),
            else_=reply_cutoff,
        )
        unread_by_conversation = dict(
            db.session.query(AISalesMessage.conversation_id, func.count(AISalesMessage.id))
            .outerjoin(read_subquery, read_subquery.c.conversation_id == AISalesMessage.conversation_id)
            .outerjoin(outbound_subquery, outbound_subquery.c.conversation_id == AISalesMessage.conversation_id)
            .filter(
                AISalesMessage.conversation_id.in_(conversation_ids),
                AISalesMessage.direction == "inbound",
                AISalesMessage.id > unread_cutoff,
            )
            .group_by(AISalesMessage.conversation_id)
            .all()
        )
    payload = []
    for row in rows:
        item = row.to_dict()
        latest = latest_by_conversation.get(row.id)
        item["last_message"] = latest.to_dict() if latest else None
        item["unread_count"] = int(unread_by_conversation.get(row.id, 0))
        payload.append(item)
    if status == "unread":
        payload = [item for item in payload if item["unread_count"] > 0]
    return jsonify({"success": True, "conversations": payload})


@ai_sales_bp.route("/api/conversations/<int:conversation_id>/messages")
def api_messages(conversation_id):
    denied = _api_guard()
    if denied:
        return denied
    conversation = AISalesConversation.query.get_or_404(conversation_id)
    if not _conversation_allowed(conversation):
        return jsonify({"success": False, "error": "هذه المحادثة محولة إلى موظف آخر"}), 403
    after_id = max(request.args.get("after_id", type=int) or 0, 0)
    messages_query = AISalesMessage.query.filter_by(conversation_id=conversation.id)
    if after_id:
        messages_query = messages_query.filter(AISalesMessage.id > after_id)
    rows = messages_query.order_by(AISalesMessage.id.asc()).limit(600).all()
    lead = AISalesLead.query.filter_by(conversation_id=conversation.id).first()
    return jsonify(
        {
            "success": True,
            "conversation": conversation.to_dict(),
            "lead": lead.to_dict() if lead else None,
            "messages": [row.to_dict() for row in rows],
            "after_id": after_id,
        }
    )


@ai_sales_bp.route("/api/conversations/<int:conversation_id>/read", methods=["POST"])
def api_mark_conversation_read(conversation_id):
    denied = _api_guard()
    if denied:
        return denied
    conversation = AISalesConversation.query.get_or_404(conversation_id)
    if not _conversation_allowed(conversation):
        return jsonify({"success": False, "error": "هذه المحادثة محولة إلى موظف آخر"}), 403
    latest = (
        AISalesMessage.query.filter_by(conversation_id=conversation.id, direction="inbound")
        .order_by(AISalesMessage.id.desc())
        .first()
    )
    receipt = AISalesConversationRead.query.filter_by(
        conversation_id=conversation.id,
        employee_id=session.get("user_id"),
    ).first()
    if not receipt:
        receipt = AISalesConversationRead(
            conversation_id=conversation.id,
            employee_id=session.get("user_id"),
        )
        db.session.add(receipt)
    receipt.last_read_message_id = latest.id if latest else receipt.last_read_message_id
    receipt.last_read_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "conversation_id": conversation.id, "unread_count": 0})


def _apply_conversation_channel_policy(conversation: AISalesConversation) -> None:
    reply_mode = (conversation.channel.reply_mode or "ai").strip().lower()
    use_ai = reply_mode == "ai"
    use_employee = reply_mode == "employee"
    conversation.status = "waiting_employee" if use_employee else "open"
    conversation.ai_enabled = use_ai
    conversation.human_takeover = use_employee
    conversation.assigned_employee_id = conversation.channel.default_employee_id
    conversation.closed_at = None


@ai_sales_bp.route("/api/conversations/<int:conversation_id>/close", methods=["POST"])
def api_close_conversation(conversation_id):
    denied = _api_guard()
    if denied:
        return denied
    conversation = AISalesConversation.query.get_or_404(conversation_id)
    if not _conversation_allowed(conversation):
        return jsonify({"success": False, "error": "هذه المحادثة محولة إلى موظف آخر"}), 403
    conversation.status = "closed"
    conversation.closed_at = datetime.utcnow()
    conversation.ai_enabled = False
    conversation.human_takeover = False
    conversation.assigned_employee_id = conversation.channel.default_employee_id
    db.session.commit()
    return jsonify({"success": True, "conversation": conversation.to_dict()})


@ai_sales_bp.route("/api/conversations/<int:conversation_id>/reopen", methods=["POST"])
def api_reopen_conversation(conversation_id):
    denied = _api_guard()
    if denied:
        return denied
    conversation = AISalesConversation.query.get_or_404(conversation_id)
    if not _conversation_allowed(conversation):
        return jsonify({"success": False, "error": "هذه المحادثة محولة إلى موظف آخر"}), 403
    _apply_conversation_channel_policy(conversation)
    db.session.commit()
    return jsonify({"success": True, "conversation": conversation.to_dict()})


@ai_sales_bp.route("/api/messages/<int:message_id>/media")
def api_message_media(message_id):
    denied = _api_guard()
    if denied:
        return denied
    message = AISalesMessage.query.get_or_404(message_id)
    if not _conversation_allowed(message.conversation):
        return jsonify({"success": False, "error": "هذه المحادثة تابعة إلى صفحة غير مسجلة لك"}), 403
    target = _message_file(message)
    if not target:
        return jsonify({"success": False, "error": "ملف الوسائط غير موجود"}), 404
    return send_file(target, mimetype=message.mime_type or None, conditional=True)


def _public_message_media_response(message_id: int, token: str):
    message = AISalesMessage.query.get_or_404(message_id)
    expected = str(message.get_media_metadata().get("public_token") or "")
    if not expected or not secrets.compare_digest(expected, str(token or "")):
        return Response("Forbidden", status=403, content_type="text/plain")
    target = _message_file(message)
    if not target:
        return Response("Not found", status=404, content_type="text/plain")
    return send_file(target, mimetype=message.mime_type or None, conditional=True, max_age=3600)


@ai_sales_bp.route("/public/media/<int:message_id>/<token>")
def public_message_media(message_id, token):
    return _public_message_media_response(message_id, token)


@ai_sales_bp.route("/public/media/<tenant_slug>/<int:message_id>/<token>")
def public_tenant_message_media(tenant_slug, message_id, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", tenant_slug or ""):
        return Response("Not found", status=404, content_type="text/plain")
    g.tenant = tenant_slug
    return _public_message_media_response(message_id, token)


@ai_sales_bp.route("/api/messages/<int:message_id>", methods=["DELETE", "PATCH"])
def api_message_action(message_id):
    denied = _api_guard()
    if denied:
        return denied
    message = AISalesMessage.query.get_or_404(message_id)
    if not _conversation_allowed(message.conversation):
        return jsonify({"success": False, "error": "هذه المحادثة محولة إلى موظف آخر"}), 403

    metadata = message.get_media_metadata()
    if request.method == "DELETE":
        if request.args.get("scope") == "everyone":
            return jsonify({
                "success": False,
                "error": "Meta لا توفر حذف الرسالة عند الطرفين عبر WhatsApp Cloud API أو Messaging API",
                "unsupported": True,
            }), 409
        metadata.update({
            "deleted_local": True,
            "deleted_at": datetime.utcnow().isoformat(),
            "deleted_by_employee_id": session.get("user_id"),
        })
        message.set_media_metadata(metadata)
        db.session.commit()
        return jsonify({"success": True, "message": message.to_dict()})

    text_value = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text_value:
        return jsonify({"success": False, "error": "اكتب نص الرسالة"}), 400
    editable = bool(
        not metadata.get("deleted_local")
        and message.direction == "outbound"
        and message.sender_type == "employee"
        and message.message_type == "text"
        and (message.status in {"queued", "failed"} or str(message.external_message_id or "").startswith("sim-"))
    )
    if not editable:
        return jsonify({
            "success": False,
            "error": "Meta لا تسمح بتعديل الرسالة بعد إرسالها؛ استخدم إرسال تصحيح",
            "unsupported": True,
        }), 409

    history = list(metadata.get("edit_history") or [])[-9:]
    history.append({"text": message.text_content or "", "edited_at": datetime.utcnow().isoformat()})
    metadata["edit_history"] = history
    metadata["edited_at"] = datetime.utcnow().isoformat()
    message.set_media_metadata(metadata)
    message.text_content = text_value[:4096]
    message.failure_code = None
    message.failure_message = None

    if str(message.external_message_id or "").startswith("sim-"):
        db.session.commit()
        return jsonify({"success": True, "message": message.to_dict()})

    try:
        conversation = message.conversation
        recipient = conversation.external_phone if conversation.channel.channel_type == "whatsapp" else conversation.external_contact_id
        body = channel_client(conversation.channel).send_text(recipient, message.text_content)
        message.external_message_id = outbound_message_id(body) or None
        message.status = "sent"
        message.sent_at = datetime.utcnow()
        conversation.last_business_message_at = message.sent_at
        db.session.commit()
        return jsonify({"success": True, "message": message.to_dict()})
    except Exception as exc:
        message.status = "failed"
        message.failure_message = str(exc)
        db.session.commit()
        return jsonify({"success": False, "error": str(exc), "message": message.to_dict()}), 400


@ai_sales_bp.route("/api/conversations/<int:conversation_id>/takeover", methods=["POST"])
def api_takeover(conversation_id):
    denied = _api_guard()
    if denied:
        return denied
    row = AISalesConversation.query.get_or_404(conversation_id)
    if not _conversation_allowed(row):
        return jsonify({"success": False, "error": "هذه المحادثة محولة إلى موظف آخر"}), 403
    pause_conversation_for_human(
        row,
        employee_id=session.get("user_id"),
        reason="استلام المحادثة يدوياً",
        indefinite=True,
    )
    db.session.commit()
    return jsonify({"success": True, "conversation": row.to_dict()})


@ai_sales_bp.route("/api/conversations/<int:conversation_id>/release", methods=["POST"])
def api_release(conversation_id):
    denied = _api_guard()
    if denied:
        return denied
    row = AISalesConversation.query.get_or_404(conversation_id)
    if not _conversation_allowed(row):
        return jsonify({"success": False, "error": "هذه المحادثة محولة إلى موظف آخر"}), 403
    _apply_conversation_channel_policy(row)
    row.ai_paused_until = None
    row.handoff_reason = None
    db.session.commit()
    return jsonify({"success": True, "conversation": row.to_dict()})


@ai_sales_bp.route("/api/conversations/<int:conversation_id>/send", methods=["POST"])
def api_manual_send(conversation_id):
    denied = _api_guard()
    if denied:
        return denied
    conversation = AISalesConversation.query.get_or_404(conversation_id)
    if not _conversation_allowed(conversation):
        return jsonify({"success": False, "error": "هذه المحادثة محولة إلى موظف آخر"}), 403
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "اكتب الرسالة"}), 400
    message = AISalesMessage(
        conversation_id=conversation.id,
        channel_account_id=conversation.channel_account_id,
        direction="outbound",
        sender_type="employee",
        message_type="text",
        text_content=text[:4096],
        status="queued",
    )
    db.session.add(message)
    db.session.flush()
    try:
        recipient = conversation.external_phone if conversation.channel.channel_type == "whatsapp" else conversation.external_contact_id
        body = channel_client(conversation.channel).send_text(recipient, text)
        message.external_message_id = outbound_message_id(body) or None
        message.status = "sent"
        message.sent_at = datetime.utcnow()
        conversation.last_business_message_at = message.sent_at
        pause_conversation_for_human(
            conversation,
            employee_id=session.get("user_id"),
            reason="رد موظف من Finora",
        )
        db.session.commit()
        response_message = message.to_dict()
        _capture_employee_learning_safely(message.id)
        return jsonify({"success": True, "message": response_message})
    except Exception as exc:
        message.status = "failed"
        message.failure_message = str(exc)
        db.session.commit()
        return jsonify({"success": False, "error": str(exc), "message": message.to_dict()}), 400


@ai_sales_bp.route("/api/conversations/<int:conversation_id>/send-media", methods=["POST"])
def api_manual_send_media(conversation_id):
    denied = _api_guard()
    if denied:
        return denied
    conversation = AISalesConversation.query.get_or_404(conversation_id)
    if not _conversation_allowed(conversation):
        return jsonify({"success": False, "error": "هذه المحادثة محولة إلى موظف آخر"}), 403
    if conversation.status == "closed":
        return jsonify({"success": False, "error": "أعد فتح المحادثة قبل الإرسال"}), 409

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"success": False, "error": "اختر صورة أو فيديو أو ملفاً صوتياً"}), 400
    mime_type = str(upload.mimetype or "").split(";", 1)[0].strip().lower()
    rule = CHAT_MEDIA_RULES.get(mime_type)
    if not rule:
        return jsonify({"success": False, "error": "صيغة الملف غير مدعومة"}), 400
    media_type, extension, max_bytes = rule
    if conversation.channel.channel_type == "instagram" and media_type != "image":
        return jsonify({"success": False, "error": "إنستغرام يدعم إرسال الصور فقط حالياً"}), 400

    content = upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        return jsonify({"success": False, "error": f"حجم الملف يتجاوز {limit_mb} MB"}), 413
    if not content:
        return jsonify({"success": False, "error": "الملف فارغ"}), 400

    tenant = str(getattr(g, "tenant", "core"))
    folder = Path(current_app.root_path) / "uploads" / "ai_sales" / tenant / "outbound"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{datetime.utcnow():%Y%m%d%H%M%S}-{secrets.token_hex(8)}{extension}"
    target.write_bytes(content)
    voice_note = str(request.form.get("voice_note") or "").lower() in {"1", "true", "yes"}
    try:
        if media_type == "audio" and (voice_note or mime_type in {"audio/webm", "audio/wav", "audio/x-wav"}):
            target, mime_type = _transcode_voice(target)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    caption = str(request.form.get("caption") or "").strip()[:1024]
    public_token = secrets.token_urlsafe(24)
    message = AISalesMessage(
        conversation_id=conversation.id,
        channel_account_id=conversation.channel_account_id,
        direction="outbound",
        sender_type="employee",
        message_type=media_type,
        text_content=caption,
        mime_type=mime_type,
        media_path=str(target),
        status="queued",
    )
    message.set_media_metadata({
        "original_filename": Path(upload.filename).name[:240],
        "file_size": target.stat().st_size,
        "public_token": public_token,
        "voice_note": voice_note,
    })
    db.session.add(message)
    db.session.commit()

    try:
        recipient = conversation.external_phone if conversation.channel.channel_type == "whatsapp" else conversation.external_contact_id
        client = channel_client(conversation.channel)
        if conversation.channel.channel_type == "whatsapp":
            media_id = client.upload_media(str(target), mime_type)
            body = client.send_media(
                recipient,
                media_type,
                media_id=media_id,
                caption=caption if media_type in {"image", "video"} else "",
            )
            message.external_media_id = media_id
            if caption and media_type == "audio":
                client.send_text(recipient, caption)
        else:
            public_url = f"{_public_base_url()}/ai-sales/public/media/{tenant}/{message.id}/{public_token}"
            body = client.send_media(recipient, media_type, url=public_url)
            if caption:
                client.send_text(recipient, caption)
        message.external_message_id = outbound_message_id(body) or None
        message.status = "sent"
        message.sent_at = datetime.utcnow()
        conversation.last_business_message_at = message.sent_at
        pause_conversation_for_human(
            conversation,
            employee_id=session.get("user_id"),
            reason="وسائط أرسلها موظف من Finora",
        )
        db.session.commit()
        return jsonify({"success": True, "message": message.to_dict()})
    except Exception as exc:
        message.status = "failed"
        message.failure_message = str(exc)
        db.session.commit()
        return jsonify({"success": False, "error": str(exc), "message": message.to_dict()}), 400


@ai_sales_bp.route("/api/leads")
def api_leads():
    denied = _api_guard()
    if denied:
        return denied
    query = AISalesLead.query
    if not _can_manage():
        visible_ids = _scope_conversations(AISalesConversation.query).with_entities(AISalesConversation.id)
        query = query.filter(AISalesLead.conversation_id.in_(visible_ids))
    rows = query.order_by(AISalesLead.score.desc(), AISalesLead.updated_at.desc()).limit(300).all()
    return jsonify({"success": True, "leads": [row.to_dict() for row in rows]})


@ai_sales_bp.route("/api/products")
def api_products():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    term = (request.args.get("q") or "").strip()
    limit = max(1, min(request.args.get("limit", type=int) or 300, 1000))
    query = Product.query
    if term:
        query = query.filter(or_(
            Product.name.ilike(f"%{term}%"),
            Product.sku.ilike(f"%{term}%"),
            Product.barcode.ilike(f"%{term}%"),
        ))
    rows = query.order_by(Product.name.asc()).limit(limit).all()
    profiles = {
        profile.product_id: profile
        for profile in AISalesProductProfile.query.filter(
            AISalesProductProfile.product_id.in_([row.id for row in rows])
        ).all()
    } if rows else {}
    return jsonify(
        {
            "success": True,
            "products": [
                {
                    "id": row.id,
                    "name": row.name or "",
                    "price": row.sale_price or 0,
                    "knowledge_score": _knowledge_payload(row, profiles.get(row.id))["knowledge_score"],
                }
                for row in rows
            ],
        }
    )


@ai_sales_bp.route("/api/product-knowledge/<int:product_id>", methods=["GET", "PUT"])
def api_product_knowledge(product_id: int):
    denied = _api_guard(manage=True)
    if denied:
        return denied
    product = Product.query.get_or_404(product_id)
    profile = AISalesProductProfile.query.filter_by(product_id=product.id).first()
    if request.method == "GET":
        return jsonify({"success": True, "knowledge": _knowledge_payload(product, profile)})

    data = request.get_json(silent=True) or {}
    if not profile:
        profile = AISalesProductProfile(product_id=product.id)
        db.session.add(profile)
    product.description = str(data.get("description") or "").strip()
    profile.marketing_name = str(data.get("marketing_name") or "").strip() or None
    profile.aliases_json = json.dumps(_string_list(data.get("aliases")), ensure_ascii=False)
    profile.selling_points_json = json.dumps(_string_list(data.get("selling_points")), ensure_ascii=False)
    profile.ideal_for_json = json.dumps(_string_list(data.get("ideal_for")), ensure_ascii=False)
    profile.objections_json = json.dumps(_objection_map(data.get("objections")), ensure_ascii=False)
    profile.warranty_text = str(data.get("warranty") or "").strip()[:220] or None
    profile.delivery_text = str(data.get("delivery") or "").strip()[:220] or None
    profile.colors_json = json.dumps(_string_list(data.get("colors")), ensure_ascii=False)
    try:
        profile.width_cm = _optional_measurement(data.get("width_cm"))
        profile.height_cm = _optional_measurement(data.get("height_cm"))
        profile.depth_cm = _optional_measurement(data.get("depth_cm"))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    profile.ai_notes = str(data.get("sales_notes") or "").strip() or None
    profile.allow_price = bool(data.get("allow_price", True))
    profile.allow_recommendation = bool(data.get("allow_recommendation", True))
    profile.is_active = bool(data.get("is_active", True))
    db.session.commit()
    return jsonify({"success": True, "knowledge": _knowledge_payload(product, profile)})


@ai_sales_bp.route("/api/learning", methods=["GET"])
def api_learning():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    entries = (
        AISalesKnowledgeEntry.query
        .order_by(AISalesKnowledgeEntry.is_active.desc(), AISalesKnowledgeEntry.updated_at.desc())
        .limit(500)
        .all()
    )
    imports = AISalesLearningImport.query.order_by(AISalesLearningImport.created_at.desc()).limit(10).all()
    return jsonify({
        "success": True,
        "stats": {
            "approved": AISalesReplyExample.query.filter(AISalesReplyExample.is_active.is_(True)).count(),
            "pending": AISalesReplyExample.query.filter(
                AISalesReplyExample.curation_status.in_(("pending", "review_failed"))
            ).count(),
            "rejected": AISalesReplyExample.query.filter(AISalesReplyExample.is_active.is_(False)).count(),
            "continuous": AISalesReplyExample.query.filter_by(source_type="employee_continuous").count(),
            "problems": sum(1 for row in entries if row.is_active),
            "excel_sources": AISalesLearningImport.query.filter(
                AISalesLearningImport.status.in_(("completed", "completed_with_errors"))
            ).count(),
        },
        "entries": [row.to_dict() for row in entries],
        "imports": [row.to_dict() for row in imports],
    })


@ai_sales_bp.route("/api/learning/problems", methods=["POST"])
@ai_sales_bp.route("/api/learning/problems/<int:entry_id>", methods=["PUT", "DELETE"])
def api_learning_problem(entry_id=None):
    denied = _api_guard(manage=True)
    if denied:
        return denied
    entry = AISalesKnowledgeEntry.query.get_or_404(entry_id) if entry_id else None
    if request.method == "DELETE":
        db.session.delete(entry)
        db.session.commit()
        return jsonify({"success": True})
    try:
        entry = save_problem_entry(request.get_json(silent=True) or {}, entry=entry, source_type="manual")
        db.session.commit()
        return jsonify({"success": True, "entry": entry.to_dict()})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@ai_sales_bp.route("/api/learning/template", methods=["GET"])
def api_learning_template():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    return send_file(
        build_learning_template(),
        as_attachment=True,
        download_name="Finora-Sales-AI-Learning.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@ai_sales_bp.route("/api/learning/import", methods=["POST"])
def api_learning_import():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"success": False, "error": "اختر ملف Excel أولاً"}), 400
    if not str(upload.filename).lower().endswith(".xlsx"):
        return jsonify({"success": False, "error": "الصيغة المطلوبة هي XLSX"}), 400
    try:
        result = import_learning_workbook(upload.read(8 * 1024 * 1024 + 1), upload.filename)
        return jsonify({"success": True, "import": result})
    except Exception as exc:
        current_app.logger.exception("Finora Sales AI workbook import failed")
        return jsonify({"success": False, "error": str(exc)}), 400


@ai_sales_bp.route("/api/learning/scan-employee-replies", methods=["POST"])
def api_learning_scan_employee_replies():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    profile = AISalesAgentProfile.query.order_by(AISalesAgentProfile.id.asc()).first()
    if profile and (not profile.continuous_learning_enabled or not profile.learn_from_employee_replies):
        return jsonify({"success": False, "error": "فعّل التعلم من ردود الموظفين أولاً"}), 409
    return jsonify({"success": True, "result": capture_new_employee_reply_examples(limit=2000)})


@ai_sales_bp.route("/api/product-media", methods=["GET", "POST"])
def api_product_media():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    if request.method == "GET":
        product_id = request.args.get("product_id", type=int)
        q = ProductMediaAsset.query
        if product_id:
            q = q.filter_by(product_id=product_id)
        rows = q.order_by(ProductMediaAsset.created_at.desc()).limit(300).all()
        return jsonify(
            {
                "success": True,
                "media": [
                    {
                        "id": row.id,
                        "product_id": row.product_id,
                        "product_name": row.product.name if row.product else "",
                        "media_type": row.media_type,
                        "title": row.title or "",
                        "public_url": row.public_url or "",
                        "has_local_file": bool(row.storage_path and not row.public_url),
                        "mime_type": row.mime_type or "",
                        "tags": row.get_tags(),
                        "ai_approved": bool(row.ai_approved),
                        "is_primary": bool(row.is_primary),
                    }
                    for row in rows
                ],
            }
        )

    product_id = request.form.get("product_id", type=int) if request.form else None
    data = request.get_json(silent=True) or {}
    product_id = product_id or int(data.get("product_id") or 0)
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404
    media_type = (request.form.get("media_type") if request.form else data.get("media_type") or "image").strip().lower()
    if media_type not in {"image", "video", "audio"}:
        return jsonify({"success": False, "error": "نوع الوسائط غير مدعوم"}), 400
    title = (request.form.get("title") if request.form else data.get("title") or product.name).strip()[:220]
    tags_raw = request.form.get("tags") if request.form else data.get("tags") or []
    tags = [part.strip() for part in tags_raw.split(",") if part.strip()] if isinstance(tags_raw, str) else [str(part).strip() for part in tags_raw if str(part).strip()]
    public_url = (request.form.get("public_url") if request.form else data.get("public_url") or "").strip()
    storage_path = public_url
    mime_type = ""
    upload = request.files.get("file") if request.files else None
    if upload and upload.filename:
        mime_type = (upload.mimetype or "application/octet-stream").split(";", 1)[0].lower()
        expected_prefix = "image/" if media_type == "image" else "video/" if media_type == "video" else "audio/"
        if not mime_type.startswith(expected_prefix):
            return jsonify({"success": False, "error": "نوع الملف لا يطابق نوع الوسائط"}), 400
        max_bytes = 50 * 1024 * 1024
        content = upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            return jsonify({"success": False, "error": "حجم الملف أكبر من 50MB"}), 400
        ext = Path(upload.filename).suffix.lower()[:10] or ".bin"
        folder = Path(current_app.root_path) / "uploads" / "ai_sales" / str(getattr(g, "tenant", "core")) / "product_media"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{secrets.token_hex(16)}{ext}"
        target.write_bytes(content)
        storage_path = str(target)
        public_url = ""
    if not storage_path:
        return jsonify({"success": False, "error": "ارفع ملفاً أو أدخل رابطاً عاماً"}), 400
    primary_raw = data.get("is_primary") if request.is_json else request.form.get("is_primary")
    is_primary = str(primary_raw or "").strip().lower() in {"1", "true", "yes", "on"}
    row = ProductMediaAsset(
        product_id=product.id,
        media_type=media_type,
        storage_path=storage_path,
        public_url=public_url or None,
        title=title,
        tags_json=json.dumps(tags, ensure_ascii=False),
        mime_type=mime_type or None,
        file_size=len(content) if upload and upload.filename else 0,
        ai_approved=True,
        is_primary=is_primary,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"success": True, "media_id": row.id})


@ai_sales_bp.route("/api/product-media/<int:media_id>", methods=["DELETE"])
def api_delete_product_media(media_id):
    denied = _api_guard(manage=True)
    if denied:
        return denied
    row = ProductMediaAsset.query.get_or_404(media_id)
    path = Path(row.storage_path) if row.storage_path and not row.public_url else None
    db.session.delete(row)
    db.session.commit()
    if path and path.is_file():
        allowed = (Path(current_app.root_path) / "uploads" / "ai_sales").resolve()
        try:
            path.resolve().relative_to(allowed)
            path.unlink(missing_ok=True)
        except ValueError:
            pass
    return jsonify({"success": True})


@ai_sales_bp.route("/api/channels", methods=["GET", "POST"])
def api_channels():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    if request.method == "GET":
        rows = AISalesChannelAccount.query.order_by(AISalesChannelAccount.id.asc()).all()
        base = _public_base_url()
        return jsonify(
            {
                "success": True,
                "channels": [
                    {
                        **row.to_dict(),
                        "webhook_url": _channel_webhook_url(row, getattr(g, "tenant", ""), base),
                    }
                    for row in rows
                ],
            }
        )
    data = request.get_json(silent=True) or {}
    channel_id = int(data.get("id") or 0)
    channel_type = str(data.get("channel_type") or "whatsapp").strip().lower()
    if channel_type not in {"whatsapp", "meta", "messenger", "instagram"}:
        return jsonify({"success": False, "error": "نوع القناة غير مدعوم"}), 400
    channel = AISalesChannelAccount.query.get(channel_id) if channel_id else AISalesChannelAccount(name="WhatsApp", channel_type=channel_type)
    is_new = channel.id is None
    if is_new:
        db.session.add(channel)
    channel.name = (data.get("name") or channel.name or "WhatsApp").strip()[:150]
    channel.channel_type = channel_type if not channel_id else channel.channel_type
    channel.phone_number = (data.get("phone_number") or channel.phone_number or "").strip()[:40]
    channel.phone_number_id = (data.get("phone_number_id") or channel.phone_number_id or "").strip()[:100]
    channel.waba_id = (data.get("waba_id") or channel.waba_id or "").strip()[:100]
    channel.api_version = (data.get("api_version") or channel.api_version or "v23.0").strip()[:20]
    if channel.channel_type == "meta" and "external_account_id" in data:
        channel.external_account_id = str(data.get("external_account_id") or "").strip()[:128] or None
    if "reply_mode" in data:
        reply_mode = str(data.get("reply_mode") or "inbox").strip().lower()
        if reply_mode not in {"ai", "inbox", "employee"}:
            return jsonify({"success": False, "error": "طريقة التوجيه غير صحيحة"}), 400
        channel.reply_mode = reply_mode
    if "comments_enabled" in data:
        channel.comments_enabled = bool(data.get("comments_enabled"))
    if "comments_reply_mode" in data:
        comments_reply_mode = str(data.get("comments_reply_mode") or "inbox").strip().lower()
        if comments_reply_mode not in {"ai", "inbox"}:
            return jsonify({"success": False, "error": "طريقة التعامل مع التعليقات غير صحيحة"}), 400
        channel.comments_reply_mode = comments_reply_mode
    if "comments_private_reply" in data:
        channel.comments_private_reply = bool(data.get("comments_private_reply"))
    if "comments_public_text" in data:
        channel.comments_public_text = str(data.get("comments_public_text") or "تم الرد على الخاص").strip()[:300]
    if "default_employee_id" in data:
        employee_id = int(data.get("default_employee_id") or 0) or None
        if employee_id and not Employee.query.filter_by(id=employee_id, is_active=True).first():
            return jsonify({"success": False, "error": "الموظف المحدد غير موجود"}), 400
        channel.default_employee_id = employee_id
    if (
        channel.channel_type in {"messenger", "instagram"}
        and channel.reply_mode == "employee"
        and not channel.default_employee_id
    ):
        return jsonify({
            "success": False,
            "error": "اختر الموظف المسؤول، أو غيّر طريقة التعامل إلى استقبال فقط أو الذكاء",
        }), 400
    if "is_active" in data:
        channel.is_active = bool(data.get("is_active"))
    verify_token_once = ""
    if data.get("access_token") and channel.channel_type != "meta":
        channel.access_token_encrypted = encrypt_secret(data["access_token"])
        _clear_meta_sync_failure(channel)
    if data.get("app_secret"):
        channel.app_secret_encrypted = encrypt_secret(data["app_secret"])
    if data.get("verify_token"):
        verify_token_once = str(data["verify_token"]).strip()
        channel.verify_token_encrypted = encrypt_secret(verify_token_once)
    elif not channel.verify_token_encrypted:
        verify_token_once = secrets.token_urlsafe(24)
        channel.verify_token_encrypted = encrypt_secret(verify_token_once)
    credentials_ready = bool(
        channel.access_token_encrypted and channel.phone_number_id
        if channel.channel_type == "whatsapp"
        else channel.app_secret_encrypted and channel.verify_token_encrypted
    )
    if not credentials_ready:
        channel.connection_status = "draft"
    elif channel.connection_status not in {"verified", "connected"}:
        channel.connection_status = "ready"
    db.session.commit()
    tenant_slug = getattr(g, "tenant", "") or ""
    payload = channel.to_dict()
    payload["webhook_url"] = _channel_webhook_url(channel, tenant_slug)
    if channel.channel_type in {"messenger", "instagram"}:
        _apply_meta_channel_policy(channel)
        db.session.commit()
    return jsonify({"success": True, "channel": payload})


def _safe_calling_settings(body: dict | None) -> dict:
    calling = (body or {}).get("calling") or {}
    restrictions = calling.get("restrictions") or {}
    call_hours = calling.get("call_hours") or {}
    return {
        "status": str(calling.get("status") or "UNKNOWN").upper(),
        "call_icon_visibility": str(calling.get("call_icon_visibility") or ""),
        "callback_permission_status": str(calling.get("callback_permission_status") or ""),
        "call_hours": {
            "status": str(call_hours.get("status") or ""),
            "timezone_id": str(call_hours.get("timezone_id") or ""),
        },
        "sip_status": str(((calling.get("sip") or {}).get("status") or "DISABLED")).upper(),
        "voicemail_status": str(((calling.get("voicemail") or {}).get("status") or "DISABLED")).upper(),
        "restrictions": restrictions.get("restrictions_list") or [],
    }


@ai_sales_bp.route("/api/channels/<int:channel_id>/calling", methods=["GET"])
def api_whatsapp_calling_readiness(channel_id):
    denied = _api_guard(manage=True)
    if denied:
        return denied
    channel = AISalesChannelAccount.query.get_or_404(channel_id)
    if channel.channel_type != "whatsapp":
        return jsonify({"success": False, "error": "Calling API is available for WhatsApp channels only"}), 400
    checked_at = datetime.utcnow()
    try:
        settings = _safe_calling_settings(WhatsAppClient(channel).get_calling_settings())
        channel.calling_status = str(settings.get("status") or "unknown").lower()
        channel.calling_last_checked_at = checked_at
        channel.set_calling_settings(settings)
        if channel.connection_status == "auth_expired":
            channel.connection_status = "connected"
        channel.last_error = None
        db.session.commit()
        return jsonify({
            "success": True,
            "calling": settings,
            "ready_for_media": bool(
                settings.get("status") == "ENABLED"
                and not settings.get("restrictions")
                and settings.get("sip_status") == "ENABLED"
            ),
            "checked_at": checked_at.isoformat(),
        })
    except WhatsAppClientError as exc:
        auth_expired = exc.status_code == 401 or exc.meta_code == 190
        channel.calling_status = "auth_expired" if auth_expired else "error"
        channel.calling_last_checked_at = checked_at
        channel.last_error = str(exc)[:1000]
        if auth_expired:
            channel.connection_status = "auth_expired"
        db.session.commit()
        error = (exc.response_body or {}).get("error", {}) if isinstance(exc.response_body, dict) else {}
        return jsonify({
            "success": False,
            "calling_status": channel.calling_status,
            "error": str(exc),
            "meta_error_code": error.get("code") or exc.meta_code,
            "meta_error_subcode": error.get("error_subcode"),
            "checked_at": checked_at.isoformat(),
        }), 401 if auth_expired else 502


@ai_sales_bp.route("/api/calls", methods=["GET"])
def api_calls():
    denied = _api_guard()
    if denied:
        return denied
    query = AISalesCall.query.order_by(AISalesCall.created_at.desc())
    if not _can_manage():
        channel_ids = _employee_channel_ids()
        if not channel_ids:
            return jsonify({"success": True, "calls": []})
        query = query.filter(AISalesCall.channel_account_id.in_(channel_ids))
    channel_id = int(request.args.get("channel_id") or 0)
    if channel_id:
        query = query.filter(AISalesCall.channel_account_id == channel_id)
    rows = query.limit(min(max(int(request.args.get("limit") or 50), 1), 200)).all()
    return jsonify({"success": True, "calls": [row.to_dict() for row in rows]})


@ai_sales_bp.route("/api/meta/pages/bulk", methods=["POST"])
def api_meta_pages_bulk():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip().lower()
    if action not in {"activate", "deactivate", "ai", "inbox"}:
        return jsonify({"success": False, "error": "الإجراء الجماعي غير مدعوم"}), 400
    try:
        ids = sorted({int(value) for value in (data.get("ids") or []) if int(value) > 0})
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "معرّفات الصفحات غير صحيحة"}), 400
    if not ids or len(ids) > 500:
        return jsonify({"success": False, "error": "اختر من صفحة واحدة إلى 500 صفحة"}), 400
    channels = AISalesChannelAccount.query.filter(
        AISalesChannelAccount.id.in_(ids),
        AISalesChannelAccount.channel_type.in_(("messenger", "instagram")),
        AISalesChannelAccount.connection_status != "removed",
    ).all()
    conversations_updated = 0
    for channel in channels:
        if action == "activate":
            channel.is_active = True
        elif action == "deactivate":
            channel.is_active = False
        elif action == "ai":
            channel.is_active = True
            channel.reply_mode = "ai"
        else:
            channel.reply_mode = "inbox"
        conversations_updated += _apply_meta_channel_policy(channel)
    db.session.commit()
    return jsonify({
        "success": True,
        "action": action,
        "pages_updated": len(channels),
        "conversations_updated": conversations_updated,
    })


@ai_sales_bp.route("/api/meta/pages/<int:channel_id>", methods=["DELETE"])
def api_delete_meta_page(channel_id):
    denied = _api_guard(manage=True)
    if denied:
        return denied
    channel = AISalesChannelAccount.query.get_or_404(channel_id)
    if channel.channel_type not in {"messenger", "instagram"}:
        return jsonify({"success": False, "error": "القناة المحددة ليست صفحة Meta"}), 400
    channel.is_active = False
    channel.reply_mode = "inbox"
    channel.default_employee_id = None
    channel.access_token_encrypted = None
    channel.connection_status = "removed"
    channel.last_error = None
    channel.sync_blocked_until = None
    conversations_updated = _apply_meta_channel_policy(channel)
    db.session.commit()
    return jsonify({
        "success": True,
        "archived": True,
        "channel_id": channel.id,
        "conversations_updated": conversations_updated,
    })


@ai_sales_bp.route("/api/meta/pages/manual", methods=["POST"])
def api_connect_meta_page():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    connector_id = int(data.get("connector_id") or 0)
    page_token = str(data.get("page_access_token") or "").strip()
    if not connector_id or not page_token:
        return jsonify({"success": False, "error": "Page Access Token مطلوب لربط الصفحة"}), 400
    connector = AISalesChannelAccount.query.get_or_404(connector_id)
    if connector.channel_type != "meta":
        return jsonify({"success": False, "error": "القناة المحددة ليست اتصال Meta"}), 400
    if not connector.external_account_id or not connector.app_secret_encrypted or not connector.verify_token_encrypted:
        return jsonify({"success": False, "error": "احفظ Meta App ID وApp Secret وVerify Token أولاً"}), 400
    try:
        client = MetaMessagingClient(connector, access_token=page_token)
        profile = client.account_profile()
        page_id = str(profile.get("id") or "").strip()
        if not page_id:
            raise ValueError("تعذر قراءة Page ID من التوكن")
        requested_page_id = str(data.get("page_id") or "").strip()
        if requested_page_id and requested_page_id != page_id:
            return jsonify({"success": False, "error": "Page ID لا يطابق الصفحة التابعة للتوكن"}), 400
        callback_url = _channel_webhook_url(connector, getattr(g, "tenant", "") or "")
        verify_token = decrypt_secret(connector.verify_token_encrypted)
        client.configure_app_webhook(
            "page",
            callback_url,
            verify_token,
            "messages,messaging_postbacks,messaging_optins,messaging_referrals,message_deliveries,message_reads,feed",
        )
        messaging_subscription = True
        subscription_warning = ""
        try:
            client.subscribe_page(page_id)
        except MetaMessagingClientError as exc:
            # A content-only Page token can still power posts and comments. Do
            # not reject the whole connection because Messenger scopes are absent.
            if exc.meta_code != 200 or "pages_messaging" not in str(exc):
                raise
            client.subscribe_page(page_id, fields="feed")
            messaging_subscription = False
            subscription_warning = (
                "تم ربط المنشورات والتعليقات فقط. التوكن لا يحمل pages_messaging، "
                "لذلك لن يرسل رداً خاصاً حتى تضيف هذه الصلاحية."
            )
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400

    page = AISalesChannelAccount.query.filter_by(
        parent_channel_id=connector.id,
        channel_type="messenger",
        external_account_id=page_id,
    ).first()
    created = page is None
    if not page:
        page = AISalesChannelAccount(
            parent_channel_id=connector.id,
            channel_type="messenger",
            external_account_id=page_id,
            page_id=page_id,
            reply_mode="inbox",
        )
        db.session.add(page)
    picture_url = str((((profile.get("picture") or {}).get("data") or {}).get("url") or ""))
    page.name = str(profile.get("name") or data.get("page_name") or f"Facebook {page_id}")[:150]
    page.platform_username = page.name
    page.profile_picture_url = picture_url or page.profile_picture_url
    page.access_token_encrypted = encrypt_secret(page_token)
    page.app_secret_encrypted = connector.app_secret_encrypted
    page.api_version = connector.api_version
    page.is_active = True
    page.connection_status = "connected" if messaging_subscription else "comments_only"
    _clear_meta_sync_failure(page, connected=True)
    db.session.commit()
    payload = page.to_dict()
    payload["has_access_token"] = True
    return jsonify({
        "success": True,
        "created": created,
        "channel": payload,
        "messaging_subscription": messaging_subscription,
        "warning": subscription_warning,
    })


@ai_sales_bp.route("/api/meta/stop-ai", methods=["POST"])
def api_meta_stop_ai():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    channels = AISalesChannelAccount.query.filter(
        AISalesChannelAccount.channel_type.in_(("messenger", "instagram")),
    ).all()
    channel_ids = [channel.id for channel in channels]
    for channel in channels:
        channel.reply_mode = "inbox"
    conversations = []
    if channel_ids:
        conversations = AISalesConversation.query.filter(
            AISalesConversation.channel_account_id.in_(channel_ids),
            AISalesConversation.status != "closed",
        ).all()
    for conversation in conversations:
        conversation.ai_enabled = False
        conversation.human_takeover = False
        conversation.assigned_employee_id = conversation.channel.default_employee_id
        conversation.status = "open"
    db.session.commit()
    return jsonify({
        "success": True,
        "mode": "inbox",
        "pages_updated": len(channels),
        "conversations_updated": len(conversations),
    })


@ai_sales_bp.route("/api/employees")
def api_employees():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    rows = Employee.query.filter_by(is_active=True).order_by(Employee.name.asc()).all()
    return jsonify({"success": True, "employees": [{"id": row.id, "name": row.name, "role": row.role} for row in rows]})


@ai_sales_bp.route("/api/meta/sync-pages/<int:connector_id>", methods=["POST"])
def api_meta_sync_pages(connector_id):
    denied = _api_guard(manage=True)
    if denied:
        return denied
    connector = AISalesChannelAccount.query.get_or_404(connector_id)
    if connector.channel_type != "meta":
        return jsonify({"success": False, "error": "القناة المحددة ليست اتصال Meta"}), 400
    data = request.get_json(silent=True) or {}
    temporary_token = str(data.get("user_access_token") or "").strip()
    try:
        client = MetaMessagingClient(connector, access_token=temporary_token or None)
        if not connector.external_account_id:
            connector.external_account_id = str(client.token_info().get("app_id") or "") or None
            db.session.flush()
        callback_url = _channel_webhook_url(connector, getattr(g, "tenant", "") or "")
        verify_token = decrypt_secret(connector.verify_token_encrypted)
        client.configure_app_webhook(
            "page",
            callback_url,
            verify_token,
            "messages,messaging_postbacks,messaging_optins,messaging_referrals,message_deliveries,message_reads,feed",
        )
        try:
            client.configure_app_webhook("instagram", callback_url, verify_token, "messages,messaging_postbacks")
        except Exception as exc:
            current_app.logger.warning("Instagram app webhook registration skipped: %s", exc)
        pages = client.list_pages()
    except Exception as exc:
        db.session.rollback()
        connector = AISalesChannelAccount.query.get(connector_id)
        auth_expired = _record_meta_sync_failure(connector, exc)
        db.session.commit()
        return jsonify({
            "success": False,
            "error": str(exc),
            "requires_reconnect": auth_expired,
        }), 400

    imported = []
    warnings = []
    for page in pages:
        page_id = str(page.get("id") or "")
        page_token = str(page.get("access_token") or "")
        if not page_id or not page_token:
            continue
        picture_url = str((((page.get("picture") or {}).get("data") or {}).get("url") or ""))
        messenger = AISalesChannelAccount.query.filter_by(
            parent_channel_id=connector.id,
            channel_type="messenger",
            external_account_id=page_id,
        ).first()
        if not messenger:
            messenger = AISalesChannelAccount(
                parent_channel_id=connector.id,
                channel_type="messenger",
                external_account_id=page_id,
                page_id=page_id,
                reply_mode="inbox",
                is_active=True,
            )
            db.session.add(messenger)
        elif messenger.connection_status in {"unavailable", "removed"}:
            messenger.is_active = True
        messenger.name = str(page.get("name") or f"Facebook {page_id}")[:150]
        messenger.platform_username = messenger.name
        messenger.profile_picture_url = picture_url or None
        messenger.access_token_encrypted = encrypt_secret(page_token)
        messenger.app_secret_encrypted = connector.app_secret_encrypted
        messenger.api_version = connector.api_version
        messenger.connection_status = "connected"
        _clear_meta_sync_failure(messenger, connected=True)
        try:
            MetaMessagingClient(messenger).subscribe_page(page_id)
        except MetaMessagingClientError as exc:
            if exc.meta_code == 200 and "pages_messaging" in str(exc):
                try:
                    MetaMessagingClient(messenger).subscribe_page(page_id, fields="feed")
                    messenger.connection_status = "comments_only"
                    warnings.append(
                        f"{page.get('name') or page_id}: تم ربط التعليقات فقط؛ pages_messaging غير موجودة"
                    )
                except Exception as feed_exc:
                    warnings.append(f"{page.get('name') or page_id}: {feed_exc}")
            else:
                warnings.append(f"{page.get('name') or page_id}: {exc}")
        except Exception as exc:
            warnings.append(f"{page.get('name') or page_id}: {exc}")
        imported.append(messenger)

        instagram_data = page.get("instagram_business_account") or {}
        instagram_id = str(instagram_data.get("id") or "")
        if instagram_id:
            instagram = AISalesChannelAccount.query.filter_by(
                parent_channel_id=connector.id,
                channel_type="instagram",
                external_account_id=instagram_id,
            ).first()
            if not instagram:
                instagram = AISalesChannelAccount(
                    parent_channel_id=connector.id,
                    channel_type="instagram",
                    external_account_id=instagram_id,
                    page_id=page_id,
                    reply_mode="inbox",
                    is_active=True,
                )
                db.session.add(instagram)
            elif instagram.connection_status in {"unavailable", "removed"}:
                instagram.is_active = True
            instagram.name = str(instagram_data.get("name") or instagram_data.get("username") or f"Instagram {instagram_id}")[:150]
            instagram.platform_username = str(instagram_data.get("username") or "")[:150]
            instagram.profile_picture_url = str(instagram_data.get("profile_picture_url") or picture_url or "") or None
            instagram.access_token_encrypted = encrypt_secret(page_token)
            instagram.app_secret_encrypted = connector.app_secret_encrypted
            instagram.api_version = connector.api_version
            instagram.connection_status = "connected"
            _clear_meta_sync_failure(instagram, connected=True)
            try:
                MetaMessagingClient(instagram).subscribe_instagram(instagram_id)
            except Exception as exc:
                warnings.append(f"Instagram {instagram_data.get('username') or instagram_id}: {exc}")
            imported.append(instagram)

    db.session.flush()
    imported_channel_ids = [row.id for row in imported if row.id]
    unavailable_channel_ids = _mark_missing_meta_channels_unavailable(connector, imported_channel_ids)
    _clear_meta_sync_failure(connector)
    connector.access_token_encrypted = None
    connector.connection_status = "connected" if connector.last_webhook_at else "ready"
    connector.last_error = "\n".join(warnings[:10]) or None
    db.session.flush()
    if imported_channel_ids:
        conversations_without_picture = AISalesConversation.query.filter(
            AISalesConversation.channel_account_id.in_(imported_channel_ids),
            AISalesConversation.contact_profile_picture_url.is_(None),
        ).all()
        for conversation in conversations_without_picture:
            context = conversation.get_context()
            context.pop("meta_profile_checked_at", None)
            conversation.set_context(context)
    db.session.commit()
    return jsonify({
        "success": True,
        "pages_found": len(pages),
        "channels": [row.to_dict() for row in imported],
        "unavailable_channel_ids": unavailable_channel_ids,
        "warnings": warnings,
    })


def _parse_graph_datetime(value: str | None) -> datetime:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return datetime.utcnow()


def _meta_contact_identity(
    client: MetaMessagingClient,
    conversation: AISalesConversation | None,
    contact_id: str,
    fallback_name: str = "",
    fallback_picture=None,
) -> tuple[str, str, bool]:
    context = conversation.get_context() if conversation else {}
    fallback_picture_url = ""
    if isinstance(fallback_picture, str):
        fallback_picture_url = fallback_picture.strip()
    elif isinstance(fallback_picture, dict):
        fallback_picture_url = str(
            fallback_picture.get("url")
            or (fallback_picture.get("data") or {}).get("url")
            or ""
        ).strip()
    checked_at = _parse_graph_datetime(context.get("meta_profile_checked_at")) if context.get("meta_profile_checked_at") else None
    retry_allowed = not checked_at or checked_at < datetime.utcnow() - timedelta(hours=24)
    should_lookup = not fallback_picture_url and (conversation is None or (
        not conversation.contact_profile_picture_url
        and retry_allowed
    ))
    profile = client.contact_profile(contact_id) if should_lookup else {}
    profile_name = str(
        profile.get("name")
        or profile.get("username")
        or " ".join(part for part in (profile.get("first_name"), profile.get("last_name")) if part)
        or ""
    ).strip()
    picture = profile.get("profile_pic") or profile.get("profile_picture_url") or fallback_picture_url
    picture_url = str(picture).strip() if isinstance(picture, str) else ""
    name = profile_name or fallback_name or (conversation.contact_name if conversation else "") or contact_id
    return name, picture_url, should_lookup


def _mark_meta_profile_checked(conversation: AISalesConversation, checked: bool) -> None:
    if not checked:
        return
    context = conversation.get_context()
    context["meta_profile_checked_at"] = datetime.utcnow().isoformat()
    conversation.set_context(context)


def _merge_meta_ad_context(conversation: AISalesConversation, event: dict) -> bool:
    referral = event.get("referral") or {}
    ads_data = event.get("ads_context_data") or {}
    if not referral and not ads_data:
        return False
    context = conversation.get_context()
    previous = dict(context.get("ad_context") or {})
    merged = {
        **previous,
        "ad_id": str(referral.get("ad_id") or ads_data.get("ad_id") or previous.get("ad_id") or "")[:120],
        "source": str(referral.get("source") or previous.get("source") or "")[:60],
        "type": str(referral.get("type") or previous.get("type") or "")[:60],
        "ref": str(referral.get("ref") or previous.get("ref") or "")[:1000],
        "title": str(ads_data.get("ad_title") or ads_data.get("title") or previous.get("title") or "")[:500],
        "body": str(ads_data.get("ad_body") or ads_data.get("body") or previous.get("body") or "")[:1500],
        "image_url": str(ads_data.get("photo_url") or ads_data.get("image_url") or previous.get("image_url") or "")[:1500],
        "video_url": str(ads_data.get("video_url") or previous.get("video_url") or "")[:1500],
        "post_id": str(ads_data.get("post_id") or previous.get("post_id") or "")[:150],
        "product_id": str(ads_data.get("product_id") or previous.get("product_id") or "")[:150],
        "updated_at": datetime.utcnow().isoformat(),
    }
    context["ad_context"] = {key: value for key, value in merged.items() if value}
    conversation.set_context(context)
    return True


def _find_social_post_for_meta_context(channel: AISalesChannelAccount, meta_context: dict):
    reel_id = str(meta_context.get("reel_id") or "").strip()
    post_id = str(meta_context.get("post_id") or "").strip()
    if not reel_id and not post_id:
        return None
    posts = AISalesSocialPost.query.filter_by(channel_account_id=channel.id).all()
    for post in posts:
        permalink = str(post.permalink_url or "")
        external_id = str(post.external_post_id or "")
        if reel_id and (f"/reel/{reel_id}" in permalink or f"/videos/{reel_id}" in permalink):
            return post
        if post_id and (external_id == post_id or external_id.endswith(f"_{post_id}") or post_id in permalink):
            return post
    return None


def _message_origin_metadata(
    channel: AISalesChannelAccount,
    text: str,
    *,
    event: dict | None = None,
    conversation: AISalesConversation | None = None,
    include_conversation_ad: bool = False,
) -> dict:
    metadata: dict = {}
    meta_context = extract_meta_system_message_context(text)
    if meta_context:
        post = _find_social_post_for_meta_context(channel, meta_context)
        if post:
            post_title = str(post.message or post.story or "منشور الصفحة").strip()
            meta_context["post"] = {
                "id": post.id,
                "external_post_id": post.external_post_id or "",
                "title": post_title[:500],
                "image_url": post.media_url or "",
                "media_type": post.media_type or "",
                "permalink_url": post.permalink_url or meta_context.get("url") or "",
            }
        metadata["meta_context"] = meta_context

    referral = (event or {}).get("referral") or {}
    ads_data = (event or {}).get("ads_context_data") or {}
    if referral or ads_data or include_conversation_ad:
        ad_context = dict((conversation.get_context().get("ad_context") if conversation else {}) or {})
        if ad_context:
            metadata["ad_context"] = ad_context
    return metadata


def _import_meta_channel(channel: AISalesChannelAccount, *, limit: int = 100) -> dict:
    client = MetaMessagingClient(channel)
    remote_conversations = client.list_conversations(limit=limit)
    conversations_created = 0
    messages_created = 0
    recent_inbound_by_conversation: dict[int, int] = {}
    recent_cutoff = datetime.utcnow() - timedelta(minutes=15)
    own_ids = {str(channel.external_account_id or ""), str(channel.page_id or "")}
    for remote in remote_conversations:
        participants = (remote.get("participants") or {}).get("data") or []
        contact = next((item for item in participants if str(item.get("id") or "") not in own_ids), None)
        if not contact:
            continue
        contact_id = str(contact.get("id") or "")
        existing = AISalesConversation.query.filter_by(channel_account_id=channel.id, external_contact_id=contact_id).first()
        contact_name, picture_url, profile_checked = _meta_contact_identity(
            client,
            existing,
            contact_id,
            str(contact.get("name") or contact.get("username") or ""),
            contact.get("picture"),
        )
        conversation = get_or_create_conversation(
            channel,
            external_contact_id=contact_id,
            phone="",
            contact_name=contact_name,
            contact_profile_picture_url=picture_url,
        )
        _mark_meta_profile_checked(conversation, profile_checked)
        conversations_created += int(existing is None)
        for remote_message in reversed(((remote.get("messages") or {}).get("data") or [])):
            external_id = str(remote_message.get("id") or "")
            if not external_id:
                continue
            sender_id = str((remote_message.get("from") or {}).get("id") or "")
            inbound = sender_id not in own_ids
            text_content = str(remote_message.get("message") or "")
            attachment = meta_attachment_details(remote_message.get("attachments"))
            message_type = attachment.get("type") or "text"
            attachment_url = str(attachment.get("url") or "")
            if message_type == "sticker":
                text_content = text_content or ("لايك" if attachment.get("is_like") else "[ملصق]")
                if attachment.get("is_like"):
                    message_type = "text"
            elif message_type not in {"image", "video", "audio", "file"}:
                message_type = "text"
            message_time = _parse_graph_datetime(remote_message.get("created_time"))
            if inbound:
                if not conversation.last_customer_message_at or message_time > conversation.last_customer_message_at:
                    mark_customer_activity(conversation, message_time)
            elif not conversation.last_business_message_at or message_time > conversation.last_business_message_at:
                conversation.last_business_message_at = message_time
            if AISalesMessage.query.filter_by(channel_account_id=channel.id, external_message_id=external_id).first():
                continue
            is_empty_opener = inbound and not str(text_content or "").strip() and message_type == "text"
            message = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                external_message_id=external_id,
                direction="inbound" if inbound else "outbound",
                sender_type="customer" if inbound else "employee",
                message_type="referral" if is_empty_opener else message_type,
                text_content=text_content or None,
                external_media_id=attachment_url or None,
                mime_type=attachment.get("mime_type") or None,
                status="received" if inbound else "sent",
                sent_at=None if inbound else message_time,
                created_at=message_time,
            )
            message.set_raw_payload(remote_message)
            origin_metadata = _message_origin_metadata(
                channel,
                text_content,
                conversation=conversation,
                include_conversation_ad=is_empty_opener,
            )
            if is_empty_opener:
                origin_metadata = {
                    **origin_metadata,
                    "thread_opener": True,
                    "synced_empty_opener": True,
                }
            attachment_metadata = {}
            if attachment.get("sticker_id"):
                attachment_metadata = {
                    "sticker_id": attachment.get("sticker_id"),
                    "is_like": bool(attachment.get("is_like")),
                }
            if attachment_url or origin_metadata or attachment_metadata:
                media_metadata = {**origin_metadata, **attachment_metadata}
                if attachment_url:
                    media_metadata.update({
                        "external_url": attachment_url,
                        "preview_url": attachment.get("preview_url") or "",
                    })
                message.set_media_metadata(media_metadata)
            db.session.add(message)
            db.session.flush()
            messages_created += 1
            actionable_text = message_type == "text" and bool(text_content.strip())
            actionable_media = message_type in {"image", "audio", "video"}
            if inbound and message.created_at >= recent_cutoff and (actionable_text or actionable_media):
                recent_inbound_by_conversation[conversation.id] = message.id
        conversation.updated_at = _parse_graph_datetime(remote.get("updated_time"))
    db.session.commit()
    return {
        "conversations_created": conversations_created,
        "messages_created": messages_created,
        "recent_inbound_ids": list(recent_inbound_by_conversation.values()),
    }


def _dispatch_recent_meta_messages(message_ids: list[int], *, asynchronous: bool = True) -> int:
    if not message_ids:
        return 0
    rows = AISalesMessage.query.filter(AISalesMessage.id.in_(message_ids)).all()
    dispatched = 0
    app = current_app._get_current_object()
    tenant_slug = getattr(g, "tenant", "") or ""
    for message in rows:
        conversation = message.conversation
        if conversation.human_takeover or not conversation.ai_enabled:
            continue
        older = AISalesMessage.query.filter(
            AISalesMessage.conversation_id == conversation.id,
            AISalesMessage.direction == "inbound",
            AISalesMessage.status == "received",
            AISalesMessage.id < message.id,
            AISalesMessage.created_at >= datetime.utcnow() - timedelta(minutes=15),
        ).all()
        for item in older:
            item.status = "processed"
        db.session.commit()
        if asynchronous:
            dispatch_inbound_async(app, tenant_slug, message.id, send_external=True)
            dispatched += 1
            continue
        try:
            process_inbound_message(message.id, send_external=True)
            dispatched += 1
        except Exception:
            current_app.logger.exception(
                "Finora Sales AI scheduled Meta message failed tenant=%s message_id=%s",
                tenant_slug,
                message.id,
            )
            db.session.rollback()
    return dispatched


def _find_pending_meta_ai_message_ids(
    channel_ids: list[int] | None = None,
    *,
    max_messages: int = 50,
) -> list[int]:
    """Find recent inbound Meta messages that were stored while AI sending was unavailable."""
    cutoff = datetime.utcnow() - META_PENDING_AI_WINDOW
    query = (
        AISalesMessage.query
        .join(AISalesConversation, AISalesConversation.id == AISalesMessage.conversation_id)
        .join(AISalesChannelAccount, AISalesChannelAccount.id == AISalesConversation.channel_account_id)
        .filter(
            AISalesChannelAccount.channel_type.in_(("messenger", "instagram")),
            AISalesChannelAccount.is_active.is_(True),
            AISalesMessage.direction == "inbound",
            AISalesMessage.status == "received",
            AISalesMessage.created_at >= cutoff,
            AISalesConversation.ai_enabled.is_(True),
            AISalesConversation.human_takeover.is_(False),
            AISalesConversation.status != "closed",
        )
        .order_by(AISalesMessage.created_at.desc(), AISalesMessage.id.desc())
    )
    if channel_ids:
        query = query.filter(AISalesConversation.channel_account_id.in_(channel_ids))
    candidates = query.limit(max_messages * 5).all()
    selected: list[int] = []
    seen_conversations: set[int] = set()
    for message in candidates:
        conversation = message.conversation
        if conversation.id in seen_conversations:
            continue
        if not (message.text_content or "").strip() and message.message_type not in {"image", "audio", "video"}:
            continue
        has_newer_reply = AISalesMessage.query.filter(
            AISalesMessage.conversation_id == conversation.id,
            AISalesMessage.direction == "outbound",
            AISalesMessage.created_at >= message.created_at,
        ).first()
        if has_newer_reply:
            continue
        selected.append(message.id)
        seen_conversations.add(conversation.id)
        if len(selected) >= max_messages:
            break
    selected.reverse()
    return selected


@ai_sales_bp.route("/api/meta/import-conversations/<int:channel_id>", methods=["POST"])
def api_meta_import_conversations(channel_id):
    denied = _api_guard(manage=True)
    if denied:
        return denied
    channel = AISalesChannelAccount.query.get_or_404(channel_id)
    if channel.channel_type not in {"messenger", "instagram"}:
        return jsonify({"success": False, "error": "الاستيراد متاح لماسنجر وإنستغرام فقط"}), 400
    try:
        result = _import_meta_channel(channel, limit=100)
    except Exception as exc:
        db.session.rollback()
        channel = AISalesChannelAccount.query.get(channel_id)
        auth_expired = _record_meta_sync_failure(channel, exc)
        db.session.commit()
        return jsonify({
            "success": False,
            "error": str(exc),
            "requires_reconnect": auth_expired,
        }), 400
    recent_ids = result.pop("recent_inbound_ids", [])
    pending_ids = _find_pending_meta_ai_message_ids([channel.id], max_messages=25)
    all_ids = list(dict.fromkeys([*recent_ids, *pending_ids]))
    dispatched = _dispatch_recent_meta_messages(all_ids)
    return jsonify({"success": True, **result, "ai_jobs": dispatched})


def _sync_meta_channels(*, ai_only: bool = False, asynchronous: bool = True) -> dict:
    channels_query = AISalesChannelAccount.query.filter(
        AISalesChannelAccount.channel_type.in_(("messenger", "instagram")),
        AISalesChannelAccount.is_active.is_(True),
    )
    if ai_only:
        active_ai_channels = db.session.query(AISalesConversation.channel_account_id).filter(
            AISalesConversation.ai_enabled.is_(True),
            AISalesConversation.human_takeover.is_(False),
            AISalesConversation.status != "closed",
        )
        channels_query = channels_query.filter(
            or_(
                AISalesChannelAccount.reply_mode == "ai",
                AISalesChannelAccount.id.in_(active_ai_channels),
            )
        )
    channels = channels_query.all()
    now = datetime.utcnow()
    totals = {
        "channels": 0,
        "eligible_channels": 0,
        "blocked_channels": [],
        "auth_expired_channels": [],
        "conversations_created": 0,
        "messages_created": 0,
        "errors": [],
    }
    recent_inbound_ids = []
    for channel in channels:
        if _meta_sync_is_blocked(channel, now):
            retry_seconds = max(1, int((channel.sync_blocked_until - now).total_seconds()))
            blocked = {
                "channel_id": channel.id,
                "name": channel.name,
                "retry_after_seconds": retry_seconds,
                "requires_reconnect": channel.connection_status == "auth_expired",
            }
            totals["blocked_channels"].append(blocked)
            if blocked["requires_reconnect"]:
                totals["auth_expired_channels"].append(blocked)
            continue
        totals["eligible_channels"] += 1
        try:
            result = _import_meta_channel(channel, limit=10 if ai_only else 25)
            channel.last_sync_at = datetime.utcnow()
            _clear_meta_sync_failure(channel, connected=True)
            db.session.commit()
            totals["channels"] += 1
            totals["conversations_created"] += result["conversations_created"]
            totals["messages_created"] += result["messages_created"]
            recent_inbound_ids.extend(result.get("recent_inbound_ids") or [])
            recent_inbound_ids.extend(
                _find_pending_meta_ai_message_ids([channel.id], max_messages=10)
            )
        except Exception as exc:
            db.session.rollback()
            failed_channel = AISalesChannelAccount.query.get(channel.id)
            auth_expired = _record_meta_sync_failure(failed_channel, exc)
            db.session.commit()
            failure = {
                "channel_id": failed_channel.id,
                "name": failed_channel.name,
                "error": str(exc),
                "meta_error_code": getattr(exc, "meta_code", None),
                "requires_reconnect": auth_expired,
                "retry_after_seconds": int(
                    (failed_channel.sync_blocked_until - datetime.utcnow()).total_seconds()
                ),
            }
            totals["errors"].append(failure)
            if auth_expired:
                totals["auth_expired_channels"].append(failure)
    totals["ai_jobs"] = _dispatch_recent_meta_messages(
        recent_inbound_ids,
        asynchronous=asynchronous,
    )
    retry_values = [
        int(item.get("retry_after_seconds") or 0)
        for item in totals["blocked_channels"] + totals["errors"]
        if int(item.get("retry_after_seconds") or 0) > 0
    ]
    totals["requires_page_refresh"] = bool(totals["auth_expired_channels"])
    # A child page token expiring does not prove the parent user token is invalid.
    # The parent is marked auth_expired only when syncing /me/accounts itself fails.
    totals["requires_reconnect"] = False
    totals["retry_after_seconds"] = min(retry_values) if retry_values else 0
    return totals


@ai_sales_bp.route("/api/meta/auto-sync", methods=["POST"])
def api_meta_auto_sync():
    denied = _api_guard()
    if denied:
        return denied
    # Live messages arrive through Meta webhooks. Older inbox builds called
    # this route every five seconds and made every open browser tab rescan all
    # pages, which caused SQLite contention and delayed the webhook itself.
    return jsonify({
        "success": True,
        "skipped": True,
        "reason": "webhook_realtime",
        "messages_created": 0,
        "ai_jobs": 0,
    })


@ai_sales_bp.route("/api/profile", methods=["GET", "PUT"])
def api_profile():
    denied = _api_guard(manage=request.method == "PUT")
    if denied:
        return denied
    profile = AISalesAgentProfile.query.order_by(AISalesAgentProfile.id.asc()).first()
    if request.method == "GET":
        payload = profile.to_dict()
        if not payload.get("voice_instructions") or is_corrupted_text(payload["voice_instructions"]):
            payload["voice_instructions"] = DEFAULT_VOICE_INSTRUCTIONS
        return jsonify({"success": True, "profile": payload})
    data = request.get_json(silent=True) or {}
    text_fields = (
        "name", "dialect", "tone", "sales_style", "text_model", "tts_model",
        "transcription_model", "realtime_model", "voice_reply_mode", "voice_name",
        "audio_format", "audio_quality", "voice_instructions", "system_instructions",
    )
    for field in text_fields:
        if field in data:
            setattr(profile, field, str(data[field] or "").strip())
    if is_corrupted_text(profile.voice_instructions or ""):
        return jsonify({"success": False, "error": "تعليمات نبرة الصوت تحتوي نصاً تالفاً"}), 400
    if profile.voice_reply_mode not in {"match_customer", "text_and_voice", "text_only", "voice_only"}:
        return jsonify({"success": False, "error": "طريقة الرد الصوتي غير صالحة"}), 400
    if profile.audio_format not in {"mp3", "opus", "aac", "flac", "wav"}:
        return jsonify({"success": False, "error": "صيغة الصوت غير صالحة"}), 400
    if profile.voice_name not in SUPPORTED_TTS_VOICES:
        return jsonify({"success": False, "error": "الصوت المحدد غير صالح"}), 400
    if profile.audio_quality not in {"professional", "standard", "original"}:
        return jsonify({"success": False, "error": "مستوى جودة الصوت غير صالح"}), 400
    if "voice_speed" in data:
        try:
            profile.voice_speed = float(data["voice_speed"])
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "سرعة الصوت غير صالحة"}), 400
    profile.voice_speed = min(max(float(profile.voice_speed or 0.96), 0.75), 1.25)
    intelligence_level = str(data.get("intelligence_level") or profile.intelligence_level or "expert").strip().lower()
    if intelligence_level not in {"fast", "professional", "expert", "elite"}:
        return jsonify({"success": False, "error": "درجة الذكاء غير صالحة"}), 400
    persuasion_style = str(data.get("persuasion_style") or profile.persuasion_style or "balanced").strip().lower()
    if persuasion_style not in {"gentle", "balanced", "assertive"}:
        return jsonify({"success": False, "error": "أسلوب الإقناع غير صالح"}), 400
    profile.intelligence_level = intelligence_level
    profile.persuasion_style = persuasion_style
    for field in (
        "max_reply_length", "handoff_threshold", "max_products", "max_context_messages",
        "max_audio_size_mb", "human_takeover_minutes", "ai_response_delay_ms", "learning_min_quality",
    ):
        if field in data:
            setattr(profile, field, int(data[field]))
    profile.max_reply_length = min(max(int(profile.max_reply_length or 650), 120), 1500)
    profile.handoff_threshold = min(max(int(profile.handoff_threshold or 45), 0), 100)
    profile.max_products = min(max(int(profile.max_products or 3), 1), 3)
    profile.max_context_messages = min(max(int(profile.max_context_messages or 18), 6), 30)
    profile.max_audio_size_mb = min(max(int(profile.max_audio_size_mb or 25), 1), 25)
    profile.human_takeover_minutes = min(max(int(profile.human_takeover_minutes or 30), 1), 1440)
    profile.ai_response_delay_ms = min(max(int(profile.ai_response_delay_ms or 0), 0), 3000)
    profile.learning_min_quality = min(max(int(profile.learning_min_quality or 76), 60), 95)
    for field in (
        "voice_enabled", "auto_escalation", "is_active",
        "continuous_learning_enabled", "learn_from_employee_replies",
    ):
        if field in data:
            setattr(profile, field, bool(data[field]))
    db.session.commit()
    return jsonify({"success": True, "profile": profile.to_dict()})


@ai_sales_bp.route("/api/openai/health")
def api_openai_health():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    profile = AISalesAgentProfile.query.order_by(AISalesAgentProfile.id.asc()).first()
    settings = settings_for_profile(profile)
    payload = {
        "success": True,
        "configured": bool(get_openai_api_key()),
        "models": settings.public_dict(),
        "validated": False,
    }
    if request.args.get("validate") in {"1", "true"} and payload["configured"]:
        try:
            get_openai_client().models.retrieve(settings.chat_model)
            payload["validated"] = True
        except Exception as exc:
            error = exc if isinstance(exc, AIServiceError) else AIServiceError("model_validation_failed", "health", str(exc))
            return jsonify({**payload, "success": False, "error": error.to_dict()}), 400
    return jsonify(payload)


@ai_sales_bp.route("/api/openai/test-speech", methods=["POST"])
def api_openai_test_speech():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    now = datetime.utcnow()
    last_test = session.get("ai_sales_last_tts_test")
    if last_test:
        try:
            if (now - datetime.fromisoformat(last_test)).total_seconds() < 5:
                return jsonify({"success": False, "error": "انتظر خمس ثوانٍ قبل إعادة تجربة الصوت"}), 429
        except (TypeError, ValueError):
            pass
    profile = AISalesAgentProfile.query.order_by(AISalesAgentProfile.id.asc()).first()
    settings = settings_for_profile(profile)
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "هلا بيك، هذا اختبار صوت المساعد الذكي في Finora.").strip()
    requested_format = str(data.get("audio_format") or settings.audio_format).strip().lower()
    requested_voice = str(data.get("voice") or settings.voice).strip()
    if requested_format not in {"mp3", "opus", "aac", "flac", "wav"}:
        return jsonify({"success": False, "error": "صيغة الصوت غير صالحة"}), 400
    if requested_voice not in SUPPORTED_TTS_VOICES:
        return jsonify({"success": False, "error": "الصوت المحدد غير صالح"}), 400
    requested_quality = str(data.get("audio_quality") or settings.audio_quality).strip().lower()
    if requested_quality not in {"professional", "standard", "original"}:
        return jsonify({"success": False, "error": "مستوى جودة الصوت غير صالح"}), 400
    try:
        requested_speed = min(max(float(data.get("voice_speed") or settings.voice_speed or 0.96), 0.75), 1.25)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "سرعة الصوت غير صالحة"}), 400
    settings = type(settings)(
        **{
            **settings.__dict__,
            "tts_model": str(data.get("tts_model") or settings.tts_model).strip(),
            "voice": requested_voice,
            "audio_format": requested_format,
            "voice_speed": requested_speed,
            "audio_quality": requested_quality,
            "voice_instructions": str(data.get("voice_instructions") or settings.voice_instructions).strip(),
        }
    )
    tenant = re.sub(r"[^A-Za-z0-9_-]", "", str(getattr(g, "tenant", "core") or "core")) or "core"
    folder = Path(current_app.root_path) / "uploads" / "ai_sales" / tenant / "tests"
    folder.mkdir(parents=True, exist_ok=True)
    for old_file in folder.glob("tts-test-*"):
        try:
            if now.timestamp() - old_file.stat().st_mtime > 3600:
                old_file.unlink()
        except OSError:
            continue
    extension = "ogg" if settings.audio_format == "opus" else settings.audio_format
    filename = f"tts-test-{secrets.token_hex(12)}.{extension}"
    target = folder / filename
    try:
        result = generate_speech_file(text[:800], target, settings, disclose_ai=True)
    except AIServiceError as exc:
        current_app.logger.warning("AI_SALES_TTS_TEST status=failed code=%s error=%s", exc.code, exc)
        return jsonify({"success": False, "error": exc.to_dict()}), exc.status_code or 400
    session["ai_sales_last_tts_test"] = now.isoformat()
    return jsonify({
        "success": True,
        "audio_url": url_for("ai_sales.api_openai_test_speech_file", filename=filename),
        "model": result["model"],
        "voice": result["voice"],
        "speed": result["speed"],
        "quality": result["quality"],
        "duration_ms": result["duration_ms"],
    })


@ai_sales_bp.route("/api/openai/test-speech/file/<filename>")
def api_openai_test_speech_file(filename):
    denied = _api_guard(manage=True)
    if denied:
        return denied
    if not re.fullmatch(r"tts-test-[a-f0-9]{24}\.(?:mp3|ogg|aac|flac|wav)", filename or ""):
        return jsonify({"success": False, "error": "ملف غير صالح"}), 404
    tenant = re.sub(r"[^A-Za-z0-9_-]", "", str(getattr(g, "tenant", "core") or "core")) or "core"
    target = Path(current_app.root_path) / "uploads" / "ai_sales" / tenant / "tests" / filename
    if not target.is_file():
        return jsonify({"success": False, "error": "انتهت صلاحية ملف التجربة"}), 404
    mimetype = "audio/ogg" if target.suffix.lower() == ".ogg" else None
    return send_file(target, mimetype=mimetype, conditional=True, max_age=0)


@ai_sales_bp.route("/api/openai/realtime/session", methods=["POST"])
def api_openai_realtime_session():
    denied = _api_guard()
    if denied:
        return denied
    profile = AISalesAgentProfile.query.filter_by(is_active=True).order_by(AISalesAgentProfile.id.asc()).first()
    settings = settings_for_profile(profile)
    try:
        secret = create_realtime_client_secret(
            settings,
            instructions=(profile.voice_instructions or "") if profile else "",
        )
        if not secret.get("value"):
            raise AIServiceError("empty_realtime_secret", "realtime", "لم ترجع الخدمة مفتاح جلسة مؤقت")
        return jsonify({"success": True, **secret})
    except AIServiceError as exc:
        current_app.logger.warning("AI_SALES_REALTIME status=failed code=%s error=%s", exc.code, exc)
        return jsonify({"success": False, "error": exc.to_dict()}), exc.status_code or 400


def _training_channel() -> AISalesChannelAccount:
    channel = AISalesChannelAccount.query.filter_by(name="Training Chat").first()
    if not channel:
        channel = AISalesChannelAccount(
            name="Training Chat",
            channel_type="training",
            connection_status="training",
            reply_mode="inbox",
            is_active=False,
        )
        db.session.add(channel)
        db.session.flush()
    return channel


def _create_training_exchange(text: str, product_id: int | None = None) -> tuple[AISalesConversation, AISalesMessage, AISalesMessage, dict]:
    channel = _training_channel()
    conversation = get_or_create_conversation(
        channel,
        external_contact_id="training-chat",
        phone="",
        contact_name="جات التدريب",
    )
    conversation.ai_enabled = False
    conversation.human_takeover = True
    conversation.status = "waiting_employee"
    result = generate_training_reply(text, product_id=product_id)
    now = datetime.utcnow()
    inbound = AISalesMessage(
        conversation_id=conversation.id,
        channel_account_id=channel.id,
        external_message_id=f"train-in-{secrets.token_hex(10)}",
        direction="inbound",
        sender_type="customer",
        message_type="text",
        text_content=text[:4096],
        status="processed",
        created_at=now,
    )
    db.session.add(inbound)
    db.session.flush()
    outbound = AISalesMessage(
        conversation_id=conversation.id,
        channel_account_id=channel.id,
        external_message_id=f"train-out-{secrets.token_hex(10)}",
        direction="outbound",
        sender_type="ai",
        message_type="text",
        text_content=result["reply"],
        status="sent",
        sent_at=now,
        created_at=now,
    )
    payload = result["raw_payload"]
    payload["inbound_message_id"] = inbound.id
    outbound.set_media_metadata({"training": payload})
    db.session.add(outbound)
    db.session.flush()
    payload["outbound_message_id"] = outbound.id
    outbound.set_media_metadata({"training": payload})
    mark_customer_activity(conversation, now)
    db.session.commit()
    return conversation, inbound, outbound, result


@ai_sales_bp.route("/api/training-chat/messages", methods=["POST"])
def api_training_chat_messages():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or data.get("question") or "").strip()
    product_id = int(data.get("product_id") or 0) or None
    if not text:
        return jsonify({"success": False, "error": "اكتب سؤال التدريب أولاً"}), 400
    try:
        conversation, inbound, outbound, result = _create_training_exchange(text, product_id)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({
        "success": True,
        "conversation": conversation.to_dict(),
        "inbound": inbound.to_dict(),
        "reply_message": outbound.to_dict(),
        "training_message_id": outbound.id,
        "reply": result["reply"],
        "matched_product": result["matched_product"],
        "used_examples_count": result["used_examples_count"],
        "needs_product_selection": result["needs_product_selection"],
    })


@ai_sales_bp.route("/api/training-feedback", methods=["POST"])
def api_training_feedback():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        row = approve_training_feedback(
            message_id=int(data.get("message_id") or data.get("training_message_id") or 0),
            rating=str(data.get("rating") or ""),
            product_id=int(data.get("product_id") or 0) or None,
            corrected_reply=str(data.get("corrected_reply") or ""),
            employee_id=int(session.get("user_id") or 0) or None,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({
        "success": True,
        "example": {
            "id": row.id,
            "product_id": row.product_id,
            "rating_source": row.rating_source,
            "customer_example": row.customer_example,
            "employee_example": row.employee_example,
        },
    })


@ai_sales_bp.route("/api/simulate", methods=["POST"])
def api_simulate():
    denied = _api_guard(manage=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    phone = re.sub(r"\D", "", str(data.get("phone") or "9647700000000"))
    if not text:
        return jsonify({"success": False, "error": "نص التجربة مطلوب"}), 400
    channel = AISalesChannelAccount.query.filter_by(name="قناة الاختبار المحلية").first()
    if not channel:
        channel = AISalesChannelAccount(name="قناة الاختبار المحلية", connection_status="simulator", is_active=False)
        db.session.add(channel)
        db.session.flush()
    conversation = get_or_create_conversation(channel, external_contact_id=phone, phone=phone, contact_name="زبون تجريبي")
    now = datetime.utcnow()
    inbound = AISalesMessage(
        conversation_id=conversation.id,
        channel_account_id=channel.id,
        external_message_id=f"sim-{secrets.token_hex(10)}",
        direction="inbound",
        sender_type="customer",
        message_type="text",
        text_content=text[:4096],
        status="received",
        created_at=now,
    )
    db.session.add(inbound)
    db.session.flush()
    mark_customer_activity(conversation, now)
    db.session.commit()
    outbound = process_inbound_message(inbound.id, send_external=False)
    return jsonify(
        {
            "success": True,
            "conversation": conversation.to_dict(),
            "inbound": inbound.to_dict(),
            "reply": outbound.to_dict() if outbound else None,
        }
    )


def _webhook_channel(tenant_slug: str, webhook_key: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", tenant_slug or ""):
        return None
    g.tenant = tenant_slug
    ensure_ai_sales_schema()
    return AISalesChannelAccount.query.filter_by(webhook_key=webhook_key).first()


def _webhook_log(event: str, **fields) -> None:
    payload = {"event": event, "timestamp": datetime.utcnow().isoformat() + "Z", **fields}
    current_app.logger.warning("AI_SALES_WEBHOOK %s", json.dumps(payload, ensure_ascii=False, default=str))


@ai_sales_webhook_bp.route("/webhooks/whatsapp/<tenant_slug>/<webhook_key>", methods=["GET", "POST"])
def whatsapp_webhook(tenant_slug, webhook_key):
    if request.method == "POST":
        _webhook_log(
            "post_received",
            tenant=tenant_slug,
            webhook_key=webhook_key,
            headers=dict(request.headers),
            body=request.get_data(cache=True).decode("utf-8", errors="replace"),
        )
    channel = _webhook_channel(tenant_slug, webhook_key)
    if not channel:
        if request.method == "POST":
            _webhook_log("channel_lookup_failed", tenant=tenant_slug, webhook_key=webhook_key)
        return Response("", status=404, mimetype="text/plain")
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token") or ""
        challenge = request.args.get("hub.challenge") or ""
        expected = decrypt_secret(channel.verify_token_encrypted)
        if mode == "subscribe" and expected and secrets.compare_digest(token, expected):
            channel.connection_status = "verified"
            channel.last_error = None
            db.session.commit()
            return Response(challenge, status=200, mimetype="text/plain")
        return Response("", status=403, mimetype="text/plain")

    if not channel.is_active:
        _webhook_log("channel_inactive", tenant=tenant_slug, webhook_key=webhook_key, channel_id=channel.id)
        return jsonify({"error": "channel_inactive"}), 403

    raw = request.get_data(cache=True)
    app_secret = decrypt_secret(channel.app_secret_encrypted)
    if app_secret and not verify_meta_signature(raw, request.headers.get("X-Hub-Signature-256"), app_secret):
        _webhook_log("signature_failed", tenant=tenant_slug, webhook_key=webhook_key, channel_id=channel.id)
        return jsonify({"error": "invalid_signature"}), 403
    payload = request.get_json(silent=True) or {}
    parsed = parse_whatsapp_payload(payload)
    _webhook_log(
        "payload_parsed",
        tenant=tenant_slug,
        webhook_key=webhook_key,
        channel_id=channel.id,
        phone_number_id=parsed["phone_number_id"],
        expected_phone_number_id=channel.phone_number_id,
        message_count=len(parsed["messages"]),
        status_count=len(parsed["statuses"]),
        call_count=len(parsed["calls"]),
    )
    if channel.phone_number_id and parsed["phone_number_id"] and channel.phone_number_id != parsed["phone_number_id"]:
        _webhook_log(
            "phone_number_mismatch",
            tenant=tenant_slug,
            webhook_key=webhook_key,
            received=parsed["phone_number_id"],
            expected=channel.phone_number_id,
        )
        return jsonify({"error": "phone_number_mismatch"}), 403
    channel.last_webhook_at = datetime.utcnow()
    channel.connection_status = "connected"
    channel.last_error = None

    for event in parsed["calls"]:
        external_call_id = event["external_call_id"]
        if not external_call_id:
            _webhook_log("call_missing_external_id", tenant=tenant_slug, webhook_key=webhook_key)
            continue
        contact_id = event["external_contact_id"] or event["from"] or external_call_id
        phone = re.sub(r"\D", "", event["from"])
        conversation = get_or_create_conversation(
            channel,
            external_contact_id=contact_id,
            phone=phone,
            contact_name=event["contact_name"],
        )
        call = AISalesCall.query.filter_by(
            channel_account_id=channel.id,
            external_call_id=external_call_id,
        ).first()
        if not call:
            call = AISalesCall(
                channel_account_id=channel.id,
                conversation_id=conversation.id,
                external_call_id=external_call_id,
                external_contact_id=contact_id,
                direction=event["direction"],
                event=event["event"],
            )
            db.session.add(call)
        event_at = external_timestamp(event["timestamp"]) or datetime.utcnow()
        call.conversation_id = conversation.id
        call.external_contact_id = contact_id
        call.direction = event["direction"]
        call.event = event["event"]
        call.from_number = event["from"] or None
        call.to_number = event["to"] or None
        call.sdp_type = event["sdp_type"] or None
        call.duration_seconds = int(event["duration"] or 0)
        call.failure_code = event["failure_code"] or None
        call.failure_message = event["failure_message"] or None
        call.set_raw_payload(event["raw"])
        if event["event"] == "connect":
            call.status = "ringing"
            call.started_at = external_timestamp(event["start_time"]) or event_at
        elif event["event"] == "terminate":
            call.status = event["status"] or ("failed" if event["failure_code"] else "completed")
            call.started_at = external_timestamp(event["start_time"]) or call.started_at
            call.ended_at = external_timestamp(event["end_time"]) or event_at
        else:
            call.status = event["status"] or call.status

        event_message_id = f"call:{external_call_id}:{event['event']}"
        if not AISalesMessage.query.filter_by(
            channel_account_id=channel.id,
            external_message_id=event_message_id,
        ).first():
            label = "مكالمة واتساب واردة" if event["event"] == "connect" else "انتهت مكالمة واتساب"
            message = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                external_message_id=event_message_id,
                direction="inbound",
                sender_type="customer",
                message_type="call",
                text_content=label,
                status="received",
                created_at=event_at,
            )
            message.set_raw_payload({
                "call_id": external_call_id,
                "event": event["event"],
                "direction": event["direction"],
                "status": call.status,
                "duration": call.duration_seconds,
            })
            db.session.add(message)
            if event["event"] == "connect":
                mark_customer_activity(conversation, event_at)
        _webhook_log(
            "call_event_saved",
            tenant=tenant_slug,
            webhook_key=webhook_key,
            phone_number_id=parsed["phone_number_id"],
            conversation_id=conversation.id,
            external_call_id=external_call_id,
            call_event=event["event"],
            call_status=call.status,
        )

    for status in parsed["statuses"]:
        message = AISalesMessage.query.filter_by(
            channel_account_id=channel.id,
            external_message_id=status["external_message_id"],
        ).first()
        if not message:
            continue
        state = status["status"]
        when = external_timestamp(status["timestamp"]) or datetime.utcnow()
        message.status = state or message.status
        if state == "delivered":
            message.delivered_at = when
        elif state == "read":
            message.read_at = when
        elif state == "failed":
            errors = status.get("errors") or []
            first = errors[0] if errors else {}
            message.failure_code = str(first.get("code") or "")
            message.failure_message = str(first.get("title") or first.get("message") or "")
            channel.last_error = f"Meta {message.failure_code}: {message.failure_message}".strip()
            _webhook_log(
                "outbound_delivery_failed",
                tenant=tenant_slug,
                webhook_key=webhook_key,
                phone_number_id=parsed["phone_number_id"],
                message_id=message.id,
                external_message_id=message.external_message_id,
                meta_error_code=message.failure_code,
                meta_error_message=message.failure_message,
                response_body=status,
            )
        else:
            _webhook_log(
                "outbound_status_updated",
                tenant=tenant_slug,
                webhook_key=webhook_key,
                phone_number_id=parsed["phone_number_id"],
                message_id=message.id,
                external_message_id=message.external_message_id,
                status=state,
            )

    queued_ids = []
    for event in parsed["messages"]:
        external_id = event["external_message_id"]
        if not external_id:
            _webhook_log("message_missing_external_id", tenant=tenant_slug, webhook_key=webhook_key)
            continue
        if AISalesMessage.query.filter_by(channel_account_id=channel.id, external_message_id=external_id).first():
            _webhook_log("duplicate_message_ignored", tenant=tenant_slug, webhook_key=webhook_key, external_message_id=external_id)
            continue
        phone = re.sub(r"\D", "", event["from"])
        conversation = get_or_create_conversation(
            channel,
            external_contact_id=event["from"],
            phone=phone,
            contact_name=event["contact_name"],
        )
        when = external_timestamp(event["timestamp"]) or datetime.utcnow()
        message = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id=external_id,
            reply_to_external_id=event["reply_to_external_id"] or None,
            direction="inbound",
            sender_type="customer",
            message_type=event["message_type"],
            text_content=event["text"] or event["caption"] or None,
            external_media_id=event["media_id"] or None,
            mime_type=event["mime_type"] or None,
            status="received",
            created_at=when,
        )
        message.set_raw_payload(event["raw"])
        db.session.add(message)
        db.session.flush()
        _webhook_log(
            "message_inserted",
            tenant=tenant_slug,
            webhook_key=webhook_key,
            phone_number_id=parsed["phone_number_id"],
            conversation_id=conversation.id,
            message_id=message.id,
            external_message_id=external_id,
            message_type=event["message_type"],
        )
        mark_customer_activity(conversation, when)
        if event["message_type"] in {"text", "button", "interactive", "image", "audio", "voice", "video"}:
            queued_ids.append(message.id)
    db.session.commit()
    _webhook_log(
        "database_commit_success",
        tenant=tenant_slug,
        webhook_key=webhook_key,
        phone_number_id=parsed["phone_number_id"],
        queued_ids=queued_ids,
    )

    app = current_app._get_current_object()
    for message_id in queued_ids:
        dispatch_inbound_async(app, tenant_slug, message_id, send_external=True)
    _webhook_log("dispatch_complete", tenant=tenant_slug, webhook_key=webhook_key, queued_count=len(queued_ids))
    return jsonify({"status": "accepted", "queued": len(queued_ids)}), 200


@ai_sales_webhook_bp.route("/webhooks/meta/<tenant_slug>/<webhook_key>", methods=["GET", "POST"])
def meta_messaging_webhook(tenant_slug, webhook_key):
    connector = _webhook_channel(tenant_slug, webhook_key)
    if not connector or connector.channel_type != "meta":
        return Response("", status=404, mimetype="text/plain")
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token") or ""
        challenge = request.args.get("hub.challenge") or ""
        expected = decrypt_secret(connector.verify_token_encrypted)
        if mode == "subscribe" and expected and secrets.compare_digest(token, expected):
            connector.connection_status = "verified"
            connector.last_error = None
            db.session.commit()
            return Response(challenge, status=200, mimetype="text/plain")
        return Response("", status=403, mimetype="text/plain")
    if not connector.is_active:
        return jsonify({"error": "channel_inactive"}), 403

    raw = request.get_data(cache=True)
    app_secret = decrypt_secret(connector.app_secret_encrypted)
    if app_secret and not verify_meta_signature(raw, request.headers.get("X-Hub-Signature-256"), app_secret):
        _webhook_log("meta_signature_failed", tenant=tenant_slug, webhook_key=webhook_key, connector_id=connector.id)
        return jsonify({"error": "invalid_signature"}), 403
    payload = request.get_json(silent=True) or {}
    events = parse_meta_messaging_payload(payload)
    comment_events = parse_meta_comment_payload(payload)
    _webhook_log(
        "meta_payload_parsed",
        tenant=tenant_slug,
        connector_id=connector.id,
        object=payload.get("object"),
        event_count=len(events),
        comment_event_count=len(comment_events),
    )
    connector.last_webhook_at = datetime.utcnow()
    connector.connection_status = "connected"
    queued_ids = []
    employee_reply_ids = []
    queued_comment_ids = []
    for event in comment_events:
        channel = AISalesChannelAccount.query.filter_by(
            parent_channel_id=connector.id,
            channel_type="messenger",
            external_account_id=event["page_id"],
        ).first()
        if not channel or not channel.is_active or not channel.comments_enabled:
            continue
        if event.get("external_user_id") == str(channel.external_account_id or ""):
            continue
        post = AISalesSocialPost.query.filter_by(
            channel_account_id=channel.id,
            external_post_id=event["external_post_id"],
        ).first()
        if not post:
            post = upsert_social_post(channel, {"id": event["external_post_id"]})
            db.session.flush()
        comment, created = upsert_social_comment(channel, post, {
            "id": event["external_comment_id"],
            "parent_external_comment_id": event.get("parent_external_comment_id"),
            "external_user_id": event.get("external_user_id"),
            "user_name": event.get("user_name"),
            "message": event.get("message"),
            "attachment_url": event.get("attachment_url"),
            "created_time": event.get("created_time"),
            "raw": event.get("raw"),
        })
        db.session.flush()
        if created:
            queued_comment_ids.append(comment.id)
    for event in events:
        channel = AISalesChannelAccount.query.filter_by(
            parent_channel_id=connector.id,
            channel_type=event["platform"],
            external_account_id=event["account_id"],
        ).first()
        if not channel:
            _webhook_log(
                "meta_page_not_synced",
                tenant=tenant_slug,
                platform=event["platform"],
                account_id=event["account_id"],
            )
            continue
        if not channel.is_active:
            _webhook_log("meta_page_inactive", tenant=tenant_slug, channel_id=channel.id)
            continue
        external_id = event["external_message_id"]
        if not external_id or AISalesMessage.query.filter_by(channel_account_id=channel.id, external_message_id=external_id).first():
            continue
        existing_conversation = AISalesConversation.query.filter_by(
            channel_account_id=channel.id,
            external_contact_id=event["from"],
        ).first()
        contact_name, picture_url, profile_checked = _meta_contact_identity(
            MetaMessagingClient(channel),
            existing_conversation,
            event["from"],
        )
        conversation = get_or_create_conversation(
            channel,
            external_contact_id=event["from"],
            phone="",
            contact_name=contact_name,
            contact_profile_picture_url=picture_url,
        )
        _mark_meta_profile_checked(conversation, profile_checked)
        _merge_meta_ad_context(conversation, event)
        if not event.get("has_message"):
            continue
        has_previous_inbound = AISalesMessage.query.filter_by(
            conversation_id=conversation.id,
            direction="inbound",
        ).first() is not None
        when = external_timestamp(event["timestamp"]) or datetime.utcnow()
        is_echo = bool(event.get("is_echo"))
        event_text = str(event.get("text") or "")
        event_attachment_url = str(event.get("attachment_url") or "")
        is_ad_opener = (
            not is_echo
            and (
                event["message_type"] == "referral"
                or bool(event.get("referral") or event.get("ads_context_data"))
            )
            and not event_text.strip()
            and event["message_type"] not in {"image", "video", "audio", "file", "sticker"}
        )
        message = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id=external_id,
            reply_to_external_id=event["reply_to_external_id"] or None,
            direction="outbound" if is_echo else "inbound",
            sender_type="employee" if is_echo else "customer",
            message_type="referral" if is_ad_opener else event["message_type"],
            text_content=event_text or None,
            external_media_id=event_attachment_url or None,
            mime_type=event.get("attachment_mime_type") or None,
            status="sent" if is_echo else "received",
            sent_at=when if is_echo else None,
            created_at=when,
        )
        message.set_raw_payload(event["raw"])
        origin_metadata = _message_origin_metadata(
            channel,
            event_text,
            event=event,
            conversation=conversation,
            include_conversation_ad=not is_echo and (not has_previous_inbound or is_ad_opener),
        )
        if is_ad_opener:
            origin_metadata = {
                **origin_metadata,
                "thread_opener": True,
                "ad_opener": True,
            }
        event_metadata = {}
        if event.get("sticker_id"):
            event_metadata = {
                "sticker_id": event.get("sticker_id"),
                "is_like": bool(event.get("is_like")),
            }
        if event_attachment_url or origin_metadata or event_metadata:
            media_metadata = {**origin_metadata, **event_metadata}
            if event_attachment_url:
                media_metadata.update({
                    "external_url": event_attachment_url,
                    "preview_url": event.get("attachment_preview_url") or "",
                })
            message.set_media_metadata(media_metadata)
        db.session.add(message)
        db.session.flush()
        if is_echo:
            if not conversation.last_business_message_at or when > conversation.last_business_message_at:
                conversation.last_business_message_at = when
            conversation.updated_at = when
            if not event.get("app_id"):
                pause_conversation_for_human(
                    conversation,
                    reason="رد موظف من تطبيق Meta",
                )
                if event_text:
                    employee_reply_ids.append(message.id)
        else:
            mark_customer_activity(conversation, when)
        is_meta_system = bool(origin_metadata.get("meta_context", {}).get("is_meta_system"))
        actionable_text = event["message_type"] in {"text", "button", "interactive"} and bool(event_text.strip())
        actionable_media = event["message_type"] in {"image", "audio", "video"}
        if not is_echo and not is_meta_system and (actionable_text or actionable_media):
            queued_ids.append(message.id)
    db.session.commit()
    for message_id in employee_reply_ids:
        _capture_employee_learning_safely(message_id)
    app = current_app._get_current_object()
    for message_id in queued_ids:
        dispatch_inbound_async(app, tenant_slug, message_id, send_external=True)
    for comment_id in queued_comment_ids:
        dispatch_social_comment_async(app, tenant_slug, comment_id)
    return jsonify({
        "status": "accepted",
        "queued": len(queued_ids),
        "comments_queued": len(queued_comment_ids),
    }), 200
