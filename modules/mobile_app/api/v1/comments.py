"""Mobile comment endpoints (Phase 3)."""
from __future__ import annotations

from flask import g, request

from modules.mobile_app.api.v1.routes import (
    mobile_api_v1_bp,
    optional_mobile_auth,
    require_mobile_auth,
)
from modules.mobile_app.schemas import api_error, api_ok, require_json_fields
from modules.mobile_app.services import comments as comments_service
from modules.mobile_app.services.comments import CommentError
from modules.mobile_app.services.feature_flags import is_flag_enabled


def _ensure_comments_enabled():
    if not is_flag_enabled("comments_enabled", True):
        return api_error("التعليقات معطّلة", 403, code="comments_disabled")
    return None


@mobile_api_v1_bp.get("/videos/<int:video_id>/comments")
@optional_mobile_auth
def list_video_comments(video_id: int):
    disabled = _ensure_comments_enabled()
    if disabled:
        return disabled
    limit = int(request.args.get("limit") or 30)
    offset = int(request.args.get("offset") or 0)
    items = comments_service.list_comments_for_video(
        video_id=video_id,
        viewer_user_id=g.mobile_user.id if g.mobile_user else None,
        limit=limit,
        offset=offset,
    )
    return api_ok({"items": items})


@mobile_api_v1_bp.post("/videos/<int:video_id>/comments")
@require_mobile_auth
def create_video_comment(video_id: int):
    disabled = _ensure_comments_enabled()
    if disabled:
        return disabled
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "body")
    if missing:
        return api_error(missing, 400, code="validation_error")
    try:
        comment = comments_service.create_comment(
            video_id=video_id,
            user_id=g.mobile_user.id,
            body=str(body.get("body") or ""),
        )
    except CommentError as exc:
        return api_error(exc.message, 400, code=exc.code)
    return api_ok(
        {
            "comment": comment.to_public_dict(
                author_name=g.mobile_user.name or g.mobile_user.phone
            )
        },
        status=201,
    )


@mobile_api_v1_bp.post("/comments/<int:comment_id>/replies")
@require_mobile_auth
def reply_to_comment(comment_id: int):
    disabled = _ensure_comments_enabled()
    if disabled:
        return disabled
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "body")
    if missing:
        return api_error(missing, 400, code="validation_error")
    from modules.mobile_app.models import MobileComment

    parent = MobileComment.query.filter_by(id=comment_id).first()
    if parent is None:
        return api_error("التعليق غير موجود", 404, code="not_found")
    try:
        comment = comments_service.create_comment(
            video_id=parent.video_id,
            user_id=g.mobile_user.id,
            body=str(body.get("body") or ""),
            parent_id=comment_id,
        )
    except CommentError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)
    return api_ok(
        {
            "comment": comment.to_public_dict(
                author_name=g.mobile_user.name or g.mobile_user.phone
            )
        },
        status=201,
    )


@mobile_api_v1_bp.post("/comments/<int:comment_id>/like")
@require_mobile_auth
def like_comment(comment_id: int):
    disabled = _ensure_comments_enabled()
    if disabled:
        return disabled
    from modules.mobile_app.models import MobileCommentLike

    existing = MobileCommentLike.query.filter_by(
        comment_id=comment_id, user_id=g.mobile_user.id
    ).first()
    if existing:
        from modules.mobile_app.models import MobileComment

        comment = MobileComment.query.get(comment_id)
        return api_ok(
            {"liked": True, "likes_count": int(getattr(comment, "likes_count", 0) or 0)}
        )
    try:
        liked, count = comments_service.toggle_comment_like(
            comment_id=comment_id, user_id=g.mobile_user.id
        )
    except CommentError as exc:
        return api_error(exc.message, 404 if exc.code == "not_found" else 400, code=exc.code)
    return api_ok({"liked": liked, "likes_count": count})


@mobile_api_v1_bp.delete("/comments/<int:comment_id>/like")
@require_mobile_auth
def unlike_comment(comment_id: int):
    disabled = _ensure_comments_enabled()
    if disabled:
        return disabled
    from modules.mobile_app.models import MobileCommentLike

    existing = MobileCommentLike.query.filter_by(
        comment_id=comment_id, user_id=g.mobile_user.id
    ).first()
    if not existing:
        from modules.mobile_app.models import MobileComment

        comment = MobileComment.query.get(comment_id)
        return api_ok(
            {"liked": False, "likes_count": int(getattr(comment, "likes_count", 0) or 0)}
        )
    try:
        _, count = comments_service.toggle_comment_like(
            comment_id=comment_id, user_id=g.mobile_user.id
        )
    except CommentError as exc:
        return api_error(exc.message, 404 if exc.code == "not_found" else 400, code=exc.code)
    return api_ok({"liked": False, "likes_count": count})


@mobile_api_v1_bp.delete("/comments/<int:comment_id>")
@require_mobile_auth
def delete_comment(comment_id: int):
    disabled = _ensure_comments_enabled()
    if disabled:
        return disabled
    try:
        comment = comments_service.soft_delete_comment(
            comment_id=comment_id, user_id=g.mobile_user.id
        )
    except CommentError as exc:
        status = 403 if exc.code == "forbidden" else 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)
    return api_ok({"comment": comment.to_public_dict()})


@mobile_api_v1_bp.post("/comments/<int:comment_id>/report")
@require_mobile_auth
def report_comment(comment_id: int):
    disabled = _ensure_comments_enabled()
    if disabled:
        return disabled
    body = request.get_json(silent=True) or {}
    try:
        report = comments_service.report_comment(
            comment_id=comment_id,
            reporter_user_id=g.mobile_user.id,
            reason=body.get("reason"),
            details=body.get("details"),
        )
    except CommentError as exc:
        return api_error(exc.message, 404 if exc.code == "not_found" else 400, code=exc.code)
    return api_ok({"report_id": report.id, "status": report.status}, status=201)
