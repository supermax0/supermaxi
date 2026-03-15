"""
pages_api.py
------------
API endpoints for managing connected Facebook pages.
"""

import traceback

from flask import Blueprint, session, g, current_app, request

from extensions import db
from modules.publisher.api.response_utils import error_response, ok_response
from modules.publisher.api.validation_utils import parse_pagination
from modules.publisher.models.publisher_page import PublisherPage
from modules.publisher.services.page_connect_service import connect_and_store_pages
from modules.publisher.services.schema_guard import ensure_publisher_schema

pages_api_bp = Blueprint("publisher_pages_api", __name__)


def _tenant():
    return getattr(g, "tenant", None) or session.get("tenant_slug")


@pages_api_bp.route("/api/pages", methods=["GET"])
def list_pages():
    try:
        ensure_publisher_schema()
        tenant = _tenant()
        page, per_page = parse_pagination(default_per_page=50, max_per_page=200)

        query = PublisherPage.query.filter_by(tenant_slug=tenant).order_by(
            PublisherPage.created_at.desc()
        )
        total = query.count()
        rows = query.offset((page - 1) * per_page).limit(per_page).all()
        items = [row.to_dict() for row in rows]
        return ok_response(
            data={"items": items},
            meta={
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": max(1, (total + per_page - 1) // per_page),
            },
            legacy={"pages": items},
        )
    except Exception as exc:
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="pages_list_failed",
            message=str(exc),
            status_code=500,
        )


@pages_api_bp.route("/api/pages/connect", methods=["POST"])
def connect_pages():
    """
    Exchange a Facebook User Access Token for page tokens, then save/update pages.
    Body: { "user_token": "EAA..." }
    """
    try:
        ensure_publisher_schema()
        data = request.get_json() or {}
        user_token = (data.get("user_token") or "").strip()
        result = connect_and_store_pages(tenant_slug=_tenant(), user_token=user_token)
        if not result.get("success"):
            return error_response(
                code=result.get("error_code") or "pages_connect_failed",
                message=result.get("message") or "فشل ربط الصفحات",
                details=result.get("details"),
                status_code=400,
            )
        return ok_response(
            data=result.get("pages") or [],
            message=result.get("message"),
            legacy={"saved": result.get("pages") or [], "count": result.get("count", 0)},
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="pages_connect_failed",
            message=str(exc),
            status_code=500,
        )


@pages_api_bp.route("/api/pages/<int:page_db_id>", methods=["DELETE"])
def delete_page(page_db_id):
    try:
        ensure_publisher_schema()
        tenant = _tenant()
        page = PublisherPage.query.filter_by(id=page_db_id, tenant_slug=tenant).first()
        if not page:
            return error_response(
                code="page_not_found",
                message="الصفحة غير موجودة",
                status_code=404,
            )
        db.session.delete(page)
        db.session.commit()
        return ok_response(data={"deleted_id": page_db_id}, legacy={"deleted_id": page_db_id})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="page_delete_failed",
            message=str(exc),
            status_code=500,
        )
