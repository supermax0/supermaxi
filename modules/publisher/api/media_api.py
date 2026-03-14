"""
media_api.py
------------
API endpoints for the Publisher media library.
"""

import traceback

from flask import Blueprint, jsonify, request, session, g, current_app

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
        items = media_service.list_media(tenant, q=q, media_type=media_type)
        return jsonify({"success": True, "media": [m.to_dict() for m in items]})
    except Exception as e:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500


@media_api_bp.route("/api/media/upload", methods=["POST"])
def upload_media():
    try:
        ensure_publisher_schema()
        tenant = _tenant()
        file = request.files.get("file")
        if not file:
            return jsonify({"success": False, "message": "لم يتم إرسال ملف"}), 400

        result = media_service.save_upload(file, tenant)
        if result.get("success"):
            media = result["media"]
            return jsonify({"success": True, "media": media.to_dict(), "url": media.url_path})
        return jsonify({"success": False, "message": result.get("message")}), 400
    except Exception as e:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500


@media_api_bp.route("/api/media/<int:media_id>", methods=["DELETE"])
def delete_media(media_id):
    try:
        ensure_publisher_schema()
        result = media_service.delete_media(media_id)
        if result.get("success"):
            return jsonify({"success": True})
        return jsonify({"success": False, "message": result.get("message")}), 404
    except Exception as e:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500
