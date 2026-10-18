"""House-scoped Telegram settings and authenticated private-chat ingestion."""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import current_app, jsonify, request, url_for
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
from modules.ai_sales.security import decrypt_secret, encrypt_secret
from modules.ai_sales.telegram import TOKEN_PATTERN, TelegramBotClient, TelegramError, message_attachments

from .api import _actor, _json, finora_core_bp
from .auth import require
from .errors import CoreApiError, validation_error
from .store import audit, core_session, house_slug, use_house


def webhook_url(channel):
    base = str(os.environ.get("FINORA_CORE_PUBLIC_URL") or current_app.config.get("BASE_URL") or
               "https://www.finora.company").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise validation_error("عنوان FINORA العام يجب أن يكون HTTPS صالحاً لربط بوت تلگرام")
    # Telegram rejects the apex-domain 301; register the final HTTPS origin directly.
    if parsed.hostname == "finora.company":
        base = parsed._replace(netloc="www.finora.company" + (f":{parsed.port}" if parsed.port else "")).geturl()
    return base + url_for("finora_core.telegram_webhook", key=channel.webhook_key)


def current_bot():
    return AISalesChannelAccount.query.filter_by(channel_type="telegram").order_by(
        AISalesChannelAccount.is_active.desc(), AISalesChannelAccount.id.desc()).first()


def settings_dto(channel=None):
    return {"houseConfigured": bool(house_slug()), "tokenConfigured": bool(channel and channel.access_token_encrypted),
            "botId": str(channel.external_account_id or "") if channel else "",
            "username": channel.platform_username or "" if channel else "",
            "name": channel.name if channel else "", "active": bool(channel and channel.is_active),
            "status": channel.connection_status or "disconnected" if channel else "disconnected",
            "webhookUrl": webhook_url(channel) if channel else "",
            "botUrl": f"https://t.me/{channel.platform_username}" if channel and channel.platform_username else "",
            "lastError": channel.last_error if channel else None}


def record(action, title):
    with core_session() as s:
        audit(s, actor=_actor(), actor_type="human", category="finora", action=action, title=title)
        s.commit()


@finora_core_bp.get("/settings/telegram")
@require("settings.manage")
def telegram_settings():
    if not house_slug():
        return jsonify(settings_dto())
    with use_house():
        return jsonify(settings_dto(current_bot()))


def verify_bot(client):
    bot = client.call("getMe")
    if not isinstance(bot, dict) or bot.get("is_bot") is not True or not isinstance(bot.get("id"), int):
        raise TelegramError(502)
    username = str(bot.get("username") or "")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise TelegramError(502)
    return bot


@finora_core_bp.post("/settings/telegram/connect")
@require("settings.manage")
def telegram_connect():
    token = _json().get("botToken")
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token.strip()):
        raise validation_error("أدخل رمز البوت الصحيح من BotFather")
    token = token.strip()
    with use_house():
        client = TelegramBotClient(token=token)
        try:
            bot = verify_bot(client)
            old = current_bot()
            if old and old.is_active and str(old.external_account_id) != str(bot["id"]):
                raise validation_error("افصل البوت الحالي قبل ربط بوت آخر؛ محادثاته تبقى محفوظة")
            channel = AISalesChannelAccount.query.filter_by(channel_type="telegram", external_account_id=str(bot["id"])).first()
            new = channel is None
            if new:
                channel = AISalesChannelAccount(channel_type="telegram", name="FINORA Telegram")
                # Column defaults run on INSERT, but setWebhook needs the key beforehand.
                channel.webhook_key = secrets.token_urlsafe(24)
            secret = decrypt_secret(channel.verify_token_encrypted) if channel.verify_token_encrypted else secrets.token_urlsafe(32)
            expected = webhook_url(channel)
            if client.call("setWebhook", {"url": expected, "secret_token": secret, "allowed_updates": ["message"]}) is not True:
                raise TelegramError(502)
            info = client.call("getWebhookInfo")
            if not isinstance(info, dict) or info.get("url") != expected:
                raise TelegramError(502)
        except TelegramError as exc:
            raise validation_error(str(exc)) from None
        channel.name = str(bot.get("first_name") or "FINORA Telegram")[:120]
        channel.external_account_id = str(bot["id"])
        channel.platform_username = bot["username"]
        channel.access_token_encrypted = encrypt_secret(token)
        channel.verify_token_encrypted = encrypt_secret(secret)
        channel.reply_mode = "ai"
        channel.connection_status = "connected"
        channel.is_active = True
        channel.last_error = None
        channel.last_sync_at = datetime.utcnow()
        if new:
            db.session.add(channel)
        db.session.commit()
        result = settings_dto(channel)
    record("settings.telegram_connect", "ربط بوت FINORA بتلگرام")
    return jsonify(result)


def check_channel_health(channel):
    if not channel.is_active:
        channel.connection_status = "disconnected"
        return settings_dto(channel)
    try:
        client = TelegramBotClient(channel)
        bot = verify_bot(client)
        info = client.call("getWebhookInfo")
        if str(bot["id"]) != str(channel.external_account_id):
            raise TelegramError(401)
        last_received = channel.last_webhook_at.replace(tzinfo=timezone.utc).timestamp() if channel.last_webhook_at else 0
        recent_error = isinstance(info, dict) and info.get("last_error_message") and info.get("last_error_date", 0) > last_received
        valid = isinstance(info, dict) and info.get("url") == webhook_url(channel) and not recent_error
        channel.connection_status = "connected" if valid else "webhook_invalid"
        channel.last_error = None if valid else "تعذر التحقق من استقبال رسائل البوت؛ أعد الربط وافحص عنوان الخادم"
    except TelegramError as exc:
        channel.connection_status = "token_invalid" if exc.status_code == 401 else "unknown"
        channel.last_error = str(exc)
    channel.last_sync_at = datetime.utcnow()
    return settings_dto(channel)


@finora_core_bp.post("/settings/telegram/health-check")
@require("settings.manage")
def telegram_health():
    with use_house():
        channel = current_bot()
        result = check_channel_health(channel) if channel else settings_dto()
        db.session.commit()
    record("settings.telegram_health", "فحص صحة قناة تلگرام")
    return jsonify(result)


@finora_core_bp.post("/settings/telegram/disconnect")
@require("settings.manage")
def telegram_disconnect():
    with use_house():
        channel = current_bot()
        if channel and channel.is_active:
            try:
                if TelegramBotClient(channel).call("deleteWebhook", {"drop_pending_updates": False}) is not True:
                    raise TelegramError(502)
            except TelegramError as exc:
                # A revoked token already prevents Telegram from delivering/sending.
                if exc.status_code not in (401, 404):
                    raise validation_error(str(exc)) from None
            channel.is_active = False
            channel.connection_status = "disconnected"
            channel.last_error = None
            db.session.commit()
        result = settings_dto(channel)
    record("settings.telegram_disconnect", "فصل بوت تلگرام مع الاحتفاظ بالمحادثات")
    return jsonify(result)


@finora_core_bp.post("/webhooks/telegram/<key>")
def telegram_webhook(key):
    if not house_slug():
        return jsonify({"ok": False}), 404
    from modules.ai_sales.engine import dispatch_inbound_async, get_or_create_conversation, mark_customer_activity
    from modules.ai_sales.attachments import dispatch_storage_async, label_for
    from modules.ai_sales.routes import _is_duplicate_message_error

    queued = None
    with use_house() as slug:
        channel = AISalesChannelAccount.query.filter_by(channel_type="telegram", webhook_key=key, is_active=True).first()
        secret = decrypt_secret(channel.verify_token_encrypted) if channel else ""
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secret or not hmac.compare_digest(secret.encode(), provided.encode()):
            return jsonify({"ok": False}), 403
        raw = request.stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise CoreApiError("VALIDATION_ERROR", "حجم الطلب كبير", 413)
        try:
            update = json.loads(raw)
        except (ValueError, UnicodeError):
            raise validation_error("تحديث تلگرام غير صالح") from None
        if not isinstance(update, dict):
            raise validation_error("تحديث تلگرام غير صالح")
        msg = update.get("message")
        if not isinstance(msg, dict):
            return jsonify({"ok": True, "ignored": True})
        chat, sender = msg.get("chat") or {}, msg.get("from") or {}
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            raise validation_error("تحديث تلگرام غير صالح")
        # Identity comes only from Telegram's authenticated envelope, never a forwarded contact/username.
        uid = chat.get("id")
        mid = msg.get("message_id")
        if chat.get("type") != "private" or sender.get("is_bot") is not False or type(uid) is not int or not 0 < uid < 10**20 or sender.get("id") != uid:
            return jsonify({"ok": True, "ignored": True})
        if type(mid) is not int or mid <= 0 or type(msg.get("date")) is not int:
            raise validation_error("تحديث تلگرام غير صالح")
        external_id = f"tg:{uid}:{mid}"
        if AISalesMessage.query.filter_by(channel_account_id=channel.id, external_message_id=external_id).first():
            return jsonify({"ok": True, "duplicate": True})
        try:
            when = datetime.utcfromtimestamp(msg["date"])
        except (ValueError, OverflowError, OSError):
            raise validation_error("توقيت تلگرام غير صالح") from None
        if when > datetime.utcnow() + timedelta(minutes=5):
            raise validation_error("توقيت تلگرام غير صالح")
        text = msg.get("text") or msg.get("caption") or ""
        if not isinstance(text, str) or len(text) > 8192:
            raise validation_error("نص تلگرام غير صالح")
        attachments = message_attachments(msg)
        if not text and not attachments:
            return jsonify({"ok": True, "ignored": True})
        name = " ".join(str(sender.get(k) or "") for k in ("first_name", "last_name")).strip()[:150]
        conv = get_or_create_conversation(channel, external_contact_id=str(uid), phone="", contact_name=name, route_facebook=False)
        message = AISalesMessage(conversation_id=conv.id, channel_account_id=channel.id, external_message_id=external_id,
                                 direction="inbound", sender_type="customer", message_type=attachments[0]["kind"] if attachments else "text",
                                 text_content=text or label_for(attachments), status="received", created_at=when)
        message.set_media_metadata({"attachments": attachments})
        try:
            with db.session.begin_nested():
                db.session.add(message)
                db.session.flush()
        except IntegrityError as exc:
            if not _is_duplicate_message_error(exc):
                raise
            db.session.rollback()
            return jsonify({"ok": True, "duplicate": True})
        mark_customer_activity(conv, when)
        channel.last_webhook_at = datetime.utcnow()
        late = bool(conv.last_business_message_at and when + timedelta(seconds=1) < conv.last_business_message_at)
        queued = message.id if not late else None
        attachment_ids = [message.id] if attachments else []
        db.session.commit()
    app = current_app._get_current_object()
    if queued:
        dispatch_inbound_async(app, slug, queued, send_external=True)
    if attachment_ids:
        dispatch_storage_async(app, slug, attachment_ids)
    return jsonify({"ok": True, "queued": bool(queued)})
