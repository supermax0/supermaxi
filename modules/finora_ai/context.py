"""Authentication, tenant and RBAC context for Finora AI/MCP."""
from __future__ import annotations

from dataclasses import dataclass

from flask import g, session

from utils.permission_checks import employee_can, get_current_employee


class AuthenticationRequired(Exception):
    pass


@dataclass(frozen=True)
class FinoraAuthContext:
    tenant_slug: str
    user_id: int
    role: str
    permissions: frozenset[str]

    @classmethod
    def current(cls) -> "FinoraAuthContext":
        tenant = str(getattr(g, "tenant", None) or session.get("tenant_slug") or "").strip()
        if not tenant or tenant != str(session.get("tenant_slug") or ""):
            raise AuthenticationRequired("Authentication is required")
        g.tenant = tenant
        employee = get_current_employee()
        if not tenant or not employee or int(session.get("user_id") or 0) != int(employee.id):
            raise AuthenticationRequired("Authentication is required")
        names = {
            permission.name
            for role in (employee.roles or [])
            for permission in (role.permissions or [])
        }
        return cls(
            tenant_slug=tenant,
            user_id=int(employee.id),
            role=str(employee.role or ""),
            permissions=frozenset(names),
        )

    def allows(self, *permission_names: str) -> bool:
        if str(getattr(g, "tenant", None) or "") != self.tenant_slug:
            return False
        if int(session.get("user_id") or 0) != self.user_id:
            return False
        employee = get_current_employee()
        return any(employee_can(employee, name) for name in permission_names)


FORBIDDEN_IDENTITY_ARGUMENTS = frozenset({"tenant_id", "tenant_slug", "user_id", "role", "permissions"})


def reject_identity_override(arguments: dict) -> None:
    found = FORBIDDEN_IDENTITY_ARGUMENTS.intersection(arguments or {})
    if found:
        raise ValueError("Identity and tenant fields are derived from authentication context")
