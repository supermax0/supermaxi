"""Permanent Messenger webhook + long-lived page tokens."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import requests
from flask import Response, current_app, g, jsonify, request

from extensions import db
from modules.facebook_monitor.routes import facebook_monitor_bp
from utils.meta_graph import GRAPH_BASE

GRAPH = GRAPH_BASE
PAGE_FIELDS = "messages,messaging_postbacks,message_echoes"


def hmac_ok(got: str, expected: str) -> bool:
    left = (got or "").encode("utf-8")
    right = (expected or "").encode("utf-8")
    if len(left) != len(right):
        return False
    return secrets.compare_digest(left, right)


def webhook_public_base() -> str:
    host = (request.host_url or "").rstrip("/")
    if "finora.company" in host:
        return "https://www.finora.company"
    return host or "https://www.finora.company"


def webhook_url(tenant_slug: str) -> str:
    return f"{webhook_public_base()}/webhooks/facebook/{tenant_slug}"


def _bind_tenant(tenant_slug: str) -> str:
    slug = "".join(ch for ch in str(tenant_slug or "") if ch.isalnum() or ch in "-_")[:100] or "super"
    g.tenant = slug
    return slug


def ensure_verify_token(settings) -> str:
    from modules.publisher.services.token_utils import decrypt_token, encrypt_token

    token = ""
    if getattr(settings, "fb_verify_token", None):
        token = decrypt_token(settings.fb_verify_token) or settings.fb_verify_token or ""
    if token and token.startswith("finora-"):
        return token
    token = "finora-" + secrets.token_urlsafe(18)
    settings.fb_verify_token = encrypt_token(token)
    db.session.commit()
    return token


def exchange_long_lived(app_id: str, app_secret: str, user_token: str) -> tuple[str, int | None, str]:
    if not app_id or not app_secret or not user_token:
        return user_token, None, ""
    try:
        payload = requests.get(
            f"{GRAPH}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": user_token,
            },
            timeout=15,
        ).json()
    except Exception as exc:
        return user_token, None, str(exc)
    token = str(payload.get("access_token") or "")
    if not token:
        error = ((payload.get("error") or {}).get("message") or "تعذر تحويل الرمز إلى دائم")
        return user_token, None, error
    expires = payload.get("expires_in")
    return token, int(expires) if expires else None, ""


def register_app_subscription(*, app_id: str, app_secret: str, callback_url: str, verify_token: str) -> str:
    try:
        payload = requests.post(
            f"{GRAPH}/{app_id}/subscriptions",
            data={
                "object": "page",
                "callback_url": callback_url,
                "verify_token": verify_token,
                "fields": PAGE_FIELDS,
                "include_values": "true",
                "access_token": f"{app_id}|{app_secret}",
            },
            timeout=20,
        ).json()
    except Exception as exc:
        return str(exc)
    if payload.get("success") or payload.get("id"):
        return ""
    return ((payload.get("error") or {}).get("message") or "تعذر تسجيل الويب هوك على التطبيق")


def subscribe_page(page_id: str, page_token: str) -> str:
    try:
        payload = requests.post(
            f"{GRAPH}/{page_id}/subscribed_apps",
            data={"subscribed_fields": PAGE_FIELDS, "access_token": page_token},
            timeout=15,
        ).json()
    except Exception as exc:
        return str(exc)
    if payload.get("success"):
        return ""
    return ((payload.get("error") or {}).get("message") or "فيسبوك رفض اشتراك الصفحة بالرسائل")


def sync_messenger_channel(*, page_id: str, page_name: str, page_token: str, app_secret: str = "") -> None:
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.ai_sales.schema import ensure_ai_sales_schema
    from modules.ai_sales.security import encrypt_secret

    ensure_ai_sales_schema()
    channel = AISalesChannelAccount.query.filter(
        AISalesChannelAccount.channel_type.in_(("messenger", "facebook")),
        AISalesChannelAccount.page_id == str(page_id),
    ).first()
    if not channel:
        channel = AISalesChannelAccount(
            channel_type="messenger",
            name=page_name or f"صفحة {page_id}",
            page_id=str(page_id),
            external_account_id=str(page_id),
            reply_mode="employee",
            is_active=True,
            connection_status="ready",
        )
        db.session.add(channel)
    channel.name = page_name or channel.name
    channel.page_id = str(page_id)
    channel.external_account_id = str(page_id)
    # AI Sales reads channel credentials with decrypt_secret(), so these values
    # must use the matching cipher rather than the publisher-token cipher.
    channel.access_token_encrypted = encrypt_secret(page_token)
    if app_secret:
        channel.app_secret_encrypted = encrypt_secret(app_secret)
    channel.reply_mode = channel.reply_mode or "employee"
    channel.is_active = True
    channel.connection_status = "connected"
    channel.updated_at = datetime.utcnow()


def persist_long_lived(settings, token: str, expires_in: int | None) -> None:
    from modules.publisher.services.token_utils import encrypt_token

    settings.fb_user_token = encrypt_token(token)
    if expires_in:
        settings.fb_token_expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
    else:
        settings.fb_token_expires_at = None


def _channel_for_page(page_id: str):
    from modules.ai_sales.models import AISalesChannelAccount

    return AISalesChannelAccount.query.filter(
        AISalesChannelAccount.channel_type.in_(("messenger", "facebook")),
        AISalesChannelAccount.page_id == str(page_id),
    ).first()


def ingest_events(payload: dict) -> int:
    from modules.ai_sales.channels import parse_meta_messaging_payload
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesMessage

    stored = 0
    for event in parse_meta_messaging_payload(payload):
        page_id = str(event.get("account_id") or "")
        if not page_id or event.get("is_echo"):
            continue
        channel = _channel_for_page(page_id)
        if not channel or not channel.is_active:
            continue
        external_id = str(event.get("external_message_id") or "")
        if external_id and AISalesMessage.query.filter_by(
            channel_account_id=channel.id, external_message_id=external_id
        ).first():
            continue
        conversation = get_or_create_conversation(
            channel,
            external_contact_id=str(event.get("from") or ""),
            phone="",
            contact_name="",
        )
        when = datetime.utcnow()
        attachment_url = str(event.get("attachment_url") or "")
        message = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id=external_id or None,
            direction="inbound",
            sender_type="customer",
            message_type=event.get("message_type") or "text",
            text_content=str(event.get("text") or "") or None,
            external_media_id=attachment_url or None,
            mime_type=str(event.get("attachment_mime_type") or "") or None,
            status="received",
            created_at=when,
        )
        if attachment_url:
            message.set_media_metadata({
                "external_url": attachment_url,
                "preview_url": str(event.get("attachment_preview_url") or ""),
            })
        db.session.add(message)
        conversation.updated_at = when
        conversation.last_customer_message_at = when
        if message.text_content:
            conversation.summary = str(message.text_content)[:300]
        stored += 1
    return stored


@facebook_monitor_bp.route("/webhooks/facebook", methods=["GET", "POST"])
@facebook_monitor_bp.route("/webhooks/facebook/<tenant_slug>", methods=["GET", "POST"])
def facebook_messenger_webhook(tenant_slug: str = "super"):
    slug = _bind_tenant(tenant_slug)
    from modules.ai_sales.schema import ensure_ai_sales_schema

    ensure_ai_sales_schema()
    from modules.publisher.models.publisher_settings import PublisherSettings
    from modules.publisher.services.schema_guard import ensure_publisher_schema
    from modules.publisher.services.token_utils import decrypt_token
    from utils.branch_context import init_public_default_branch

    try:
        ensure_publisher_schema(force=True)
    except TypeError:
        ensure_publisher_schema()
    except Exception:
        pass
    init_public_default_branch()
    settings = PublisherSettings.get(slug)
    expected = ""
    if settings and settings.fb_verify_token:
        expected = decrypt_token(settings.fb_verify_token) or settings.fb_verify_token

    if request.method == "GET":
        mode = request.args.get("hub.mode") or ""
        token = request.args.get("hub.verify_token") or ""
        challenge = request.args.get("hub.challenge") or ""
        if mode == "subscribe" and expected and hmac_ok(token, expected):
            settings.fb_webhook_verified = True
            settings.fb_webhook_at = datetime.utcnow()
            db.session.commit()
            return Response(challenge, status=200, mimetype="text/plain")
        return Response("forbidden", status=403, mimetype="text/plain")

    raw = request.get_data(cache=True)
    app_secret = decrypt_token(settings.fb_app_secret) if settings and settings.fb_app_secret else ""
    if app_secret:
        from modules.ai_sales.security import verify_meta_signature

        if not verify_meta_signature(raw, request.headers.get("X-Hub-Signature-256"), app_secret):
            return jsonify({"error": "invalid_signature"}), 403
    payload = request.get_json(silent=True) or {}
    try:
        stored = ingest_events(payload)
        settings.fb_webhook_verified = True
        settings.fb_webhook_at = datetime.utcnow()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("facebook webhook ingest failed: %s", exc)
        return jsonify({"ok": False}), 200
    return jsonify({"ok": True, "stored": stored})
