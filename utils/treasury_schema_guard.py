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
_TREASURY_SCHEMA_ENSURED_BINDS: set[str] = set()


def _treasury_bind_key() -> str:
    return getattr(g, "tenant", None) or "__core__"


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

    bind_key = _treasury_bind_key()
    if bind_key in _TREASURY_SCHEMA_ENSURED_BINDS:
        return

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

    if _table_exists(inspector, "supplier_payment"):
        cols = _column_names(inspector, "supplier_payment")
        if "payment_method" not in cols:
            stmts.append(
                'ALTER TABLE "supplier_payment" ADD COLUMN "payment_method" VARCHAR(20) DEFAULT \'cash\''
            )
        if "supplier_sale_id" not in cols:
            stmts.append(
                'ALTER TABLE "supplier_payment" ADD COLUMN "supplier_sale_id" INTEGER'
            )

    if _table_exists(inspector, "account_transaction"):
        cols = _column_names(inspector, "account_transaction")
        if "treasury_transfer_id" not in cols:
            stmts.append(
                'ALTER TABLE "account_transaction" ADD COLUMN "treasury_transfer_id" INTEGER'
            )

    if _table_exists(inspector, "expense"):
        cols = _column_names(inspector, "expense")
        if "treasury_account_id" not in cols:
            stmts.append(
                'ALTER TABLE "expense" ADD COLUMN "treasury_account_id" INTEGER'
            )
        if "cash_posted" not in cols:
            # الافتراضي مخصوم: المصاريف القديمة اعتُبرت مخصومة مسبقاً
            dialect = engine.dialect.name
            bool_default = "true" if dialect == "postgresql" else "1"
            stmts.append(
                f'ALTER TABLE "expense" ADD COLUMN "cash_posted" BOOLEAN DEFAULT {bool_default} NOT NULL'
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

    _TREASURY_SCHEMA_ENSURED_BINDS.add(bind_key)
