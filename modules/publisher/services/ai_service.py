"""
ai_service.py
-------------
AI content generation for the Publisher using OpenAI API.
Three capabilities:
  1. generate_post  — write a full post from a topic
  2. rewrite_post   — improve / rephrase existing text
  3. generate_hashtags — suggest relevant hashtags
"""

from __future__ import annotations

import logging
import os
from typing import List

logger = logging.getLogger("publisher")


def _get_client():
    """Return an OpenAI client or None if key not set."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import openai
        return openai.OpenAI(api_key=api_key)
    except ImportError:
        logger.warning("openai package not installed")
        return None


def _chat(messages: list, max_tokens: int = 400) -> str:
    client = _get_client()
    if not client:
        raise RuntimeError("OPENAI_API_KEY غير مضبوط — يرجى إضافته في ملف .env")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


# ─────────────────────────────────────────────────────────────────────────────

def generate_post(topic: str, tone: str = "احترافي", length: str = "متوسط") -> str:
    """
    Generate a Facebook post caption.
    tone: احترافي / ودي / تسويقي / إبداعي
    length: قصير / متوسط / طويل
    """
    length_map = {"قصير": 80, "متوسط": 150, "طويل": 280}
    words = length_map.get(length, 150)

    system = (
        "أنت كاتب محتوى محترف متخصص في السوشيال ميديا والتسويق الرقمي. "
        "تكتب بالعربية حصراً ما لم يُطلب غير ذلك."
    )
    user = (
        f"اكتب منشور فيسبوك احترافي عن: {topic}\n"
        f"الأسلوب: {tone}\n"
        f"الطول: حوالي {words} كلمة\n"
        "لا تضف هاشتاقات. فقط نص المنشور."
    )
    return _chat([{"role": "system", "content": system}, {"role": "user", "content": user}])


def rewrite_post(original_text: str, tone: str = "تسويقي") -> str:
    """Rewrite / improve existing post text."""
    system = (
        "أنت خبير تسويق محتوى. أعد صياغة النص المُعطى بأسلوب أفضل وأكثر تأثيراً."
    )
    user = f"أعد كتابة هذا المنشور بأسلوب {tone}:\n\n{original_text}"
    return _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=300,
    )


def generate_hashtags(topic: str) -> List[str]:
    """Generate a list of relevant hashtags for a topic."""
    system = "أنت خبير سوشيال ميديا. أعطِ هاشتاقات فيسبوك ذات صلة بالموضوع."
    user = (
        f"اقترح 10 هاشتاقات فيسبوك مناسبة لموضوع: {topic}\n"
        "اكتب كل هاشتاق في سطر مستقل بدون أرقام أو نقاط."
    )
    text = _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=200,
    )
    tags = [line.strip() for line in text.splitlines() if line.strip()]
    # Ensure each tag starts with #
    result = []
    for tag in tags:
        tag = tag.lstrip("- •·").strip()
        if tag and not tag.startswith("#"):
            tag = "#" + tag.replace(" ", "_")
        if tag:
            result.append(tag)
    return result[:12]
