"""Central RBAC permission helpers."""

from __future__ import annotations

from flask import jsonify, redirect, request, session

from models.employee import Employee

LEGACY_TO_RBAC: dict[str, str] = {
    "can_see_orders": "view_orders",
    "can_see_orders_placed": "view_orders_placed",
    "can_see_orders_delivered": "view_orders_delivered",
    "can_see_orders_returned": "view_orders_returned",
    "can_see_orders_shipped": "view_orders_shipped",
    "can_see_reports": "view_reports",
    "can_manage_inventory": "manage_inventory",
    "can_see_expenses": "view_expenses",
    "can_manage_suppliers": "manage_suppliers",
    "can_manage_customers": "manage_customers",
    "can_see_accounts": "view_accounts",
    "can_see_financial": "view_financial",
    "can_edit_price": "edit_price",
    "can_manage_orders": "manage_orders",
    "can_manage_shipping": "manage_shipping",
    "can_manage_settings": "manage_settings",
    "can_view_dashboard": "view_dashboard",
    "can_use_pos": "view_pos",
    "can_see_shipping": "view_shipping",
    "can_see_agents": "view_agents",
    "can_see_pages": "view_pages",
    "can_see_messages": "view_messages",
    "can_manage_employees": "manage_employees",
    "can_manage_agents": "manage_agents",
    "can_manage_pages": "manage_pages",
}

ORDER_STATUS_PERMISSIONS = (
    "view_orders_placed",
    "view_orders_delivered",
    "view_orders_returned",
    "view_orders_shipped",
)

_STATUS_TO_PERMISSION: dict[str, str] = {
    "تم الطلب": "view_orders_placed",
    "واصل": "view_orders_delivered",
    "واصلة": "view_orders_delivered",
    "تم التوصيل": "view_orders_delivered",
    "مرتجع": "view_orders_returned",
    "راجع": "view_orders_returned",
    "راجعة": "view_orders_returned",
    "ملغي": "view_orders_returned",
    "مشحون": "view_orders_shipped",
    "مشحونة": "view_orders_shipped",
    "جاري الشحن": "view_orders_shipped",
}


def get_current_employee() -> Employee | None:
    if "user_id" not in session:
        return None
    employee = Employee.query.get(session["user_id"])
    if not employee or not employee.is_active:
        return None
    return employee


def employee_can(employee: Employee | None, permission_name: str) -> bool:
    if not employee or not employee.is_active:
        return False
    if employee.role == "admin":
        return True
    rbac_name = LEGACY_TO_RBAC.get(permission_name, permission_name)
    return employee.has_permission(rbac_name)


def check_permission(permission_name: str) -> bool:
    return employee_can(get_current_employee(), permission_name)


def _wants_json_response(explicit_json: bool | None = None) -> bool:
    if explicit_json is not None:
        return explicit_json
    if request.is_json:
        return True
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        accept = (request.headers.get("Accept") or "").lower()
        if "application/json" in accept or request.path.startswith("/api/"):
            return True
        if (request.headers.get("X-Requested-With") or "").lower() == "xmlhttprequest":
            return True
        if (request.content_type or "").startswith("application/json"):
            return True
    return False


def guard_permission(permission_name: str, *, json: bool | None = None):
    """Return a Flask response if denied, else None."""
    if check_permission(permission_name):
        return None
    if _wants_json_response(json):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    return redirect("/pos"), 403


def allowed_order_statuses_for(employee: Employee | None) -> list[str]:
    if not employee or employee.role == "admin":
        return []
    allowed: list[str] = []
    if employee_can(employee, "view_orders_placed"):
        allowed.append("تم الطلب")
    if employee_can(employee, "view_orders_delivered"):
        allowed.extend(["واصل", "واصلة", "تم التوصيل"])
    if employee_can(employee, "view_orders_returned"):
        allowed.extend(["مرتجع", "راجع", "راجعة", "ملغي"])
    if employee_can(employee, "view_orders_shipped"):
        allowed.extend(["مشحون", "مشحونة", "جاري الشحن"])
    return allowed


def employee_can_access_order(employee: Employee | None, order) -> bool:
    if not employee_can(employee, "view_orders"):
        return False
    if not employee or employee.role == "admin":
        return bool(employee)
    status = (getattr(order, "status", None) or "").strip()
    perm = _STATUS_TO_PERMISSION.get(status)
    if perm:
        return employee_can(employee, perm)
    allowed = allowed_order_statuses_for(employee)
    if not allowed:
        return False
    return status in allowed


def guard_order_access(order, *, json: bool | None = None):
    employee = get_current_employee()
    if employee_can_access_order(employee, order):
        return None
    if _wants_json_response(json):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    return redirect("/pos"), 403


def legacy_rbac_names_for_employee(employee: Employee) -> list[str]:
    names: list[str] = []
    for col, rbac in LEGACY_TO_RBAC.items():
        if getattr(employee, col, False):
            names.append(rbac)
    return names


def migrate_legacy_permissions_to_roles() -> None:
    """One-time per tenant: map legacy can_* columns to RBAC roles."""
    from extensions import db
    from models.role import Permission, Role
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags() if settings else {}
    if flags.get("legacy_rbac_migrated"):
        return

    employees = Employee.query.filter(Employee.role != "admin").all()
    for emp in employees:
        rbac_names = legacy_rbac_names_for_employee(emp)
        if not rbac_names:
            continue
        role_name = f"emp_{emp.id}_legacy"
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            from datetime import datetime

            role = Role(name=role_name, description=f"ترحيل صلاحيات {emp.name}", created_at=datetime.utcnow())
            db.session.add(role)
            db.session.flush()
        perms = Permission.query.filter(Permission.name.in_(rbac_names)).all()
        role.permissions = perms
        if role not in emp.roles:
            emp.roles.append(role)

    flags["legacy_rbac_migrated"] = True
    settings.set_ui_flags(flags)
    db.session.commit()
