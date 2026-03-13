from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Protocol

from flask import current_app

from extensions import db
from models.publish_channel import PublishChannel
from models.publish_job import PublishJob


@dataclass
class PublishResult:
    success: bool
    remote_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class PublisherChannel(Protocol):
    """واجهة موحّدة لكل قناة نشر (فيسبوك، تيليجرام، ...)."""

    def publish(self, job: PublishJob) -> PublishResult:  # pragma: no cover - بروتوكول
        ...


def create_jobs_for_channels(
    *,
    tenant_slug: str,
    channels: Iterable[PublishChannel],
    text: str,
    media_url: Optional[str],
    media_type: Optional[str],
    scheduled_at: datetime,
    title: Optional[str] = None,
) -> List[PublishJob]:
    """إنشاء PublishJob لكل قناة وإرجاع القائمة."""

    text = (text or "").strip()
    media_url = (media_url or "").strip() or None
    media_type = (media_type or "").strip() or None

    if not text and not media_url:
        raise ValueError("يجب توفير نص أو وسائط للمهمة.")

    channel_list = list(channels)
    if not channel_list:
        raise ValueError("لا توجد قنوات محددة لإنشاء مهام النشر.")

    jobs: List[PublishJob] = []

    for ch in channel_list:
        if not ch.is_active:
            continue

        job = PublishJob(
            tenant_slug=tenant_slug,
            channel_id=ch.id,
            channel_type=ch.type,
            title=title,
            text=text,
            media_url=media_url,
            media_type=media_type,
            status="pending",
            scheduled_at=scheduled_at,
        )
        db.session.add(job)
        jobs.append(job)

    db.session.commit()
    return jobs


def get_channels_for_tenant(
    tenant_slug: str,
    channel_ids: Optional[Iterable[int]] = None,
    require_active: bool = True,
) -> List[PublishChannel]:
    """جلب القنوات لمستأجر معيّن مع إمكانية تحديد قائمة IDs."""

    q = PublishChannel.query.filter_by(tenant_slug=tenant_slug)
    if channel_ids:
        q = q.filter(PublishChannel.id.in_(list(channel_ids)))
    if require_active:
        q = q.filter_by(is_active=True)
    return q.order_by(PublishChannel.created_at.desc()).all()


def log_publish_error(job: PublishJob, message: str) -> None:
    """تسجيل خطأ بسيط في لوج التطبيق وتحديث job في نفس الوقت."""
    current_app.logger.error("Publish job %s failed: %s", job.id, message)
    job.error_message = (message or "")[:1000]

