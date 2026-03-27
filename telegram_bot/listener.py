# telegram_bot/listener.py — استخراج chat_id و message_text من تحديث تيليجرام
from __future__ import annotations

import logging
from typing import Any, Tuple

logger = logging.getLogger(__name__)


def parse_telegram_update(data: dict[str, Any]) -> Tuple[str | None, str | None]:
    """استخراج (chat_id, message_text) من payload التحديث. قد يكون أحدهما None."""
    if not data:
        return None, None
    # محادثة خاصة / مجموعة
    message = data.get("message") or data.get("edited_message")
    # قنوات
    if not message:
        message = data.get("channel_post") or data.get("edited_channel_post")
    # أزرار شفافة: نأخذ الرسالة المرتبطة ونضع callback data كنص افتراضي
    callback_data: str | None = None
    if not message and data.get("callback_query"):
        cq = data["callback_query"]
        message = cq.get("message")
        callback_data = (cq.get("data") or "").strip() or None
    if not message:
        return None, None
    chat = message.get("chat") or {}
    chat_id_raw = chat.get("id")
    chat_id = str(chat_id_raw) if chat_id_raw is not None else None
    message_text = (message.get("text") or message.get("caption") or "").strip() or None
    if callback_data:
        message_text = callback_data if not message_text else f"{message_text}\n{callback_data}"
    logger.info("Telegram listener: chat_id=%s has_text=%s", chat_id, bool(message_text))
    return chat_id, message_text
