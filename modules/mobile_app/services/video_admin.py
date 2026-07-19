"""Admin video upload / publish services."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from extensions import db
from modules.mobile_app.models import MobileVideo, MobileVideoAsset, MobileVideoProduct
from modules.mobile_app.services.storage import (
    public_media_url,
    safe_upload_filename,
    tenant_video_dir,
)
from modules.mobile_app.services.video_processing import enqueue_video_processing

logger = logging.getLogger(__name__)

ALLOWED_CONTENT = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-matroska",
    "application/octet-stream",
}
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


def _max_upload_bytes() -> int:
    import os

    try:
        mb = int(os.environ.get("MOBILE_VIDEO_MAX_MB") or "200")
    except ValueError:
        mb = 200
    return max(1, mb) * 1024 * 1024


def max_upload_mb() -> int:
    return max(1, _max_upload_bytes() // (1024 * 1024))


def create_video_from_upload(
    *,
    tenant_slug: str,
    employee_id: int | None,
    title: str,
    description: str,
    file_storage,
    publish_now: bool = False,
    product_ids: list[int] | None = None,
) -> MobileVideo:
    original_name = getattr(file_storage, "filename", "") or ""
    original_ext = Path(original_name).suffix.lower()
    if original_ext not in ALLOWED_EXTENSIONS:
        raise ValueError("امتداد ملف الفيديو غير مدعوم")

    filename = safe_upload_filename(original_name)
    content_type = (getattr(file_storage, "content_type", None) or "").lower()
    if content_type and content_type not in ALLOWED_CONTENT:
        raise ValueError("نوع ملف الفيديو غير مدعوم")

    video = MobileVideo(
        creator_employee_id=employee_id,
        title=(title or "").strip() or "فيديو بدون عنوان",
        description=(description or "").strip(),
        status="uploaded",
        processing_status="pending",
        processing_progress=0,
    )
    db.session.add(video)
    db.session.flush()

    dest_dir = tenant_video_dir(video.id, tenant_slug)
    dest_path = dest_dir / filename
    max_bytes = _max_upload_bytes()
    size = 0
    try:
        with dest_path.open("wb") as output:
            while True:
                chunk = file_storage.stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(
                        "Video exceeds the configured upload size limit"
                    )
                output.write(chunk)
    except Exception:
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:
            pass
        db.session.rollback()
        raise

    if size <= 0:
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:
            pass
        db.session.rollback()
        raise ValueError("الملف فارغ أو تعذر حفظه")
    if size > max_bytes:
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:
            pass
        db.session.rollback()
        raise ValueError(f"حجم الفيديو يتجاوز الحد المسموح ({max_bytes // (1024 * 1024)} ميجابايت)")

    video.original_path = str(dest_path)
    video.original_asset_url = public_media_url(video.id, "original")
    db.session.add(
        MobileVideoAsset(
            video_id=video.id,
            asset_type="original",
            path=str(dest_path),
            public_url=video.original_asset_url,
        )
    )

    for index, product_id in enumerate(product_ids or []):
        db.session.add(
            MobileVideoProduct(
                video_id=video.id,
                product_id=int(product_id),
                display_order=index,
            )
        )

    if publish_now:
        video.status = "processing"
        video.published_at = datetime.utcnow()
    db.session.commit()

    enqueue_video_processing(tenant_slug, video.id)
    return video


def publish_video(video: MobileVideo) -> MobileVideo:
    if video.deleted_at is not None:
        raise ValueError("الفيديو محذوف")
    if video.processing_status not in {"ready", "failed", "pending", "processing"}:
        pass
    video.status = "published" if video.processing_status == "ready" else "processing"
    if video.published_at is None:
        video.published_at = datetime.utcnow()
    if video.processing_status == "ready":
        video.status = "published"
    db.session.commit()
    return video


def hide_video(video: MobileVideo) -> MobileVideo:
    video.status = "hidden"
    db.session.commit()
    return video


def soft_delete_video(video: MobileVideo) -> MobileVideo:
    video.status = "deleted"
    video.deleted_at = datetime.utcnow()
    db.session.commit()
    return video


def list_admin_videos(*, limit: int = 50, offset: int = 0) -> list[MobileVideo]:
    return (
        MobileVideo.query.filter(MobileVideo.deleted_at.is_(None))
        .order_by(MobileVideo.id.desc())
        .offset(max(0, offset))
        .limit(min(100, max(1, limit)))
        .all()
    )
