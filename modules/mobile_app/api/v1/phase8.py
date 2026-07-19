"""Notifications, devices, analytics, design, feature-flag APIs (Phase 8)."""
from __future__ import annotations

from flask import g, request

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp, require_mobile_auth
from modules.mobile_app.schemas import api_error, api_ok, require_json_fields
from modules.mobile_app.services import analytics as analytics_service
from modules.mobile_app.services import design as design_service
from modules.mobile_app.services import feature_flags as flags_service
from modules.mobile_app.services import notifications as notif_service
from modules.mobile_app.services.analytics import AnalyticsError
from modules.mobile_app.services.notifications import NotificationError
from utils.permission_checks import check_permission, get_current_employee


def _require_staff(*permission_names: str):
    from functools import wraps

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            employee = get_current_employee()
            if employee is None:
                from flask import current_app

                if current_app.config.get("TESTING") and request.headers.get("X-Test-Staff-Id"):
                    from extensions import db
                    from models.employee import Employee

                    employee = db.session.get(
                        Employee, int(request.headers["X-Test-Staff-Id"])
                    )
                    if employee:
                        g.mobile_staff = employee
                        return view(*args, **kwargs)
                return api_error("Staff login required", 401, code="staff_required")
            role = (employee.role or "").strip().lower()
            if role != "admin":
                allowed = False
                for name in permission_names:
                    if check_permission(name):
                        allowed = True
                        break
                if not allowed:
                    return api_error("Permission denied", 403, code="forbidden")
            g.mobile_staff = employee
            return view(*args, **kwargs)

        return wrapped

    return decorator


@mobile_api_v1_bp.get("/notifications")
@require_mobile_auth
def notifications_list():
    unread_only = str(request.args.get("unread_only") or "").lower() in {
        "1",
        "true",
        "yes",
    }
    limit = min(100, max(1, int(request.args.get("limit") or 40)))
    items = notif_service.list_notifications(
        g.mobile_user.id, limit=limit, unread_only=unread_only
    )
    return api_ok(
        {
            "items": items,
            "unread_count": notif_service.unread_count(g.mobile_user.id),
        }
    )


@mobile_api_v1_bp.patch("/notifications/<int:notification_id>/read")
@require_mobile_auth
def notifications_mark_read(notification_id: int):
    try:
        return api_ok(notif_service.mark_read(g.mobile_user.id, notification_id))
    except NotificationError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)


@mobile_api_v1_bp.get("/notifications/preferences")
@require_mobile_auth
def notifications_prefs_get():
    return api_ok({"preferences": notif_service.get_preferences(g.mobile_user.id)})


@mobile_api_v1_bp.patch("/notifications/preferences")
@require_mobile_auth
def notifications_prefs_patch():
    body = request.get_json(silent=True) or {}
    return api_ok(
        {"preferences": notif_service.update_preferences(g.mobile_user.id, body)}
    )


@mobile_api_v1_bp.post("/devices/register")
@require_mobile_auth
def devices_register():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "device_id")
    if missing:
        return api_error(missing, 400, code="validation_error")
    try:
        device = notif_service.register_device(
            user_id=g.mobile_user.id,
            device_id=str(body.get("device_id")),
            platform=str(body.get("platform") or "unknown"),
            push_token=body.get("push_token"),
            app_version=body.get("app_version"),
        )
        return api_ok({"device": device})
    except NotificationError as exc:
        return api_error(exc.message, 400, code=exc.code)


@mobile_api_v1_bp.delete("/devices/<int:device_id>")
@require_mobile_auth
def devices_delete(device_id: int):
    try:
        notif_service.unregister_device(user_id=g.mobile_user.id, device_row_id=device_id)
        return api_ok({"deleted": True})
    except NotificationError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)


@mobile_api_v1_bp.post("/analytics/events")
@require_mobile_auth
def analytics_events():
    body = request.get_json(silent=True) or {}
    events = body.get("events")
    try:
        result = analytics_service.ingest_events(
            user_id=g.mobile_user.id,
            events=events if isinstance(events, list) else [],
            device_id=str(body.get("device_id") or "") or None,
        )
        return api_ok(result)
    except AnalyticsError as exc:
        return api_error(exc.message, 400, code=exc.code)


@mobile_api_v1_bp.post("/admin/notifications/send")
@_require_staff("mobile_app.send_notifications", "mobile_app.manage_settings")
def admin_send_notification():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "title", "body")
    if missing:
        return api_error(missing, 400, code="validation_error")
    user_id = body.get("user_id")
    if user_id:
        notif = notif_service.create_user_notification(
            user_id=int(user_id),
            title=str(body.get("title")),
            body=str(body.get("body")),
            notification_type=str(body.get("type") or "general"),
            data=body.get("data") if isinstance(body.get("data"), dict) else {},
        )
        return api_ok(
            {"notification_id": notif.id if notif else None, "status": "sent"},
            status=201,
        )
    result = notif_service.enqueue_broadcast(
        title=str(body.get("title")),
        body=str(body.get("body")),
        notification_type=str(body.get("type") or "marketing"),
        audience=str(body.get("audience") or "all"),
        data=body.get("data") if isinstance(body.get("data"), dict) else {},
        created_by=getattr(g.mobile_staff, "id", None),
        tenant_slug=getattr(g, "tenant", None),
    )
    return api_ok(result, status=202)


@mobile_api_v1_bp.get("/admin/analytics/summary")
@_require_staff("mobile_app.view_analytics", "mobile_app.manage_settings")
def admin_analytics_summary():
    days = int(request.args.get("days") or 7)
    return api_ok({"summary": analytics_service.conversion_summary(days=days)})


@mobile_api_v1_bp.get("/admin/feature-flags")
@_require_staff("mobile_app.manage_settings")
def admin_feature_flags_get():
    return api_ok({"feature_flags": flags_service.list_feature_flags()})


@mobile_api_v1_bp.patch("/admin/feature-flags")
@_require_staff("mobile_app.manage_settings")
def admin_feature_flags_patch():
    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or "").strip()
    if not key:
        return api_error("key مطلوب", 400, code="validation_error")
    if "enabled" not in body:
        return api_error("enabled مطلوب", 400, code="validation_error")
    try:
        flags = flags_service.set_feature_flag(key, bool(body.get("enabled")))
        return api_ok({"feature_flags": flags})
    except ValueError as exc:
        return api_error(str(exc), 400, code="validation_error")


@mobile_api_v1_bp.get("/admin/design")
@_require_staff("mobile_app.manage_design", "mobile_app.manage_settings")
def admin_design_get():
    return api_ok({"design": design_service.get_design()})


@mobile_api_v1_bp.patch("/admin/design")
@_require_staff("mobile_app.manage_design", "mobile_app.manage_settings")
def admin_design_patch():
    body = request.get_json(silent=True) or {}
    return api_ok({"design": design_service.update_design(body)})
