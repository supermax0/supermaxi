"""
pages_api.py
------------
API endpoints for managing connected Facebook pages.
"""

import traceback

from flask import Blueprint, jsonify, request, session, g, current_app

from extensions import db
from modules.publisher.models.publisher_page import PublisherPage
from modules.publisher.services import facebook_service as fb
from modules.publisher.services.schema_guard import ensure_publisher_schema
from modules.publisher.services.token_utils import encrypt_token, decrypt_token

pages_api_bp = Blueprint("publisher_pages_api", __name__)


def _tenant():
    return getattr(g, "tenant", None) or session.get("tenant_slug")


@pages_api_bp.route("/api/pages", methods=["GET"])
def list_pages():
    try:
        ensure_publisher_schema()
        tenant = _tenant()
        pages = PublisherPage.query.filter_by(tenant_slug=tenant).order_by(
            PublisherPage.created_at.desc()
        ).all()
        return jsonify({"success": True, "pages": [p.to_dict() for p in pages]})
    except Exception as e:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500


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
        if not user_token:
            return jsonify({"success": False, "message": "user_token مطلوب"}), 400

        result = fb.get_user_pages(user_token)
        if not result.get("success"):
            return jsonify(result), 400

        tenant = _tenant()
        saved = []
        for page_data in result.get("pages", []):
            page_id = page_data.get("id")
            page_name = page_data.get("name", "")
            access_token = page_data.get("access_token", "")
            if not page_id or not access_token:
                continue

            existing = PublisherPage.query.filter_by(
                tenant_slug=tenant, page_id=page_id
            ).first()
            if existing:
                existing.page_name = page_name
                existing.page_token = encrypt_token(access_token)
            else:
                new_page = PublisherPage(
                    tenant_slug=tenant,
                    page_id=page_id,
                    page_name=page_name,
                    page_token=encrypt_token(access_token),
                )
                db.session.add(new_page)
            saved.append({"page_id": page_id, "page_name": page_name})

        db.session.commit()
        return jsonify({"success": True, "saved": saved, "count": len(saved)})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500


@pages_api_bp.route("/api/pages/<int:page_db_id>", methods=["DELETE"])
def delete_page(page_db_id):
    try:
        ensure_publisher_schema()
        tenant = _tenant()
        page = PublisherPage.query.filter_by(id=page_db_id, tenant_slug=tenant).first()
        if not page:
            return jsonify({"success": False, "message": "الصفحة غير موجودة"}), 404
        db.session.delete(page)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500
