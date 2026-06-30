"""Central RBAC permission helpers."""

from __future__ import annotations

from flask import session

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
}

ORDER_STATUS_PERMISSIONS = (
    "view_orders_placed",
    "view_orders_delivered",
    "view_orders_returned",
    "view_orders_shipped",
)


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
