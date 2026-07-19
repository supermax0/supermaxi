"""Filesystem helpers for mobile video assets."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import current_app, g


def mobile_videos_root() -> Path:
    configured = (
        (current_app.config.get("MOBILE_VIDEO_ROOT") or "").strip()
        or os.environ.get("MOBILE_VIDEO_ROOT", "").strip()
    )
    if configured:
        root = Path(configured)
    else:
        root = Path(current_app.root_path) / "uploads" / "mobile_videos"
    root.mkdir(parents=True, exist_ok=True)
    return root


def tenant_video_dir(video_id: int, tenant_slug: str | None = None) -> Path:
    slug = (tenant_slug or getattr(g, "tenant", None) or "default").strip().lower()
    path = mobile_videos_root() / slug / str(int(video_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_media_url(video_id: int, kind: str) -> str:
    """API-relative URL served by mobile media routes."""
    if kind == "hls":
        return f"/api/mobile/v1/media/videos/{int(video_id)}/hls/master.m3u8"
    return f"/api/mobile/v1/media/videos/{int(video_id)}/{kind}"


def safe_upload_filename(original_name: str) -> str:
    ext = Path(original_name or "").suffix.lower() or ".mp4"
    if ext not in {".mp4", ".mov", ".webm", ".m4v", ".mkv"}:
        ext = ".mp4"
    return f"{uuid.uuid4().hex}{ext}"
