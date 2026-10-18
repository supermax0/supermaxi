"""Reports dashboard + ten detail reports (JSON, Excel, printable) — services/reports_service.py."""

from __future__ import annotations

from flask import Flask


def init_reports_api(app: Flask) -> None:
    from modules.reports_api.routes import reports_api_bp

    app.register_blueprint(reports_api_bp)
