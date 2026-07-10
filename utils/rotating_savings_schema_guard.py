"""Schema guard for rotating savings tables."""

from flask import g, has_request_context
from sqlalchemy import inspect, text

from extensions import db
from models.rotating_savings import (
    RotatingSaving,
    RotatingSavingAttachment,
    RotatingSavingPayment,
    RotatingSavingReceipt,
    RotatingSavingSettings,
)

_SCHEMA_ENSURED_BINDS: set[str] = set()


def _schema_bind_key() -> str:
    if has_request_context():
        return getattr(g, "tenant", None) or "__core__"
    return "__core__"


def _schema_engine():
    tenant_slug = getattr(g, "tenant", None) if has_request_context() else None
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def _ensure_columns(engine, table_name, columns: dict):
    """Add missing columns on existing tenant DBs."""
    try:
        inspector = inspect(engine)
        if table_name not in inspector.get_table_names():
            return
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        stmts = [ddl for col, ddl in columns.items() if col not in existing]
        if not stmts:
            return
        with engine.begin() as conn:
            for stmt in stmts:
                conn.execute(text(stmt))
    except Exception:
        db.session.rollback()


def ensure_rotating_savings_schema():
    bind_key = _schema_bind_key()
    if bind_key in _SCHEMA_ENSURED_BINDS:
        return

    engine = _schema_engine()
    RotatingSavingSettings.__table__.create(bind=engine, checkfirst=True)
    RotatingSaving.__table__.create(bind=engine, checkfirst=True)
    RotatingSavingPayment.__table__.create(bind=engine, checkfirst=True)
    RotatingSavingReceipt.__table__.create(bind=engine, checkfirst=True)
    RotatingSavingAttachment.__table__.create(bind=engine, checkfirst=True)

    _ensure_columns(
        engine,
        "rotating_saving_payments",
        {
            "reversed_at": "ALTER TABLE rotating_saving_payments ADD COLUMN reversed_at DATETIME",
            "reversal_journal_entry_id": "ALTER TABLE rotating_saving_payments ADD COLUMN reversal_journal_entry_id INTEGER",
        },
    )
    _ensure_columns(
        engine,
        "rotating_saving_receipts",
        {
            "reversed_at": "ALTER TABLE rotating_saving_receipts ADD COLUMN reversed_at DATETIME",
        },
    )
    _SCHEMA_ENSURED_BINDS.add(bind_key)
