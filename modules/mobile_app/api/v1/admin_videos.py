"""Staff-authenticated admin video endpoints."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp
from modules.mobile_app.models import MobileVideo
from modules.mobile_app.schemas import api_error, api_ok
from modules.mobile_app.services import video_admin as video_admin_service
from utils.permission_checks import check_permission, get_current_employee


def require_staff_video_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        employee = get_current_employee()
        if employee is None:
            # Allow tests to inject staff via header when TESTING
            from flask import current_app

            if current_app.config.get("TESTING") and request.headers.get("X-Test-Staff-Id"):
                from extensions import db
                from models.employee import Employee

                employee = db.session.get(Employee, int(request.headers["X-Test-Staff-Id"]))
                if employee:
                    g.mobile_staff = employee
                    return view(*args, **kwargs)
            return api_error("Staff login required", 401, code="staff_required")
        if (employee.role or "") != "admin" and not check_permission("mobile_app.manage_videos"):
            return api_error("Permission denied", 403, code="forbidden")
        g.mobile_staff = employee
        return view(*args, **kwargs)

    return wrapped


@mobile_api_v1_bp.get("/admin/videos")
@require_staff_video_admin
def admin_list_videos():
    limit = int(request.args.get("limit") or 50)
    offset = int(request.args.get("offset") or 0)
    rows = video_admin_service.list_admin_videos(limit=limit, offset=offset)
    return api_ok({"items": [v.to_admin_dict() for v in rows]})


@mobile_api_v1_bp.post("/admin/videos")
@require_staff_video_admin
def admin_upload_video():
    upload = request.files.get("file") or request.files.get("video")
    if upload is None or not upload.filename:
        return api_error("ملف الفيديو مطلوب", 400, code="file_required")

    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    publish_now = (request.form.get("publish_now") or "1").strip() in {"1", "true", "yes"}
    product_raw = (request.form.get("product_ids") or "").strip()
    product_ids: list[int] = []
    if product_raw:
        for part in product_raw.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                product_ids.append(int(part))

    try:
        video = video_admin_service.create_video_from_upload(
            tenant_slug=g.tenant,
            employee_id=getattr(g.mobile_staff, "id", None),
            title=title,
            description=description,
            file_storage=upload,
            publish_now=publish_now,
            product_ids=product_ids,
        )
    except ValueError as exc:
        return api_error(str(exc), 400, code="upload_error")
    except Exception:
        return api_error("فشل رفع الفيديو", 500, code="upload_failed")

    return api_ok({"video": video.to_admin_dict()}, status=201)


@mobile_api_v1_bp.post("/admin/videos/<int:video_id>/publish")
@require_staff_video_admin
def admin_publish_video(video_id: int):
    video = MobileVideo.query.filter_by(id=video_id).first()
    if video is None or video.deleted_at is not None:
        return api_error("الفيديو غير موجود", 404, code="not_found")
    video = video_admin_service.publish_video(video)
    return api_ok({"video": video.to_admin_dict()})


@mobile_api_v1_bp.post("/admin/videos/<int:video_id>/hide")
@require_staff_video_admin
def admin_hide_video(video_id: int):
    video = MobileVideo.query.filter_by(id=video_id).first()
    if video is None or video.deleted_at is not None:
        return api_error("الفيديو غير موجود", 404, code="not_found")
    video = video_admin_service.hide_video(video)
    return api_ok({"video": video.to_admin_dict()})


@mobile_api_v1_bp.delete("/admin/videos/<int:video_id>")
@require_staff_video_admin
def admin_delete_video(video_id: int):
    video = MobileVideo.query.filter_by(id=video_id).first()
    if video is None or video.deleted_at is not None:
        return api_error("الفيديو غير موجود", 404, code="not_found")
    video = video_admin_service.soft_delete_video(video)
    return api_ok({"video": video.to_admin_dict()})


@mobile_api_v1_bp.post("/admin/videos/<int:video_id>/products")
@require_staff_video_admin
def admin_link_video_product(video_id: int):
    from modules.mobile_app.services import catalog as catalog_service

    body = request.get_json(silent=True) or {}
    product_id = body.get("product_id")
    if not product_id:
        return api_error("product_id مطلوب", 400, code="validation_error")
    try:
        link = catalog_service.link_product_to_video(
            video_id=video_id,
            product_id=int(product_id),
            display_order=int(body.get("display_order") or 0),
            special_price=int(body["special_price"]) if body.get("special_price") is not None else None,
            custom_title=(body.get("custom_title") or None),
            custom_cta=(body.get("custom_cta") or None),
        )
    except ValueError as exc:
        return api_error(str(exc), 400, code="link_error")
    return api_ok({"link": link.to_dict()}, status=201)
