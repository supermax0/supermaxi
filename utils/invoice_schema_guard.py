from __future__ import annotations

import logging

from flask import g
from sqlalchemy import inspect, text

from extensions import db

_log = logging.getLogger(__name__)


def _schema_engine():
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def ensure_invoice_schema() -> None:
    """Ensure invoice table has columns required by POS discount and related features."""
    try:
        engine = _schema_engine()
        inspector = inspect(engine)
        if "invoice" not in inspector.get_table_names():
            return

        invoice_columns = {col["name"] for col in inspector.get_columns("invoice")}
        stmts: list[str] = []
        if "discount_amount" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN discount_amount INTEGER DEFAULT 0")

        if stmts:
            with engine.begin() as conn:
                for stmt in stmts:
                    conn.execute(text(stmt))
    except Exception:
        _log.exception("ensure_invoice_schema failed")
