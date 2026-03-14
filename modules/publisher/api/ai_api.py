"""
ai_api.py
---------
AI content generation endpoints for the Publisher.
"""

import traceback

from flask import Blueprint, jsonify, request, current_app

from modules.publisher.services import ai_service

ai_api_bp = Blueprint("publisher_ai_api", __name__)


@ai_api_bp.route("/api/ai/generate_post", methods=["POST"])
def generate_post():
    data = request.get_json() or {}
    topic = (data.get("topic") or "").strip()
    tone = (data.get("tone") or "احترافي").strip()
    length = (data.get("length") or "متوسط").strip()

    if not topic:
        return jsonify({"success": False, "message": "الموضوع مطلوب"}), 400

    try:
        text = ai_service.generate_post(topic, tone, length)
        return jsonify({"success": True, "text": text})
    except Exception as exc:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(exc)}), 500


@ai_api_bp.route("/api/ai/rewrite", methods=["POST"])
def rewrite():
    data = request.get_json() or {}
    original = (data.get("text") or "").strip()
    tone = (data.get("tone") or "تسويقي").strip()

    if not original:
        return jsonify({"success": False, "message": "النص الأصلي مطلوب"}), 400

    try:
        text = ai_service.rewrite_post(original, tone)
        return jsonify({"success": True, "text": text})
    except Exception as exc:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(exc)}), 500


@ai_api_bp.route("/api/ai/hashtags", methods=["POST"])
def hashtags():
    data = request.get_json() or {}
    topic = (data.get("topic") or "").strip()

    if not topic:
        return jsonify({"success": False, "message": "الموضوع مطلوب"}), 400

    try:
        tags = ai_service.generate_hashtags(topic)
        return jsonify({"success": True, "hashtags": tags})
    except Exception as exc:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(exc)}), 500
