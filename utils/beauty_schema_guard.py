from __future__ import annotations

import logging

from flask import g
from sqlalchemy import inspect, text

from extensions import db

_log = logging.getLogger(__name__)


def _current_engine():
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def ensure_beauty_schema() -> None:
    """Create beauty-center tables and optional columns on the active tenant DB."""
    try:
        engine = _current_engine()
        from models.beauty_service import BeautyService
        from models.beauty_service_product import BeautyServiceProduct
        from models.beauty_appointment import BeautyAppointment
        from models.beauty_session_note import BeautySessionNote

        for model in (BeautyService, BeautyServiceProduct, BeautyAppointment, BeautySessionNote):
            model.__table__.create(bind=engine, checkfirst=True)

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        if "tenant" in tables:
            tenant_cols = {col["name"] for col in inspector.get_columns("tenant")}
            if "business_type" not in tenant_cols:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE tenant ADD COLUMN business_type VARCHAR(50) DEFAULT 'general'"))

        if "product" in tables:
            product_cols = {col["name"] for col in inspector.get_columns("product")}
            additions = {
                "skin_type": "ALTER TABLE product ADD COLUMN skin_type VARCHAR(100)",
                "usage_type": "ALTER TABLE product ADD COLUMN usage_type VARCHAR(100)",
                "requires_patch_test": "ALTER TABLE product ADD COLUMN requires_patch_test BOOLEAN DEFAULT 0",
                "expiry_date": "ALTER TABLE product ADD COLUMN expiry_date DATE",
                "opened_date": "ALTER TABLE product ADD COLUMN opened_date DATE",
                "batch_number": "ALTER TABLE product ADD COLUMN batch_number VARCHAR(100)",
            }
            to_run = [stmt for col, stmt in additions.items() if col not in product_cols]
            if to_run:
                with engine.begin() as conn:
                    for stmt in to_run:
                        conn.execute(text(stmt))
    except Exception:
        _log.exception("ensure_beauty_schema failed")
