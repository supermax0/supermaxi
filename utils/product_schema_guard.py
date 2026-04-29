from __future__ import annotations

import os
import sys

import logging

from flask import g
from sqlalchemy import inspect, text

# If this file is executed directly (e.g. `python utils/product_schema_guard.py`),
# Python's import path points at `utils/` and won't find project-root modules.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from extensions import db

_log = logging.getLogger(__name__)


def _product_schema_engine():
    """Same DB as Product queries: tenant SQLite when g.tenant is set."""
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def ensure_product_schema() -> None:
    """
    Ensures `product` table has required columns for the advanced product form.
    Runs against the currently-bound engine (Core or the active tenant), so it
    works in multi-tenant mode where each tenant has its own DB.
    """
    try:
        engine = _product_schema_engine()
        inspector = inspect(engine)

        if "product" not in inspector.get_table_names():
            return

        existing_cols = {col["name"] for col in inspector.get_columns("product")}

        # Columns introduced for the advanced product page.
        additions = {
            "sku": "ALTER TABLE product ADD COLUMN sku VARCHAR(100)",
            "description": "ALTER TABLE product ADD COLUMN description TEXT",
            "image_url": "ALTER TABLE product ADD COLUMN image_url VARCHAR(512)",
            "meta_json": "ALTER TABLE product ADD COLUMN meta_json TEXT",
        }

        # Also keep prior additions that some installs might miss.
        # (These are safe to run only if the column is absent.)
        # SQLite: ADD COLUMN must NOT use UNIQUE/PRIMARY KEY — use plain type only.
        additions.setdefault(
            "barcode",
            "ALTER TABLE product ADD COLUMN barcode VARCHAR(100)",
        )
        additions.setdefault(
            "low_stock_threshold",
            "ALTER TABLE product ADD COLUMN low_stock_threshold INTEGER DEFAULT 5",
        )
        additions.setdefault("skin_type", "ALTER TABLE product ADD COLUMN skin_type VARCHAR(100)")
        additions.setdefault("usage_type", "ALTER TABLE product ADD COLUMN usage_type VARCHAR(100)")
        additions.setdefault(
            "requires_patch_test",
            "ALTER TABLE product ADD COLUMN requires_patch_test BOOLEAN DEFAULT 0",
        )
        additions.setdefault("expiry_date", "ALTER TABLE product ADD COLUMN expiry_date DATE")
        additions.setdefault("opened_date", "ALTER TABLE product ADD COLUMN opened_date DATE")
        additions.setdefault("batch_number", "ALTER TABLE product ADD COLUMN batch_number VARCHAR(100)")

        to_run = [stmt for col_name, stmt in additions.items() if col_name not in existing_cols]
        if to_run:
            with engine.begin() as conn:
                for stmt in to_run:
                    conn.execute(text(stmt))
    except Exception:
        _log.exception("ensure_product_schema failed (product table migrations)")
        return


def ensure_customer_blacklist_columns() -> None:
    """Adds customer blacklist columns on tenant/core engine bound to current request."""
    try:
        engine = _product_schema_engine()
        inspector = inspect(engine)
        if "customer" not in inspector.get_table_names():
            return
        existing = {c["name"] for c in inspector.get_columns("customer")}
        dialect = engine.dialect.name
        dt_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
        stmts: list[str] = []
        if "is_blacklisted" not in existing:
            stmts.append("ALTER TABLE customer ADD COLUMN is_blacklisted BOOLEAN DEFAULT 0")
        if "blacklist_reason" not in existing:
            stmts.append("ALTER TABLE customer ADD COLUMN blacklist_reason TEXT")
        if "blacklisted_at" not in existing:
            stmts.append(f"ALTER TABLE customer ADD COLUMN blacklisted_at {dt_type}")
        if stmts:
            with engine.begin() as conn:
                for stmt in stmts:
                    conn.execute(text(stmt))
    except Exception:
        _log.exception("ensure_customer_blacklist_columns failed")
        return


if __name__ == "__main__":
    # This helper needs the app + SQLAlchemy to be initialized (app context).
    # It is intended to be imported and executed from routes / app startup.
    print(
        "This script is not meant to be run standalone.\n"
        "Start the app (app.py) and visit /inventory or /inventory/add to auto-apply the schema guard."
    )

