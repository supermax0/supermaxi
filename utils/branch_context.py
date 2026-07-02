"""Session and request context for active branch."""
from __future__ import annotations

from flask import g, jsonify, request, session

from models.employee import Employee
from utils.branch_migration import ensure_branch_schema, get_default_branch


def _is_admin(employee: Employee | None) -> bool:
    if not employee:
        return False
    if employee.role == "admin":
        return True
    return employee.has_permission("view_all_branches")


def init_branch_context() -> None:
    """Initialize g.branch, g.view_all_branches from session."""
    g.branch = None
    g.view_all_branches = False
    g.branches = []

    if "user_id" not in session:
        return

    ensure_branch_schema()

    from models.branch import Branch

    employee = Employee.query.get(session.get("user_id"))
    active_branches = Branch.query.filter_by(is_active=True).order_by(Branch.is_default.desc(), Branch.id).all()
    g.branches = active_branches

    default_branch = get_default_branch()
    admin = _is_admin(employee)

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


def current_branch_id() -> int | None:
    branch = getattr(g, "branch", None)
    return branch.id if branch else None


def resolve_branch_id(explicit_id: int | None = None) -> int | None:
    if explicit_id:
        return explicit_id
    return current_branch_id()


def can_switch_branch() -> bool:
    if "user_id" not in session:
        return False
    employee = Employee.query.get(session.get("user_id"))
    return _is_admin(employee)


def switch_branch_api():
    from flask import session as flask_session

    if not can_switch_branch():
        return jsonify({"ok": False, "error": "غير مصرح"}), 403

    data = request.get_json(silent=True) or {}
    view_all = bool(data.get("view_all"))
    branch_id = data.get("branch_id")

    if view_all:
        flask_session["view_all_branches"] = True
        flask_session.pop("branch_id", None)
        init_branch_context()
        return jsonify({"ok": True, "view_all": True})

    from models.branch import Branch

    branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
    if not branch:
        return jsonify({"ok": False, "error": "الفرع غير موجود"}), 404

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
