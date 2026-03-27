from __future__ import annotations

from typing import Any

import requests
from flask import current_app


def send_whatsapp_message(phone: str, message: str) -> None:
    """
    إرسال رسالة واتساب عبر WhatsApp Cloud API.

    تعتمد على:
    - WHATSAPP_ACCESS_TOKEN
    - WHATSAPP_PHONE_NUMBER_ID

    إذا لم تُضبط هذه الإعدادات لن يتم إرسال شيء (يتم فقط تسجيل تحذير في اللوج).
    """
    if not phone or not message:
        return

    access_token = current_app.config.get("WHATSAPP_ACCESS_TOKEN") or ""
    phone_number_id = current_app.config.get("WHATSAPP_PHONE_NUMBER_ID") or ""
    if not access_token or not phone_number_id:
        current_app.logger.warning(
            "WhatsApp send skipped: missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID"
        )
        return

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code >= 400:
            current_app.logger.error(
                "WhatsApp send failed: status=%s body=%s", resp.status_code, resp.text
            )
        else:
            current_app.logger.info("WhatsApp send OK: to=%s", phone)
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("WhatsApp send error: %s", exc)


def send_telegram_message(chat_id: str, message: str, bot_token: str | None = None) -> None:
    """
    إرسال رسالة تيليجرام عبر Bot API.

    يستخدم bot_token إذا مُرّر، وإلا TELEGRAM_BOT_TOKEN أو BOT_TOKEN من إعدادات التطبيق.
    """
    if not chat_id or not message:
        return

    token = (bot_token or "").strip()
    if not token:
        token = (
            (current_app.config.get("TELEGRAM_BOT_TOKEN") or "")
            or (current_app.config.get("BOT_TOKEN") or "")
        ).strip()
    if not token:
        current_app.logger.warning("Telegram send skipped: no bot token (set in عقدة تيليجرام Listener or TELEGRAM_BOT_TOKEN)")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": message,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code >= 400:
            current_app.logger.error(
                "Telegram send failed: status=%s body=%s", resp.status_code, resp.text
            )
        else:
            current_app.logger.info("Telegram send OK: chat_id=%s", chat_id)
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("Telegram send error: %s", exc)


def send_telegram_photo(
    chat_id: str,
    photo_url: str,
    bot_token: str | None = None,
    caption: str | None = None,
) -> bool:
    """
    إرسال صورة إلى تيليجرام عبر sendPhoto (يقبل رابط https مباشر).
    """
    photo_url = (photo_url or "").strip()
    if not chat_id or not photo_url:
        return False
    if not photo_url.startswith(("http://", "https://")):
        current_app.logger.warning("Telegram photo skipped: invalid URL %s", photo_url[:80])
        return False

    token = (bot_token or "").strip()
    if not token:
        token = (
            (current_app.config.get("TELEGRAM_BOT_TOKEN") or "")
            or (current_app.config.get("BOT_TOKEN") or "")
        ).strip()
    if not token:
        current_app.logger.warning("Telegram photo skipped: no bot token")
        return False

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    if caption and caption.strip():
        payload["caption"] = caption[:1024]

    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code >= 400:
            current_app.logger.error(
                "Telegram sendPhoto failed: status=%s body=%s", resp.status_code, resp.text
            )
            return False
        current_app.logger.info("Telegram sendPhoto OK: chat_id=%s", chat_id)
        return True
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("Telegram sendPhoto error: %s", exc)
        return False

