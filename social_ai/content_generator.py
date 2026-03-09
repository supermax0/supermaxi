"""توليد منشور كامل (كابشن + صورة) باستخدام وحدات AI."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask import g

from extensions import db
from models.social_post import SocialPost
from social_ai.ai_engine import generate_caption, generate_hashtags
from social_ai.image_generator import generate_image


def create_ai_post(topic: str, *, user_id: Optional[int] = None, auto: bool = False) -> SocialPost:
    """إنشاء منشور كامل (كابشن + صورة) وتخزينه كمسودة في SocialPost."""
    tenant_slug = getattr(g, "tenant", None)

    caption = generate_caption(topic)
    hashtags = generate_hashtags(topic)
    full_caption = f"{caption}\n\n{hashtags}"

    image_prompt = f"modern marketing image about: {topic}"
    image_url = generate_image(image_prompt)

    post = SocialPost(
        tenant_slug=tenant_slug,
        user_id=user_id,
        topic=topic,
        caption=full_caption,
        image_url=image_url,
        status="draft",
        source="auto_ai_daily" if auto else "manual",
        created_at=datetime.utcnow(),
    )
    db.session.add(post)
    db.session.commit()
    return post

