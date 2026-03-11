# telegram_bot/listener.py — استخراج chat_id و message_text من تحديث تيليجرام
from __future__ import annotations

import logging
from typing import Any, Tuple

logger = logging.getLogger(__name__)


def parse_telegram_update(data: dict[str, Any]) -> Tuple[str | None, str | None]:
    """استخراج (chat_id, message_text) من payload التحديث. قد يكون أحدهما None."""
    if not data:
        return None, None
    message = data.get("message") or data.get("edited_message")
    if not message and data.get("callback_query"):
        message = data["callback_query"].get("message")
    if not message:
        return None, None
    chat = message.get("chat") or {}
    chat_id_raw = chat.get("id")
    chat_id = str(chat_id_raw) if chat_id_raw is not None else None
    message_text = (message.get("text") or message.get("caption") or "").strip() or None
    logger.info("Telegram listener: chat_id=%s has_text=%s", chat_id, bool(message_text))
    return chat_id, message_text
