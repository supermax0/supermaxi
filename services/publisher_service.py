from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional

from flask import current_app, g

from extensions import db
from models.publisher_channel import PublisherChannel
from models.publisher_job import PublisherJob
from routes.autoposter_facebook import publish_post as publish_facebook_post


def _get_tenant_slug() -> str:
    return getattr(g, "tenant", None) or ""


def create_jobs_for_channels(
    *,
    channels: Iterable[PublisherChannel],
    content: str,
    media_url: Optional[str],
    media_type: Optional[str],
    scheduled_at: datetime,
) -> List[PublisherJob]:
    """إنشاء مهام نشر (job) لكل قناة محددة."""
    tenant_slug = _get_tenant_slug()
    jobs: List[PublisherJob] = []
    for ch in channels:
        job = PublisherJob(
            tenant_slug=tenant_slug,
            channel_id=ch.id,
            channel_type=ch.type,
            content=content or "",
            media_url=media_url,
            media_type=media_type,
            status="pending",
            scheduled_at=scheduled_at,
        )
        db.session.add(job)
        jobs.append(job)
    db.session.commit()
    return jobs


def _publish_to_facebook(job: PublisherJob, channel: PublisherChannel) -> Dict[str, Any]:
    """نشر فعلي على فيسبوك لصفحة واحدة باستخدام Graph API."""
    message = job.content or ""
    photo_url = job.media_url if job.media_type == "image" else None
    video_url = job.media_url if job.media_type == "video" else None

    result = publish_facebook_post(
        page_access_token=channel.access_token or "",
        message=message,
        photo_url=photo_url,
        video_url=video_url,
        page_id=channel.external_id,
    )
    return result


def process_pending_jobs_for_tenant(
    *,
    tenant_slug: str,
    now: Optional[datetime] = None,
    max_retries: int = 5,
) -> None:
    """تشغيل كل مهام النشر المعلقة/المجدولة لمستأجر واحد."""
    now = now or datetime.utcnow()
    g.tenant = tenant_slug  # يضمن استخدام قاعدة بيانات المستأجر في أي مكان يحتاج g.tenant

    jobs: List[PublisherJob] = (
        PublisherJob.query.filter(
            PublisherJob.tenant_slug == tenant_slug,
            PublisherJob.status.in_(["pending", "processing"]),
            PublisherJob.scheduled_at <= now,
        )
        .order_by(PublisherJob.scheduled_at.asc())
        .all()
    )

    for job in jobs:
        try:
            job.status = "processing"
            db.session.commit()

            channel = PublisherChannel.query.get(job.channel_id)
            if not channel or not channel.is_active:
                job.status = "failed"
                job.error_message = "القناة غير متاحة أو معطّلة"
                db.session.commit()
                continue

            if channel.type == "facebook_page":
                result = _publish_to_facebook(job, channel)
            else:
                # قنوات أخرى (واتساب، تيليجرام) يمكن إضافتها لاحقاً
                raise RuntimeError(f"Channel type {channel.type} غير مدعوم بعد.")

            job.status = "published"
            job.published_at = datetime.utcnow()
            job.error_message = None
            db.session.commit()
        except Exception as e:
            job.retry_count = (job.retry_count or 0) + 1
            job.error_message = str(e)
            if job.retry_count >= max_retries:
                job.status = "failed"
            else:
                job.status = "pending"
                job.scheduled_at = now + timedelta(minutes=5)
            db.session.commit()

