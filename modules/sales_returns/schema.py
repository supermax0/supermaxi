"""Lazy additive tables for the explicitly selected tenant; no opening posts."""
from threading import RLock
from sqlalchemy import inspect
from extensions import db
from modules.finance.common import tenant_key
from extensions_tenant import get_tenant_engine
from .models import SalesReturnOrigin, SalesReturn, SalesReturnLine, SalesReturnCost, SalesReturnFunding

_READY = set()
_LOCK = RLock()


def ensure_schema():
    tenant = tenant_key()
    engine = get_tenant_engine(tenant)
    key = tenant, id(engine)
    with _LOCK:
        if key in _READY:
            return
        tables = [model.__table__ for model in (SalesReturnOrigin, SalesReturn, SalesReturnLine, SalesReturnCost, SalesReturnFunding)]
        inspector = inspect(engine)
        for table in tables:
            if inspector.has_table(table.name):
                columns = {column["name"] for column in inspector.get_columns(table.name)}
                if not {column.name for column in table.columns} <= columns:
                    raise RuntimeError("Existing sales return evidence needs an explicit compatible migration")
        db.metadata.create_all(bind=engine, tables=tables, checkfirst=True)
        _READY.add(key)
