"""Finora Phone staff companion API (Phase 1)."""

from __future__ import annotations

from flask import Flask


def init_phone_app(app: Flask) -> None:
    """Register the phone staff API blueprint."""
    from modules.phone_app.api.v1 import phone_api_v1_bp

    app.register_blueprint(phone_api_v1_bp)
