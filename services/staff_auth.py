"""Staff (employee) sign-in shared by the web login and the desktop management client.

Both clients must verify credentials and establish the Flask session in exactly
the same way, so the session-based endpoints (orders, purchases, inventory)
behave identically regardless of which client signed in.
"""
from __future__ import annotations

from flask import current_app, g, session
from werkzeug.security import check_password_hash

from extensions import db
from models.employee import Employee


def find_core_tenant(tenant_slug: str):
    """Look up the tenant in the Core DB (g.tenant must be unset while querying)."""
    from models.core.tenant import Tenant as CoreTenant

    prev_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        return CoreTenant.query.filter_by(slug=tenant_slug).first()
    finally:
        if not getattr(g, "tenant", None):
            g.tenant = prev_tenant


def verify_staff_credentials(username: str, password: str) -> Employee | None:
    """Return the employee whose hashed password matches (username is case-insensitive).

    Requires g.tenant to be bound to the tenant DB.
    """
    matching = Employee.query.filter(db.func.lower(Employee.username) == username.lower()).all()
    for candidate in matching:
        try:
            if check_password_hash(candidate.password, password):
                return candidate
        except (AttributeError, TypeError, ValueError):
            continue
    return None


def employee_must_change_password(emp: Employee) -> bool:
    """True while the employee still holds a one-time (admin-issued) password."""
    try:
        from extensions_tenant import get_tenant_engine
        from services.tenant_provisioning import ensure_password_policy_column

        ensure_password_policy_column(get_tenant_engine(g.tenant))
        return bool(emp.must_change_password)
    except Exception:
        current_app.logger.exception("must_change_password check failed")
        return False


def establish_staff_session(core_tenant, emp: Employee) -> None:
    """Replace the current session with a signed-in staff session."""
    session.clear()
    session.permanent = True  # PERMANENT_SESSION_LIFETIME
    session["tenant_slug"] = core_tenant.slug
    session["user_id"] = emp.id
    session["name"] = emp.name
    session["role"] = emp.role
    session["tenant_id"] = emp.tenant_id
    session["business_type"] = getattr(core_tenant, "business_type", None) or "general"
    try:
        from modules.order_installment_lifecycle.constants import SESSION_MODE_KEY

        session[SESSION_MODE_KEY] = False
    except ImportError:
        pass

    if emp.tenant_id:
        from models.tenant import Tenant as _Tenant

        tenant = _Tenant.query.get(emp.tenant_id)
        if tenant:
            session["plan_key"] = tenant.plan_key
