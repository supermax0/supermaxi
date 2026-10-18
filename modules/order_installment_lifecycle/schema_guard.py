# -*- coding: utf-8 -*-
"""Ensure order-installment lifecycle tables exist on the current tenant bind."""

from __future__ import annotations

from sqlalchemy import inspect

from extensions import db


def _bind():
    try:
        from flask import g

        tenant_slug = getattr(g, "tenant", None)
        if tenant_slug:
            from extensions_tenant import get_tenant_engine

            return get_tenant_engine(tenant_slug)
    except Exception:
        pass
    try:
        b = db.session.get_bind()
        if b is not None:
            return b
    except Exception:
        pass
    return db.engine


def ensure_order_installment_tables() -> None:
    from modules.order_installment_lifecycle.models import (
        OrderInstallmentEvent,
        OrderInstallmentLifecycle,
        OrderInstallmentSettings,
    )

    bind = _bind()
    schema_bind = bind
    is_memory_sqlite = (
        getattr(getattr(bind, "dialect", None), "name", None) == "sqlite"
        and ":memory:" in str(getattr(bind, "url", ""))
    )
    if is_memory_sqlite:
        schema_bind = db.session.connection()

    inspector = inspect(schema_bind)
    tables = set(inspector.get_table_names())

    for model in (OrderInstallmentSettings, OrderInstallmentLifecycle, OrderInstallmentEvent):
        if model.__tablename__ not in tables:
            model.__table__.create(bind=schema_bind, checkfirst=True)
