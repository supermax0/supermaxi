"""Branch comparison report (spec phase 15): real figures from the books' own sources, per branch and combined.

Rules: no profit/net-result is shown because the books carry no per-branch cost of goods sold for a period —
a figure we cannot source is absent, never estimated. Inter-branch stock and cash transfers are not sales,
expenses or revenue and appear in no total here. ``central_expenses`` is reported apart from the branches.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func

from extensions import db
from models.branch import Branch
from utils.branch_management import BranchError, branch_stats


def build(start: date, end: date, branch_ids: list[int] | None = None) -> dict[str, Any]:
    from models.invoice import Invoice
    from utils import expense_allocation
    from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES

    if start > end:
        raise BranchError("الفترة غير صحيحة", "validation", 400)
    q = Branch.query.filter(Branch.is_active.is_(True))
    if branch_ids:
        q = q.filter(Branch.id.in_(branch_ids))
    branches = q.order_by(Branch.id).all()
    if not branches:
        raise BranchError("لا فروع فعّالة للمقارنة", "not_found", 404)
    ids = [b.id for b in branches]
    dead, returned = list(CANCELED_STATUSES), list(RETURN_STATUSES)

    rows = (Invoice.query.execution_options(skip_branch_scope=True)
            .filter(Invoice.branch_id.in_(ids), func.date(Invoice.created_at) >= start,
                    func.date(Invoice.created_at) <= end)
            .with_entities(Invoice.branch_id, Invoice.status, func.count(Invoice.id),
                           func.coalesce(func.sum(Invoice.total), 0))
            .group_by(Invoice.branch_id, Invoice.status).all())
    sales: dict[int, dict[str, int]] = {i: {"gross": 0, "orders": 0, "canceled": 0, "returned": 0,
                                            "returns_value": 0} for i in ids}
    for branch_id, status, count, total in rows:
        bucket = sales[int(branch_id)]
        if status in dead:
            bucket["canceled"] += int(count)
        elif status in returned:
            bucket["returned"] += int(count)
            bucket["returns_value"] += int(total or 0)
        else:
            bucket["orders"] += int(count)
            bucket["gross"] += int(total or 0)

    spend = expense_allocation.branch_report(start, end)
    expenses = {int(b["branch_id"]): int(b["amount"]) for b in spend["branches"]}

    out = []
    for branch in branches:
        s = sales[branch.id]
        live = branch_stats(branch.id)  # stock value, in transit and cash are as-of-now balances
        out.append({
            "branch_id": branch.id, "branch": branch.name, "code": branch.code,
            "sales": s["gross"], "orders": s["orders"], "average_invoice": int(s["gross"] / s["orders"]) if s["orders"] else 0,
            "canceled": s["canceled"], "returned": s["returned"], "returns_value": s["returns_value"],
            "expenses": expenses.get(branch.id, 0),
            "stock_value": live["stock_value"], "in_transit_value": live["in_transit_value"], "cash": live["cash"],
        })

    def total(key: str) -> int | None:
        values = [r[key] for r in out]
        return None if any(v is None for v in values) else int(sum(values))

    return {
        "from": start.isoformat(), "to": end.isoformat(), "branches": out,
        "totals": {k: total(k) for k in ("sales", "orders", "canceled", "returned", "returns_value",
                                         "expenses", "stock_value", "in_transit_value", "cash")},
        "central_expenses": int(spend["central"]), "unassigned_expenses": int(spend["unassigned"]),
        "notes": ["المبيعات = فواتير الفترة غير الملغاة وغير المرتجعة؛ المرتجعات تُعرض منفصلة.",
                  "صافي الفرع/الربح غير معروض: لا تتوفر كلفة بضاعة مباعة لكل فرع بالفترة من مصدر موثوق.",
                  "المخزون والنقد والبضاعة بالطريق أرصدة لحظية وليست للفترة.",
                  "تحويلات المخزون والنقد بين الفروع لا تدخل في المبيعات أو المصاريف."],
    }
