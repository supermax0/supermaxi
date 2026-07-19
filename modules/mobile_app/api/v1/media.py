"""Serve mobile video media assets with basic Range support."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from flask import Response, request, send_file

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp
from modules.mobile_app.models import MobileVideo, MobileVideoAsset
from modules.mobile_app.schemas import api_error
from modules.mobile_app.services.storage import tenant_video_dir


def _media_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".m3u8":
        return "application/vnd.apple.mpegurl"
    if suffix == ".ts":
        # Python's platform MIME database may incorrectly classify MPEG-TS as
        # Qt Linguist text, which Android ExoPlayer refuses to decode.
        return "video/mp2t"
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _safe_media_path(path: Path, video_id: int) -> Path | None:
    candidate = path.resolve()
    allowed_root = tenant_video_dir(video_id).resolve()
    try:
        candidate.relative_to(allowed_root)
    except ValueError:
        return None
    return candidate


def _asset_path(video: MobileVideo, kind: str) -> Path | None:
    kind = (kind or "").lower()
    if kind == "original" and video.original_path:
        return Path(video.original_path)
    if kind == "thumbnail":
        asset = MobileVideoAsset.query.filter_by(
            video_id=video.id, asset_type="thumbnail"
        ).first()
        if asset and asset.path:
            return Path(asset.path)
    if kind == "hls":
        if video.hls_master_path:
            return Path(video.hls_master_path)
        asset = MobileVideoAsset.query.filter_by(video_id=video.id, asset_type="hls").first()
        if asset and asset.path:
            return Path(asset.path)
    return None


@mobile_api_v1_bp.get("/media/videos/<int:video_id>/<string:kind>")
def serve_video_media(video_id: int, kind: str):
    video = MobileVideo.query.filter_by(id=video_id).first()
    if video is None or video.deleted_at is not None:
        return api_error("not found", 404, code="not_found")

    # HLS segments: /media/videos/<id>/hls/<file>
    if kind == "hls" and request.view_args is not None:
        pass

    path = _asset_path(video, kind)
    if path is None or not path.exists():
        # Fallback: original for playback when HLS missing
        if kind == "hls" and video.original_path and Path(video.original_path).exists():
            path = Path(video.original_path)
        else:
            return api_error("media not found", 404, code="media_missing")

    path = _safe_media_path(path, video_id)
    if path is None:
        return api_error("invalid media path", 400, code="bad_path")

    mime = _media_mime(path)
    return send_file(path, mimetype=mime, conditional=True)


@mobile_api_v1_bp.get("/media/videos/<int:video_id>/hls/<path:filename>")
def serve_hls_segment(video_id: int, filename: str):
    video = MobileVideo.query.filter_by(id=video_id).first()
    if video is None or not video.hls_master_path:
        return api_error("not found", 404, code="not_found")
    base = Path(video.hls_master_path).parent
    target = (base / filename).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return api_error("invalid path", 400, code="bad_path")
    target = _safe_media_path(target, video_id)
    if target is None:
        return api_error("invalid path", 400, code="bad_path")
    if not target.exists():
        return api_error("not found", 404, code="not_found")
    mime = _media_mime(target)
    return send_file(target, mimetype=mime, conditional=True)
