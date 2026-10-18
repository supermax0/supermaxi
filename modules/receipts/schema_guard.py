"""Safe CREATE for receipts tables and permission seeding."""
from __future__ import annotations

import logging
from datetime import datetime

from flask import g
from sqlalchemy import inspect, text

from extensions import db

_log = logging.getLogger(__name__)
_ENSURED: set[str] = set()

RECEIPT_PERMISSIONS = [
    ("view_receipts", "رؤية القبض والتسديدات"),
    ("create_receipts", "إنشاء سند قبض"),
    ("print_receipts", "طباعة سندات القبض"),
    ("cancel_receipts", "إلغاء سندات القبض"),
]


def _current_engine():
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def ensure_receipt_permissions() -> None:
    from models.role import Permission

    created = False
    for name, desc in RECEIPT_PERMISSIONS:
        if not Permission.query.filter_by(name=name).first():
            db.session.add(Permission(name=name, description=desc, created_at=datetime.utcnow()))
            created = True
    if created:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def ensure_receipts_schema() -> None:
    tenant_key = str(getattr(g, "tenant", None) or "default")
    if tenant_key in _ENSURED:
        return
    try:
        engine = _current_engine()
        from models.receipt import Receipt, ReceiptAllocation

        for model in (Receipt, ReceiptAllocation):
            model.__table__.create(bind=engine, checkfirst=True)

        inspector = inspect(engine)
        if "receipts" in set(inspector.get_table_names()):
            cols = {c["name"] for c in inspector.get_columns("receipts")}
            additions = {
                "idempotency_key": "ALTER TABLE receipts ADD COLUMN idempotency_key VARCHAR(80)",
                "journal_entry_id": "ALTER TABLE receipts ADD COLUMN journal_entry_id INTEGER",
                "reverse_journal_entry_id": "ALTER TABLE receipts ADD COLUMN reverse_journal_entry_id INTEGER",
                "source_name": "ALTER TABLE receipts ADD COLUMN source_name VARCHAR(150)",
            }
            with engine.begin() as conn:
                for col, stmt in additions.items():
                    if col not in cols:
                        conn.execute(text(stmt))

        ensure_receipt_permissions()
        _ENSURED.add(tenant_key)
    except Exception:
        _log.exception("ensure_receipts_schema failed for %s", tenant_key)
