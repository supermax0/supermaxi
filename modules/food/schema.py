"""Lazy, tenant-local schema creation for the food workspace."""
from __future__ import annotations

import logging

from flask import g
from sqlalchemy import inspect, text

from extensions import db
from modules.food.models import FOOD_MODELS

_log = logging.getLogger(__name__)
_ensured: set[str] = set()


ADDITIVE_COLUMNS = {
    "food_product_profile": {
        "origin_country": "VARCHAR(100)",
        "subcategory": "VARCHAR(120)",
        "supplier_product_code": "VARCHAR(120)",
        "track_batches": "BOOLEAN DEFAULT 0",
        "shelf_life_value": "INTEGER",
        "shelf_life_unit": "VARCHAR(20)",
        "expiry_warning_days": "INTEGER DEFAULT 30",
        "issue_policy": "VARCHAR(10) DEFAULT 'FIFO'",
        "reorder_quantity": "INTEGER DEFAULT 0",
        "maximum_stock": "INTEGER",
        "storage_location": "VARCHAR(255)",
        "storage_type": "VARCHAR(20) DEFAULT 'normal'",
        "return_policy": "VARCHAR(40) DEFAULT 'normal'",
        "taxable": "BOOLEAN DEFAULT 0",
        "tax_rate": "NUMERIC(7,3) DEFAULT 0",
        "auto_wholesale_pricing": "BOOLEAN DEFAULT 1",
        "status": "VARCHAR(20) DEFAULT 'active'",
        "updated_at": "DATETIME",
    },
    "food_product_variant": {
        "size_value": "NUMERIC(12,3)",
        "size_unit": "VARCHAR(20)",
        "reorder_quantity": "INTEGER DEFAULT 0",
        "maximum_stock": "INTEGER",
        "storage_location": "VARCHAR(255)",
        "default_sale_unit_id": "INTEGER",
        "default_purchase_unit_id": "INTEGER",
        "status": "VARCHAR(20) DEFAULT 'active'",
    },
    "food_product_unit": {
        "parent_unit_id": "INTEGER",
        "parent_multiplier": "INTEGER",
        "wholesale_minimum": "INTEGER DEFAULT 1",
        "auto_wholesale": "BOOLEAN DEFAULT 0",
        "can_sell": "BOOLEAN DEFAULT 1",
        "can_purchase": "BOOLEAN DEFAULT 1",
        "sort_order": "INTEGER DEFAULT 0",
    },
    "food_inventory_movement": {
        "warehouse_id": "INTEGER",
        "batch_id": "INTEGER",
    },
    "food_expiry_batch": {
        "warehouse_id": "INTEGER",
        "received_unit_id": "INTEGER",
        "production_date": "DATE",
        "reserved_quantity_base": "INTEGER DEFAULT 0",
        "received_quantity": "INTEGER",
        "unit_factor_snapshot": "INTEGER DEFAULT 1",
        "unit_cost_snapshot": "INTEGER DEFAULT 0",
        "supplier_id": "INTEGER",
        "purchase_id": "INTEGER",
        "status": "VARCHAR(20) DEFAULT 'sellable'",
    },
    "food_sale_item_snapshot": {
        "warehouse_id": "INTEGER",
        "barcode_snapshot": "VARCHAR(160)",
        "product_name_snapshot": "VARCHAR(150)",
        "quantity_snapshot": "NUMERIC(18,3)",
        "discount_snapshot": "INTEGER DEFAULT 0",
        "tax_snapshot": "INTEGER DEFAULT 0",
        "line_total_snapshot": "INTEGER",
        "note_snapshot": "TEXT",
    },
    "food_purchase_item_snapshot": {
        "warehouse_id": "INTEGER",
        "unit_price_snapshot": "INTEGER DEFAULT 0",
        "barcode_snapshot": "VARCHAR(160)",
    },
    "food_settings": {
        "negative_stock_policy": "VARCHAR(30) DEFAULT 'prevent'",
        "hide_out_of_stock": "BOOLEAN DEFAULT 0",
        "auto_print": "VARCHAR(20) DEFAULT 'ask'",
        "fast_pos_mode": "BOOLEAN DEFAULT 0",
        "scale_barcode_enabled": "BOOLEAN DEFAULT 0",
        "scale_barcode_prefix": "VARCHAR(10) DEFAULT '20'",
        "scale_barcode_product_digits": "INTEGER DEFAULT 5",
        "scale_barcode_value_digits": "INTEGER DEFAULT 5",
        "scale_barcode_divisor": "INTEGER DEFAULT 1000",
        "default_receivable_days": "INTEGER DEFAULT 30",
        "default_payable_days": "INTEGER DEFAULT 30",
        "default_issue_policy": "VARCHAR(10) DEFAULT 'FEFO'",
        "receipt_footer": "VARCHAR(255)",
    },
    "food_customer_profile": {
        "payment_term_days": "INTEGER",
    },
}


def _engine():
    slug = getattr(g, "tenant", None)
    if slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(slug)
    return db.session.get_bind() or db.engine


def ensure_food_schema() -> None:
    """Create only additive food tables, and only after the food guard passes."""
    key = str(getattr(g, "tenant", None) or "default")
    if key in _ensured:
        return
    engine = _engine()
    try:
        for model in FOOD_MODELS:
            model.__table__.create(bind=engine, checkfirst=True)
        inspector = inspect(engine)
        with engine.begin() as connection:
            for table_name, additions in ADDITIVE_COLUMNS.items():
                if not inspector.has_table(table_name):
                    continue
                existing = {column["name"] for column in inspector.get_columns(table_name)}
                for column_name, definition in additions.items():
                    if column_name in existing:
                        continue
                    connection.execute(text(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'
                    ))
        _ensured.add(key)
    except Exception:
        _log.exception("Food workspace schema initialization failed")
        raise


def clear_food_schema_cache() -> None:
    _ensured.clear()
