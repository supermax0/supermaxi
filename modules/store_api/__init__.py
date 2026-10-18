"""Public read API for the online store catalog."""

from __future__ import annotations

from flask import Flask


def init_store_api(app: Flask) -> None:
    from modules.store_api.api.v1 import store_api_v1_bp

    app.register_blueprint(store_api_v1_bp)
