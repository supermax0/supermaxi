"""Ensure purchase tables/columns used by reports exist."""
from __future__ import annotations

from flask import g
from sqlalchemy import inspect, text

from extensions import db
from models.purchase_attachment import PurchaseAttachment
from models.purchase_item import PurchaseItem
from models.purchase_payment import PurchasePayment


_PURCHASE_SCHEMA_ENSURED_BINDS: set[str] = set()


def _purchase_bind_key() -> str:
    return getattr(g, "tenant", None) or "__core__"


def _purchase_schema_engine():
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def ensure_purchase_schema() -> None:
    bind_key = _purchase_bind_key()
    if bind_key in _PURCHASE_SCHEMA_ENSURED_BINDS:
        return

    engine = _purchase_schema_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    bool_default = "BOOLEAN DEFAULT false" if dialect == "postgresql" else "BOOLEAN DEFAULT 0"
    date_type = "DATE"
    datetime_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

    if "purchase" in tables:
        cols = {c["name"] for c in inspector.get_columns("purchase")}
        additions = {
            "invoice_no": "ALTER TABLE purchase ADD COLUMN invoice_no VARCHAR(60)",
            "status": "ALTER TABLE purchase ADD COLUMN status VARCHAR(30) DEFAULT 'confirmed'",
            "branch_code": "ALTER TABLE purchase ADD COLUMN branch_code VARCHAR(60)",
            "branch_id": "ALTER TABLE purchase ADD COLUMN branch_id INTEGER",
            "reference_no": "ALTER TABLE purchase ADD COLUMN reference_no VARCHAR(120)",
            "supplier_invoice_no": "ALTER TABLE purchase ADD COLUMN supplier_invoice_no VARCHAR(120)",
            "address": "ALTER TABLE purchase ADD COLUMN address VARCHAR(255)",
            "purchase_mode": "ALTER TABLE purchase ADD COLUMN purchase_mode VARCHAR(30)",
            "payment_term": "ALTER TABLE purchase ADD COLUMN payment_term VARCHAR(80)",
            "notes": "ALTER TABLE purchase ADD COLUMN notes TEXT",
            "shipping_details": "ALTER TABLE purchase ADD COLUMN shipping_details TEXT",
            "extra_cost_note": "ALTER TABLE purchase ADD COLUMN extra_cost_note VARCHAR(255)",
            "sub_total": "ALTER TABLE purchase ADD COLUMN sub_total INTEGER DEFAULT 0",
            "discount_value": "ALTER TABLE purchase ADD COLUMN discount_value INTEGER DEFAULT 0",
            "shipping_extra": "ALTER TABLE purchase ADD COLUMN shipping_extra INTEGER DEFAULT 0",
            "grand_total": "ALTER TABLE purchase ADD COLUMN grand_total INTEGER DEFAULT 0",
            "paid_total": "ALTER TABLE purchase ADD COLUMN paid_total INTEGER DEFAULT 0",
            "remaining_total": "ALTER TABLE purchase ADD COLUMN remaining_total INTEGER DEFAULT 0",
            "created_by_employee_id": "ALTER TABLE purchase ADD COLUMN created_by_employee_id INTEGER",
            "stock_applied": f"ALTER TABLE purchase ADD COLUMN stock_applied {bool_default}",
            "purchase_date": f"ALTER TABLE purchase ADD COLUMN purchase_date {date_type}",
            "created_at": f"ALTER TABLE purchase ADD COLUMN created_at {datetime_type}",
        }
        stmts = [stmt for column, stmt in additions.items() if column not in cols]
        if stmts:
            with engine.begin() as conn:
                for stmt in stmts:
                    conn.execute(text(stmt))
                if "purchase_date" not in cols:
                    conn.execute(text("UPDATE purchase SET purchase_date = DATE(created_at) WHERE purchase_date IS NULL AND created_at IS NOT NULL"))
                if "purchase_date" not in cols and dialect == "sqlite":
                    conn.execute(text("UPDATE purchase SET purchase_date = DATE('now') WHERE purchase_date IS NULL"))

    PurchaseItem.__table__.create(bind=engine, checkfirst=True)
    PurchasePayment.__table__.create(bind=engine, checkfirst=True)
    PurchaseAttachment.__table__.create(bind=engine, checkfirst=True)

    _PURCHASE_SCHEMA_ENSURED_BINDS.add(bind_key)
