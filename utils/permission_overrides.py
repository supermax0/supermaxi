"""Reading per-employee permission overrides (never raises: permission checks must not break on a missing table)."""
from __future__ import annotations

from flask import g, has_request_context

from extensions import db


def ensure_table() -> None:
    from models.employee_permission import EmployeePermissionOverride

    EmployeePermissionOverride.__table__.create(bind=db.session.connection(), checkfirst=True)


def overrides_for(employee_id: int | None) -> dict[str, str]:
    """{permission: 'grant'|'deny'} for one employee. Cached per request; empty when the table is absent."""
    if not employee_id:
        return {}
    key = f"_perm_overrides_{int(employee_id)}"
    if has_request_context() and key in g.__dict__:
        return g.__dict__[key]
    result: dict[str, str] = {}
    try:
        from models.employee_permission import EmployeePermissionOverride

        # a SAVEPOINT: a missing table (not created yet on an older tenant) must not poison — or roll back —
        # the surrounding transaction of the request that merely asked "may he?"
        with db.session.begin_nested():
            rows = db.session.query(EmployeePermissionOverride.permission,
                                    EmployeePermissionOverride.effect).filter(
                EmployeePermissionOverride.employee_id == int(employee_id)).all()
        result = {str(p): str(e) for p, e in rows}
    except Exception:
        result = {}
    if has_request_context():
        g.__dict__[key] = result
    return result


def forget(employee_id: int) -> None:
    if has_request_context():
        g.__dict__.pop(f"_perm_overrides_{int(employee_id)}", None)


def override_decision(employee, permission_name: str) -> bool | None:
    """True = explicitly granted, False = explicitly denied, None = no exception (roles decide)."""
    effect = overrides_for(getattr(employee, "id", None)).get(permission_name)
    if effect == "grant":
        return True
    if effect == "deny":
        return False
    return None
