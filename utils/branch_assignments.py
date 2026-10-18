"""Employee branch assignments: who may work in which branches, and how that changed over time.

The home branch is ``employee.branch_id`` (unchanged for every other module). Extra branches live in
``branch_user_assignment``. A general admin reaches every branch and needs no assignment.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from flask import g, has_request_context

from extensions import db
from models.branch import Branch
from models.branch_assignment import BranchUserAssignment
from utils.branch_management import BranchError


def _today() -> date:
    from modules.finance.common import today

    return today()


def ensure_table() -> None:
    BranchUserAssignment.__table__.create(bind=db.session.connection(), checkfirst=True)


def extra_branch_ids(employee_id: int) -> list[int]:
    """Active extra branches (only active branches count). Never raises: scope resolution must not break."""
    try:
        rows = (db.session.query(BranchUserAssignment.branch_id)
                .join(Branch, Branch.id == BranchUserAssignment.branch_id)
                .filter(BranchUserAssignment.employee_id == int(employee_id),
                        BranchUserAssignment.kind == "extra", BranchUserAssignment.active.is_(True),
                        Branch.is_active.is_(True)).all())
        return sorted({int(r[0]) for r in rows})
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def assigned_branch_ids(employee: Any) -> list[int]:
    """Home branch first, then the active extras. Cached for the request."""
    if employee is None:
        return []
    key = f"_assigned_branches_{int(employee.id)}"
    if has_request_context() and key in g.__dict__:
        return list(g.__dict__[key])
    ids: list[int] = []
    if getattr(employee, "branch_id", None):
        ids.append(int(employee.branch_id))
    for branch_id in extra_branch_ids(employee.id):
        if branch_id not in ids:
            ids.append(branch_id)
    if has_request_context():
        g.__dict__[key] = list(ids)
    return ids


def forget(employee_id: int) -> None:
    if has_request_context():
        g.__dict__.pop(f"_assigned_branches_{int(employee_id)}", None)


# ───────────────────────────── administration ─────────────────────────────


def _employee(employee_id: int):
    from models.employee import Employee

    row = Employee.query.execution_options(skip_branch_scope=True).filter_by(id=int(employee_id)).first()
    if row is None or not row.is_active:
        raise BranchError("الموظف غير موجود أو غير فعّال", "not_found", 404)
    if row.role == "admin":
        raise BranchError("المدير العام يصل لكل الفروع ولا يحتاج تعيين", "validation", 400)
    return row


def _branch(branch_id: int) -> Branch:
    row = Branch.query.filter_by(id=int(branch_id), is_active=True).first()
    if row is None:
        raise BranchError("الفرع غير موجود أو مؤرشف", "not_found", 404)
    return row


def add_extra(employee_id: int, branch_id: int, *, by: int | None, note: str = "") -> BranchUserAssignment:
    ensure_table()
    employee, branch = _employee(employee_id), _branch(branch_id)
    if employee.branch_id and int(employee.branch_id) == branch.id:
        raise BranchError("هذا هو فرعه الأساسي أصلاً", "conflict", 409)
    if branch.id in extra_branch_ids(employee.id):
        raise BranchError("الموظف معيّن لهذا الفرع مسبقاً", "conflict", 409)
    row = BranchUserAssignment(employee_id=employee.id, branch_id=branch.id, kind="extra", active=True,
                               valid_from=_today(), note=(note or "").strip()[:255] or None, created_by_id=by)
    db.session.add(row)
    forget(employee.id)
    return row


def remove_extra(employee_id: int, branch_id: int, *, by: int | None) -> BranchUserAssignment:
    ensure_table()
    row = (BranchUserAssignment.query.filter_by(employee_id=int(employee_id), branch_id=int(branch_id),
                                                kind="extra", active=True).first())
    if row is None:
        raise BranchError("لا يوجد تعيين إضافي نشط لهذا الفرع", "not_found", 404)
    row.active, row.valid_to = False, _today()
    forget(employee_id)
    return row


def move_home(employee_id: int, branch_id: int, *, by: int | None, note: str = "") -> dict[str, Any]:
    """Change the employee's home branch. Past records keep the branch they were created in."""
    ensure_table()
    employee, branch = _employee(employee_id), _branch(branch_id)
    old = int(employee.branch_id) if employee.branch_id else None
    if old == branch.id:
        raise BranchError("الموظف في هذا الفرع أصلاً", "conflict", 409)
    today = _today()
    # close the open home record, or write the one that was implicit before this table existed
    open_home = BranchUserAssignment.query.filter_by(employee_id=employee.id, kind="home", active=True).first()
    if open_home is not None:
        open_home.active, open_home.valid_to = False, today
    elif old:
        db.session.add(BranchUserAssignment(employee_id=employee.id, branch_id=old, kind="home", active=False,
                                            valid_from=None, valid_to=today, note="الفرع الأساسي قبل النقل",
                                            created_by_id=by))
    # the new home replaces any extra assignment to the same branch
    for extra in BranchUserAssignment.query.filter_by(employee_id=employee.id, branch_id=branch.id,
                                                      kind="extra", active=True).all():
        extra.active, extra.valid_to = False, today
    employee.branch_id = branch.id
    db.session.add(BranchUserAssignment(employee_id=employee.id, branch_id=branch.id, kind="home", active=True,
                                        valid_from=today, note=(note or "").strip()[:255] or None,
                                        created_by_id=by))
    forget(employee.id)
    return {"employee_id": employee.id, "from_branch_id": old, "to_branch_id": branch.id}


# ───────────────────────────── read models ─────────────────────────────


def history(employee_id: int) -> list[dict[str, Any]]:
    ensure_table()
    names = {b.id: b.name for b in Branch.query.execution_options(skip_branch_scope=True).all()}
    rows = (BranchUserAssignment.query.filter_by(employee_id=int(employee_id))
            .order_by(BranchUserAssignment.id.desc()).all())
    return [{"id": r.id, "branch_id": r.branch_id, "branch": names.get(r.branch_id, "—"), "kind": r.kind,
             "active": bool(r.active), "valid_from": r.valid_from.isoformat() if r.valid_from else "",
             "valid_to": r.valid_to.isoformat() if r.valid_to else "", "note": r.note or ""} for r in rows]


def people(branch_id: int | None = None) -> list[dict[str, Any]]:
    """Active non-admin employees with their home branch and active extras (optionally of one branch)."""
    from models.employee import Employee

    ensure_table()
    names = {b.id: b.name for b in Branch.query.execution_options(skip_branch_scope=True).all()}
    extras: dict[int, list[int]] = {}
    for emp_id, bid in (db.session.query(BranchUserAssignment.employee_id, BranchUserAssignment.branch_id)
                        .filter(BranchUserAssignment.kind == "extra", BranchUserAssignment.active.is_(True)).all()):
        extras.setdefault(int(emp_id), []).append(int(bid))
    out = []
    for e in (Employee.query.execution_options(skip_branch_scope=True)
              .filter(Employee.is_active.is_(True), Employee.role != "admin").order_by(Employee.name).all()):
        mine = [b for b in extras.get(e.id, []) if names.get(b)]
        if branch_id is not None and int(e.branch_id or 0) != branch_id and branch_id not in mine:
            continue
        out.append({"id": e.id, "name": e.name, "role": e.role, "home_branch_id": e.branch_id,
                    "home_branch": names.get(e.branch_id, ""),
                    "extras": [{"branch_id": b, "name": names[b]} for b in mine]})
    return out
