"""Optional Celery hook for mobile video processing.

Without Redis/Celery installed, `celery_app` stays None and the thread
fallback in `enqueue_video_processing` is used.
"""
from __future__ import annotations

celery_app = None

try:
    import os

    broker = (os.environ.get("CELERY_BROKER_URL") or os.environ.get("REDIS_URL") or "").strip()
    if broker:
        from celery import Celery

        celery_app = Celery("finora_mobile", broker=broker)
        celery_app.conf.task_always_eager = False

        @celery_app.task(name="mobile_app.process_video")
        def process_video_task(tenant_slug: str, video_id: int) -> None:
            from flask import current_app

            from modules.mobile_app.services.video_processing import process_video_job

            process_video_job(current_app._get_current_object(), tenant_slug, video_id)

except Exception:
    celery_app = None
