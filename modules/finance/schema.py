"""Additive schema only: no balance migration and no historical operation reposting."""
from flask import g
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from threading import RLock
from extensions import db
from . import models
from .common import DEFAULT_ACCOUNTS, PERMISSIONS, actor, tenant_key

_READY = set()
_BOOTSTRAP_LOCK = RLock()


def ensure_schema():
    actor()
    from extensions_tenant import get_tenant_engine
    engine = get_tenant_engine(tenant_key())
    key = (tenant_key(), id(engine))
    if key in _READY:
        return
    with _BOOTSTRAP_LOCK:
        if key in _READY:
            return
        # Concurrent worker startup can encounter the same unique seed. Retry
        # after rollback against the other worker's committed schema/seed.
        for attempt in range(3):
            try:
                _initialize(engine,key)
                return
            except IntegrityError:
                db.session.rollback()
                if attempt==2:
                    raise


def _initialize(engine,key):
    from modules.hr import models as hr_models  # Register referenced HR tables without importing historical balances.
    from models.account import Account
    from models.role import Permission
    from utils.accounting_logic import get_or_create_account
    tables = [t for t in db.metadata.sorted_tables if t.name.startswith("hr_") or
              t.name in {cls.__tablename__ for cls in vars(models).values() if isinstance(cls, type) and hasattr(cls, "__tablename__")}]
    existing = inspect(engine)
    for table in tables:
        if existing.has_table(table.name):
            actual = {c["name"] for c in existing.get_columns(table.name)}
            required = {c.name for c in table.columns}
            if table.name in {"financial_vouchers", "loans", "finance_policy"} and not required <= actual:
                raise RuntimeError(f"Existing {table.name} needs an explicit compatible migration")
    db.metadata.create_all(bind=engine, tables=tables, checkfirst=True)
    if not db.session.get(models.FinancePolicy, 1):
        db.session.add(models.FinancePolicy(id=1, revision=0, settings="{}"))
    for permission, label in PERMISSIONS.items():
        if not Permission.query.filter_by(name=permission).first():
            db.session.add(Permission(name=permission, description=label))
    for role, (code, name, kind) in DEFAULT_ACCOUNTS.items():
        if not db.session.get(models.FinanceMapping, role):
            # Preserve FINORA's established sales/COGS/payable codes where configured.
            from utils.accounting_logic import ACCOUNT_CODES
            alias = {"receivable": "ACCOUNTS_RECEIVABLE", "inventory": "INVENTORY", "payable": "ACCOUNTS_PAYABLE",
                     "capital": "CAPITAL", "revenue": "REVENUE_SALES", "expense": "EXPENSES"}.get(role)
            account = get_or_create_account(ACCOUNT_CODES.get(alias, code), name, kind, commit=False)
            db.session.add(models.FinanceMapping(key=role, account_id=account.id))
    db.session.commit()
    from utils.fixed_assets_service import seed_default_categories
    seed_default_categories()
    _READY.add(key)
