"""Branches & warehouses (FINORA Management Desktop) — JSON over utils/branch_management.

Permissions are enforced here, never in the UI: only a general admin creates / edits / archives branches or
turns multi-branch on; every other employee sees only the branch(es) they are assigned to.
"""
from __future__ import annotations

from typing import Any

from flask import g, jsonify, request, session

from extensions import db
from models.branch import Branch
from models.branch_profile import BRANCH_TYPES
from modules.desktop_api.routes import _error, desktop_api_bp
from modules.stock_operations import transfer_partial
from utils import branch_management as service
from utils.branch_context import can_switch_branch, can_view_all_branches, init_branch_context, switch_branch_api
from utils.branch_scope import allowed_branch_ids, current_employee, is_general_admin, viewing_all_branches

PREFIX = "/branches"


def _ok(**data: Any):
    return jsonify({"ok": True, **data})


def _authorize(*, admin: bool = False, permission: str | None = None):
    """``admin=True`` = general admin only, unless ``permission`` names a delegable right the employee holds."""
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
        from utils.permission_checks import employee_can

        if not (permission and employee_can(employee, permission)):
            return _error("ليست لديك صلاحية لهذا الإجراء", 403, "forbidden")
    return None


def _holds(employee, permission: str) -> bool:
    from utils.permission_checks import employee_can

    return bool(employee is not None and (is_general_admin(employee) or employee_can(employee, permission)))


def _can_report(employee) -> bool:
    return bool(employee is not None and (is_general_admin(employee) or employee.has_permission("view_branch_reports")))


def _visible_branches() -> list[Branch]:
    query = Branch.query.order_by(Branch.is_default.desc(), Branch.name)
    if is_general_admin() or can_view_all_branches(current_employee()):
        return query.all()
    ids = allowed_branch_ids()
    return query.filter(Branch.id.in_(ids)).all() if ids else []


@desktop_api_bp.get(f"{PREFIX}/meta")
def branches_meta():
    denied = _authorize()
    if denied:
        return denied
    state = service.multi_branch_state()
    primary = service.primary_branch()
    switch_allowed = bool(can_switch_branch())
    visible = [b for b in _visible_branches() if b.is_active]
    return _ok(
        multi_branch=state,
        primary_branch_id=primary.id if primary else None,
        can_manage=is_general_admin() or _holds(current_employee(), "manage_branches"),
        can_report=_can_report(current_employee()),
        types=[{"id": key, "label": label} for key, label in BRANCH_TYPES.items()],
        current_branch_id=getattr(getattr(g, "branch", None), "id", None),
        transfer_policy={"approval_required": transfer_partial.approval_required()},
        scope={
            "can_switch": switch_allowed,
            # shared mode: records are not split by branch — every screen already shows all branches
            "shared": not bool(getattr(g, "independent_branches_enabled", True)),
            "view_all": bool(viewing_all_branches() and switch_allowed),
            "branches": [{"id": b.id, "name": b.name, "code": b.code, "is_default": bool(b.is_default)}
                         for b in visible],
        },
    )


@desktop_api_bp.post(f"{PREFIX}/switch")
def branches_switch():
    """Change the VIEW scope (one branch / all branches). Creating operations still needs one real branch —
    that rule lives in ``resolve_write_branch_id`` on the server, not in this selector."""
    denied = _authorize()
    if denied:
        return denied
    return switch_branch_api()


@desktop_api_bp.get(PREFIX)
def branches_list():
    denied = _authorize()
    if denied:
        return denied
    include_archived = request.args.get("archived") == "1"
    can_see_figures = _can_report(current_employee())
    rows = []
    for branch in _visible_branches():
        if not branch.is_active and not include_archived:
            continue
        # sales / stock value / cash of a branch are report figures: only for who may report
        rows.append(service.serialize(branch, stats=service.branch_stats(branch.id) if can_see_figures else None))
    db.session.commit()  # profile rows created lazily above
    scope_ids = None if is_general_admin() else [b.id for b in _visible_branches()]
    return _ok(rows=rows, multi_branch=service.multi_branch_state(),
               pending_transfers=service.pending_transfers(scope_ids) if can_see_figures else None)


@desktop_api_bp.get(f"{PREFIX}/<int:branch_id>")
def branches_detail(branch_id: int):
    denied = _authorize()
    if denied:
        return denied
    branch = next((b for b in _visible_branches() if b.id == branch_id), None)
    if branch is None:
        return _error("الفرع غير موجود أو خارج نطاقك", 404, "not_found")
    employee = current_employee()
    payload = service.serialize(branch, stats=service.branch_stats(branch.id) if _can_report(employee) else None)
    db.session.commit()
    from utils.permission_checks import employee_can

    blockers = service.branch_blockers(branch.id) if employee_can(employee, "manage_branches") else []
    return _ok(branch=payload, blockers=blockers)


def _guard(callable_):
    try:
        return callable_()
    except service.BranchError as exc:
        db.session.rollback()
        return _error(str(exc), exc.status, exc.code)


@desktop_api_bp.post(PREFIX)
def branches_create():
    denied = _authorize(admin=True, permission="manage_branches")
    if denied:
        return denied

    def run():
        if not service.multi_branch_state()["enabled"]:
            raise service.BranchError("فعّل تعدد الفروع من الإعدادات أولاً", "conflict", 409)
        employee = current_employee()
        branch = service.create_branch(request.get_json(silent=True) or {}, actor_id=employee.id if employee else None)
        db.session.commit()
        _audit("create", branch, f"إضافة فرع {branch.name}")
        return _ok(branch=service.serialize(branch, stats=service.branch_stats(branch.id)))

    return _guard(run)


@desktop_api_bp.post(f"{PREFIX}/<int:branch_id>/update")
def branches_update(branch_id: int):
    denied = _authorize(admin=True, permission="manage_branches")
    if denied:
        return denied

    def run():
        branch = db.session.get(Branch, branch_id)
        if branch is None:
            return _error("الفرع غير موجود", 404, "not_found")
        before = branch.to_dict()
        service.update_branch(branch, request.get_json(silent=True) or {})
        db.session.commit()
        _audit("update", branch, f"تعديل فرع {branch.name}", before)
        return _ok(branch=service.serialize(branch, stats=service.branch_stats(branch.id)))

    return _guard(run)


@desktop_api_bp.post(f"{PREFIX}/<int:branch_id>/archive")
def branches_archive(branch_id: int):
    denied = _authorize(admin=True, permission="manage_branches")
    if denied:
        return denied

    def run():
        branch = db.session.get(Branch, branch_id)
        if branch is None:
            return _error("الفرع غير موجود", 404, "not_found")
        data = request.get_json(silent=True) or {}
        before = branch.to_dict()
        employee = current_employee()
        if data.get("restore"):
            service.restore_branch(branch)
        else:
            service.archive_branch(branch, actor_id=employee.id if employee else None, reason=data.get("reason", ""))
        db.session.commit()
        _audit("update", branch, f"{'استعادة' if data.get('restore') else 'أرشفة'} فرع {branch.name}", before)
        return _ok(branch=service.serialize(branch))

    return _guard(run)


@desktop_api_bp.post(f"{PREFIX}/feature")
def branches_feature():
    denied = _authorize(admin=True, permission="manage_branches")
    if denied:
        return denied
    return _guard(lambda: _ok(multi_branch=service.set_multi_branch(
        bool((request.get_json(silent=True) or {}).get("enabled")))))


@desktop_api_bp.get(f"{PREFIX}/availability")
def branches_availability():
    """Where else is this product in stock? Allowed for a general admin, or for everyone when the company
    sells from other branches' stock; otherwise another branch's quantities are not the cashier's business."""
    denied = _authorize()
    if denied:
        return denied
    from utils.branch_sales import branches_stock_for_product, is_sell_from_all_branches_enabled

    if not (is_general_admin() or is_sell_from_all_branches_enabled()):
        return _error("عرض مخزون الفروع الأخرى غير مفعّل لهذه الشركة", 403, "forbidden")
    try:
        product_id = int(request.args.get("product_id", ""))
    except ValueError:
        return _error("حدد المنتج", 400, "validation")
    variant = (request.args.get("variant") or "").strip() or None
    current = getattr(getattr(g, "branch", None), "id", None)
    rows = [{**row, "is_current": row["id"] == current}
            for row in branches_stock_for_product(product_id, variant)]
    return _ok(rows=rows, total=sum(int(r["quantity"] or 0) for r in rows))


def _date_arg(value: Any):
    from datetime import date

    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        raise service.BranchError("تاريخ غير صالح", "validation", 400) from None


def _alloc_args(data: dict):
    weights = {int(k): float(v) for k, v in (data.get("weights") or {}).items()}
    ids = [int(x) for x in (data.get("branch_ids") or weights.keys())]
    return ids, weights, _date_arg(data.get("from")), _date_arg(data.get("to"))


@desktop_api_bp.post(f"{PREFIX}/expense-allocation/preview")
def branches_expense_preview():
    """What a rule WOULD do to an amount. Stores nothing, posts nothing."""
    denied = _authorize(admin=True, permission="allocate_branch_expenses")
    if denied:
        return denied

    def run():
        from utils import expense_allocation

        data = request.get_json(silent=True) or {}
        ids, weights, start, end = _alloc_args(data)
        return _ok(**expense_allocation.preview(int(data.get("amount") or 0), str(data.get("rule") or ""), ids,
                                                weights=weights, start=start, end=end))

    return _guard(run)


@desktop_api_bp.post(f"{PREFIX}/expense-allocation/<int:expense_id>")
def branches_expense_allocate(expense_id: int):
    """Marks an expense central or shared. The expense row and its cash posting are untouched."""
    denied = _authorize(admin=True, permission="allocate_branch_expenses")
    if denied:
        return denied

    def run():
        from utils import expense_allocation

        data = request.get_json(silent=True) or {}
        actor = current_employee()
        ids, weights, start, end = _alloc_args(data)
        kind = str(data.get("kind") or "")
        if kind == "branch":
            expense_allocation.clear(expense_id)
            result = {"expense_id": expense_id, "kind": "branch", "lines": []}
        else:
            result = expense_allocation.save(expense_id, kind, rule=data.get("rule"), branch_ids=ids,
                                             weights=weights, start=start, end=end, note=str(data.get("note") or ""),
                                             by=actor.id if actor else None)
        db.session.commit()
        _audit_person("allocate_expense", expense_id, {"kind": kind, "rule": data.get("rule")})
        return _ok(**result)

    return _guard(run)


@desktop_api_bp.get(f"{PREFIX}/expense-allocation/assignments")
def branches_expense_assignments():
    denied = _authorize(admin=True, permission="allocate_branch_expenses")
    if denied:
        return denied

    def run():
        from utils import expense_allocation

        start, end = _date_arg(request.args.get("from")), _date_arg(request.args.get("to"))
        if start is None or end is None or start > end:
            raise service.BranchError("حدد فترة صحيحة", "validation", 400)
        return _ok(rows={str(k): v for k, v in expense_allocation.assignments(start, end).items()})

    return _guard(run)


@desktop_api_bp.get(f"{PREFIX}/expense-allocation/report")
def branches_expense_report():
    denied = _authorize(admin=True, permission="allocate_branch_expenses")
    if denied:
        return denied

    def run():
        from utils import expense_allocation

        start, end = _date_arg(request.args.get("from")), _date_arg(request.args.get("to"))
        if start is None or end is None or start > end:
            raise service.BranchError("حدد فترة صحيحة", "validation", 400)
        return _ok(**expense_allocation.branch_report(start, end))

    return _guard(run)


def _distribution(doc_id: int):
    from models.branch_distribution import BranchDistribution
    from utils import branch_distribution

    branch_distribution.ensure_table()
    doc = db.session.get(BranchDistribution, doc_id)
    if doc is None:
        raise service.BranchError("جلسة التوزيع غير موجودة", "not_found", 404)
    return doc


@desktop_api_bp.get(f"{PREFIX}/distribution")
def distribution_list():
    denied = _authorize(admin=True, permission="run_branch_distribution")
    if denied:
        return denied
    from utils import branch_distribution

    return _ok(eligibility=branch_distribution.eligibility(), rows=branch_distribution.listing())


@desktop_api_bp.post(f"{PREFIX}/distribution")
def distribution_create():
    denied = _authorize(admin=True, permission="run_branch_distribution")
    if denied:
        return denied

    def run():
        from utils import branch_distribution

        data = request.get_json(silent=True) or {}
        actor = current_employee()
        doc = branch_distribution.create(str(data.get("title") or ""), data.get("items"),
                                         by=actor.id if actor else None)
        db.session.commit()
        return _ok(session=branch_distribution.report(doc))

    return _guard(run)


@desktop_api_bp.get(f"{PREFIX}/distribution/<int:doc_id>")
def distribution_detail(doc_id: int):
    denied = _authorize(admin=True, permission="run_branch_distribution")
    if denied:
        return denied

    def run():
        from utils import branch_distribution

        doc = _distribution(doc_id)
        return _ok(session=branch_distribution.report(doc), preview=branch_distribution.preview(doc))

    return _guard(run)


@desktop_api_bp.post(f"{PREFIX}/distribution/<int:doc_id>/<action>")
def distribution_action(doc_id: int, action: str):
    """action: items (replace the selection) | approve | execute | cancel."""
    denied = _authorize(admin=True, permission="run_branch_distribution")
    if denied:
        return denied

    def run():
        from utils import branch_distribution

        doc = _distribution(doc_id)
        actor = current_employee()
        data = request.get_json(silent=True) or {}
        if action == "items":
            branch_distribution.replace_items(doc, data.get("items"))
        elif action == "approve":
            branch_distribution.approve(doc, actor.id if actor else None)
        elif action == "cancel":
            branch_distribution.cancel(doc)
        elif action == "execute":
            db.session.commit()
            result = branch_distribution.execute(doc, actor)
            _audit_person("distribution_execute", doc_id, {"status": result["status"]})
            return _ok(session=result)
        else:
            raise service.BranchError("إجراء غير معروف", "validation", 400)
        db.session.commit()
        _audit_person(f"distribution_{action}", doc_id, {})
        return _ok(session=branch_distribution.report(doc))

    return _guard(run)


@desktop_api_bp.get(f"{PREFIX}/report")
def branches_report():
    """Comparison of branches for a period. A general admin sees every branch; an employee holding
    ``view_branch_reports`` sees only the branches assigned to him, with company-wide figures withheld."""
    denied = _authorize()
    if denied:
        return denied
    employee = current_employee()
    if not _can_report(employee):
        return _error("تقارير الفروع تحتاج صلاحية عرض تقارير الفروع", 403, "forbidden")
    admin = is_general_admin(employee)

    def run():
        from utils import branch_reports

        start, end = _date_arg(request.args.get("from")), _date_arg(request.args.get("to"))
        if start is None or end is None:
            raise service.BranchError("حدد الفترة", "validation", 400)
        ids = [int(x) for x in request.args.get("branch_ids", "").split(",") if x.strip().isdigit()]
        if not admin:
            from utils.branch_assignments import assigned_branch_ids

            mine = assigned_branch_ids(employee)
            ids = [i for i in ids if i in mine] if ids else mine
            if not ids:
                raise service.BranchError("لا فروع معيّنة لك", "forbidden", 403)
        data = branch_reports.build(start, end, ids or None)
        if not admin:  # company-level figures are not his business
            data["central_expenses"] = data["unassigned_expenses"] = 0
            data["notes"].append("الإجماليات لفروعك المعيّنة فقط.")
        return _ok(**data)

    return _guard(run)


@desktop_api_bp.get(f"{PREFIX}/people")
def branches_people():
    """Active staff with their home branch and extra branches (``?branch_id=`` limits to one branch)."""
    denied = _authorize(admin=True, permission="manage_branch_staff")
    if denied:
        return denied
    from utils import branch_assignments

    only = request.args.get("branch_id", type=int)
    return _ok(rows=branch_assignments.people(only))


@desktop_api_bp.get(f"{PREFIX}/people/<int:employee_id>/history")
def branches_people_history(employee_id: int):
    denied = _authorize(admin=True, permission="manage_branch_staff")
    if denied:
        return denied
    from utils import branch_assignments

    return _ok(rows=branch_assignments.history(employee_id))


@desktop_api_bp.post(f"{PREFIX}/people/<int:employee_id>/assign")
def branches_people_assign(employee_id: int):
    """``mode: "extra"`` lets the employee also work in the branch; ``mode: "move"`` changes his home branch.
    Past records keep the branch they were made in — nothing is rewritten."""
    denied = _authorize(admin=True, permission="manage_branch_staff")
    if denied:
        return denied

    def run():
        from utils import branch_assignments

        data = request.get_json(silent=True) or {}
        actor = current_employee()
        mode = str(data.get("mode") or "extra")
        try:
            branch_id = int(data.get("branch_id"))
        except (TypeError, ValueError):
            raise service.BranchError("اختر الفرع") from None
        note = str(data.get("note") or "")
        if mode == "move":
            result = branch_assignments.move_home(employee_id, branch_id, by=actor.id if actor else None, note=note)
        elif mode == "extra":
            branch_assignments.add_extra(employee_id, branch_id, by=actor.id if actor else None, note=note)
            result = {"employee_id": employee_id, "to_branch_id": branch_id}
        else:
            raise service.BranchError("نوع التعيين غير معروف")
        db.session.commit()
        _audit_person("assign", employee_id, {"mode": mode, **result})
        return _ok(result=result, rows=branch_assignments.people())

    return _guard(run)


@desktop_api_bp.post(f"{PREFIX}/people/<int:employee_id>/unassign")
def branches_people_unassign(employee_id: int):
    denied = _authorize(admin=True, permission="manage_branch_staff")
    if denied:
        return denied

    def run():
        from utils import branch_assignments

        actor = current_employee()
        try:
            branch_id = int((request.get_json(silent=True) or {}).get("branch_id"))
        except (TypeError, ValueError):
            raise service.BranchError("اختر الفرع") from None
        branch_assignments.remove_extra(employee_id, branch_id, by=actor.id if actor else None)
        db.session.commit()
        _audit_person("unassign", employee_id, {"branch_id": branch_id})
        return _ok(rows=branch_assignments.people())

    return _guard(run)


def _audit_person(action: str, employee_id: int, payload: dict) -> None:
    try:
        from utils.activity_logger import log_activity

        log_activity(action, "employees", f"تعيين موظف على فرع ({action})", entity_type="employee",
                     entity_id=employee_id, payload=payload)
    except Exception:
        pass


@desktop_api_bp.post(f"{PREFIX}/transfer-policy")
def branches_transfer_policy():
    """Company policy: a branch transfer must be approved before it can be sent (enforced in the engine)."""
    denied = _authorize(admin=True, permission="manage_branches")
    if denied:
        return denied
    value = bool((request.get_json(silent=True) or {}).get("approval_required"))
    transfer_partial.set_approval_required(value)
    db.session.commit()
    return _ok(transfer_policy={"approval_required": value})


def _audit(action: str, branch: Branch, summary: str, before: dict | None = None) -> None:
    try:
        from utils.activity_logger import log_mutation

        log_mutation(action, "branch", "branch", branch.id, before, branch.to_dict(), summary)
    except Exception:
        pass
