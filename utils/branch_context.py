"""Session and request context for active branch."""
from __future__ import annotations

from flask import current_app, g, jsonify, request, session

from extensions import db
from models.employee import Employee
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.branch_mode import independent_branches_enabled


def _is_admin(employee: Employee | None) -> bool:
    return bool(employee and employee.role == "admin")


def can_view_all_branches(employee: Employee | None) -> bool:
    """The general admin, or anyone granted «عرض كل الفروع» (view_all_branches) — e.g. a general-manager role.
    Viewing all branches is a READ scope; creating a record still needs one real branch."""
    if _is_admin(employee):
        return True
    if employee is None or not employee.is_active:
        return False
    try:
        from utils.permission_checks import employee_can

        return bool(employee_can(employee, "view_all_branches"))
    except Exception:
        return False


def init_branch_context() -> None:
    """Initialize g.branch, g.view_all_branches from session."""
    g.branch = None
    g.view_all_branches = False
    g.branches = []
    g.branch_scope_ready = False
    g.independent_branches_enabled = independent_branches_enabled()

    if "user_id" not in session:
        return

    try:
        ensure_branch_schema()

        from models.branch import Branch

        employee = Employee.query.get(session.get("user_id"))
        active_branches = Branch.query.filter_by(is_active=True).order_by(Branch.is_default.desc(), Branch.id).all()
        g.branches = active_branches

        default_branch = get_default_branch()
        admin = can_view_all_branches(employee)

        if not g.independent_branches_enabled:
            # Shared mode does not isolate records by branch.  Keep the
            # default branch as the internal write owner, but expose every
            # active physical branch to pages that offer branch summaries,
            # filters, stock views, and reports.  Limiting this list to the
            # default branch was making the whole UI look as if only the main
            # branch existed.
            g.branches = active_branches
            g.branch = default_branch
            g.view_all_branches = False
            session["view_all_branches"] = False
            if default_branch:
                session["branch_id"] = default_branch.id
                if employee and not employee.branch_id:
                    employee.branch_id = default_branch.id
            return

        if admin:
            view_all = session.get("view_all_branches")
            if view_all is None:
                view_all = True
                session["view_all_branches"] = True
            g.view_all_branches = bool(view_all)

            branch_id = session.get("branch_id")
            if branch_id:
                branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
                if branch:
                    g.branch = branch
                    return
            if default_branch and not g.view_all_branches:
                g.branch = default_branch
                session["branch_id"] = default_branch.id
            return

        branch_id = employee.branch_id if employee else None
        if employee is not None:
            # An employee may also work in extra assigned branches; the one he switched to is kept while it
            # is still assigned, otherwise his home branch applies (exactly the previous behaviour).
            from utils.branch_assignments import assigned_branch_ids

            chosen = session.get("branch_id")
            try:
                chosen = int(chosen) if chosen is not None else None
            except (TypeError, ValueError):
                chosen = None
            if chosen is not None and chosen in assigned_branch_ids(employee):
                branch_id = chosen
        if branch_id:
            branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
            if branch:
                g.branch = branch
                session["branch_id"] = branch.id
                session["view_all_branches"] = False
                return

        if default_branch:
            g.branch = default_branch
            session["branch_id"] = default_branch.id
            session["view_all_branches"] = False
            if employee and not employee.branch_id:
                employee.branch_id = default_branch.id
    except Exception:
        db.session.rollback()
        try:
            current_app.logger.exception("init_branch_context failed")
        except Exception:
            pass
        g.branch = None
        g.view_all_branches = False
        g.branches = []
    finally:
        g.branch_scope_ready = True


def current_branch_id() -> int | None:
    branch = getattr(g, "branch", None)
    return branch.id if branch else None


def init_public_default_branch() -> int | None:
    """Lock storefront, mobile and webhook traffic to the default branch."""
    g.branch_scope_ready = False
    ensure_branch_schema()
    branch = get_default_branch()
    g.public_branch_id = int(branch.id) if branch else None
    g.branch_scope_ready = True
    return g.public_branch_id


def resolve_branch_id(explicit_id: int | None = None) -> int | None:
    if explicit_id:
        return explicit_id
    return current_branch_id()


def can_switch_branch() -> bool:
    if "user_id" not in session:
        return False
    if not independent_branches_enabled():
        return False
    employee = Employee.query.get(session.get("user_id"))
    if can_view_all_branches(employee):
        return True
    from utils.branch_assignments import assigned_branch_ids

    return employee is not None and len(assigned_branch_ids(employee)) > 1


def switch_branch_api():
    from flask import session as flask_session

    if not can_switch_branch():
        return jsonify({"ok": False, "error": "غير مصرح"}), 403

    data = request.get_json(silent=True) or {}
    view_all = bool(data.get("view_all"))
    branch_id = data.get("branch_id")
    switching_employee = Employee.query.get(flask_session.get("user_id"))

    if view_all and not can_view_all_branches(switching_employee):
        return jsonify({"ok": False, "error": "العرض المجمّع لكل الفروع للمدير العام أو من لديه صلاحية «عرض كل الفروع»"}), 403

    if view_all:
        flask_session["view_all_branches"] = True
        flask_session.pop("branch_id", None)
        init_branch_context()
        return jsonify({"ok": True, "view_all": True})

    from models.branch import Branch

    branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
    if not branch:
        return jsonify({"ok": False, "error": "الفرع غير موجود"}), 404
    if not can_view_all_branches(switching_employee):
        from utils.branch_assignments import assigned_branch_ids

        if int(branch.id) not in assigned_branch_ids(switching_employee):
            return jsonify({"ok": False, "error": "هذا الفرع غير معيّن لك"}), 403

    flask_session["view_all_branches"] = False
    flask_session["branch_id"] = branch.id
    init_branch_context()

    from utils.activity_logger import log_activity

    log_activity(
        action="switch",
        category="branch",
        summary=f"تبديل الفرع إلى {branch.name}",
        entity_type="branch",
        entity_id=str(branch.id),
        payload={"branch_id": branch.id, "branch_name": branch.name},
    )
    return jsonify({"ok": True, "branch": branch.to_dict()})


def branches_for_select(include_all: bool = False) -> list[dict]:
    branches = getattr(g, "branches", []) or []
    items = [b.to_dict() for b in branches]
    if include_all and can_switch_branch():
        items.insert(0, {"id": 0, "code": "ALL", "name": "كل الفروع", "is_active": True})
    return items
