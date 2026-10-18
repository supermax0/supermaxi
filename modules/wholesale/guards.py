"""Access guards for wholesale routes (business type + RBAC)."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import flash, g, jsonify, redirect, request, session

from extensions import db
from models.employee import Employee
from models.tenant import Tenant as TenantModel


WHOLESALE_PERMISSIONS = (
    "wholesale_ops",
    "wholesale_sales",
    "wholesale_purchases",
    "wholesale_receipts",
    "wholesale_payments",
    "wholesale_warehouses",
    "wholesale_statement",
    "wholesale_reports",
    "wholesale_settings",
)


def tenant_business_type() -> str:
    try:
        tenant = TenantModel.query.first()
        if tenant and getattr(tenant, "business_type", None):
            return str(tenant.business_type).strip() or "general"
    except Exception:
        pass
    return (session.get("business_type") or "general").strip()


def current_employee() -> Employee | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(Employee, user_id)


def current_tenant_id() -> int | None:
    tid = session.get("tenant_id")
    if tid is not None:
        try:
            return int(tid)
        except (TypeError, ValueError):
            pass
    try:
        tenant = TenantModel.query.first()
        if tenant:
            return int(tenant.id)
    except Exception:
        pass
    return None


def is_wholesale_tenant() -> bool:
    return tenant_business_type() == "wholesale"


def employee_can_wholesale(emp: Employee | None, permission: str | None = None) -> bool:
    if not emp or not emp.is_active:
        return False
    if emp.role == "admin":
        return True
    if permission:
        return emp.has_permission(permission)
    return any(emp.has_permission(p) for p in WHOLESALE_PERMISSIONS)


def require_wholesale(permission: str | None = None, *, json_mode: bool | None = None):
    """Decorator: require wholesale business type + optional RBAC permission."""

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            wants_json = json_mode
            if wants_json is None:
                wants_json = request.path.startswith("/api/") or (
                    request.accept_mimetypes.best == "application/json"
                    and request.accept_mimetypes["application/json"]
                    >= request.accept_mimetypes["text/html"]
                )

            if not is_wholesale_tenant():
                msg = "هذه الصفحات مخصصة للشركات من نوع تجارة الجملة."
                if wants_json:
                    return jsonify({"ok": False, "error": msg}), 403
                flash(msg, "warning")
                return redirect("/")

            emp = current_employee()
            if not employee_can_wholesale(emp, permission):
                msg = "ليس لديك صلاحية للوصول إلى هذه العملية."
                if wants_json:
                    return jsonify({"ok": False, "error": msg}), 403
                flash(msg, "danger")
                return redirect("/")

            g.wholesale_employee = emp
            g.wholesale_tenant_id = current_tenant_id()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
