"""Receipts & Settlements module — central cash collection for Finora."""
from __future__ import annotations

from flask import Flask


def init_receipts(app: Flask) -> None:
    from modules.receipts.api.routes import receipts_api_bp
    from modules.receipts.web.routes import receipts_web_bp

    app.register_blueprint(receipts_web_bp)
    app.register_blueprint(receipts_api_bp)


__all__ = ["init_receipts"]
