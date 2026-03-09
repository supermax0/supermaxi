from __future__ import annotations

"""منطق جدولة منشورات SocialPost ومعالجتها لكل مستأجر."""

from datetime import datetime, timedelta
from typing import Optional

from flask import g

from extensions import db
from models.social_account import SocialAccount
from models.social_post import SocialPost
from social_ai.publish_manager import publish_post_to_accounts


def process_scheduled_social_posts(now: Optional[datetime] = None) -> None:
    """نشر جميع social_posts المجدولة التي حان وقتها للمستأجر الحالي."""
    now = now or datetime.utcnow()
    tenant_slug = getattr(g, "tenant", None)

    query = SocialPost.query.filter(
        SocialPost.status == "scheduled",
        SocialPost.publish_time <= now,
    )
    if tenant_slug:
        query = query.filter_by(tenant_slug=tenant_slug)

    posts = query.all()
    for post in posts:
        post.status = "publishing"
        db.session.commit()
        try:
            acc_query = SocialAccount.query.filter_by(tenant_slug=tenant_slug)
            accounts = acc_query.all()
            if not accounts:
                post.status = "failed"
                post.error_message = "لا توجد حسابات سوشيال مرتبطة."
                db.session.commit()
                continue
            publish_post_to_accounts(post, accounts)
            post.status = "published"
            post.error_message = None
            db.session.commit()
        except Exception as e:  # pragma: no cover
            post.status = "failed"
            post.error_message = str(e)
            db.session.commit()


def schedule_daily_ai_posts_for_tenant(topic: str, *, user_id: Optional[int] = None) -> None:
    """مثال مبسط: إنشاء 3 منشورات مجدولة لهذا اليوم لمستأجر واحد.

    يمكن استدعاؤها يدوياً أو من مجدول يومي.
    """
    from social_ai.content_generator import create_ai_post

    tenant_slug = getattr(g, "tenant", None)
    times = ["10:00", "15:00", "21:00"]
    today = datetime.utcnow().date()

    for t in times:
        hour, minute = map(int, t.split(":"))
        publish_dt = datetime(today.year, today.month, today.day, hour, minute)
        post = create_ai_post(topic, user_id=user_id, auto=True)
        # تحديث الحقول الخاصة بالجدولة
        post.tenant_slug = tenant_slug
        post.publish_time = publish_dt
        post.status = "scheduled"
        db.session.commit()

