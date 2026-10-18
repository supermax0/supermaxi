"""Central RBAC permission helpers."""

from __future__ import annotations

from flask import jsonify, redirect, request, session

from models.employee import Employee
from utils.order_status import RETURN_STATUS

LEGACY_TO_RBAC: dict[str, str] = {
    "can_see_orders": "view_orders",
    "can_see_orders_placed": "view_orders_placed",
    "can_see_orders_packed": "view_orders_packed",
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
    "can_see_fixed_assets": "view_fixed_assets",
    "can_manage_fixed_assets": "manage_fixed_assets",
    "can_approve_fixed_asset_disposal": "approve_fixed_asset_disposal",
    "can_see_rotating_savings": "view_rotating_savings",
    "can_manage_rotating_savings": "manage_rotating_savings",
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
    "facebook_employee_inbox.view": "view_messages",
    "facebook_employee_inbox.reply": "view_messages",
    "facebook_employee_inbox.view_all": "view_reports",
    "facebook_conversations.transfer": "manage_employees",
    "facebook_monitor.view": "view_reports",
    "facebook_routing.manage": "manage_settings",
    "can_manage_employees": "manage_employees",
    "can_manage_agents": "manage_agents",
    "can_manage_pages": "manage_pages",
    "can_view_activity": "view_activity",
}

ORDER_STATUS_PERMISSIONS = (
    "view_orders_placed",
    "view_orders_packed",
    "view_orders_delivered",
    "view_orders_returned",
    "view_orders_shipped",
)

_STATUS_TO_PERMISSION: dict[str, str] = {
    "تم الطلب": "view_orders_placed",
    "معباة": "view_orders_packed",
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


def ensure_cashier_role_has_messages() -> None:
    """Ensure the default cashier RBAC role includes messaging (POS chat button)."""
    ensure_cashier_role_has_permissions(("view_messages", "print_pos_invoice"))


def ensure_cashier_role_has_permissions(permission_names: tuple[str, ...] | list[str]) -> None:
    """Attach missing default POS permissions to the cashier role."""
    from extensions import db
    from models.role import Permission, Role

    names = [n for n in permission_names if n]
    if not names:
        return
    try:
        role = Role.query.filter_by(name="cashier").first()
        if not role:
            return
        existing = {p.name for p in (role.permissions or [])}
        changed = False
        for name in names:
            if name in existing:
                continue
            perm = Permission.query.filter_by(name=name).first()
            if not perm:
                continue
            role.permissions.append(perm)
            existing.add(name)
            changed = True
        if changed:
            db.session.commit()
    except Exception:
        db.session.rollback()


def _primary_role_has_permission(employee: Employee, permission_name: str) -> bool:
    """Bridge legacy ``employee.role`` values to the RBAC role with that name.

    Older employees were created with ``role='cashier'`` but without a row in
    ``employee_roles``.  Permissions edited on the cashier role therefore never
    reached them.  Explicitly assigned RBAC roles remain authoritative; this
    fallback only applies when an employee has no role assignments at all.
    """
    assigned_roles = list(employee.roles or [])
    if assigned_roles or not str(employee.role or "").strip():
        return False
    try:
        from models.role import Role

        primary_role = Role.query.filter_by(name=str(employee.role).strip()).first()
        return bool(
            primary_role
            and any(permission.name == permission_name for permission in (primary_role.permissions or []))
        )
    except Exception:
        return False


def employee_can(employee: Employee | None, permission_name: str) -> bool:
    if not employee or not employee.is_active:
        return False
    if employee.role == "admin":
        return True
    rbac_name = LEGACY_TO_RBAC.get(permission_name, permission_name)
    from utils.permission_overrides import override_decision

    decided = override_decision(employee, rbac_name)  # a per-employee exception beats every role and built-in default
    if decided is not None:
        return decided
    # Cashiers can always print POS invoices (core POS duty).
    if employee.role == "cashier" and rbac_name == "print_pos_invoice":
        return True
    if employee.role == "cashier" and not list(employee.roles or []):
        if rbac_name in ("view_pos", "view_my_orders", "view_messages"):
            return True
    return employee.has_permission(rbac_name) or _primary_role_has_permission(employee, rbac_name)


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
    # Print iframe embeds must NEVER receive a login page (users were printing /pos/login).
    if (request.args.get("finora_embed") or "").strip() == "1":
        return (
            "<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>"
            "<title>غير مصرح</title></head><body>"
            "<p data-finora-print-blocked='permission'>غير مصرح بطباعة هذه الفاتورة.</p>"
            "</body></html>",
            403,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    if request.path.rstrip("/") == "/pos":
        return redirect("/pos/login")
    return redirect("/pos/login")


def allowed_order_statuses_for(employee: Employee | None) -> list[str]:
    if not employee or employee.role == "admin":
        return []
    allowed: list[str] = []
    if employee_can(employee, "view_orders_placed"):
        allowed.append("تم الطلب")
    if employee_can(employee, "view_orders_packed"):
        allowed.append("معباة")
    if employee_can(employee, "view_orders_delivered"):
        allowed.extend(["واصل", "واصلة", "تم التوصيل"])
    if employee_can(employee, "view_orders_returned"):
        allowed.extend([RETURN_STATUS, "ملغي"])
    if employee_can(employee, "view_orders_shipped"):
        allowed.extend(["مشحون", "مشحونة", "جاري الشحن"])
    return allowed


def employee_can_access_order(employee: Employee | None, order, *, for_print: bool = False) -> bool:
    if not employee:
        return False
    if employee.role == "admin":
        return True
    # POS cashiers with print permission may open invoices for printing
    # without needing the full orders-list permission.
    if for_print and employee_can(employee, "print_pos_invoice") and (
        employee_can(employee, "view_pos")
        or employee_can(employee, "view_orders")
        or employee_can(employee, "view_my_orders")
    ):
        return True
    if not employee_can(employee, "view_orders"):
        return False
    status = (getattr(order, "status", None) or "").strip()
    perm = _STATUS_TO_PERMISSION.get(status)
    if perm:
        return employee_can(employee, perm)
    allowed = allowed_order_statuses_for(employee)
    if not allowed:
        return False
    return status in allowed


def guard_order_access(order, *, json: bool | None = None, for_print: bool = False):
    employee = get_current_employee()
    if employee_can_access_order(employee, order, for_print=for_print):
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
