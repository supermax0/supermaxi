"""Permissions administration for the desktop client (/api/v1/desktop/permissions/*).

General admin only — except ``/me``, which tells any signed-in employee what he may do (so the client can hide
what the server would refuse). Every change is written to the activity log under the «permissions» category.
"""
from __future__ import annotations

from typing import Any

from flask import g, jsonify, request, session

from extensions import db
from models.employee import Employee
from modules.desktop_api.routes import _error, desktop_api_bp
from utils import permission_admin as service
from utils.branch_context import init_branch_context
from utils.branch_management import BranchError
from utils.branch_scope import current_employee, is_general_admin

PREFIX = "/permissions"


def _ok(**data: Any):
    return jsonify({"ok": True, **data})


def _authorize(*, admin: bool = True):
    if not session.get("user_id") or not session.get("tenant_slug"):
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    if str(getattr(g, "tenant", "")) != session["tenant_slug"]:
        return _error("تعذر تحديد الشركة", 403, "tenant_required")
    employee = current_employee()
    if employee is None:
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    if not getattr(g, "branch_scope_ready", False):
        init_branch_context()
    if admin and not is_general_admin(employee):
        return _error("إدارة الصلاحيات للمدير العام فقط", 403, "forbidden")
    return None


def _guard(run):
    try:
        return run()
    except BranchError as exc:
        db.session.rollback()
        return _error(str(exc), exc.status, exc.code)


def _log(action: str, summary: str, employee_id: int | None, payload: dict[str, Any]) -> None:
    from utils.activity_logger import log_activity

    log_activity(action, "permissions", summary, entity_type="employee", entity_id=employee_id, payload=payload,
                 commit=False)


@desktop_api_bp.get(f"{PREFIX}/me")
def permissions_me():
    denied = _authorize(admin=False)
    if denied:
        return denied
    from utils.permission_checks import employee_can

    employee = current_employee()
    names = [p["name"] for grp in service.catalog() for p in grp["permissions"]]
    return _ok(is_admin=is_general_admin(employee), allowed=[n for n in names if employee_can(employee, n)])


@desktop_api_bp.get(f"{PREFIX}/catalog")
def permissions_catalog():
    denied = _authorize()
    if denied:
        return denied
    return _guard(lambda: _ok(groups=service.catalog()))


@desktop_api_bp.get(f"{PREFIX}/employees")
def permissions_employees():
    denied = _authorize()
    if denied:
        return denied
    return _guard(lambda: _ok(rows=service.employees()))


@desktop_api_bp.get(f"{PREFIX}/employees/<int:employee_id>")
def permissions_employee(employee_id: int):
    denied = _authorize()
    if denied:
        return denied
    return _guard(lambda: _ok(**service.detail(employee_id)))


@desktop_api_bp.post(f"{PREFIX}/employees/<int:employee_id>/overrides")
def permissions_set_overrides(employee_id: int):
    denied = _authorize()
    if denied:
        return denied

    def run():
        data = request.get_json(silent=True) or {}
        actor = current_employee()
        result = service.set_overrides(employee_id, data.get("changes") or {}, by=actor.id if actor else None,
                                       note=str(data.get("note") or ""))
        _log("set_overrides", "تعديل صلاحيات موظف (استثناءات فردية)", employee_id, result)
        db.session.commit()
        return _ok(**service.detail(employee_id))

    return _guard(run)


@desktop_api_bp.post(f"{PREFIX}/employees/<int:employee_id>/roles")
def permissions_set_roles(employee_id: int):
    denied = _authorize()
    if denied:
        return denied

    def run():
        data = request.get_json(silent=True) or {}
        try:
            ids = [int(i) for i in data.get("role_ids") or []]
        except (TypeError, ValueError):
            raise BranchError("أدوار غير صحيحة", "validation", 400) from None
        result = service.assign_roles(employee_id, ids)
        _log("assign_roles", "تعيين أدوار موظف", employee_id, result)
        db.session.commit()
        return _ok(**service.detail(employee_id))

    return _guard(run)


@desktop_api_bp.get(f"{PREFIX}/roles")
def permissions_roles():
    denied = _authorize()
    if denied:
        return denied
    return _guard(lambda: _ok(rows=service.roles()))


def _save_role(role_id: int | None):
    data = request.get_json(silent=True) or {}
    perms = data.get("permissions") or []
    if not isinstance(perms, list):
        raise BranchError("الصلاحيات غير صحيحة", "validation", 400)
    role = service.save_role(role_id, str(data.get("name") or ""), str(data.get("description") or ""),
                             [str(p) for p in perms])
    _log("save_role", f"حفظ الدور {role.name}", None, {"role_id": role.id, "permissions": sorted(perms)})
    db.session.commit()
    return _ok(rows=service.roles())


@desktop_api_bp.post(f"{PREFIX}/roles")
def permissions_role_create():
    denied = _authorize()
    if denied:
        return denied
    return _guard(lambda: _save_role(None))


@desktop_api_bp.post(f"{PREFIX}/roles/<int:role_id>")
def permissions_role_update(role_id: int):
    denied = _authorize()
    if denied:
        return denied
    return _guard(lambda: _save_role(role_id))


@desktop_api_bp.post(f"{PREFIX}/roles/<int:role_id>/delete")
def permissions_role_delete(role_id: int):
    denied = _authorize()
    if denied:
        return denied

    def run():
        service.delete_role(role_id)
        _log("delete_role", "حذف دور", None, {"role_id": role_id})
        db.session.commit()
        return _ok(rows=service.roles())

    return _guard(run)


@desktop_api_bp.get(f"{PREFIX}/role-templates")
def permissions_role_templates():
    """Ready-made roles (cashier, accountant, order follow-up …) and whether each is already installed."""
    denied = _authorize()
    if denied:
        return denied
    from utils import permission_templates

    return _guard(lambda: _ok(rows=permission_templates.listing()))


@desktop_api_bp.post(f"{PREFIX}/role-templates/install")
def permissions_install_templates():
    """Creates the chosen templates as ordinary roles. Never overwrites a role that already has the name."""
    denied = _authorize()
    if denied:
        return denied

    def run():
        from utils import permission_templates

        keys = (request.get_json(silent=True) or {}).get("keys") or []
        if not isinstance(keys, list):
            raise BranchError("اختيار غير صحيح", "validation", 400)
        result = permission_templates.install([str(k) for k in keys])
        _log("install_role_templates", "إضافة أدوار جاهزة", None, result)
        db.session.commit()
        return _ok(**result, rows=service.roles(), templates=permission_templates.listing())

    return _guard(run)


@desktop_api_bp.get(f"{PREFIX}/audit")
def permissions_audit():
    denied = _authorize()
    if denied:
        return denied
    return _guard(lambda: _ok(rows=service.audit(request.args.get("limit", 100, type=int))))
