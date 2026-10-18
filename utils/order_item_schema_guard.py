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
    """Ensure order line variant/trade-in columns and supporting tables exist."""
    try:
        engine = _schema_engine()
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        with engine.begin() as conn:
            if "order_item" in tables:
                cols = {c["name"] for c in inspector.get_columns("order_item")}
                if "variant_color" not in cols:
                    conn.execute(text("ALTER TABLE order_item ADD COLUMN variant_color VARCHAR(80)"))
                if "sale_mode" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE order_item ADD COLUMN sale_mode VARCHAR(20) "
                            "NOT NULL DEFAULT 'normal'"
                        )
                    )
                if "trade_in_source_product_id" not in cols:
                    conn.execute(
                        text("ALTER TABLE order_item ADD COLUMN trade_in_source_product_id INTEGER")
                    )
                if "trade_in_source_product_name" not in cols:
                    conn.execute(
                        text("ALTER TABLE order_item ADD COLUMN trade_in_source_product_name VARCHAR(150)")
                    )

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
                                buy_price INTEGER,
                                sale_price INTEGER,
                                governorate_sale_price INTEGER,
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
                                buy_price INTEGER,
                                sale_price INTEGER,
                                governorate_sale_price INTEGER,
                                FOREIGN KEY(product_id) REFERENCES product(id) ON DELETE CASCADE,
                                UNIQUE(product_id, color_name)
                            )
                            """
                        )
                    )

            color_variant_cols = set()
            try:
                color_variant_cols = {
                    c["name"] for c in inspect(engine).get_columns("product_color_variant")
                }
            except Exception:
                color_variant_cols = set()
            if color_variant_cols:
                if "buy_price" not in color_variant_cols:
                    conn.execute(text("ALTER TABLE product_color_variant ADD COLUMN buy_price INTEGER"))
                if "sale_price" not in color_variant_cols:
                    conn.execute(text("ALTER TABLE product_color_variant ADD COLUMN sale_price INTEGER"))
                if "governorate_sale_price" not in color_variant_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE product_color_variant ADD COLUMN governorate_sale_price INTEGER"
                        )
                    )

            if "trade_in_receipt" not in tables:
                dialect = engine.dialect.name
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS trade_in_receipt (
                                id SERIAL PRIMARY KEY,
                                invoice_id INTEGER NOT NULL REFERENCES invoice(id) ON DELETE CASCADE,
                                order_item_id INTEGER NOT NULL UNIQUE REFERENCES order_item(id) ON DELETE CASCADE,
                                source_product_id INTEGER REFERENCES product(id) ON DELETE SET NULL,
                                source_product_name VARCHAR(150) NOT NULL,
                                replacement_product_id INTEGER REFERENCES product(id),
                                branch_id INTEGER REFERENCES branch(id),
                                quantity INTEGER NOT NULL DEFAULT 1,
                                status VARCHAR(20) NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'received', 'reversed')),
                                received_at TIMESTAMP,
                                reversed_at TIMESTAMP,
                                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS trade_in_receipt (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                invoice_id INTEGER NOT NULL,
                                order_item_id INTEGER NOT NULL UNIQUE,
                                source_product_id INTEGER,
                                source_product_name VARCHAR(150) NOT NULL,
                                replacement_product_id INTEGER,
                                branch_id INTEGER,
                                quantity INTEGER NOT NULL DEFAULT 1,
                                status VARCHAR(20) NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'received', 'reversed')),
                                received_at DATETIME,
                                reversed_at DATETIME,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                FOREIGN KEY(invoice_id) REFERENCES invoice(id) ON DELETE CASCADE,
                                FOREIGN KEY(order_item_id) REFERENCES order_item(id) ON DELETE CASCADE,
                                FOREIGN KEY(source_product_id) REFERENCES product(id) ON DELETE SET NULL,
                                FOREIGN KEY(replacement_product_id) REFERENCES product(id),
                                FOREIGN KEY(branch_id) REFERENCES branch(id)
                            )
                            """
                        )
                    )
    except Exception:
        _log.exception("ensure_order_item_schema failed")
