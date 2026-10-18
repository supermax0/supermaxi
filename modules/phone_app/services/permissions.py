"""Phone permission helpers — soft RBAC with safe defaults for phone staff."""

from __future__ import annotations

from typing import Any

PHONE_PERMS = {
    "phone.timeline.view",
    "phone.outcomes.create",
    "phone.outcomes.update",
    "phone.search.all",
    "phone.tasks.view_own",
    "phone.tasks.view_team",
    "phone.tasks.assign",
    "phone.tasks.complete",
    "phone.financial.view",
}

# Roles that get full phone defaults when has_permission is unavailable.
_FULL_ROLES = {"admin", "owner", "manager", "superadmin", "call_center", "sales"}


def _employee_role(employee: Any) -> str:
    return str(getattr(employee, "role", "") or "").strip().lower()


def employee_has_phone_perm(employee: Any, permission: str) -> bool:
    if permission not in PHONE_PERMS:
        return False
    has_perm = getattr(employee, "has_permission", None)
    if callable(has_perm):
        try:
            if has_perm(permission):
                return True
            # Legacy aliases sometimes used without phone. prefix.
            if has_perm(permission.replace("phone.", "", 1)):
                return True
        except Exception:
            pass
    role = _employee_role(employee)
    if role in _FULL_ROLES or not role:
        # Default allow for authenticated phone employees (Phase 1 compat).
        return True
    if permission in ("phone.tasks.view_own", "phone.outcomes.create", "phone.timeline.view"):
        return True
    if permission == "phone.tasks.view_team":
        return role in _FULL_ROLES
    if permission == "phone.financial.view":
        return role in _FULL_ROLES or role in {"accountant", "cashier"}
    return True


def require_phone_perm(employee: Any, permission: str) -> Any | None:
    if employee_has_phone_perm(employee, permission):
        return None
    from modules.phone_app.schemas import api_error

    return api_error("Permission denied", 403, code="forbidden")


def mask_phone(phone: str | None) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"
