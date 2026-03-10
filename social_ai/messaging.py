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


def send_telegram_message(chat_id: str, message: str) -> None:
    """إرسال رسالة تيليجرام عبر Bot API (حالياً تسجيل فقط، يمكن توسيعها لاحقاً)."""
    if not chat_id or not message:
        return
    current_app.logger.info("Telegram send: chat_id=%s message=%s", chat_id, message)
    # يمكن لاحقاً استخدام TELEGRAM_BOT_TOKEN من الإعدادات واستدعاء Telegram Bot API هنا.

