"""Read-only assistant tools over FINORA's existing report engine.

Every figure comes from services/reports_service.py (the same functions the
reports dashboard uses) or from existing FINORA helpers, so the assistant can
never disagree with the reports pages. No new accounting logic lives here.
"""
from __future__ import annotations

from contextlib import contextmanager

from services import reports_service as rs

PERIOD = {"type": "string", "enum": [p for p in rs.PERIODS]}
DATE = {"type": "string"}
BRANCH = {"type": "integer", "minimum": 1}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 20}
PERIOD_ARGS = {"period": PERIOD, "date_from": DATE, "date_to": DATE, "branch_id": BRANCH}


def _filters(args: dict) -> rs.ReportFilters:
    period = args.get("period") or ("custom" if args.get("date_from") or args.get("date_to") else "this_month")
    values = {"period": period, "date_from": args.get("date_from"), "date_to": args.get("date_to"),
              "branch_id": args.get("branch_id")}
    if period == "custom":
        values["date_from"] = values["date_from"] or values["date_to"]
        values["date_to"] = values["date_to"] or values["date_from"]
    try:
        return rs.parse_filters(values)
    except rs.ReportError as error:
        raise ValueError(error.message)


@contextmanager
def _section(section: str, filters: rs.ReportFilters):
    """Same permission and branch guards as the reports API, as tool errors."""
    try:
        rs.require_section(section)
        with rs.branch_scope(filters):
            yield
    except rs.ReportError as error:
        if error.status == 403:
            raise PermissionError(error.message)
        if error.status == 404:
            raise LookupError(error.message)
        raise ValueError(error.message)


def _range(filters: rs.ReportFilters, date_from=None, date_to=None) -> dict:
    return {"period": filters.period, "from": (date_from or filters.date_from).isoformat(),
            "to": (date_to or filters.date_to).isoformat(), "branch_id": filters.branch_id}


def _figures(filters: rs.ReportFilters, date_from, date_to) -> dict:
    sales = rs.sales_totals(filters, date_from, date_to)
    data = {
        "invoices": sales["invoices"],
        "net_sales": sales["net"],
        "collected": sales["collected"],
        "credit_sales": sales["credit"],
        "average_invoice": sales["average"],
        "returns": rs.returns_total(filters, date_from, date_to)["amount"],
    }
    if rs.can_view("profit"):
        pnl = rs.profit_and_loss(filters, date_from, date_to)
        data.update(cogs=pnl["cogs"], gross_profit=pnl["gross_profit"],
                    operating_expenses=pnl["operating_expenses"], other_expenses=pnl["other_expenses"],
                    net_profit=pnl["net_profit"])
    elif rs.can_view("expenses"):
        data["operating_expenses"] = rs.expenses_total(filters, date_from, date_to)["amount"]
    return data


def period_comparison(args: dict, _scope: dict) -> dict:
    filters = _filters(args)
    with _section("sales", filters):
        if args.get("compare_to") == "last_year":
            prev_from, prev_to = filters.last_year()
        else:
            prev_from, prev_to = filters.previous()
        current = _figures(filters, filters.date_from, filters.date_to)
        previous = _figures(filters, prev_from, prev_to)
    return {
        "current": {**_range(filters), **current},
        "previous": {**_range(filters, prev_from, prev_to), **previous},
        "change_percent": {key: rs._pct(value, previous.get(key)) for key, value in current.items()},
        "basis": "نفس محرك صفحة التقارير: مبيعات محجوزة غير ملغاة/راجعة، تكلفة FIFO، مصاريف مرحّلة. الربح يظهر فقط مع صلاحية التقارير المالية.",
        "currency": "IQD",
    }


def sales_breakdown(args: dict, _scope: dict) -> dict:
    filters = _filters(args)
    by = args.get("by") or "branch"
    with _section("sales", filters):
        rows = rs.sales_breakdown(filters, by, int(args.get("limit") or 10))
    if by in ("day", "month"):
        rows = rows[-31:]
    return {**_range(filters), "by": by, "rows": rows, "count": len(rows),
            "note": "الفروع والسجلات ضمن نطاق صلاحياتك فقط. amount = صافي المبيعات.", "currency": "IQD"}


def purchases_summary(args: dict, _scope: dict) -> dict:
    filters = _filters(args)
    limit = int(args.get("limit") or 10)
    with _section("purchases", filters):
        report = rs.purchases_report(filters, 1, limit, "debts" if args.get("unpaid_only") else "purchases")
    return {**_range(filters), "totals": report["metrics"], "top_suppliers": report["by_supplier"][:limit],
            "purchases": report["rows"], "unpaid_only": bool(args.get("unpaid_only")),
            "note": "مشتريات مؤكدة غير ملغاة وفق صفحة تقارير المشتريات. supplier_debts رصيد الموردين الحالي وليس للفترة.",
            "currency": "IQD"}


def receivables_aging(args: dict, _scope: dict) -> dict:
    filters = _filters({"branch_id": args.get("branch_id")})
    with _section("customers", filters):
        report = rs.customers_report(filters, 1, int(args.get("limit") or 10), "debts")
    metrics = report["metrics"]
    return {
        "receivables": metrics["receivables"],
        "open_invoices": metrics["open_invoices"],
        "due_today": metrics["due_today"],
        "overdue": metrics["overdue"],
        "aging": report["aging"],
        "oldest_open_invoices": report["rows"],
        "branch_id": filters.branch_id,
        "note": "أعمار الذمم من تاريخ الفاتورة وفق تقرير العملاء. الرصيد الحالي، وليس لفترة.",
        "currency": "IQD",
    }


def sales_returns(args: dict, _scope: dict) -> dict:
    filters = _filters(args)
    with _section("sales", filters):
        returns = rs.returns_total(filters, filters.date_from, filters.date_to)
        sales = rs.sales_totals(filters, filters.date_from, filters.date_to)
        documents = rs._return_activity(filters, filters.date_from, filters.date_to)["returns"]
    gross = sales["net"] + returns["amount"]
    return {
        **_range(filters),
        "returns_count": returns["count"],
        "returns_amount": returns["amount"],
        "net_sales": sales["net"],
        "return_rate_percent": round(returns["amount"] / gross * 100, 1) if gross else None,
        "recent_return_documents": [
            {"return_id": row["id"], "invoice_id": row["invoice_id"], "date": row["date"], "credit": row["credit"]}
            for row in documents[-int(args.get("limit") or 10):]
        ],
        "currency": "IQD",
    }


def overdue_installments(args: dict, _scope: dict) -> dict:
    from models.customer import Customer
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment
    from utils.business_time import business_today
    from utils.customer_credit_service import compute_installment_status

    today = business_today()
    query = (
        CustomerInstallment.query.join(CustomerCreditPlan, CustomerCreditPlan.id == CustomerInstallment.plan_id)
        .filter(CustomerInstallment.due_date < today, CustomerInstallment.amount > CustomerInstallment.paid_amount)
    )
    if args.get("customer_id"):
        query = query.filter(CustomerCreditPlan.customer_id == int(args["customer_id"]))
    late = query.order_by(CustomerInstallment.due_date.asc(), CustomerInstallment.id.asc()).all()
    # Customers are read through the ORM tenant/branch scope; others are dropped.
    plans = {inst.plan_id: inst.plan for inst in late}
    customers = {
        c.id: c for c in Customer.query.filter(Customer.id.in_({p.customer_id for p in plans.values()} or {-1})).all()
    }
    visible = [inst for inst in late if plans[inst.plan_id].customer_id in customers]
    limit = int(args.get("limit") or 10)
    return {
        "count": len(visible),
        "amount": sum(inst.remaining for inst in visible),
        "customers": len({plans[inst.plan_id].customer_id for inst in visible}),
        "items": [
            {
                "customer_id": plans[inst.plan_id].customer_id,
                "customer": customers[plans[inst.plan_id].customer_id].name,
                "phone": customers[plans[inst.plan_id].customer_id].phone or "",
                "installment_id": inst.id,
                "sequence": inst.sequence,
                "due_date": inst.due_date.isoformat(),
                "days_late": (today - inst.due_date).days,
                "amount": int(inst.amount or 0),
                "paid": int(inst.paid_amount or 0),
                "remaining": inst.remaining,
                "status": compute_installment_status(inst, today),
            }
            for inst in visible[:limit]
        ],
        "as_of": today.isoformat(),
        "note": "أقساط خطط التقسيط التي فات موعدها وبقي منها مبلغ، بما فيها المدفوعة جزئياً.",
        "currency": "IQD",
    }


def stagnant_products(args: dict, scope: dict) -> dict:
    days = int(args.get("min_days") or 30)
    rows = rs.stagnant_products(days)
    limit = int(args.get("limit") or 10)
    items = [{k: v for k, v in row.items() if scope.get("cost") or k != "value"} for row in rows[:limit]]
    for item in items:
        item["product_id"] = item.pop("id")
    result = {"min_days": days, "count": len(rows), "items": items,
              "note": "منتجات فعّالة بمخزون ولم تُبع منذ المدة المحددة (أو منذ إنشائها إن لم تُبع)."}
    if scope.get("cost"):
        result["stock_value"] = sum(int(row["value"] or 0) for row in rows)
        result["currency"] = "IQD"
    return result


def product_movements(args: dict, scope: dict) -> dict:
    from utils.ai_assistant_tools import tool_get_product_movements

    result = tool_get_product_movements({**args, "limit": int(args.get("limit") or 15)}, scope)
    if not scope.get("cost"):
        result["movements"] = [
            {k: v for k, v in row.items() if k not in {"cost_per_unit", "total_cost"}}
            for row in result.get("movements", [])
        ]
    return result
