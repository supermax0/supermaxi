"""Authoritative branch access and write-scope helpers.

All web/POS routes should use these helpers instead of trusting ``branch_id``
from a form or query string.  Admin users may aggregate or select a branch;
every other employee is permanently scoped to the branch on their profile.
"""
from __future__ import annotations

from typing import Any

from flask import abort, g, request, session

from extensions import db
from models.employee import Employee


def current_employee() -> Employee | None:
    api_employee = getattr(g, "pos_employee", None)
    if api_employee is not None and getattr(api_employee, "is_active", False):
        return api_employee
    employee_id = session.get("user_id")
    if not employee_id:
        return None
    employee = db.session.get(Employee, employee_id)
    if not employee or not employee.is_active:
        return None
    return employee


def is_general_admin(employee: Employee | None = None) -> bool:
    employee = employee or current_employee()
    return bool(employee and employee.role == "admin")


def active_branch_id() -> int | None:
    branch = getattr(g, "branch", None)
    if branch is not None:
        return int(branch.id)
    public_branch_id = getattr(g, "public_branch_id", None)
    return int(public_branch_id) if public_branch_id else None


def viewing_all_branches() -> bool:
    if not getattr(g, "view_all_branches", False):
        return False
    if is_general_admin():
        return True
    from utils.branch_context import can_view_all_branches

    return can_view_all_branches(current_employee())


def allowed_branch_ids() -> list[int]:
    from utils.branch_mode import independent_branches_enabled

    if not independent_branches_enabled():
        return [int(branch.id) for branch in (getattr(g, "branches", []) or [])]
    if viewing_all_branches():
        return [int(branch.id) for branch in (getattr(g, "branches", []) or [])]
    if is_general_admin():
        if viewing_all_branches():
            return [int(branch.id) for branch in (getattr(g, "branches", []) or [])]
        branch_id = active_branch_id()
        return [branch_id] if branch_id else []
    employee = current_employee()
    if employee is None:
        return []
    from utils.branch_assignments import assigned_branch_ids

    return assigned_branch_ids(employee)


def _raw_branch_id(source: Any = None) -> Any:
    if source is not None:
        try:
            return source.get("branch_id")
        except AttributeError:
            return source
    if request.is_json:
        return (request.get_json(silent=True) or {}).get("branch_id")
    return request.form.get("branch_id") or request.args.get("branch_id")


def _active_branch(raw: Any):
    from models.branch import Branch

    try:
        branch_id = int(raw)
    except (TypeError, ValueError):
        return None
    if branch_id <= 0:
        return None
    return Branch.query.filter_by(id=branch_id, is_active=True).first()


def _related_branch_id(source: Any) -> int | None:
    """Infer a write branch from records already selected by the workflow."""
    if source is None:
        return None
    try:
        get_value = source.get
    except AttributeError:
        return None

    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.product import Product
    from models.shipping import ShippingCompany
    from models.supplier import Supplier
    from models.treasury_account import TreasuryAccount

    references = (
        ("treasury_account_id", TreasuryAccount),
        ("customer_id", Customer),
        ("supplier_id", Supplier),
        ("product_id", Product),
        ("shipping_company_id", ShippingCompany),
        ("employee_id", Employee),
        ("invoice_id", Invoice),
        ("order_id", Invoice),
    )
    inferred: set[int] = set()
    for field, model in references:
        raw = get_value(field)
        if raw in (None, "", 0, "0"):
            continue
        try:
            entity_id = int(raw)
        except (TypeError, ValueError):
            continue
        query = model.query.execution_options(skip_branch_scope=True)
        entity = query.filter(model.id == entity_id).first()
        branch_id = getattr(entity, "branch_id", None) if entity is not None else None
        if branch_id:
            inferred.add(int(branch_id))

    if len(inferred) > 1:
        abort(400, description="السجلات المختارة تتبع فروعاً مختلفة")
    if not inferred:
        return None
    branch_id = next(iter(inferred))
    branch = _active_branch(branch_id)
    return int(branch.id) if branch else None


def resolve_write_branch_id(
    source: Any = None,
    *,
    required: bool = True,
    allow_admin_any_branch: bool = False,
) -> int | None:
    """Resolve and authorize the branch for a new mutation.

    In the admin aggregate view an explicit branch is honored when the
    workflow provides one; otherwise new standalone records use the company
    default branch automatically.  A staff employee can only ever write to
    their assigned branch.
    """
    scope_was_ready = bool(getattr(g, "branch_scope_ready", False))
    if not scope_was_ready:
        from utils.branch_context import init_branch_context

        init_branch_context()
    from utils.branch_mode import independent_branches_enabled

    if not independent_branches_enabled():
        from utils.branch_migration import get_default_branch

        default = get_default_branch()
        if default:
            return int(default.id)
        if required:
            abort(400, description="لا يوجد فرع رئيسي للحفظ")
        return None
    employee = current_employee()
    if not employee:
        abort(401)

    raw = _raw_branch_id(source)
    requested = _active_branch(raw) if raw not in (None, "", 0, "0", "all") else None

    if is_general_admin(employee):
        # Some focused workflows (currently POS) expose their own explicit
        # branch selector.  The server still validates that the target exists
        # and is active, but it need not match the dashboard viewing filter.
        if allow_admin_any_branch and raw not in (None, "", 0, "0", "all") and not requested:
            abort(400, description="الفرع المطلوب غير موجود أو غير نشط")
        if allow_admin_any_branch and requested:
            return int(requested.id)
        current_id = active_branch_id()
        if viewing_all_branches():
            if requested:
                return int(requested.id)
            related_branch_id = _related_branch_id(source)
            if related_branch_id:
                return related_branch_id
            from utils.branch_migration import get_default_branch

            default = get_default_branch()
            if default:
                return int(default.id)
            if required:
                abort(400, description="لا يوجد فرع افتراضي نشط للحفظ")
            return None
        if requested and current_id and int(requested.id) != int(current_id):
            abort(403, description="الفرع المطلوب لا يطابق الفرع الحالي")
        if requested:
            return int(requested.id)
        if current_id:
            return int(current_id)
        if required:
            abort(400, description="يجب اختيار الفرع قبل الحفظ")
        return None

    from utils.branch_assignments import assigned_branch_ids

    allowed = assigned_branch_ids(employee)
    if not allowed:
        abort(403, description="لم يتم تعيين فرع لهذا الموظف")
    if requested:
        if int(requested.id) not in allowed:
            abort(403, description="لا يمكنك استخدام فرع آخر")
        return int(requested.id)
    chosen = active_branch_id()
    if chosen is not None and int(chosen) in allowed:
        return int(chosen)
    return int(employee.branch_id) if employee.branch_id else int(allowed[0])


def scope_query(query, model_or_column):
    """Apply current branch visibility to a SQLAlchemy query."""
    from utils.branch_mode import independent_branches_enabled

    if not independent_branches_enabled():
        return query
    if viewing_all_branches():
        return query
    column = getattr(model_or_column, "branch_id", model_or_column)
    branch_id = active_branch_id()
    if branch_id is None:
        employee = current_employee()
        branch_id = int(employee.branch_id) if employee and employee.branch_id else None
    if branch_id is None:
        return query.filter(db.false())
    return query.filter(column == branch_id)


def entity_is_visible(entity: Any) -> bool:
    if entity is None:
        return False
    from utils.branch_mode import independent_branches_enabled

    if not independent_branches_enabled():
        return True
    if viewing_all_branches():
        return True
    entity_branch_id = getattr(entity, "branch_id", None)
    return bool(entity_branch_id and int(entity_branch_id) in allowed_branch_ids())


def require_visible(entity: Any, *, hide: bool = True):
    if entity_is_visible(entity):
        return entity
    abort(404 if hide else 403)


def scoped_get_or_404(model, entity_id: int):
    entity = db.session.get(model, entity_id)
    return require_visible(entity)


def branch_context_payload() -> dict[str, Any]:
    from utils.branch_mode import independent_branches_enabled

    independent = independent_branches_enabled()
    branch = getattr(g, "branch", None)
    branches = getattr(g, "branches", []) or []
    return {
        "branches": branches,
        "current_branch": branch,
        "current_branch_id": int(branch.id) if branch else None,
        "view_all_branches": viewing_all_branches(),
        "can_switch_branch": bool(independent and is_general_admin()),
        "independent_branches_enabled": independent,
        "branch_scope_label": (
            "النظام المشترك"
            if not independent
            else ("كل الفروع" if viewing_all_branches() else (branch.name if branch else "غير محدد"))
        ),
    }
