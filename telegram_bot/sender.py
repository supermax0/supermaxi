# telegram_bot/sender.py — إرسال رسالة إلى تيليجرام عبر Bot API
from __future__ import annotations

import logging
import requests

logger = logging.getLogger(__name__)


def send_telegram_reply(bot_token: str, chat_id: str, text: str) -> bool:
    """إرسال رسالة إلى محادثة. يرجع True عند النجاح."""
    if not bot_token or not chat_id or text is None:
        logger.warning("Telegram send skipped: missing token, chat_id, or text")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
        if resp.status_code >= 400:
            logger.error("Telegram send failed: status=%s body=%s", resp.status_code, resp.text[:500])
            return False
        logger.info("Telegram send OK: chat_id=%s", chat_id)
        return True
    except Exception as exc:
        logger.exception("Telegram send error: %s", exc)
        return False
