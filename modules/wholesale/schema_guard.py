"""Safe CREATE/ALTER for wholesale tables and shared-model extensions."""
from __future__ import annotations

import logging

from flask import g
from sqlalchemy import inspect, text

from extensions import db

_log = logging.getLogger(__name__)
_ENSURED: set[str] = set()


def _current_engine():
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def _add_columns(engine, table: str, additions: dict[str, str]) -> None:
    inspector = inspect(engine)
    if table not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns(table)}
    to_run = [stmt for col, stmt in additions.items() if col not in cols]
    if not to_run:
        return
    with engine.begin() as conn:
        for stmt in to_run:
            conn.execute(text(stmt))


def ensure_wholesale_schema() -> None:
    tenant_key = str(getattr(g, "tenant", None) or "default")
    if tenant_key in _ENSURED:
        return
    try:
        engine = _current_engine()
        datetime_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
        bool_false = "false" if engine.dialect.name == "postgresql" else "0"
        from modules.wholesale.models.warehouse import (
            Warehouse,
            WarehouseMovement,
            WarehouseStock,
            WarehouseTransfer,
            WarehouseTransferLine,
        )
        from modules.wholesale.models.party_ledger import PartyLedgerEntry
        from modules.wholesale.models.draft import WholesaleDraft

        for model in (
            Warehouse,
            WarehouseStock,
            WarehouseMovement,
            WarehouseTransfer,
            WarehouseTransferLine,
            PartyLedgerEntry,
            WholesaleDraft,
        ):
            model.__table__.create(bind=engine, checkfirst=True)

        _add_columns(
            engine,
            "invoice",
            {
                "warehouse_id": "ALTER TABLE invoice ADD COLUMN warehouse_id INTEGER",
                "currency": "ALTER TABLE invoice ADD COLUMN currency VARCHAR(10) DEFAULT 'IQD'",
                "exchange_rate": "ALTER TABLE invoice ADD COLUMN exchange_rate FLOAT DEFAULT 1.0",
                "payment_currency": "ALTER TABLE invoice ADD COLUMN payment_currency VARCHAR(10)",
                "sale_type": "ALTER TABLE invoice ADD COLUMN sale_type VARCHAR(30)",
                "is_draft": f"ALTER TABLE invoice ADD COLUMN is_draft BOOLEAN DEFAULT {bool_false}",
                "deleted_at": f"ALTER TABLE invoice ADD COLUMN deleted_at {datetime_type}",
                "source_module": "ALTER TABLE invoice ADD COLUMN source_module VARCHAR(40)",
                "invoice_no": "ALTER TABLE invoice ADD COLUMN invoice_no VARCHAR(80)",
                "shipping_fee": "ALTER TABLE invoice ADD COLUMN shipping_fee INTEGER DEFAULT 0",
            },
        )
        _add_columns(
            engine,
            "employee",
            {
                "default_warehouse_id": "ALTER TABLE employee ADD COLUMN default_warehouse_id INTEGER",
            },
        )
        _add_columns(
            engine,
            "warehouse_movement",
            {
                "quantity_before": "ALTER TABLE warehouse_movement ADD COLUMN quantity_before INTEGER",
                "quantity_after": "ALTER TABLE warehouse_movement ADD COLUMN quantity_after INTEGER",
            },
        )
        _add_columns(
            engine,
            "warehouse_transfer",
            {
                "approved_by_id": "ALTER TABLE warehouse_transfer ADD COLUMN approved_by_id INTEGER",
                "approved_at": f"ALTER TABLE warehouse_transfer ADD COLUMN approved_at {datetime_type}",
            },
        )
        _add_columns(
            engine,
            "warehouse_stock",
            {
                "reserved_quantity": "ALTER TABLE warehouse_stock ADD COLUMN reserved_quantity INTEGER DEFAULT 0",
                "in_transit_quantity": "ALTER TABLE warehouse_stock ADD COLUMN in_transit_quantity INTEGER DEFAULT 0",
            },
        )
        _add_columns(
            engine,
            "purchase",
            {
                "warehouse_id": "ALTER TABLE purchase ADD COLUMN warehouse_id INTEGER",
                "currency": "ALTER TABLE purchase ADD COLUMN currency VARCHAR(10) DEFAULT 'IQD'",
                "exchange_rate": "ALTER TABLE purchase ADD COLUMN exchange_rate FLOAT DEFAULT 1.0",
                "payment_currency": "ALTER TABLE purchase ADD COLUMN payment_currency VARCHAR(10)",
                "is_draft": f"ALTER TABLE purchase ADD COLUMN is_draft BOOLEAN DEFAULT {bool_false}",
                "deleted_at": f"ALTER TABLE purchase ADD COLUMN deleted_at {datetime_type}",
                "source_module": "ALTER TABLE purchase ADD COLUMN source_module VARCHAR(40)",
                "customs_extra": "ALTER TABLE purchase ADD COLUMN customs_extra INTEGER DEFAULT 0",
                "other_extra": "ALTER TABLE purchase ADD COLUMN other_extra INTEGER DEFAULT 0",
            },
        )
        _add_columns(
            engine,
            "order_item",
            {
                "discount_value": "ALTER TABLE order_item ADD COLUMN discount_value INTEGER DEFAULT 0",
                "warehouse_id": "ALTER TABLE order_item ADD COLUMN warehouse_id INTEGER",
                "variant_color": "ALTER TABLE order_item ADD COLUMN variant_color VARCHAR(80)",
                "sale_mode": "ALTER TABLE order_item ADD COLUMN sale_mode VARCHAR(20) DEFAULT 'normal'",
                "trade_in_source_product_id": "ALTER TABLE order_item ADD COLUMN trade_in_source_product_id INTEGER",
                "trade_in_source_product_name": "ALTER TABLE order_item ADD COLUMN trade_in_source_product_name VARCHAR(150)",
            },
        )
        _add_columns(
            engine,
            "supplier_payment",
            {
                "tenant_id": "ALTER TABLE supplier_payment ADD COLUMN tenant_id INTEGER",
                "currency": "ALTER TABLE supplier_payment ADD COLUMN currency VARCHAR(10) DEFAULT 'IQD'",
                "exchange_rate": "ALTER TABLE supplier_payment ADD COLUMN exchange_rate FLOAT DEFAULT 1.0",
                "source_module": "ALTER TABLE supplier_payment ADD COLUMN source_module VARCHAR(40)",
                "deleted_at": f"ALTER TABLE supplier_payment ADD COLUMN deleted_at {datetime_type}",
                "document_number": "ALTER TABLE supplier_payment ADD COLUMN document_number VARCHAR(100)",
            },
        )
        _add_columns(
            engine,
            "invoice_payment_ledger",
            {
                "tenant_id": "ALTER TABLE invoice_payment_ledger ADD COLUMN tenant_id INTEGER",
                "currency": "ALTER TABLE invoice_payment_ledger ADD COLUMN currency VARCHAR(10) DEFAULT 'IQD'",
                "exchange_rate": "ALTER TABLE invoice_payment_ledger ADD COLUMN exchange_rate FLOAT DEFAULT 1.0",
                "source_module": "ALTER TABLE invoice_payment_ledger ADD COLUMN source_module VARCHAR(40)",
                "note": "ALTER TABLE invoice_payment_ledger ADD COLUMN note TEXT",
                "payment_method": "ALTER TABLE invoice_payment_ledger ADD COLUMN payment_method VARCHAR(40)",
            },
        )
        _ENSURED.add(tenant_key)
    except Exception:
        _log.exception("ensure_wholesale_schema failed")
