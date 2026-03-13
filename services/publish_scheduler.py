from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from flask import current_app

from extensions import db
from models.publish_channel import PublishChannel
from models.publish_job import PublishJob
from services.publish_service import PublishResult, PublisherChannel, log_publish_error


def _get_channel_handler(channel: PublishChannel) -> Optional[PublisherChannel]:
    """إرجاع handler مناسب حسب نوع القناة.

    مبدئياً نرجع None ليُعتبر كأن القناة غير مدعومة حتى نضيف قنوات فعلية لاحقاً.
    """

    # TODO: إضافة قنوات حقيقية مثل FacebookPublisherChannel أو TelegramPublisherChannel
    _ = channel
    return None


def fetch_due_jobs(now: Optional[datetime] = None, limit: int = 50) -> List[PublishJob]:
    """جلب المهام المستحقة للنشر (pending أو processing المتأخرة عن scheduled_at)."""

    if now is None:
        now = datetime.utcnow()

    q = PublishJob.query.filter(
        PublishJob.status.in_(["pending", "processing"]),
        PublishJob.scheduled_at <= now,
    ).order_by(PublishJob.scheduled_at.asc(), PublishJob.id.asc())

    return q.limit(limit).all()


def process_job(job: PublishJob) -> PublishResult:
    """معالجة Job واحدة (تحديث الحالة وتسجيل النتائج)."""

    channel = PublishChannel.query.get(job.channel_id)
    if not channel or not channel.is_active:
        job.status = "failed"
        log_publish_error(job, "القناة غير موجودة أو معطّلة.")
        db.session.commit()
        return PublishResult(
            success=False,
            error_code="channel_inactive",
            error_message="القناة غير موجودة أو معطّلة.",
        )

    handler = _get_channel_handler(channel)
    if handler is None:
        job.status = "failed"
        log_publish_error(job, f"نوع القناة غير مدعوم حالياً: {channel.type}")
        db.session.commit()
        return PublishResult(
            success=False,
            error_code="channel_not_supported",
            error_message=f"نوع القناة غير مدعوم حالياً: {channel.type}",
        )

    job.status = "processing"
    job.retry_count = (job.retry_count or 0) + 1
    db.session.commit()

    try:
        result = handler.publish(job)
    except Exception as exc:  # pragma: no cover - حماية من أخطاء القناة
        current_app.logger.exception("Publish job %s raised exception", job.id)
        result = PublishResult(
            success=False,
            error_code="exception",
            error_message=str(exc),
        )

    if result.success:
        job.status = "published"
        job.published_at = datetime.utcnow()
        job.error_code = None
        job.error_message = None
    else:
        job.status = "failed"
        job.error_code = result.error_code
        log_publish_error(job, result.error_message or "خطأ غير معروف في النشر.")

    db.session.commit()
    return result


def process_pending_jobs_for_tenant(
    tenant_slug: str,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> int:
    """معالجة جميع المهام المستحقة لمستأجر واحد وإرجاع عدد المهام التي تمت معالجتها."""

    if now is None:
        now = datetime.utcnow()

    jobs = (
        PublishJob.query.filter(
            PublishJob.tenant_slug == tenant_slug,
            PublishJob.status.in_(["pending", "processing"]),
            PublishJob.scheduled_at <= now,
        )
        .order_by(PublishJob.scheduled_at.asc(), PublishJob.id.asc())
        .limit(limit)
        .all()
    )

    count = 0
    for job in jobs:
        process_job(job)
        count += 1

    return count

