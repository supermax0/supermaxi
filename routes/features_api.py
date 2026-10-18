"""Tenant-facing feature APIs. Enforcement is always backend-side."""
from __future__ import annotations

from flask import Blueprint, jsonify, session

from services import feature_service as fs

features_api_bp = Blueprint("features_api", __name__)


@features_api_bp.app_context_processor
def _inject_feature_helper():
    def feature_enabled(feature_key: str) -> bool:
        """Template helper; UI hiding only — APIs enforce independently."""
        if not session.get("user_id"):
            return False
        try:
            return fs.is_enabled_for_slug(fs.current_tenant_slug(), feature_key)
        except Exception:
            return False  # fail closed: a broken lookup must never enable a feature

    return {"feature_enabled": feature_enabled}


@features_api_bp.get("/api/features/me")
def my_features():
    if not session.get("user_id") or not fs.current_tenant_slug():
        return jsonify({"error": "AUTH_REQUIRED"}), 401
    return jsonify({"features": fs.effective_features_for_slug(fs.current_tenant_slug())})


@features_api_bp.get("/api/clinic/ai-tutor/status")
@fs.require_feature(fs.AI_TUTOR)
def ai_tutor_status():
    status = fs.get_status(fs.current_tenant_slug(), fs.AI_TUTOR)
    return jsonify({
        "ok": True,
        "feature": fs.AI_TUTOR,
        "enabled": True,
        "expires_at": status["expires_at"],
        "configuration": status["configuration"],
    })
