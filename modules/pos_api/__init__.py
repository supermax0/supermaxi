"""Finora POS machine API (voice Core / staff clients)."""

from __future__ import annotations

from flask import Flask


def init_pos_api(app: Flask) -> None:
    from modules.pos_api.api.v1 import pos_api_v1_bp

    app.register_blueprint(pos_api_v1_bp)
