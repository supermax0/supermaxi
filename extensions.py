# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session
from flask import g

class DynamicTenantSession(Session):
    """
    A custom SQLAlchemy session that dynamically chooses the database engine
    based on the current tenant stored in `g.tenant`.
    If no tenant is active, it falls back to the default engine (Core DB).
    """
    def get_bind(self, mapper=None, clause=None, **kw):
        tenant_slug = getattr(g, 'tenant', None)
        if tenant_slug:
            from extensions_tenant import get_tenant_engine
            return get_tenant_engine(tenant_slug)
        
        # Route to Core database
        return super().get_bind(mapper=mapper, clause=clause, **kw)

db = SQLAlchemy(session_options={'class_': DynamicTenantSession})
