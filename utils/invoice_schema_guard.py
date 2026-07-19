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
        dialect = engine.dialect.name
        bool_default = "BOOLEAN DEFAULT false" if dialect == "postgresql" else "BOOLEAN DEFAULT 0"
        datetime_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
        if "discount_amount" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN discount_amount INTEGER DEFAULT 0")
        if "is_stock_locked" not in invoice_columns:
            stmts.append(f"ALTER TABLE invoice ADD COLUMN is_stock_locked {bool_default}")
        if "stock_lock_reason" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN stock_lock_reason TEXT")
        if "stock_locked_at" not in invoice_columns:
            stmts.append(f"ALTER TABLE invoice ADD COLUMN stock_locked_at {datetime_type}")
        if "stock_unlocked_at" not in invoice_columns:
            stmts.append(f"ALTER TABLE invoice ADD COLUMN stock_unlocked_at {datetime_type}")
        stock_state_added = "stock_is_deducted" not in invoice_columns
        if stock_state_added:
            # Existing unlocked invoices used the legacy eager-deduction policy.
            bool_true = "true" if dialect == "postgresql" else "1"
            stmts.append(f"ALTER TABLE invoice ADD COLUMN stock_is_deducted BOOLEAN DEFAULT {bool_true}")
        if "stock_deducted_at" not in invoice_columns:
            stmts.append(f"ALTER TABLE invoice ADD COLUMN stock_deducted_at {datetime_type}")
        if "stock_restored_at" not in invoice_columns:
            stmts.append(f"ALTER TABLE invoice ADD COLUMN stock_restored_at {datetime_type}")

        if stmts:
            with engine.begin() as conn:
                for stmt in stmts:
                    conn.execute(text(stmt))
                if stock_state_added:
                    conn.execute(text(
                        "UPDATE invoice SET stock_is_deducted = 0 "
                        "WHERE COALESCE(is_stock_locked, 0) = 1 "
                        "OR status IN ('ملغي','راجع','مرتجع','راجعة','راجعه') "
                        "OR payment_status IN ('ملغي','راجع','مرتجع','راجعة','راجعه')"
                    ))
                    conn.execute(text(
                        "UPDATE invoice SET stock_deducted_at = created_at "
                        "WHERE stock_deducted_at IS NULL AND (stock_is_deducted = 1 "
                        "OR status IN ('ملغي','راجع','مرتجع','راجعة','راجعه') "
                        "OR payment_status IN ('ملغي','راجع','مرتجع','راجعة','راجعه'))"
                    ))
                    conn.execute(text(
                        "UPDATE invoice SET stock_restored_at = created_at "
                        "WHERE stock_is_deducted = 0 AND stock_deducted_at IS NOT NULL "
                        "AND stock_restored_at IS NULL"
                    ))
    except Exception:
        _log.exception("ensure_invoice_schema failed")
