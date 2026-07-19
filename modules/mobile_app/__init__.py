"""Finora Social Commerce mobile app package (Phase 1)."""

from __future__ import annotations

from flask import Flask


def init_mobile_app(app: Flask) -> None:
    """Register the mobile API + Finora admin UI blueprints."""
    from modules.mobile_app.api.v1 import mobile_api_v1_bp
    from modules.mobile_app.admin_routes import mobile_admin_bp

    app.register_blueprint(mobile_api_v1_bp)
    app.register_blueprint(mobile_admin_bp)
