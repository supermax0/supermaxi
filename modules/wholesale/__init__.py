"""Wholesale (تجارة الجملة) module — isolated from general / beauty_center."""
from __future__ import annotations

from flask import Flask


def init_wholesale(app: Flask) -> None:
    from modules.wholesale.api.routes import wholesale_api_bp
    from modules.wholesale.web.routes import wholesale_web_bp

    app.register_blueprint(wholesale_web_bp)
    app.register_blueprint(wholesale_api_bp)


__all__ = ["init_wholesale"]
