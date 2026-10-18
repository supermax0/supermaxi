"""Desktop management client: JSON sign-in, session probe and sign-out.

Sign-in establishes the very same Flask session as the web login form
(services.staff_auth), so every existing session-based endpoint works for the
desktop client unchanged and FINORA stays the single source of truth.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, session

from extensions import db
from models.employee import Employee
from services.staff_auth import (
    employee_must_change_password,
    establish_staff_session,
    find_core_tenant,
    verify_staff_credentials,
)
from utils.permission_checks import employee_can, get_current_employee
from modules.hr.common import HR_PERMISSIONS, can as hr_can, access_revision
from modules.finance.common import PERMISSIONS as FINANCE_PERMISSIONS
from modules.inventory_audit.common import PERMISSIONS as INVENTORY_AUDIT_PERMISSIONS

desktop_api_bp = Blueprint("desktop_api_v1", __name__, url_prefix="/api/v1/desktop")

# Permissions the desktop client needs to decide which actions to show. The
# backend still enforces each one on the real endpoint.
DESKTOP_PERMISSIONS: tuple[str, ...] = (
    "can_see_orders",
    "can_see_orders_placed",
    "can_see_orders_packed",
    "can_see_orders_shipped",
    "can_see_orders_delivered",
    "can_see_orders_returned",
    "manage_orders",
    "delete_orders",
    "return_orders",
    "pay_orders",
    "print_pos_invoice",
    "can_manage_inventory",
    "wholesale_warehouses",
    "edit_product",
    "edit_price",
    "edit_current_stock",
    "can_manage_suppliers",
    "manage_customers",
    "view_all_branches",
    "view_pos",
    "view_reports",
    "view_financial",
    "view_expenses",
    "view_accounts",
    "can_see_shipping",
    "can_manage_shipping",
    "manage_employees",
    "manage_permissions",  # general admin only (not in the grantable catalog)
    "pricing.view",
    "pricing.manage",
    "pricing.approve",
    "manage_branches",
    "view_branch_reports",
    "manage_branch_staff",
    "run_branch_distribution",
    "allocate_branch_expenses",
    "merge_delivery_agents",
    *HR_PERMISSIONS,
    *FINANCE_PERMISSIONS,
    *INVENTORY_AUDIT_PERMISSIONS,
)

LOGIN_RATE_LIMIT = 10
LOGIN_RATE_WINDOW_SECONDS = 60


def _ok(status: int = 200, **data: Any):
    return jsonify({"ok": True, **data}), status


def _error(message: str, status: int, code: str):
    return jsonify({"ok": False, "error": message, "code": code}), status


@desktop_api_bp.after_request
def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@desktop_api_bp.before_request
def _bind_session_tenant():
    slug = (session.get("tenant_slug") or "").strip()
    if slug and session.get("user_id") and not getattr(g, "tenant", None):
        g.tenant = slug
    return None


def _tenant_info(core_tenant) -> dict[str, Any]:
    """Plain copy of the Core tenant row, read before g.tenant switches databases."""
    return {
        "slug": core_tenant.slug,
        "name": core_tenant.name,
        "business_type": getattr(core_tenant, "business_type", None) or "general",
    }


def _session_payload(emp: Employee, tenant: dict[str, Any]) -> dict[str, Any]:
    from utils.branch_context import current_branch_id, init_branch_context
    from utils.branch_migration import get_default_branch

    init_branch_context()
    branch_id = current_branch_id()
    if not branch_id:
        default = get_default_branch()
        branch_id = default.id if default else None
    branch = None
    if branch_id:
        from models.branch import Branch

        row = db.session.get(Branch, branch_id)
        if row is not None:
            branch = {"id": row.id, "name": row.name}
    lifetime = current_app.permanent_session_lifetime
    return {
        "user": {"id": emp.id, "name": emp.name, "username": emp.username, "role": emp.role},
        "tenant": {"id": emp.tenant_id, **tenant},
        "branch": branch,
        "branch_scope": "shared" if not getattr(g, "independent_branches_enabled", True) else ("all" if getattr(g, "view_all_branches", False) else "branch"),
        "roles": sorted({role.name for role in (emp.roles or [])} | ({emp.role} if emp.role else set())),
        "permissions": [name for name in DESKTOP_PERMISSIONS if (hr_can(name) if name.startswith("hr.") else employee_can(emp, name))],
        "session_max_age_seconds": int(lifetime.total_seconds()),
        "offline_pos_enabled": db.session.connection().dialect.name == "sqlite",
        "hr_scope_revision": access_revision(emp),
    }


def _log_auth(action: str, emp: Employee | None, *, success: bool, extra: dict[str, Any]) -> None:
    try:
        from utils.activity_logger import log_auth

        log_auth(action, employee=emp, success=success, extra={"client": "desktop", **extra})
    except Exception:
        current_app.logger.exception("desktop auth activity log failed (%s)", action)


@desktop_api_bp.post("/auth/login")
def login():
    from modules.pos_api.services.rate_limit import allow_request

    if not allow_request("desktop_login", limit=LOGIN_RATE_LIMIT, window_seconds=LOGIN_RATE_WINDOW_SECONDS):
        return _error("محاولات كثيرة، انتظر دقيقة ثم أعد المحاولة", 429, "rate_limited")

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("صيغة الطلب غير صحيحة", 400, "validation_error")
    tenant_slug = str(body.get("tenant_slug") or "").strip().lower()
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not tenant_slug or not username or not password:
        return _error("أدخل معرف الشركة واسم المستخدم وكلمة المرور", 400, "validation_error")

    core_tenant = find_core_tenant(tenant_slug)
    if core_tenant is None:
        return _error("الشركة غير موجودة. تأكد من معرف الشركة.", 404, "tenant_not_found")
    if not core_tenant.is_active:
        return _error("اشتراك هذه الشركة غير مفعل أو تم إيقافه.", 403, "tenant_inactive")
    tenant = _tenant_info(core_tenant)

    g.tenant = core_tenant.slug
    try:
        from routes.employees import _ensure_employee_profile_schema

        _ensure_employee_profile_schema()
    except Exception:
        current_app.logger.exception("employee profile schema ensure failed (desktop login)")

    emp = verify_staff_credentials(username, password)
    if emp is None:
        _log_auth("login_failed", None, success=False, extra={"username": username, "tenant_slug": tenant_slug})
        return _error("بيانات الدخول غير صحيحة", 401, "invalid_credentials")
    if not emp.is_active:
        _log_auth("login_failed", emp, success=False, extra={"reason": "inactive"})
        return _error("هذا الحساب معطل، يرجى التواصل مع الإدارة", 403, "user_inactive")
    if employee_must_change_password(emp):
        # No half-open session: the one-time password must be replaced on the web first.
        session.clear()
        return _error(
            "كلمة المرور مؤقتة. غيّرها من FINORA على الويب ثم سجّل الدخول.",
            403,
            "password_change_required",
        )

    establish_staff_session(core_tenant, emp)
    _log_auth("login", emp, success=True, extra={"tenant_slug": tenant["slug"], "role": emp.role})
    return _ok(session=_session_payload(emp, tenant))


@desktop_api_bp.get("/auth/session")
def current_session():
    if not session.get("user_id") or not session.get("tenant_slug"):
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    emp = get_current_employee()
    if emp is None:
        session.clear()
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    core_tenant = find_core_tenant(session["tenant_slug"])
    if core_tenant is None or not core_tenant.is_active:
        session.clear()
        return _error("اشتراك هذه الشركة غير مفعل أو تم إيقافه.", 403, "tenant_inactive")
    return _ok(session=_session_payload(emp, _tenant_info(core_tenant)))


@desktop_api_bp.post("/auth/logout")
def logout():
    emp = get_current_employee() if session.get("user_id") else None
    if emp is not None:
        _log_auth("logout", emp, success=True, extra={})
    session.clear()
    return _ok(signed_out=True)
