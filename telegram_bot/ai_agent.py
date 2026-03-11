"""
توليد رد الذكاء الاصطناعي باستخدام OpenAI API.

الـ prompt: مساعد متجر تقنية، الرد بالعربية.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Prompt حسب المواصفات: مساعد متجر تقنية، الرد بالعربية
DEFAULT_SYSTEM = "You are a helpful assistant for a tech store. Reply in Arabic."
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def generate_ai_reply(
    message_text: str,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    system_prompt: Optional[str] = None,
) -> Optional[str]:
    """
    توليد رد من OpenAI: "You are a helpful assistant for a tech store. Reply in Arabic. User message: {message_text}"
    """
    if not api_key:
        logger.warning("OpenAI API key not set; skipping AI reply")
        return None

    system = (system_prompt or DEFAULT_SYSTEM).strip()
    user_content = f"User message: {message_text}" if message_text else "User said nothing (e.g. sent a photo). Reply briefly in Arabic."

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 500,
    }

    try:
        resp = requests.post(
            OPENAI_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.error(
                "OpenAI API error: status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            return None

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            logger.warning("OpenAI returned no choices")
            return None

        message = choices[0].get("message") or {}
        content = (message.get("content") or "").strip()
        if content:
            logger.info("OpenAI reply generated, length=%s", len(content))
        return content or None
    except Exception as exc:
        logger.exception("OpenAI request error: %s", exc)
        return None
