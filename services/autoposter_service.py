from datetime import datetime, timedelta
from typing import Iterable, List, Tuple

from flask import g

from extensions import db
from models.autoposter_facebook_page import AutoposterFacebookPage
from models.autoposter_post import AutoposterPost
from services.autoposter_channels import ChannelType
from routes.autoposter_facebook import publish_post


def _normalize_post_type(post_type: str) -> str:
    post_type = (post_type or "post").strip().lower()
    if post_type not in ("post", "story", "reels"):
        return "post"
    return post_type


def schedule_posts_for_pages(
    *,
    pages: Iterable[AutoposterFacebookPage],
    content: str,
    image_url: str | None,
    video_url: str | None,
    post_type: str,
    scheduled_at: datetime,
) -> int:
    """إنشاء سجلات منشورات مجدولة لعدة صفحات في شركة واحدة."""
    post_type = _normalize_post_type(post_type)
    count = 0
    for page in pages:
        post = AutoposterPost(
            page_id=page.page_id,
            page_name=page.name,
            content=content or "",
            image_url=image_url,
            video_url=video_url,
            channel=ChannelType.FACEBOOK_PAGE,
            post_type=post_type,
            status="scheduled",
            scheduled_at=scheduled_at,
        )
        db.session.add(post)
        count += 1
    db.session.commit()
    return count


def publish_now_for_pages(
    *,
    pages: Iterable[AutoposterFacebookPage],
    content: str,
    image_url: str | None,
    video_url: str | None,
    post_type: str,
) -> Tuple[List[dict], List[dict]]:
    """نشر منشور فوراً لعدة صفحات في شركة واحدة مع نتيجة تفصيلية لكل صفحة."""
    post_type = _normalize_post_type(post_type)
    published: List[dict] = []
    errors: List[dict] = []

    for page in pages:
        post = AutoposterPost(
            page_id=page.page_id,
            page_name=page.name,
            content=content or "",
            image_url=image_url,
            video_url=video_url,
            channel=ChannelType.FACEBOOK_PAGE,
            post_type=post_type,
            status="publishing",
        )
        db.session.add(post)
        db.session.commit()
        try:
            result = publish_post(
                page.access_token,
                content,
                photo_url=image_url,
                video_url=video_url,
                post_type=post_type,
                page_id=page.page_id,
            )
            post.status = "published"
            post.published_at = datetime.utcnow()
            post.facebook_post_id = result.get("id") or result.get("post_id")
            post.error_message = None
            db.session.commit()
            published.append({
                "page_id": page.page_id,
                "page_name": page.name,
                "post_id": post.facebook_post_id,
            })
        except Exception as e:  # pragma: no cover - يعتمد على استجابات فيسبوك الحية
            post.status = "failed"
            post.error_message = str(e)
            db.session.commit()
            errors.append({
                "page_id": page.page_id,
                "page_name": page.name,
                "error": str(e),
            })

    return published, errors


def process_scheduled_posts_for_current_tenant(now: datetime | None = None) -> None:
    """نشر جميع المنشورات المجدولة التي حان وقتها في قاعدة بيانات المستأجر الحالي."""
    now = now or datetime.utcnow()
    max_retries = 5
    retry_delay = timedelta(minutes=10)
    posts = AutoposterPost.query.filter(
        AutoposterPost.status == "scheduled",
        AutoposterPost.scheduled_at <= now,
    ).all()

    for post in posts:
        post.status = "publishing"
        post.last_attempt_at = now
        db.session.commit()
        try:
            page = AutoposterFacebookPage.query.filter_by(page_id=post.page_id).first()
            if not page or not page.access_token:
                post.status = "failed"
                post.error_message = "صفحة غير متصلة أو انتهى التوكن"
                db.session.commit()
                continue
            result = publish_post(
                page.access_token,
                post.content,
                photo_url=getattr(post, "image_url", None),
                video_url=getattr(post, "video_url", None),
                post_type=getattr(post, "post_type", None) or "post",
                page_id=page.page_id,
            )
            post.status = "published"
            post.published_at = datetime.utcnow()
            post.facebook_post_id = result.get("id") or result.get("post_id")
            post.error_message = None
            post.retry_count = getattr(post, "retry_count", 0)
            db.session.commit()
        except Exception as e:  # pragma: no cover
            current_retries = (getattr(post, "retry_count", 0) or 0) + 1
            post.retry_count = current_retries
            post.error_message = str(e)
            if current_retries >= max_retries:
                post.status = "failed"
            else:
                post.status = "scheduled"
                post.scheduled_at = now + retry_delay
            db.session.commit()


def run_scheduled_posts_for_all_tenants(app) -> None:
    """تشغيل منشورات مجدولة لكل الشركات النشطة (تُستدعى من المجدول في app.py)."""
    from models.core.tenant import Tenant as CoreTenant

    with app.app_context():
        g.tenant = None
        try:
            tenants = CoreTenant.query.filter_by(is_active=True).all()
        except Exception:  # pragma: no cover
            tenants = []
        for t in tenants:
            slug = getattr(t, "slug", None)
            if not slug:
                continue
            g.tenant = slug
            try:
                process_scheduled_posts_for_current_tenant()
            except Exception:
                db.session.rollback()
            finally:
                g.tenant = None

