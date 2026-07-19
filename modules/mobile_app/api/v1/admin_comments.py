"""Admin comment moderation endpoints."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp
from modules.mobile_app.schemas import api_error, api_ok, require_json_fields
from modules.mobile_app.services import comments as comments_service
from modules.mobile_app.services.comments import CommentError
from utils.permission_checks import check_permission, get_current_employee


def require_staff_comment_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        employee = get_current_employee()
        if employee is None:
            from flask import current_app

            if current_app.config.get("TESTING") and request.headers.get("X-Test-Staff-Id"):
                from extensions import db
                from models.employee import Employee

                employee = db.session.get(Employee, int(request.headers["X-Test-Staff-Id"]))
                if employee:
                    g.mobile_staff = employee
                    return view(*args, **kwargs)
            return api_error("Staff login required", 401, code="staff_required")
        if (employee.role or "") != "admin" and not check_permission(
            "mobile_app.manage_comments"
        ):
            return api_error("Permission denied", 403, code="forbidden")
        g.mobile_staff = employee
        return view(*args, **kwargs)

    return wrapped


@mobile_api_v1_bp.get("/admin/comments")
@require_staff_comment_admin
def admin_list_comments():
    status = request.args.get("status")
    limit = int(request.args.get("limit") or 50)
    rows = comments_service.list_admin_comments(status=status, limit=limit)
    return api_ok({"items": [c.to_admin_dict() for c in rows]})


@mobile_api_v1_bp.post("/admin/comments/<int:comment_id>/hide")
@require_staff_comment_admin
def admin_hide_comment(comment_id: int):
    try:
        comment = comments_service.admin_hide_comment(comment_id)
    except CommentError as exc:
        return api_error(exc.message, 404, code=exc.code)
    return api_ok({"comment": comment.to_admin_dict()})


@mobile_api_v1_bp.post("/admin/comments/<int:comment_id>/pin")
@require_staff_comment_admin
def admin_pin_comment(comment_id: int):
    body = request.get_json(silent=True) or {}
    pinned = body.get("pinned", True)
    try:
        comment = comments_service.admin_pin_comment(comment_id, pinned=bool(pinned))
    except CommentError as exc:
        return api_error(exc.message, 400, code=exc.code)
    return api_ok({"comment": comment.to_admin_dict()})


@mobile_api_v1_bp.post("/admin/comments/reply")
@require_staff_comment_admin
def admin_company_reply():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "video_id", "body")
    if missing:
        return api_error(missing, 400, code="validation_error")
    try:
        comment = comments_service.admin_company_reply(
            video_id=int(body["video_id"]),
            parent_id=int(body["parent_id"]) if body.get("parent_id") else None,
            body=str(body.get("body") or ""),
            employee_id=getattr(g.mobile_staff, "id", None),
        )
    except CommentError as exc:
        return api_error(exc.message, 400, code=exc.code)
    return api_ok(
        {"comment": comment.to_public_dict(author_name="Finora")},
        status=201,
    )


@mobile_api_v1_bp.post("/admin/users/<int:user_id>/block")
@require_staff_comment_admin
def admin_block_user(user_id: int):
    body = request.get_json(silent=True) or {}
    row = comments_service.admin_block_user(
        user_id=user_id,
        employee_id=getattr(g.mobile_staff, "id", None),
        reason=body.get("reason"),
    )
    return api_ok({"blocked_user_id": row.user_id, "reason": row.reason})
