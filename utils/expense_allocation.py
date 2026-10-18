"""Expense kinds (branch / central / shared) and allocation rules — a reporting overlay, nothing is posted."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func

from extensions import db
from models.branch import Branch
from models.expense import Expense
from models.expense_allocation import ExpenseAllocation, ExpenseAllocationLine
from utils.branch_management import BranchError

RULES = {"fixed": "نسبة ثابتة", "sales": "نسبة المبيعات", "employees": "عدد الموظفين",
         "area": "المساحة", "manual": "يدوي"}
KINDS = {"branch": "خاص بفرع", "central": "إدارة رئيسية", "shared": "مشترك"}


def ensure_tables() -> None:
    conn = db.session.connection()
    ExpenseAllocation.__table__.create(bind=conn, checkfirst=True)
    ExpenseAllocationLine.__table__.create(bind=conn, checkfirst=True)


def _active_branches(ids: list[int] | None = None) -> list[Branch]:
    q = Branch.query.filter(Branch.is_active.is_(True))
    if ids:
        q = q.filter(Branch.id.in_(ids))
    return q.order_by(Branch.id).all()


def split_amount(amount: int, weights: dict[int, float]) -> dict[int, int]:
    """Integer split whose parts always add up to ``amount`` (the remainder goes to the largest weight)."""
    total = sum(w for w in weights.values() if w > 0)
    if amount < 0 or total <= 0:
        raise BranchError("لا يمكن حساب التوزيع: الأوزان صفر", "validation", 400)
    parts = {b: int(amount * w / total) for b, w in weights.items() if w > 0}
    rest = amount - sum(parts.values())
    if rest:
        parts[max(parts, key=lambda b: (weights[b], -b))] += rest
    return parts


def _sales_weights(ids: list[int], start: date, end: date) -> dict[int, float]:
    from models.invoice import Invoice
    from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES

    dead = list(CANCELED_STATUSES | RETURN_STATUSES)
    rows = (Invoice.query.execution_options(skip_branch_scope=True)
            .filter(Invoice.branch_id.in_(ids), Invoice.status.notin_(dead),
                    func.date(Invoice.created_at) >= start, func.date(Invoice.created_at) <= end)
            .with_entities(Invoice.branch_id, func.coalesce(func.sum(Invoice.total), 0))
            .group_by(Invoice.branch_id).all())
    return {int(b): float(t) for b, t in rows}


def _employee_weights(ids: list[int]) -> dict[int, float]:
    from models.employee import Employee

    rows = (Employee.query.execution_options(skip_branch_scope=True)
            .filter(Employee.is_active.is_(True), Employee.branch_id.in_(ids))
            .with_entities(Employee.branch_id, func.count(Employee.id)).group_by(Employee.branch_id).all())
    return {int(b): float(c) for b, c in rows}


def preview(amount: int, rule: str, branch_ids: list[int], *, weights: dict[int, float] | None = None,
            start: date | None = None, end: date | None = None) -> dict[str, Any]:
    """The split a rule would produce. Computed from real data only; nothing is stored."""
    if rule not in RULES:
        raise BranchError("قاعدة التوزيع غير معروفة", "validation", 400)
    branches = _active_branches(branch_ids)
    if len(branches) < 2:
        raise BranchError("اختر فرعين فعّالين على الأقل", "validation", 400)
    ids = [b.id for b in branches]
    weights = {int(k): float(v) for k, v in (weights or {}).items() if int(k) in ids}
    if rule == "sales":
        if start is None or end is None or start > end:
            raise BranchError("حدد فترة صحيحة لحساب نسبة المبيعات", "validation", 400)
        weights = _sales_weights(ids, start, end)
    elif rule == "employees":
        weights = _employee_weights(ids)
    elif rule in ("fixed", "area", "manual") and not weights:
        raise BranchError("حدد النسب/الأوزان لكل فرع", "validation", 400)
    if rule == "manual":
        parts = {b: int(v) for b, v in weights.items() if v > 0}
        if sum(parts.values()) != int(amount):
            raise BranchError("مجموع المبالغ اليدوية يجب أن يساوي مبلغ المصروف", "validation", 400)
    else:
        parts = split_amount(int(amount), weights)
    names = {b.id: b.name for b in branches}
    return {"amount": int(amount), "rule": rule,
            "lines": [{"branch_id": b, "branch": names[b], "weight": weights.get(b), "amount": a}
                      for b, a in parts.items()]}


def save(expense_id: int, kind: str, *, rule: str | None = None, branch_ids: list[int] | None = None,
         weights: dict[int, float] | None = None, start: date | None = None, end: date | None = None,
         note: str = "", by: int | None = None) -> dict[str, Any]:
    ensure_tables()
    if kind not in ("central", "shared"):
        raise BranchError("النوع: إدارة رئيسية أو مشترك", "validation", 400)
    expense = Expense.query.execution_options(skip_branch_scope=True).get(int(expense_id))
    if expense is None:
        raise BranchError("المصروف غير موجود", "not_found", 404)
    lines: list[dict[str, Any]] = []
    if kind == "shared":
        lines = preview(int(expense.amount), rule or "", branch_ids or [], weights=weights,
                        start=start, end=end)["lines"]
    row = ExpenseAllocation.query.filter_by(expense_id=expense.id).first()
    if row is None:
        row = ExpenseAllocation(expense_id=expense.id, kind=kind)
        db.session.add(row)
        db.session.flush()
    else:
        ExpenseAllocationLine.query.filter_by(allocation_id=row.id).delete()
    row.kind, row.rule = kind, rule if kind == "shared" else None
    row.period_from, row.period_to, row.note, row.created_by_id = start, end, (note or "")[:255] or None, by
    for ln in lines:
        db.session.add(ExpenseAllocationLine(allocation_id=row.id, branch_id=ln["branch_id"],
                                             weight=ln["weight"], amount=ln["amount"]))
    return {"expense_id": expense.id, "kind": kind, "rule": row.rule, "lines": lines}


def clear(expense_id: int) -> None:
    ensure_tables()
    row = ExpenseAllocation.query.filter_by(expense_id=int(expense_id)).first()
    if row is not None:
        ExpenseAllocationLine.query.filter_by(allocation_id=row.id).delete()
        db.session.delete(row)


def branch_report(start: date, end: date) -> dict[str, Any]:
    """Per-branch expenses for a period: direct + allocated shares; central kept apart. ``company_total`` is
    the plain sum of expense rows and always equals branches + unassigned + central."""
    ensure_tables()
    exp = (Expense.query.execution_options(skip_branch_scope=True)
           .filter(Expense.expense_date >= start, Expense.expense_date <= end).all())
    plan = {a.expense_id: a for a in ExpenseAllocation.query.filter(
        ExpenseAllocation.expense_id.in_([e.id for e in exp] or [0])).all()}
    lines: dict[int, list[ExpenseAllocationLine]] = {}
    for ln in ExpenseAllocationLine.query.filter(
            ExpenseAllocationLine.allocation_id.in_([a.id for a in plan.values()] or [0])).all():
        lines.setdefault(ln.allocation_id, []).append(ln)
    per: dict[int, int] = {}
    central = unassigned = 0
    for e in exp:
        a = plan.get(e.id)
        if a is not None and a.kind == "central":
            central += int(e.amount)
        elif a is not None and a.kind == "shared":
            for ln in lines.get(a.id, []):
                per[ln.branch_id] = per.get(ln.branch_id, 0) + int(ln.amount)
        elif e.branch_id:
            per[int(e.branch_id)] = per.get(int(e.branch_id), 0) + int(e.amount)
        else:
            unassigned += int(e.amount)
    names = {b.id: b.name for b in Branch.query.all()}
    return {"from": start.isoformat(), "to": end.isoformat(),
            "branches": [{"branch_id": b, "branch": names.get(b, "—"), "amount": v} for b, v in sorted(per.items())],
            "central": central, "unassigned": unassigned,
            "company_total": sum(int(e.amount) for e in exp)}


def assignments(start: date, end: date) -> dict[int, dict[str, Any]]:
    """expense_id → {kind, rule, lines} for the expenses of a period that are central or shared."""
    ensure_tables()
    rows = (db.session.query(ExpenseAllocation).join(Expense, Expense.id == ExpenseAllocation.expense_id)
            .filter(Expense.expense_date >= start, Expense.expense_date <= end).all())
    out: dict[int, dict[str, Any]] = {}
    for a in rows:
        lines = ExpenseAllocationLine.query.filter_by(allocation_id=a.id).all()
        out[int(a.expense_id)] = {"kind": a.kind, "rule": a.rule,
                                  "lines": [{"branch_id": ln.branch_id, "amount": int(ln.amount)} for ln in lines]}
    return out
