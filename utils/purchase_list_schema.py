"""Additive schema/permission guard for Daily Purchase Lists."""
from __future__ import annotations

from datetime import datetime

from flask import g
from sqlalchemy import inspect, text

from extensions import db

_ENSURED: set[str] = set()


def _engine():
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    return db.session.get_bind() or db.engine


def _add_column(engine, table: str, column: str, ddl: str) -> None:
    inspector = inspect(engine)
    if table not in set(inspector.get_table_names()):
        return
    if column in {row["name"] for row in inspector.get_columns(table)}:
        return
    with engine.begin() as conn:
        conn.execute(text(ddl))


def ensure_purchase_list_schema() -> None:
    key = str(getattr(g, "tenant", None) or "__core__")
    if key in _ENSURED:
        return

    # Warehouse is an existing optional Finora capability. Register/create its
    # tables before resolving PurchaseList's FK graph.
    from modules.wholesale.schema_guard import ensure_wholesale_schema

    ensure_wholesale_schema()

    from models.purchase_list import PurchaseList, PurchaseListItem
    from models.role import Permission

    engine = _engine()
    PurchaseList.__table__.create(bind=engine, checkfirst=True)
    PurchaseListItem.__table__.create(bind=engine, checkfirst=True)

    _add_column(
        engine,
        "purchase",
        "purchase_list_id",
        "ALTER TABLE purchase ADD COLUMN purchase_list_id INTEGER REFERENCES purchase_list(id)",
    )
    _add_column(
        engine,
        "account_transaction",
        "purchase_list_id",
        "ALTER TABLE account_transaction ADD COLUMN purchase_list_id INTEGER REFERENCES purchase_list(id)",
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_purchase_purchase_list_id ON purchase (purchase_list_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_account_transaction_purchase_list_id ON account_transaction (purchase_list_id)"))

    permissions = {
        "purchase_list.view": "عرض قوائم الشراء",
        "purchase_list.create": "إنشاء قوائم الشراء",
        "purchase_list.edit": "تعديل قوائم الشراء",
        "purchase_list.delete": "إلغاء قوائم الشراء",
        "purchase_list.execute": "تنفيذ قوائم الشراء",
        "purchase_list.print": "طباعة قوائم الشراء وتقاريرها",
        "purchase_list.view_cost": "عرض تكاليف قوائم الشراء",
        "purchase_list.manage_payment": "إدارة طرق وحسابات دفع قوائم الشراء",
    }
    if "permissions" in set(inspect(engine).get_table_names()):
        changed = False
        for name, description in permissions.items():
            if not Permission.query.filter_by(name=name).first():
                db.session.add(Permission(name=name, description=description, created_at=datetime.utcnow()))
                changed = True
        if changed:
            db.session.commit()
    _ENSURED.add(key)

