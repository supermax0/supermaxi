"""Ensure treasury tables/columns exist and default cash account is present."""
from __future__ import annotations

from flask import g
from sqlalchemy import inspect, text

from extensions import db
from models.treasury_account import TreasuryAccount


_TABLES_NEEDING_TREASURY_ACCOUNT_ID = (
    "account_transaction",
    "supplier_payment",
    "shipping_payment",
    "purchase_payment",
)


def _treasury_schema_engine():
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


def ensure_treasury_schema() -> None:
    """Create treasury tables/columns and seed default cash account."""
    from models.treasury_transfer import TreasuryTransfer  # noqa: F401

    engine = _treasury_schema_engine()
    TreasuryAccount.__table__.create(bind=engine, checkfirst=True)
    TreasuryTransfer.__table__.create(bind=engine, checkfirst=True)

    inspector = inspect(engine)
    stmts: list[str] = []

    for table_name in _TABLES_NEEDING_TREASURY_ACCOUNT_ID:
        if not _table_exists(inspector, table_name):
            continue
        cols = _column_names(inspector, table_name)
        if "treasury_account_id" not in cols:
            stmts.append(
                f'ALTER TABLE "{table_name}" ADD COLUMN "treasury_account_id" INTEGER'
            )

    if _table_exists(inspector, "account_transaction"):
        cols = _column_names(inspector, "account_transaction")
        if "treasury_transfer_id" not in cols:
            stmts.append(
                'ALTER TABLE "account_transaction" ADD COLUMN "treasury_transfer_id" INTEGER'
            )

    if stmts:
        with engine.begin() as conn:
            for stmt in stmts:
                conn.execute(text(stmt))

    cash = (
        TreasuryAccount.query.filter_by(account_type="cash", is_default=True)
        .order_by(TreasuryAccount.id.asc())
        .first()
    )
    if not cash:
        cash = TreasuryAccount(
            name="الصندوق",
            account_type="cash",
            is_default=True,
            is_active=True,
        )
        db.session.add(cash)
        db.session.commit()
