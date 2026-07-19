"""Background video processing (thumbnail + optional HLS).

Celery/Redis is optional. When unavailable we process in a daemon thread
using the same `process_video_job` entrypoint — ready for `.delay()` later.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, current_app

logger = logging.getLogger(__name__)


def _ffmpeg_bin() -> str | None:
    try:
        from modules.ai_sales.openai_service import get_ffmpeg_binary

        return get_ffmpeg_binary()
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _ffprobe_duration_ms(ffmpeg: str, path: Path) -> int | None:
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe") if "ffmpeg" in ffmpeg else shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            return None
        seconds = float((result.stdout or "").strip() or "0")
        return int(seconds * 1000) if seconds > 0 else None
    except Exception:
        logger.exception("ffprobe failed for %s", path)
        return None


def _run_ffmpeg(cmd: list[str]) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        if result.returncode != 0:
            logger.warning("ffmpeg failed: %s", (result.stderr or "")[-500:])
            return False
        return True
    except Exception:
        logger.exception("ffmpeg invoke error")
        return False


def process_video_job(app: Flask, tenant_slug: str, video_id: int) -> None:
    """Process one video inside an app/tenant context."""
    with app.app_context():
        from flask import g

        from extensions import db
        from modules.mobile_app.models import MobileVideo, MobileVideoAsset
        from modules.mobile_app.schema_guard import ensure_mobile_app_schema
        from modules.mobile_app.services.storage import public_media_url, tenant_video_dir

        g.tenant = tenant_slug
        ensure_mobile_app_schema()
        video = db.session.get(MobileVideo, video_id)
        if video is None or video.deleted_at is not None:
            return

        video.status = "processing"
        video.processing_status = "processing"
        video.processing_progress = 5
        video.processing_error = None
        db.session.commit()

        try:
            source = Path(video.original_path or "")
            if not source.exists():
                raise FileNotFoundError(f"original missing: {source}")

            out_dir = tenant_video_dir(video.id, tenant_slug)
            ffmpeg = _ffmpeg_bin()
            video.processing_progress = 20
            db.session.commit()

            thumb_path = out_dir / "thumbnail.jpg"
            if ffmpeg:
                ok = _run_ffmpeg(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        str(source),
                        "-ss",
                        "00:00:01",
                        "-vframes",
                        "1",
                        "-q:v",
                        "2",
                        str(thumb_path),
                    ]
                )
                if ok and thumb_path.exists():
                    video.thumbnail_url = public_media_url(video.id, "thumbnail")
                    db.session.add(
                        MobileVideoAsset(
                            video_id=video.id,
                            asset_type="thumbnail",
                            path=str(thumb_path),
                            public_url=video.thumbnail_url,
                        )
                    )

            video.processing_progress = 50
            duration = _ffprobe_duration_ms(ffmpeg, source) if ffmpeg else None
            if duration:
                video.duration_ms = duration
            db.session.commit()

            # HLS (best-effort). Fallback: progressive MP4 ready.
            hls_dir = out_dir / "hls"
            hls_dir.mkdir(parents=True, exist_ok=True)
            master = hls_dir / "master.m3u8"
            hls_ok = False
            if ffmpeg:
                hls_ok = _run_ffmpeg(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        str(source),
                        "-c:v",
                        "libx264",
                        "-c:a",
                        "aac",
                        "-hls_time",
                        "2",
                        "-hls_list_size",
                        "0",
                        "-f",
                        "hls",
                        str(master),
                    ]
                )
            if hls_ok and master.exists():
                video.hls_master_path = str(master)
                video.hls_master_url = public_media_url(video.id, "hls")
                db.session.add(
                    MobileVideoAsset(
                        video_id=video.id,
                        asset_type="hls",
                        path=str(master),
                        public_url=video.hls_master_url,
                    )
                )

            video.processing_progress = 100
            video.processing_status = "ready"
            if video.published_at is not None or video.status in {"processing", "uploaded", "ready"}:
                # Keep explicit hidden/archived; otherwise become published when ready
                if video.status not in {"hidden", "archived", "deleted", "draft"}:
                    video.status = "published"
                    if video.published_at is None:
                        video.published_at = datetime.utcnow()
            video.updated_at = datetime.utcnow()
            db.session.commit()
            logger.info(
                "mobile video processed id=%s tenant=%s hls=%s",
                video.id,
                tenant_slug,
                bool(video.hls_master_url),
            )
        except Exception as exc:
            logger.exception("mobile video processing failed id=%s", video_id)
            video.processing_status = "failed"
            video.status = "failed"
            video.processing_error = str(exc)[:1000]
            video.processing_progress = 0
            db.session.commit()


def enqueue_video_processing(tenant_slug: str, video_id: int) -> None:
    """Queue processing. Prefer Celery when configured; else background thread."""
    app = current_app._get_current_object()

    try:
        from modules.mobile_app.tasks.celery_app import celery_app  # type: ignore

        if celery_app is not None:
            celery_app.send_task(
                "mobile_app.process_video",
                args=[tenant_slug, video_id],
            )
            return
    except Exception:
        pass

    thread = threading.Thread(
        target=process_video_job,
        args=(app, tenant_slug, video_id),
        daemon=True,
        name=f"mobile-video-{video_id}",
    )
    thread.start()
