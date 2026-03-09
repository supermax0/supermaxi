from __future__ import annotations

"""طبقة التعامل مع OpenAI لتوليد المحتوى للنشر على السوشيال."""

from typing import Optional

from openai import OpenAI  # type: ignore[import-untyped]
from flask import current_app


_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
  """إرجاع عميل OpenAI باستخدام الإعدادات من Flask config."""
  global _client
  if _client is None:
      api_key = current_app.config.get("OPENAI_API_KEY")
      if not api_key:
          raise RuntimeError("OPENAI_API_KEY غير مضبوط في إعدادات التطبيق")
      _client = OpenAI(api_key=api_key)
  return _client


def generate_caption(topic: str, tone: str = "تسويقي", language: str = "ar") -> str:
    """توليد كابشن منشور إنستجرام/تيك توك."""
    client = get_client()
    prompt = f"""
اكتب كابشن احترافي لمنشور سوشيال ميديا عن:
{topic}

المطلوب:
- لغة: {language}
- أسلوب: {tone}
- استخدم ايموجي مناسبة
- أضف سطر هاشتاغ في النهاية
"""
    resp = client.chat.completions.create(
        model=current_app.config.get("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=[
            {"role": "system", "content": "أنت خبير كتابة محتوى تسويقي للسوشيال ميديا."},
            {"role": "user", "content": prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def generate_hashtags(topic: str, n: int = 10, language: str = "ar") -> str:
    """توليد مجموعة هاشتاغات مختصرة حول موضوع معيّن."""
    client = get_client()
    prompt = f"""
اقترح {n} هاشتاغ قصير بدون شرح عن:
{topic}

اللغة: {language}
اكتبهم في سطر واحد مفصولين بمسافة.
"""
    resp = client.chat.completions.create(
        model=current_app.config.get("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


def generate_comment_reply(comment: str, post_caption: str | None = None) -> str:
    """توليد رد مهني على تعليق."""
    client = get_client()
    base = f"رد على هذا التعليق بطريقة لطيفة ومهنية:\n\n{comment}\n"
    if post_caption:
        base += f"\nسياق المنشور:\n{post_caption}\n"
    resp = client.chat.completions.create(
        model=current_app.config.get("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=[{"role": "user", "content": base}],
    )
    return (resp.choices[0].message.content or "").strip()

