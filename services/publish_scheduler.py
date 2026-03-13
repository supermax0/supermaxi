from __future__ import annotations

from datetime import datetime
import json
import time
from typing import List, Optional

from flask import current_app

import requests

from extensions import db
from models.publish_channel import PublishChannel
from models.publish_job import PublishJob
from services.publish_service import PublishResult, PublisherChannel, log_publish_error


class FacebookPageChannel:
    """قناة نشر لصفحات فيسبوك تعتمد على page_access_token المخزن في credentials."""

    def __init__(self, channel: PublishChannel):
        self.channel = channel

    def publish(self, job: PublishJob) -> PublishResult:
        try:
            creds = json.loads(self.channel.credentials or "{}")
        except Exception:
            creds = {}

        token = creds.get("page_access_token")
        if not token:
            return PublishResult(
                success=False,
                error_code="no_page_token",
                error_message="لا يوجد Page Access Token مخزّن لهذه الصفحة.",
            )

        page_id = self.channel.external_id
        if not page_id:
            return PublishResult(
                success=False,
                error_code="no_page_id",
                error_message="لا يوجد معرّف صفحة صالح في القناة.",
            )

        message = (job.text or "").strip()
        media_url = (job.media_url or "").strip() or None
        media_type = (job.media_type or "").strip() or None

        # فيسبوك يحتاج رابط وسائط مطلقاً وقابلاً للوصول من الإنترنت
        if media_url and media_url.startswith("/"):
            try:
                base_url = current_app.config.get("PUBLISH_BASE_URL") or current_app.config.get("SERVER_NAME")
                if base_url:
                    if not base_url.startswith("http"):
                        base_url = "https://" + base_url.rstrip("/")
                    else:
                        base_url = base_url.rstrip("/")
                    media_url = base_url + media_url
            except Exception:
                pass

        base = f"https://graph.facebook.com/v19.0/{page_id}"
        params = {"access_token": token}
        data = {}
        endpoint = base + "/feed"

        if media_url and media_type == "image":
            endpoint = base + "/photos"
            data = {"url": media_url}
            if message:
                data["caption"] = message
        elif media_url and media_type == "video":
            endpoint = base + "/videos"
            data = {"file_url": media_url}
            if message:
                data["description"] = message
        else:
            endpoint = base + "/feed"
            if message:
                data["message"] = message
            if media_url and media_type in (None, "", "link"):
                data["link"] = media_url

        try:
            resp = requests.post(endpoint, params=params, data=data, timeout=60)
        except Exception as exc:
            return PublishResult(
                success=False,
                error_code="network_error",
                error_message=f"فشل الاتصال بـ Facebook: {exc}",
            )

        try:
            payload = resp.json()
        except Exception:
            payload = {}

        if not resp.ok:
            return PublishResult(
                success=False,
                error_code="facebook_error",
                error_message=str(payload)[:500],
            )

        remote_id = payload.get("id") or payload.get("post_id") or payload.get("video_id")
        if not remote_id:
            return PublishResult(
                success=False,
                error_code="facebook_no_id",
                error_message="تم الاتصال بـ Facebook لكن لم يتم إرجاع معرّف للمنشور.",
            )

        return PublishResult(success=True, remote_id=str(remote_id))


def _get_channel_handler(channel: PublishChannel) -> Optional[PublisherChannel]:
    """إرجاع handler مناسب حسب نوع القناة."""

    if channel.type == "facebook_page":
        return FacebookPageChannel(channel)
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
    total = len(jobs)
    for idx, job in enumerate(jobs):
        process_job(job)
        count += 1
        # تأخير 5 ثوانٍ بين كل مهمة وأخرى لتجنّب الضغط على المنصة (صفحة بعد صفحة)
        if idx < total - 1:
            time.sleep(5)

    return count

