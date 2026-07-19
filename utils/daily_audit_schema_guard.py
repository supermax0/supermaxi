"""Ensure daily audit table exists for the active tenant."""
from __future__ import annotations

from flask import g
from sqlalchemy import inspect, text

from extensions import db
from models.daily_audit import DailyAudit


_DAILY_AUDIT_SCHEMA_ENSURED_BINDS: set[str] = set()


def _daily_audit_bind_key() -> str:
    return getattr(g, "tenant", None) or "__core__"


def _daily_audit_schema_engine():
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _column_names(inspector, table_name: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table_name)}


def ensure_daily_audit_schema() -> None:
    bind_key = _daily_audit_bind_key()
    if bind_key in _DAILY_AUDIT_SCHEMA_ENSURED_BINDS:
        return

    engine = _daily_audit_schema_engine()
    DailyAudit.__table__.create(bind=engine, checkfirst=True)

    inspector = inspect(engine)
    if not _table_exists(inspector, "daily_audit"):
        _DAILY_AUDIT_SCHEMA_ENSURED_BINDS.add(bind_key)
        return

    cols = _column_names(inspector, "daily_audit")
    stmts: list[str] = []
    additions = {
        "status": 'ALTER TABLE "daily_audit" ADD COLUMN "status" VARCHAR(20) DEFAULT \'pending\' NOT NULL',
        "expected_cash_balance": 'ALTER TABLE "daily_audit" ADD COLUMN "expected_cash_balance" INTEGER DEFAULT 0 NOT NULL',
        "actual_cash_count": 'ALTER TABLE "daily_audit" ADD COLUMN "actual_cash_count" INTEGER',
        "difference": 'ALTER TABLE "daily_audit" ADD COLUMN "difference" INTEGER DEFAULT 0 NOT NULL',
        "notes": 'ALTER TABLE "daily_audit" ADD COLUMN "notes" TEXT',
        "reviewed_by": 'ALTER TABLE "daily_audit" ADD COLUMN "reviewed_by" INTEGER',
        "reviewed_at": 'ALTER TABLE "daily_audit" ADD COLUMN "reviewed_at" DATETIME',
        "created_at": 'ALTER TABLE "daily_audit" ADD COLUMN "created_at" DATETIME',
        "updated_at": 'ALTER TABLE "daily_audit" ADD COLUMN "updated_at" DATETIME',
    }
    for column, stmt in additions.items():
        if column not in cols:
            stmts.append(stmt)

    if stmts:
        with engine.begin() as conn:
            for stmt in stmts:
                conn.execute(text(stmt))

    _DAILY_AUDIT_SCHEMA_ENSURED_BINDS.add(bind_key)
