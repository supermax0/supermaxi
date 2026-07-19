"""Mobile feed + engagement endpoints."""
from __future__ import annotations

from flask import g, request

from modules.mobile_app.api.v1.routes import (
    mobile_api_v1_bp,
    optional_mobile_auth,
    require_mobile_auth,
)
from modules.mobile_app.models import MobileVideo
from modules.mobile_app.schemas import api_error, api_ok
from modules.mobile_app.services import feed as feed_service
from modules.mobile_app.services import shared_cache
from modules.mobile_app.services.feature_flags import is_flag_enabled


def _feed_video_or_404(video_id: int) -> MobileVideo | tuple:
    video = MobileVideo.query.filter(
        MobileVideo.id == video_id,
        MobileVideo.deleted_at.is_(None),
        MobileVideo.processing_status == "ready",
        MobileVideo.status.in_(["published", "ready"]),
    ).first()
    if video is None:
        return api_error("الفيديو غير موجود", 404, code="not_found")
    return video


@mobile_api_v1_bp.get("/feed")
@optional_mobile_auth
def feed():
    if not is_flag_enabled("video_feed_enabled", True):
        return api_error("Video feed disabled", 403, code="feed_disabled")
    cursor = request.args.get("cursor")
    limit = min(20, max(1, int(request.args.get("limit") or 6)))
    cache_parts = {"version": 2, "limit": limit}
    if g.mobile_user is None and not cursor:
        cached = shared_cache.get_json("guest-feed-first-page", cache_parts)
        if isinstance(cached, dict):
            response, status = api_ok(cached)
            response.headers["X-Finora-Cache"] = "HIT"
            return response, status
    items, next_cursor = feed_service.list_feed(
        user_id=g.mobile_user.id if g.mobile_user else None,
        cursor=cursor,
        limit=limit,
    )
    payload = {"items": items, "next_cursor": next_cursor}
    if g.mobile_user is None and not cursor:
        shared_cache.set_json("guest-feed-first-page", cache_parts, payload, ttl=3)
    response, status = api_ok(payload)
    response.headers["X-Finora-Cache"] = "MISS"
    return response, status


@mobile_api_v1_bp.get("/videos/<int:video_id>")
@optional_mobile_auth
def get_video(video_id: int):
    video = _feed_video_or_404(video_id)
    if not isinstance(video, MobileVideo):
        return video
    user_id = g.mobile_user.id if g.mobile_user else None
    # Prefer dedicated like/save flags for signed-in shoppers.
    from modules.mobile_app.models import MobileVideoLike, MobileVideoSave

    liked = bool(user_id) and (
        MobileVideoLike.query.filter_by(video_id=video.id, user_id=g.mobile_user.id).first()
        is not None
    )
    saved = bool(user_id) and (
        MobileVideoSave.query.filter_by(video_id=video.id, user_id=g.mobile_user.id).first()
        is not None
    )
    return api_ok({"video": video.to_feed_dict(liked=liked, saved=saved)})


@mobile_api_v1_bp.post("/videos/<int:video_id>/view")
@optional_mobile_auth
def view_video(video_id: int):
    video = _feed_video_or_404(video_id)
    if not isinstance(video, MobileVideo):
        return video
    body = request.get_json(silent=True) or {}
    feed_service.record_view(
        video=video,
        user_id=g.mobile_user.id if g.mobile_user else None,
        device_id=body.get("device_id"),
        watch_ms=int(body.get("watch_ms") or 0),
        completed=bool(body.get("completed")),
    )
    return api_ok({"views_count": int(video.views_count or 0)})


@mobile_api_v1_bp.post("/videos/<int:video_id>/like")
@require_mobile_auth
def like_video(video_id: int):
    video = _feed_video_or_404(video_id)
    if not isinstance(video, MobileVideo):
        return video
    from modules.mobile_app.models import MobileVideoLike

    existing = MobileVideoLike.query.filter_by(
        video_id=video.id, user_id=g.mobile_user.id
    ).first()
    if existing:
        return api_ok({"liked": True, "likes_count": int(video.likes_count or 0)})
    liked, count = feed_service.toggle_like(video=video, user_id=g.mobile_user.id)
    return api_ok({"liked": liked, "likes_count": count})


@mobile_api_v1_bp.delete("/videos/<int:video_id>/like")
@require_mobile_auth
def unlike_video(video_id: int):
    video = _feed_video_or_404(video_id)
    if not isinstance(video, MobileVideo):
        return video
    from modules.mobile_app.models import MobileVideoLike

    existing = MobileVideoLike.query.filter_by(
        video_id=video.id, user_id=g.mobile_user.id
    ).first()
    if not existing:
        return api_ok({"liked": False, "likes_count": int(video.likes_count or 0)})
    _, count = feed_service.toggle_like(video=video, user_id=g.mobile_user.id)
    return api_ok({"liked": False, "likes_count": count})


@mobile_api_v1_bp.post("/videos/<int:video_id>/save")
@require_mobile_auth
def save_video(video_id: int):
    video = _feed_video_or_404(video_id)
    if not isinstance(video, MobileVideo):
        return video
    try:
        from modules.mobile_app.models import MobileVideoSave

        existing = MobileVideoSave.query.filter_by(
            video_id=video.id, user_id=g.mobile_user.id
        ).first()
        if existing:
            saved, count = True, int(video.saves_count or 0)
        else:
            saved, count = feed_service.toggle_save(video=video, user_id=g.mobile_user.id)
    except ValueError as exc:
        return api_error(str(exc), 403, code="save_disabled")
    return api_ok({"saved": True, "saves_count": count})


@mobile_api_v1_bp.delete("/videos/<int:video_id>/save")
@require_mobile_auth
def unsave_video(video_id: int):
    video = _feed_video_or_404(video_id)
    if not isinstance(video, MobileVideo):
        return video
    from modules.mobile_app.models import MobileVideoSave

    existing = MobileVideoSave.query.filter_by(
        video_id=video.id, user_id=g.mobile_user.id
    ).first()
    if existing:
        try:
            feed_service.toggle_save(video=video, user_id=g.mobile_user.id)
        except ValueError as exc:
            return api_error(str(exc), 403, code="save_disabled")
    return api_ok({"saved": False, "saves_count": int(video.saves_count or 0)})


@mobile_api_v1_bp.post("/videos/<int:video_id>/share")
@optional_mobile_auth
def share_video(video_id: int):
    video = _feed_video_or_404(video_id)
    if not isinstance(video, MobileVideo):
        return video
    if not is_flag_enabled("video_sharing_enabled", True):
        return api_error("المشاركة معطّلة", 403, code="share_disabled")
    body = request.get_json(silent=True) or {}
    try:
        count = feed_service.record_share(
            video=video,
            user_id=g.mobile_user.id if g.mobile_user else None,
            channel=str(body.get("channel") or "app"),
        )
    except ValueError as exc:
        return api_error(str(exc), 403, code="share_disabled")
    return api_ok({"shares_count": count})
