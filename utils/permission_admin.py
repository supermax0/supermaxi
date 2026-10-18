"""Permission administration: catalog, effective permissions with their source, per-employee exceptions, roles.

Only a general admin administers permissions (granting power is never itself delegable). A general admin is
all-powerful and cannot be restricted by a row, so admin employees are refused here instead of silently ignored.
"""
from __future__ import annotations

from typing import Any

from extensions import db
from models.employee import Employee
from models.employee_permission import EmployeePermissionOverride
from models.role import Permission, Role
from utils import permission_overrides
from utils.branch_management import BranchError

HIDDEN = {"view_all_branches"}  # an intrinsic admin capability, never grantable
# Permissions that move money, change prices/stock, or delegate power — flagged in the UI.
SENSITIVE = {
    "delete_orders", "return_orders", "pay_orders", "edit_price", "manage_inventory", "manage_employees",
    "manage_settings", "view_financial", "view_accounts", "manage_branches", "manage_transfers",
    "manage_branch_staff", "run_branch_distribution", "allocate_branch_expenses", "merge_delivery_agents",
    "cashier.override_credit_limit", "cashier.void_sale", "cashier.override_price", "cashier.sell_negative_stock",
    "products.manage_cost", "products.manage_prices", "manage_fixed_assets", "approve_fixed_asset_disposal",
}


def _labels() -> dict[str, str]:
    from routes.permissions import DEFAULT_PERMISSIONS

    labels = dict(DEFAULT_PERMISSIONS)
    for row in Permission.query.all():
        labels.setdefault(row.name, row.description or row.name)
    return labels


def catalog() -> list[dict[str, Any]]:
    """Display groups → permissions. Everything grantable appears exactly once."""
    from routes.permissions import PERMISSION_GROUPS, ensure_default_permissions

    ensure_default_permissions()
    db.session.commit()
    labels = _labels()
    seen: set[str] = set()
    groups = []
    for key, title, names in PERMISSION_GROUPS:
        items = []
        for name in names:
            if name in labels and name not in seen and name not in HIDDEN:
                seen.add(name)
                items.append({"name": name, "label": labels[name], "sensitive": name in SENSITIVE})
        if items:
            groups.append({"key": key, "title": title, "permissions": items})
    rest = [n for n in sorted(labels) if n not in seen and n not in HIDDEN]
    if rest:
        groups.append({"key": "other", "title": "صلاحيات أخرى",
                       "permissions": [{"name": n, "label": labels[n], "sensitive": n in SENSITIVE} for n in rest]})
    return groups


def grantable_names() -> set[str]:
    return {p["name"] for g in catalog() for p in g["permissions"]}


def _role_names(employee: Employee) -> list[str]:
    return sorted(r.name for r in (employee.roles or []))


def _employee(employee_id: int, *, allow_admin: bool = False) -> Employee:
    row = Employee.query.execution_options(skip_branch_scope=True).get(int(employee_id))
    if row is None:
        raise BranchError("الموظف غير موجود", "not_found", 404)
    if row.role == "admin" and not allow_admin:
        raise BranchError("المدير العام يملك كل الصلاحيات ولا تُقيَّد بصف", "validation", 400)
    return row


def employees() -> list[dict[str, Any]]:
    ensure = permission_overrides.ensure_table
    ensure()
    counts: dict[int, int] = {}
    for emp_id, n in (db.session.query(EmployeePermissionOverride.employee_id, db.func.count(EmployeePermissionOverride.id))
                      .group_by(EmployeePermissionOverride.employee_id).all()):
        counts[int(emp_id)] = int(n)
    branches = {}
    try:
        from models.branch import Branch

        branches = {b.id: b.name for b in Branch.query.execution_options(skip_branch_scope=True).all()}
    except Exception:
        pass
    out = []
    for e in Employee.query.execution_options(skip_branch_scope=True).order_by(Employee.name).all():
        out.append({"id": e.id, "name": e.name, "username": e.username, "role": e.role, "active": bool(e.is_active),
                    "branch": branches.get(e.branch_id, ""), "roles": _role_names(e),
                    "overrides": counts.get(e.id, 0), "is_admin": e.role == "admin"})
    return out


def detail(employee_id: int) -> dict[str, Any]:
    """Everything the editor needs: roles, per-permission effective state and where it comes from."""
    permission_overrides.ensure_table()
    emp = _employee(employee_id, allow_admin=True)
    permission_overrides.forget(emp.id)
    over = permission_overrides.overrides_for(emp.id)
    role_grants: dict[str, list[str]] = {}
    for role in emp.roles or []:
        for perm in role.permissions or []:
            role_grants.setdefault(perm.name, []).append(role.name)
    legacy = None
    if not (emp.roles or []) and emp.role:
        legacy = Role.query.filter_by(name=str(emp.role).strip()).first()
        if legacy:
            for perm in legacy.permissions or []:
                role_grants.setdefault(perm.name, []).append(f"{legacy.name} (الدور الأساسي)")
    rows = []
    from utils.permission_checks import employee_can

    for group in catalog():
        for p in group["permissions"]:
            name = p["name"]
            allowed = employee_can(emp, name)
            if emp.role == "admin":
                source = "admin"
            elif over.get(name) == "deny":
                source = "deny"
            elif over.get(name) == "grant":
                source = "grant"
            elif name in role_grants:
                source = "role"
            else:
                source = "none"
            rows.append({"name": name, "group": group["key"], "allowed": bool(allowed), "source": source,
                         "override": over.get(name), "roles": role_grants.get(name, [])})
    return {"employee": {"id": emp.id, "name": emp.name, "role": emp.role, "active": bool(emp.is_active),
                         "is_admin": emp.role == "admin"},
            "role_ids": sorted(r.id for r in (emp.roles or [])), "permissions": rows}


def set_overrides(employee_id: int, changes: dict[str, Any], *, by: int | None, note: str = "") -> dict[str, Any]:
    """``changes``: {permission: 'grant' | 'deny' | None}. None removes the exception (the roles decide again)."""
    permission_overrides.ensure_table()
    emp = _employee(employee_id)
    valid = grantable_names()
    if not isinstance(changes, dict) or not changes:
        raise BranchError("لا تغييرات")
    unknown = sorted(n for n in changes if n not in valid)
    if unknown:
        raise BranchError(f"صلاحية غير معروفة: {unknown[0]}", "validation", 400)
    bad = [n for n, v in changes.items() if v not in ("grant", "deny", None)]
    if bad:
        raise BranchError("القيمة يجب أن تكون سماح أو منع أو إزالة", "validation", 400)
    existing = {r.permission: r for r in EmployeePermissionOverride.query.filter_by(employee_id=emp.id).all()}
    before = {n: r.effect for n, r in existing.items()}
    for name, effect in changes.items():
        row = existing.get(name)
        if effect is None:
            if row is not None:
                db.session.delete(row)
        elif row is None:
            db.session.add(EmployeePermissionOverride(employee_id=emp.id, permission=name, effect=effect,
                                                      note=(note or "")[:255] or None, created_by_id=by))
        else:
            row.effect, row.note, row.created_by_id = effect, (note or "")[:255] or None, by
    db.session.flush()
    permission_overrides.forget(emp.id)
    return {"employee_id": emp.id, "before": before,
            "after": {r.permission: r.effect for r in EmployeePermissionOverride.query.filter_by(employee_id=emp.id).all()}}


def assign_roles(employee_id: int, role_ids: list[int]) -> dict[str, Any]:
    emp = _employee(employee_id)
    roles = Role.query.filter(Role.id.in_([int(i) for i in role_ids])).all() if role_ids else []
    if len(roles) != len({int(i) for i in role_ids}):
        raise BranchError("دور غير موجود", "not_found", 404)
    before = _role_names(emp)
    emp.roles = roles
    db.session.flush()
    permission_overrides.forget(emp.id)
    return {"employee_id": emp.id, "before": before, "after": _role_names(emp)}


def roles() -> list[dict[str, Any]]:
    out = []
    for r in Role.query.order_by(Role.name).all():
        out.append({"id": r.id, "name": r.name, "description": r.description or "",
                    "permissions": sorted(p.name for p in r.permissions if p.name not in HIDDEN),
                    "employees": r.employees.count()})
    return out


def save_role(role_id: int | None, name: str, description: str, permissions: list[str]) -> Role:
    name = (name or "").strip()
    if len(name) < 2:
        raise BranchError("اكتب اسم الدور")
    valid = grantable_names()
    unknown = sorted(n for n in permissions if n not in valid)
    if unknown:
        raise BranchError(f"صلاحية غير معروفة: {unknown[0]}", "validation", 400)
    clash = Role.query.filter(Role.name == name)
    if role_id:
        clash = clash.filter(Role.id != int(role_id))
    if clash.first():
        raise BranchError("اسم الدور مستخدم", "conflict", 409)
    role = db.session.get(Role, int(role_id)) if role_id else Role(name=name)
    if role is None:
        raise BranchError("الدور غير موجود", "not_found", 404)
    role.name, role.description = name, (description or "")[:200]
    role.permissions = Permission.query.filter(Permission.name.in_(permissions)).all() if permissions else []
    db.session.add(role)
    db.session.flush()
    return role


def delete_role(role_id: int) -> None:
    role = db.session.get(Role, int(role_id))
    if role is None:
        raise BranchError("الدور غير موجود", "not_found", 404)
    if role.employees.count():
        raise BranchError("الدور معيّن لموظفين — انقلهم لدور آخر أولاً", "conflict", 409)
    db.session.delete(role)


def audit(limit: int = 100) -> list[dict[str, Any]]:
    from models.activity_log import ActivityLog

    rows = (ActivityLog.query.filter(ActivityLog.category == "permissions")
            .order_by(ActivityLog.id.desc()).limit(max(1, min(int(limit), 500))).all())
    return [{"id": r.id, "at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
             "by": r.employee_name or "", "action": r.action, "summary": r.summary, "payload": r.get_payload()}
            for r in rows]
