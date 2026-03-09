"""توليد ردود تلقائية على التعليقات باستخدام AI."""

from __future__ import annotations

from social_ai.ai_engine import generate_comment_reply


def build_reply_for_comment(comment_text: str, post_caption: str | None = None) -> str:
    """إرجاع نص رد مناسب لتعليق معين."""
    return generate_comment_reply(comment_text, post_caption)

