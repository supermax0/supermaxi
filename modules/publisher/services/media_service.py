"""
media_service.py
----------------
Handles file uploads, storage and retrieval for the Publisher media library.
Storage layout: media/<tenant_slug>/images/ or media/<tenant_slug>/videos/
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from flask import current_app
from werkzeug.utils import secure_filename

from extensions import db
from modules.publisher.models.publisher_media import PublisherMedia

logger = logging.getLogger("publisher")

ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
ALLOWED_VIDEO_EXT = {"mp4", "mov", "avi", "mkv", "webm"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _media_root() -> str:
    return current_app.config.get("PUBLISHER_MEDIA_ROOT") or os.path.join(
        current_app.root_path, "media"
    )


def _get_media_type(ext: str) -> Optional[str]:
    ext = ext.lower().lstrip(".")
    if ext in ALLOWED_IMAGE_EXT:
        return "image"
    if ext in ALLOWED_VIDEO_EXT:
        return "video"
    return None


def save_upload(file_storage, tenant_slug: str) -> dict:
    """
    Validate and save an uploaded file.
    Returns {"success": True, "media": PublisherMedia} or {"success": False, "message": "..."}
    """
    if not file_storage or not file_storage.filename:
        return {"success": False, "message": "لم يتم رفع أي ملف"}

    original_name = file_storage.filename
    ext = os.path.splitext(original_name)[1]
    media_type = _get_media_type(ext)
    if not media_type:
        return {"success": False, "message": f"نوع الملف غير مدعوم: {ext}"}

    # Build per-tenant folder: media/<tenant>/images/ or media/<tenant>/videos/
    tenant_dir = tenant_slug or "default"
    sub = "images" if media_type == "image" else "videos"
    folder = os.path.join(_media_root(), tenant_dir, sub)
    os.makedirs(folder, exist_ok=True)

    # Unique filename to prevent collisions
    safe_ext = secure_filename(ext).lstrip(".")
    filename = f"{uuid.uuid4().hex}.{safe_ext}"
    file_path = os.path.join(folder, filename)

    try:
        file_storage.save(file_path)
    except Exception as exc:
        logger.error("media save error: %s", exc)
        return {"success": False, "message": f"خطأ في حفظ الملف: {exc}"}

    size_bytes = os.path.getsize(file_path)
    if size_bytes > MAX_UPLOAD_BYTES:
        os.remove(file_path)
        return {"success": False, "message": "حجم الملف يتجاوز الحد المسموح (500 MB)"}

    url_path = f"/media/{tenant_dir}/{sub}/{filename}"

    media = PublisherMedia(
        tenant_slug=tenant_slug,
        filename=filename,
        original_name=original_name,
        media_type=media_type,
        size_bytes=size_bytes,
        url_path=url_path,
    )
    db.session.add(media)
    db.session.commit()

    logger.info("Media uploaded: %s (%s, %d bytes)", filename, media_type, size_bytes)
    return {"success": True, "media": media}


def delete_media(media_id: int) -> dict:
    """Delete media from DB + disk."""
    media = PublisherMedia.query.get(media_id)
    if not media:
        return {"success": False, "message": "الوسيط غير موجود"}

    # Try to remove the physical file
    try:
        root = _media_root()
        tenant_dir = media.tenant_slug or "default"
        sub = "images" if media.media_type == "image" else "videos"
        file_path = os.path.join(root, tenant_dir, sub, media.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as exc:
        logger.warning("Could not delete file %s: %s", media.filename, exc)

    db.session.delete(media)
    db.session.commit()
    return {"success": True}


def list_media(tenant_slug: str, q: str = None, media_type: str = None):
    """Return PublisherMedia list for a tenant."""
    query = PublisherMedia.query.filter_by(tenant_slug=tenant_slug)
    if media_type in ("image", "video"):
        query = query.filter_by(media_type=media_type)
    if q:
        query = query.filter(PublisherMedia.original_name.ilike(f"%{q}%"))
    return query.order_by(PublisherMedia.created_at.desc()).all()
