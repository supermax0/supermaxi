"""
media_api.py
------------
API endpoints for the Publisher media library.
"""

import traceback

from flask import Blueprint, request, session, g, current_app

from modules.publisher.api.response_utils import error_response, ok_response
from modules.publisher.api.validation_utils import parse_pagination
from modules.publisher.services import media_service
from modules.publisher.services.schema_guard import ensure_publisher_schema

media_api_bp = Blueprint("publisher_media_api", __name__)


def _tenant():
    return getattr(g, "tenant", None) or session.get("tenant_slug") or "default"


@media_api_bp.route("/api/media", methods=["GET"])
def list_media():
    try:
        ensure_publisher_schema()
        tenant = _tenant()
        q = request.args.get("q")
        media_type = request.args.get("type")
        page, per_page = parse_pagination(default_per_page=24, max_per_page=200)
        items, total = media_service.list_media(
            tenant, q=q, media_type=media_type, page=page, per_page=per_page
        )
        payload = [row.to_dict() for row in items]
        return ok_response(
            data={"items": payload},
            meta={
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": max(1, (total + per_page - 1) // per_page),
            },
            legacy={"media": payload},
        )
    except Exception as exc:
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="media_list_failed",
            message=str(exc),
            status_code=500,
        )


@media_api_bp.route("/api/media/upload", methods=["POST"])
def upload_media():
    try:
        ensure_publisher_schema()
        tenant = _tenant()
        file = request.files.get("file")
        if not file:
            return error_response(
                code="missing_file",
                message="لم يتم إرسال ملف",
                status_code=400,
            )

        result = media_service.save_upload(file, tenant)
        if result.get("success"):
            media = result["media"]
            return ok_response(
                data=media.to_dict(),
                message="تم رفع الوسيط بنجاح",
                legacy={"media": media.to_dict(), "url": media.url_path},
            )
        return error_response(
            code="media_upload_failed",
            message=result.get("message") or "فشل رفع الوسيط",
            status_code=400,
        )
    except Exception as exc:
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="media_upload_failed",
            message=str(exc),
            status_code=500,
        )


@media_api_bp.route("/api/media/<int:media_id>", methods=["DELETE"])
def delete_media(media_id):
    try:
        ensure_publisher_schema()
        result = media_service.delete_media(media_id, tenant_slug=_tenant())
        if result.get("success"):
            return ok_response(data={"deleted_id": media_id}, legacy={"deleted_id": media_id})
        return error_response(
            code="media_not_found",
            message=result.get("message") or "الوسيط غير موجود",
            status_code=404,
        )
    except Exception as exc:
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="media_delete_failed",
            message=str(exc),
            status_code=500,
        )
