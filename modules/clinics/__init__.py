"""Finora Clinics — medical clinic & medical center workspace."""
from __future__ import annotations

from flask import Flask


def init_clinics(app: Flask) -> None:
    from modules.clinics.public_routes import clinics_public_api_bp, clinics_public_bp
    from modules.clinics.routes import clinics_bp
    from modules.clinics.service_jobs import start_clinics_scheduler

    app.register_blueprint(clinics_public_bp)
    # Public patient portal. Keep /book temporarily for existing saved links.
    app.register_blueprint(clinics_public_bp, url_prefix="/c", name="clinics_portal")
    app.register_blueprint(clinics_public_api_bp)
    app.register_blueprint(clinics_bp)
    start_clinics_scheduler(app)


__all__ = ["init_clinics"]
