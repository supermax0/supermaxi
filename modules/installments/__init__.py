"""Finora installment sales module."""

from .routes import installments_admin_bp, installments_short_bp, installments_store_bp


def init_installments(app):
    app.register_blueprint(installments_admin_bp)
    app.register_blueprint(installments_store_bp)
    app.register_blueprint(installments_short_bp)
