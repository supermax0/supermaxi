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


def ensure_order_item_schema() -> None:
    """Ensure order_item and purchase_item have variant_color; create color variant table."""
    try:
        engine = _schema_engine()
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        with engine.begin() as conn:
            if "order_item" in tables:
                cols = {c["name"] for c in inspector.get_columns("order_item")}
                if "variant_color" not in cols:
                    conn.execute(text("ALTER TABLE order_item ADD COLUMN variant_color VARCHAR(80)"))

            if "purchase_item" in tables:
                cols = {c["name"] for c in inspector.get_columns("purchase_item")}
                if "variant_color" not in cols:
                    conn.execute(text("ALTER TABLE purchase_item ADD COLUMN variant_color VARCHAR(80)"))

            if "product_color_variant" not in tables:
                dialect = engine.dialect.name
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS product_color_variant (
                                id SERIAL PRIMARY KEY,
                                product_id INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,
                                color_name VARCHAR(80) NOT NULL,
                                quantity INTEGER NOT NULL DEFAULT 0,
                                CONSTRAINT _product_color_uc UNIQUE (product_id, color_name)
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS product_color_variant (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                product_id INTEGER NOT NULL,
                                color_name VARCHAR(80) NOT NULL,
                                quantity INTEGER NOT NULL DEFAULT 0,
                                FOREIGN KEY(product_id) REFERENCES product(id) ON DELETE CASCADE,
                                UNIQUE(product_id, color_name)
                            )
                            """
                        )
                    )
    except Exception:
        _log.exception("ensure_order_item_schema failed")
