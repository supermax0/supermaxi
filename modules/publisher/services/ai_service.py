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


def _resolve_api_key() -> str:
    """
    Resolve OpenAI API key with this priority:
      1) Publisher settings (per-tenant, when request context exists)
      2) Flask config OPENAI_API_KEY
      3) Environment OPENAI_API_KEY
    """
    # 1) Per-tenant key from Publisher settings (if we're inside a request)
    try:
        from flask import current_app, g, has_app_context, has_request_context, session
        if has_request_context():
            from modules.publisher.models.publisher_settings import PublisherSettings
            from modules.publisher.services.schema_guard import ensure_publisher_schema
            from modules.publisher.services.token_utils import decrypt_token

            # Ensure legacy DBs are upgraded before reading the new column.
            ensure_publisher_schema()
            tenant = getattr(g, "tenant", None) or session.get("tenant_slug") or "default"
            settings_row = PublisherSettings.get(tenant)
            if settings_row and settings_row.openai_api_key:
                try:
                    key = decrypt_token(settings_row.openai_api_key).strip()
                except Exception:
                    key = (settings_row.openai_api_key or "").strip()
                if key:
                    return key

            cfg_key = (current_app.config.get("OPENAI_API_KEY") or "").strip()
            if cfg_key:
                return cfg_key
        elif has_app_context():
            cfg_key = (current_app.config.get("OPENAI_API_KEY") or "").strip()
            if cfg_key:
                return cfg_key
    except Exception:
        # Soft-fail: we can still continue with environment fallback.
        pass

    # 2/3) Process-level fallback
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def _get_client():
    """Return an OpenAI client or None if key not set."""
    api_key = _resolve_api_key()
    if not api_key:
        return None
    try:
        from openai import OpenAI  # type: ignore
        return OpenAI(api_key=api_key)
    except Exception:
        # Older openai versions may not expose OpenAI client class.
        # We fallback in _chat() to legacy ChatCompletion API.
        return None


def _chat(messages: list, max_tokens: int = 400) -> str:
    api_key = _resolve_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY غير مضبوط — أضفه من إعدادات Publisher أو عبر .env")

    # Preferred path (openai>=1.x)
    client = _get_client()
    if client:
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.8,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            err = str(exc).lower()
            if "api key" in err or "incorrect" in err or "authentication" in err:
                raise RuntimeError(
                    "مفتاح OpenAI غير صالح أو غير مقبول. تأكد من المفتاح من منصة OpenAI ثم احفظه من جديد."
                ) from exc
            raise RuntimeError(f"تعذر توليد النص عبر OpenAI: {exc}") from exc

    # Legacy fallback (openai<1.x)
    try:
        import openai  # type: ignore

        openai.api_key = api_key
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.8,
        )
        return (response["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        err = str(exc).lower()
        if "api key" in err or "incorrect" in err or "authentication" in err:
            raise RuntimeError(
                "مفتاح OpenAI غير صالح أو غير مقبول. تأكد من المفتاح من منصة OpenAI ثم احفظه من جديد."
            ) from exc
        if "chatcompletion" in err and "attribute" in err:
            raise RuntimeError(
                "نسخة مكتبة openai على السيرفر غير متوافقة. حدّث الحزمة إلى نسخة حديثة."
            ) from exc
        raise RuntimeError(f"تعذر توليد النص عبر OpenAI: {exc}") from exc


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


def create_page_caption_variant(
    base_text: str,
    *,
    page_name: str = "",
    variant_index: int = 1,
    total_variants: int = 1,
) -> str:
    """
    Create a slightly different caption per page while preserving meaning.
    Falls back to the original text when AI output is empty.
    """
    original = (base_text or "").strip()
    if not original:
        return ""
    if total_variants <= 1:
        return original

    page_label = (page_name or "بدون اسم").strip()
    max_tokens = min(500, max(180, int(len(original.split()) * 3)))
    system = (
        "أنت محرر محتوى سوشيال ميديا. مهمتك إعادة صياغة النص بشكل خفيف فقط، "
        "مع الحفاظ على نفس الفكرة والهدف."
    )
    user = (
        f"النص الأساسي:\n{original}\n\n"
        f"المطلوب: أنشئ نسخة بديلة رقم {variant_index} من {total_variants} "
        f"مناسبة للنشر على صفحة: {page_label}.\n"
        "الشروط:\n"
        "- اختلاف خفيف فقط في الصياغة (لا تغير الرسالة الأساسية).\n"
        "- حافظ على نفس اللغة والأسلوب العام.\n"
        "- بدون شرح أو ملاحظات إضافية.\n"
        "- أرجع النص النهائي فقط."
    )
    out = _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
    ).strip()
    return out or original
