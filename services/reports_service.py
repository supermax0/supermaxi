"""Central reporting engine for the reports dashboard and its ten detail reports.

Every figure is produced by exactly one function here, built on FINORA's own
accounting definitions (utils/accounting_calculations.py,
utils/financial_report_data.py, utils/treasury_calculations.py), so the
dashboard, the detail pages and the exports always agree:

* sales          = booked, non-cancelled, non-returned invoices (net of discount)
* COGS           = FIFO cost layers with the saved line cost as fallback
* expenses       = posted (cash_posted) expenses on expense_date
* net profit     = net sales − COGS − expenses − depreciation − savings fees
* available cash = treasury balances (cash + bank accounts) at the period end
* customer debt  = open remainder of booked direct-customer invoices
* inventory      = FIFO lot valuation of the current stock

Money is whole Iraqi dinars held as Python ints (no floats in sums).
Tenant isolation comes from the request's tenant database; branch isolation
from FINORA's ORM branch scope (utils/branch_orm_scope.py).
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterator

from flask import g
from sqlalchemy import and_, case, func, or_

from extensions import db
from models.expense import Expense
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.purchase import Purchase
from models.supplier import Supplier
from utils.accounting_calculations import (
    _order_item_cogs_expr,
    _order_item_layer_costs_subquery,
    calculate_supplier_debts,
)
from utils.date_periods import get_period_dates
from utils.expense_queries import posted_expense_filter
from utils.financial_report_data import (
    _comparison_period,
    _fixed_assets_financial_summary,
    _rotating_savings_financial_summary,
    _valid_invoice_payment_status_filter,
)
from utils.order_item_costs import exclude_delivery_fee_items
from utils.accounting_calculations import CANCELED_STATUSES, RETURN_STATUSES  # lists, as the financial report uses
from utils.order_stock_lock import stock_unlocked_filter
from utils.permission_checks import check_permission

PERIODS = ("today", "yesterday", "this_week", "this_month", "last_month", "this_year", "custom")
SECTIONS = (
    "sales",
    "profit",
    "expenses",
    "cash",
    "customers",
    "purchases",
    "inventory",
    "invoices",
    "employees",
    "cashflow",
    "equity",
)
# Existing FINORA RBAC permissions (routes/permissions.py) — roles keep working as configured.
SECTION_PERMISSIONS: dict[str, str] = {
    "sales": "view_reports",
    "invoices": "view_reports",
    "employees": "view_reports",
    "inventory": "view_reports",
    "customers": "view_reports",
    "purchases": "view_reports",
    "expenses": "view_expenses",
    "cash": "view_accounts",
    "profit": "view_financial",
    "cashflow": "view_financial",
    "equity": "view_financial",
}
EXPORT_PERMISSION = "view_reports"
PAGE_SIZE_MAX = 200

# Treasury movement reasons (utils/treasury_calculations.get_treasury_movements).
TRANSFER_REASONS = {"تحويل وارد", "تحويل صادر"}
SALES_COLLECTION_REASONS = {"بيع مباشر", "قبض من مندوب التوصيل", "تعديل تحصيل", "تعديل تحصيل مندوب"}
DEBT_COLLECTION_REASONS = {"سند قبض", "إلغاء سند قبض", "قبض من شركة نقل"}
SUPPLIER_PAYMENT_REASONS = {"دفع مورد", "شراء"}
EXPENSE_REASONS = {"مصروف"}
ASSET_REASONS = {"شراء أصل"}
OWNER_REASONS = {"سحب مالك"}


class ReportError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- filters ---


@dataclass(frozen=True)
class ReportFilters:
    period: str
    date_from: date
    date_to: date
    branch_id: int | None = None
    employee_id: int | None = None

    def previous(self) -> tuple[date, date]:
        prev_from, prev_to, _label = _comparison_period(self.period, self.date_from, self.date_to)
        return prev_from, prev_to

    def last_year(self) -> tuple[date, date]:
        def shift(d: date) -> date:
            try:
                return d.replace(year=d.year - 1)
            except ValueError:  # 29 Feb
                return d.replace(year=d.year - 1, day=28)

        return shift(self.date_from), shift(self.date_to)

    def as_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "branch_id": self.branch_id,
            "employee_id": self.employee_id,
        }


def _parse_date(raw: str | None, field: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError as exc:
        raise ReportError(f"تاريخ غير صحيح: {field}") from exc


def _parse_id(raw: Any, field: str) -> int | None:
    if raw in (None, "", "all", "0", 0):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ReportError(f"قيمة غير صحيحة: {field}") from exc
    if value <= 0:
        raise ReportError(f"قيمة غير صحيحة: {field}")
    return value


def parse_filters(args) -> ReportFilters:
    period = (args.get("period") or "this_month").strip()
    if period not in PERIODS:
        raise ReportError("الفترة غير معروفة")
    custom_from = _parse_date(args.get("date_from"), "date_from")
    custom_to = _parse_date(args.get("date_to"), "date_to")
    if period == "custom":
        if not custom_from or not custom_to:
            raise ReportError("حدد بداية ونهاية الفترة")
        if custom_from > custom_to:
            raise ReportError("بداية الفترة بعد نهايتها")
        if (custom_to - custom_from).days > 366 * 5:
            raise ReportError("الفترة طويلة جداً (أكثر من 5 سنوات)")
        date_from, date_to = custom_from, custom_to
    else:
        date_from, date_to = get_period_dates(period)
    return ReportFilters(
        period=period,
        date_from=date_from,
        date_to=date_to,
        branch_id=_parse_id(args.get("branch_id"), "branch_id"),
        employee_id=_parse_id(args.get("employee_id"), "employee_id"),
    )


def can_view(section: str) -> bool:
    return check_permission("view_reports") and check_permission(SECTION_PERMISSIONS[section])


def require_section(section: str) -> None:
    if section not in SECTIONS:
        raise ReportError("التقرير غير موجود", 404)
    if not can_view(section):
        raise ReportError("ليست لديك صلاحية عرض هذا التقرير", 403)


def _independent_branches() -> bool:
    from utils.branch_mode import independent_branches_enabled

    return bool(independent_branches_enabled())


@contextmanager
def branch_scope(filters: ReportFilters) -> Iterator[None]:
    """Run the report inside the requested branch, if the user may see it.

    FINORA's ORM scope (utils/branch_orm_scope.py) then filters every
    branch-owned query, including the reused accounting helpers. A user who
    cannot switch branches is always held to their own branch.
    """
    if filters.branch_id is None:
        yield
        return
    from models.branch import Branch
    from utils.branch_scope import allowed_branch_ids, is_general_admin

    allowed = set(allowed_branch_ids())
    if is_general_admin():
        allowed |= {int(b.id) for b in (getattr(g, "branches", []) or [])}
    if filters.branch_id not in allowed:
        raise ReportError("لا يمكنك عرض تقارير هذا الفرع", 403)
    branch = Branch.query.execution_options(skip_branch_scope=True).get(filters.branch_id)
    if branch is None:
        raise ReportError("الفرع غير موجود", 404)
    saved = (getattr(g, "branch", None), getattr(g, "view_all_branches", False))
    g.branch, g.view_all_branches = branch, False
    try:
        yield
    finally:
        g.branch, g.view_all_branches = saved


# ------------------------------------------------------------- primitives ---


def _pct(current: int | None, previous: int | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def _day(column):
    return func.date(column)


def _in_range(column, date_from: date, date_to: date):
    return and_(_day(column) >= date_from, _day(column) <= date_to)


def _sqlite() -> bool:
    return db.session.get_bind().dialect.name == "sqlite"


_PG_FORMATS = {"%Y": "YYYY", "%Y-%m": "YYYY-MM", "%Y-W%W": 'IYYY-"W"IW'}


def _fmt(column, pattern: str):
    """Date bucket label on SQLite (tenant files) and PostgreSQL alike."""
    if _sqlite():
        return func.strftime(pattern, column)
    return func.to_char(column, _PG_FORMATS[pattern])


def _invoice_scope(filters: ReportFilters):
    conds = []
    if filters.branch_id is not None:
        conds.append(Invoice.branch_id == filters.branch_id)
    if filters.employee_id is not None:
        conds.append(Invoice.employee_id == filters.employee_id)
    return conds


def booked_sale_conditions(filters: ReportFilters, date_from: date, date_to: date) -> list:
    """Same definition as the financial report's period invoices."""
    return [
        _in_range(Invoice.created_at, date_from, date_to),
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        stock_unlocked_filter(Invoice),
        _valid_invoice_payment_status_filter(),
        *_invoice_scope(filters),
    ]


def effective_paid_expr():
    """SQL twin of _effective_paid_amount (utils/financial_report_data.py)."""
    total = func.coalesce(Invoice.total, 0)
    paid = func.coalesce(Invoice.paid_amount, 0)
    dead = ("مرتجع", "ملغي", "راجع", "راجعة")
    return case(
        (Invoice.is_stock_locked.is_(True), 0),
        (Invoice.payment_status.in_(dead), 0),
        (Invoice.status.in_(dead), 0),
        (Invoice.payment_status == "مسدد", case((total > 0, total), else_=0)),
        (
            Invoice.payment_status == "جزئي",
            case((paid < 0, 0), (and_(total > 0, paid > total), total), else_=paid),
        ),
        (
            and_(Invoice.payment_status.is_(None), Invoice.status.in_(("مسدد", "تم التوصيل"))),
            case((total > 0, total), else_=0),
        ),
        else_=0,
    )


def sales_totals(filters: ReportFilters, date_from: date, date_to: date) -> dict[str, int]:
    row = (
        db.session.query(
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.total), 0),
            func.coalesce(func.sum(Invoice.discount_amount), 0),
            func.coalesce(func.sum(effective_paid_expr()), 0),
        )
        .filter(*booked_sale_conditions(filters, date_from, date_to))
        .one()
    )
    count, net, discounts, collected = (int(v or 0) for v in row)
    return {
        "invoices": count,
        "net": net,
        "discounts": discounts,
        "gross": net + discounts,
        "collected": collected,
        "credit": max(0, net - collected),
        "average": net // count if count else 0,
    }


def returns_total(filters: ReportFilters, date_from: date, date_to: date) -> dict[str, int]:
    returned = or_(Invoice.status.in_(RETURN_STATUSES), Invoice.payment_status.in_(RETURN_STATUSES))
    row = (
        db.session.query(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0))
        .filter(_in_range(Invoice.created_at, date_from, date_to), returned, *_invoice_scope(filters))
        .one()
    )
    return {"count": int(row[0] or 0), "amount": int(row[1] or 0)}


def _sale_items_query(filters: ReportFilters, date_from: date, date_to: date, columns):
    layer = _order_item_layer_costs_subquery()
    query = (
        db.session.query(*columns(layer))
        .select_from(OrderItem)
        .outerjoin(layer, layer.c.order_item_id == OrderItem.id)
        .join(Invoice, Invoice.id == OrderItem.invoice_id)
        .filter(*booked_sale_conditions(filters, date_from, date_to), exclude_delivery_fee_items(OrderItem))
    )
    return query


def cogs_total(filters: ReportFilters, date_from: date, date_to: date) -> int:
    value = _sale_items_query(
        filters, date_from, date_to, lambda layer: (func.coalesce(func.sum(_order_item_cogs_expr(layer)), 0),)
    ).scalar()
    return int(value or 0)


def _expense_conditions(filters: ReportFilters, date_from: date, date_to: date) -> list:
    conds = [posted_expense_filter(), Expense.expense_date.isnot(None), _in_range(Expense.expense_date, date_from, date_to)]
    if filters.branch_id is not None:
        conds.append(Expense.branch_id == filters.branch_id)
    if filters.employee_id is not None:
        conds.append(Expense.employee_id == filters.employee_id)
    return conds


def expenses_total(filters: ReportFilters, date_from: date, date_to: date) -> dict[str, int]:
    row = (
        db.session.query(func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
        .filter(*_expense_conditions(filters, date_from, date_to))
        .one()
    )
    return {"count": int(row[0] or 0), "amount": int(row[1] or 0)}


def other_operating(date_from: date, date_to: date) -> dict[str, int]:
    fa = _fixed_assets_financial_summary(date_from, date_to)
    rs = _rotating_savings_financial_summary(date_from, date_to)
    return {
        "depreciation": int(fa["fixed_assets_depreciation_period"] or 0),
        "savings_fees": int(rs["rotating_savings_fees"] or 0),
    }


def profit_and_loss(filters: ReportFilters, date_from: date, date_to: date) -> dict[str, int]:
    from utils.inventory_writeoff_totals import inventory_writeoff_loss
    inventory_losses=inventory_writeoff_loss(date_from,date_to,branch_id=filters.branch_id,employee_id=filters.employee_id)
    sales = sales_totals(filters, date_from, date_to)
    returns = returns_total(filters, date_from, date_to)
    cogs = cogs_total(filters, date_from, date_to)
    expenses = expenses_total(filters, date_from, date_to)["amount"]
    # Depreciation and savings fees are company-level: not attributable to one employee.
    other = (
        {"depreciation": 0, "savings_fees": 0}
        if filters.employee_id is not None
        else other_operating(date_from, date_to)
    )
    gross_profit = sales["net"] - cogs
    other_total = other["depreciation"] + other["savings_fees"] + inventory_losses
    net_profit = gross_profit - expenses - other_total
    gross_revenue = sales["net"] + sales["discounts"] + returns["amount"]
    return {
        "gross_revenue": gross_revenue,
        "returns": returns["amount"],
        "discounts": sales["discounts"],
        "net_revenue": sales["net"],
        "cogs": cogs,
        "gross_profit": gross_profit,
        "operating_expenses": expenses,
        "depreciation": other["depreciation"],
        "savings_fees": other["savings_fees"],
        "other_expenses": other_total,
        "inventory_losses": inventory_losses,
        "net_profit": net_profit,
    }


def _purchase_conditions(filters: ReportFilters, date_from: date, date_to: date) -> list:
    status = func.lower(func.coalesce(Purchase.status, "confirmed"))
    conds = [
        Purchase.deleted_at.is_(None),
        status.notin_(("cancelled", "canceled")),
        or_(status.notin_(("draft", "draft_editing")), Purchase.stock_applied.is_(True)),
        _in_range(func.coalesce(Purchase.purchase_date, Purchase.created_at), date_from, date_to),
    ]
    if filters.branch_id is not None:
        conds.append(Purchase.branch_id == filters.branch_id)
    if filters.employee_id is not None:
        conds.append(Purchase.created_by_employee_id == filters.employee_id)
    return conds


def _purchase_amount():
    return func.coalesce(Purchase.grand_total, Purchase.total, 0)


def purchases_total(filters: ReportFilters, date_from: date, date_to: date) -> dict[str, int]:
    row = (
        db.session.query(
            func.count(Purchase.id),
            func.coalesce(func.sum(_purchase_amount()), 0),
            func.coalesce(func.sum(Purchase.paid_total), 0),
            func.coalesce(func.sum(Purchase.quantity), 0),
        )
        .filter(*_purchase_conditions(filters, date_from, date_to))
        .one()
    )
    count, amount, paid, qty = (int(v or 0) for v in row)
    return {"count": count, "amount": amount, "paid": paid, "remaining": max(0, amount - paid), "quantity": qty}


# ---------------------------------------------------------------- treasury ---


def _treasury_accounts(filters: ReportFilters):
    from utils.treasury_calculations import list_treasury_accounts

    accounts = list_treasury_accounts()
    if filters.branch_id is not None:
        accounts = [a for a in accounts if int(a.branch_id or 0) == filters.branch_id]
    return accounts


def treasury_snapshot(filters: ReportFilters) -> dict[str, Any]:
    """Per-account opening/in/out/closing for the period, from the treasury ledger.

    Closing = current balance − movements after the period end, so it always
    reconciles with the balances FINORA shows today.
    """
    from utils.treasury_calculations import calculate_treasury_balance, get_treasury_movements

    today = date.today()
    accounts = []
    movements: list[dict[str, Any]] = []
    for account in _treasury_accounts(filters):
        current = int(calculate_treasury_balance(account.id))
        rows = get_treasury_movements(account.id, filters.date_from, max(today, filters.date_to))
        in_period = [m for m in rows if m["date"] <= filters.date_to]
        after = [m for m in rows if m["date"] > filters.date_to]

        def net(items):
            return sum(int(m["amount"] or 0) * (1 if m["type"] == "cash_in" else -1) for m in items)

        closing = current - net(after)
        opening = closing - net(in_period)
        cash_in = sum(int(m["amount"] or 0) for m in in_period if m["type"] == "cash_in")
        cash_out = sum(int(m["amount"] or 0) for m in in_period if m["type"] != "cash_in")
        transfers_in = sum(
            int(m["amount"] or 0) for m in in_period if m["type"] == "cash_in" and m.get("reason") in TRANSFER_REASONS
        )
        transfers_out = sum(
            int(m["amount"] or 0) for m in in_period if m["type"] != "cash_in" and m.get("reason") in TRANSFER_REASONS
        )
        last = max((m.get("datetime") or datetime.combine(m["date"], datetime.min.time()) for m in rows), default=None)
        accounts.append(
            {
                "id": int(account.id),
                "name": account.name,
                "type": account.account_type,
                "is_cash": bool(account.is_cash),
                "branch_id": account.branch_id,
                "opening": opening,
                "cash_in": cash_in,
                "cash_out": cash_out,
                "transfers_in": transfers_in,
                "transfers_out": transfers_out,
                "closing": closing,
                "current": current,
                "last_movement": last.isoformat(sep=" ", timespec="minutes") if last else None,
            }
        )
        for m in in_period:
            movements.append({**m, "account_id": int(account.id), "account_name": account.name})
    totals = {
        key: sum(a[key] for a in accounts)
        for key in ("opening", "cash_in", "cash_out", "transfers_in", "transfers_out", "closing", "current")
    }
    return {"accounts": accounts, "movements": movements, "totals": totals}


def _classify(movement: dict[str, Any]) -> str:
    reason = (movement.get("reason") or "").strip()
    if reason in TRANSFER_REASONS:
        return "transfer"
    if movement.get("type") == "cash_in":
        if reason in SALES_COLLECTION_REASONS:
            return "sales_collected"
        if reason in DEBT_COLLECTION_REASONS:
            return "debt_collected"
        if reason in ("إيداع", "قبض (صندوق)"):
            return "deposits"
        return "other_in"
    if reason in SUPPLIER_PAYMENT_REASONS:
        return "supplier_payments"
    if reason in EXPENSE_REASONS:
        return "expenses_paid"
    if reason in ASSET_REASONS:
        return "assets"
    if reason in OWNER_REASONS:
        return "owner_withdrawals"
    return "other_out"


INFLOW_LABELS = {
    "sales_collected": "المبيعات المقبوضة فعلياً",
    "debt_collected": "تحصيل الديون",
    "deposits": "إيداعات وتمويل",
    "other_in": "مقبوضات نقدية أخرى",
}
OUTFLOW_LABELS = {
    "supplier_payments": "دفعات الموردين والمشتريات",
    "expenses_paid": "المصاريف المدفوعة (تشمل الرواتب)",
    "assets": "شراء الأصول",
    "owner_withdrawals": "سحوبات المالك",
    "other_out": "مدفوعات أخرى",
}


def cash_flow(snapshot: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[str, int] = {}
    for m in snapshot["movements"]:
        key = _classify(m)
        buckets[key] = buckets.get(key, 0) + int(m["amount"] or 0)
    inflow = sum(buckets.get(k, 0) for k in INFLOW_LABELS)
    outflow = sum(buckets.get(k, 0) for k in OUTFLOW_LABELS)
    totals = snapshot["totals"]
    net_transfers = totals["transfers_in"] - totals["transfers_out"]
    return {
        "opening": totals["opening"],
        "inflow": inflow,
        "outflow": outflow,
        "net": inflow - outflow,
        "net_transfers": net_transfers,
        "closing": totals["closing"],
        "inflows": [{"key": k, "label": v, "amount": buckets.get(k, 0)} for k, v in INFLOW_LABELS.items()],
        "outflows": [{"key": k, "label": v, "amount": buckets.get(k, 0)} for k, v in OUTFLOW_LABELS.items()],
    }


# ---------------------------------------------------------- receivables ---


def receivable_conditions(filters: ReportFilters) -> list:
    """calculate_accounts_receivable(): direct customers, booked, not cancelled/returned."""
    from utils.accounting_calculations import _valid_revenue_payment_status_filter

    return [
        Invoice.shipping_company_id.is_(None),
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        _valid_revenue_payment_status_filter(),
        func.coalesce(Invoice.total, 0) - effective_paid_expr() > 0,
        *_invoice_scope(filters),
    ]


def receivables_total(filters: ReportFilters) -> dict[str, int]:
    remaining = func.coalesce(Invoice.total, 0) - effective_paid_expr()
    row = (
        db.session.query(func.count(Invoice.id), func.coalesce(func.sum(remaining), 0), func.count(func.distinct(Invoice.customer_id)))
        .filter(*receivable_conditions(filters))
        .one()
    )
    return {"invoices": int(row[0] or 0), "amount": int(row[1] or 0), "customers": int(row[2] or 0)}


AGING_BUCKETS = (
    ("today", "مستحق اليوم", 0, 0),
    ("d1_30", "1–30 يوم", 1, 30),
    ("d31_60", "31–60 يوم", 31, 60),
    ("d61_90", "61–90 يوم", 61, 90),
    ("d90p", "أكثر من 90 يوم", 91, None),
)


def aging_bucket(days: int) -> str:
    for key, _label, low, high in AGING_BUCKETS:
        if days >= low and (high is None or days <= high):
            return key
    return "today"


# -------------------------------------------------------------- inventory ---


def _product_meta(product) -> dict[str, Any]:
    try:
        parsed = json.loads(product.meta_json or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def product_category(product) -> str:
    meta = _product_meta(product)
    return str(meta.get("category") or product.catalog_category or "").strip() or "بدون تصنيف"


def inventory_valuation() -> dict[int, dict[str, int]]:
    """Per-product quantity/value; the sum equals calculate_inventory_value()."""
    from sqlalchemy import inspect

    from utils.accounting_calculations import calculate_inventory_value

    rows = db.session.query(Product.id, Product.quantity, Product.buy_price).all()
    result = {int(r.id): {"quantity": max(0, int(r.quantity or 0)), "value": 0} for r in rows}
    if not _independent_branches():
        # Shared catalogue: valuation groups copies across branches; keep the
        # company figure from FINORA and spread it by quantity × buy price.
        total = int(calculate_inventory_value())
        for r in rows:
            result[int(r.id)]["value"] = max(0, int(r.quantity or 0)) * max(0, int(r.buy_price or 0))
        result[0] = {"quantity": 0, "value": total - sum(v["value"] for v in result.values())}
        return result
    bind = db.session.get_bind()
    if "inventory_lot" not in inspect(bind).get_table_names():
        for r in rows:
            result[int(r.id)]["value"] = int(r.quantity or 0) * int(r.buy_price or 0)
        return result
    from models.inventory_lot import InventoryLot

    lots: dict[int, list] = {}
    for lot in (
        InventoryLot.query.filter(InventoryLot.remaining_quantity > 0)
        .order_by(InventoryLot.product_id.asc(), InventoryLot.created_at.asc(), InventoryLot.id.asc())
        .all()
    ):
        lots.setdefault(int(lot.product_id), []).append(lot)
    for r in rows:
        remaining = max(0, int(r.quantity or 0))
        value = 0
        for lot in lots.get(int(r.id), []):
            if remaining <= 0:
                break
            used = min(remaining, max(0, int(lot.remaining_quantity or 0)))
            value += used * int(lot.unit_cost or 0)
            remaining -= used
        if remaining > 0:
            value += remaining * int(r.buy_price or 0)
        result[int(r.id)]["value"] = value
    return result


def inventory_totals() -> dict[str, int]:
    from utils.accounting_calculations import calculate_inventory_value

    quantity = int(
        db.session.query(func.coalesce(func.sum(case((Product.quantity > 0, Product.quantity), else_=0)), 0))
        .filter(Product.active.is_(True))
        .scalar()
        or 0
    )
    low = Product.query.filter(
        Product.active.is_(True),
        Product.quantity <= func.coalesce(Product.low_stock_threshold, 2),
    ).count()
    return {"quantity": quantity, "value": int(calculate_inventory_value()), "low_stock": low}


def _last_sale_by_product() -> dict[int, date]:
    rows = (
        db.session.query(OrderItem.product_id, func.max(Invoice.created_at))
        .join(Invoice, Invoice.id == OrderItem.invoice_id)
        .filter(
            OrderItem.product_id.isnot(None),
            Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
            _valid_invoice_payment_status_filter(),
        )
        .group_by(OrderItem.product_id)
        .all()
    )
    out: dict[int, date] = {}
    for product_id, last in rows:
        if last is None:
            continue
        out[int(product_id)] = last.date() if isinstance(last, datetime) else date.fromisoformat(str(last)[:10])
    return out


def stagnant_products(min_days: int = 30) -> list[dict[str, Any]]:
    """Products in stock that were not sold for `min_days` (since creation if never sold)."""
    today = date.today()
    last_sale = _last_sale_by_product()
    values = inventory_valuation()
    rows = []
    for p in Product.query.filter(Product.active.is_(True), Product.quantity > 0).all():
        since = last_sale.get(int(p.id))
        reference = since or (p.created_at.date() if p.created_at else None)
        if reference is None:
            continue
        days = (today - reference).days
        if days < min_days:
            continue
        rows.append(
            {
                "id": int(p.id),
                "name": p.name,
                "sku": p.sku or "",
                "quantity": int(p.quantity or 0),
                "value": values.get(int(p.id), {}).get("value", 0),
                "days": days,
                "last_sale": since.isoformat() if since else None,
                "bucket": 180 if days >= 180 else 90 if days >= 90 else 60 if days >= 60 else 30,
            }
        )
    rows.sort(key=lambda r: (-r["days"], -r["value"]))
    return rows


def top_products(filters: ReportFilters, date_from: date, date_to: date, limit: int = 10) -> list[dict[str, Any]]:
    rows = (
        _sale_items_query(
            filters,
            date_from,
            date_to,
            lambda layer: (
                OrderItem.product_id,
                func.max(OrderItem.product_name),
                func.coalesce(func.sum(OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.total), 0),
                func.coalesce(func.sum(_order_item_cogs_expr(layer)), 0),
            ),
        )
        .filter(OrderItem.product_id.isnot(None))  # lines without a product (e.g. a device taken in) are not sellers
        .group_by(OrderItem.product_id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(limit)
        .all()
    )
    # The product's own current name — not the alphabetically largest line label («… — استبدال»).
    live = dict(
        Product.query.execution_options(skip_branch_scope=True)
        .filter(Product.id.in_([int(r[0]) for r in rows if r[0]] or [0]))
        .with_entities(Product.id, Product.name)
        .all()
    )
    return [
        {
            "product_id": int(pid) if pid else None,
            "name": (live.get(int(pid)) if pid else None) or name or "غير محدد",
            "quantity": int(qty or 0),
            "revenue": int(revenue or 0),
            "cogs": int(cogs or 0),
            "profit": int(revenue or 0) - int(cogs or 0),
        }
        for pid, name, qty, revenue, cogs in rows
    ]


# ------------------------------------------------------------ chart series ---


def _bucket_expr(column, grain: str):
    if grain == "year":
        return _fmt(column, "%Y")
    if grain == "month":
        return _fmt(column, "%Y-%m")
    return func.date(column)


def _bucket_keys(date_from: date, date_to: date, grain: str) -> list[str]:
    keys: list[str] = []
    if grain == "day":
        d = date_from
        while d <= date_to:
            keys.append(d.isoformat())
            d += timedelta(days=1)
    elif grain == "month":
        y, m = date_from.year, date_from.month
        while (y, m) <= (date_to.year, date_to.month):
            keys.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    else:
        keys = [f"{y:04d}" for y in range(date_from.year, date_to.year + 1)]
    return keys


def sales_series(filters: ReportFilters, grain: str) -> list[dict[str, Any]]:
    if grain not in ("day", "month", "year"):
        raise ReportError("تجميع غير معروف")
    if grain == "day" and (filters.date_to - filters.date_from).days > 400:
        grain = "month"
    bucket = _bucket_expr(Invoice.created_at, grain)
    rows = {
        str(key)[:10]: amount
        for key, amount in db.session.query(bucket, func.coalesce(func.sum(Invoice.total), 0))
        .filter(*booked_sale_conditions(filters, filters.date_from, filters.date_to))
        .group_by(bucket)
        .all()
    }
    return [{"key": key, "amount": int(rows.get(key, 0) or 0)} for key in _bucket_keys(filters.date_from, filters.date_to, grain)]


# --------------------------------------------------------------- dashboard ---


def _kpi(key: str, label: str, value: int | None, previous: int | None, good_when_up: bool, section: str) -> dict:
    change = _pct(value, previous)
    tone = "neutral"
    if change is not None and change != 0:
        tone = "good" if (change > 0) == good_when_up else "bad"
    return {
        "key": key,
        "label": label,
        "value": value,
        "previous": previous,
        "change_pct": change,
        "tone": tone,
        "section": section,
    }


def dashboard(filters: ReportFilters) -> dict[str, Any]:
    prev_from, prev_to = filters.previous()
    ly_from, ly_to = filters.last_year()
    allowed = {s: can_view(s) for s in SECTIONS}
    show_profit = allowed["profit"]
    show_cash = allowed["cash"]
    show_expenses = allowed["expenses"]

    sales = sales_totals(filters, filters.date_from, filters.date_to)
    sales_prev = sales_totals(filters, prev_from, prev_to)
    sales_ly = sales_totals(filters, ly_from, ly_to)
    pl = pl_prev = pl_ly = None
    if show_profit:
        pl = profit_and_loss(filters, filters.date_from, filters.date_to)
        pl_prev = profit_and_loss(filters, prev_from, prev_to)
        pl_ly = profit_and_loss(filters, ly_from, ly_to)
    exp = expenses_total(filters, filters.date_from, filters.date_to)
    exp_prev = expenses_total(filters, prev_from, prev_to)
    exp_ly = expenses_total(filters, ly_from, ly_to)
    pur = purchases_total(filters, filters.date_from, filters.date_to)
    pur_prev = purchases_total(filters, prev_from, prev_to)
    pur_ly = purchases_total(filters, ly_from, ly_to)

    snapshot = treasury_snapshot(filters) if (show_cash or show_profit) else None
    flow = cash_flow(snapshot) if snapshot else None
    receivables = receivables_total(filters)
    inventory = inventory_totals()
    returns = returns_total(filters, filters.date_from, filters.date_to)

    kpis = [
        _kpi("sales", "المبيعات", sales["net"], sales_prev["net"], True, "sales"),
        _kpi("net_profit", "صافي الربح", pl["net_profit"] if pl else None, pl_prev["net_profit"] if pl_prev else None, True, "profit")
        if show_profit
        else None,
        _kpi("expenses", "المصاريف", exp["amount"], exp_prev["amount"], False, "expenses") if show_expenses else None,
        _kpi("cash", "النقد المتوفر", snapshot["totals"]["closing"], snapshot["totals"]["opening"], True, "cash")
        if show_cash and snapshot
        else None,
        # Debt and stock value are point-in-time balances; FINORA keeps no past snapshot to compare.
        _kpi("receivables", "ديون العملاء", receivables["amount"], None, False, "customers"),
        _kpi("inventory", "قيمة المخزون", inventory["value"], None, True, "inventory"),
    ]

    comparison_metrics = [("sales", "المبيعات", sales["net"], sales_prev["net"], sales_ly["net"])]
    if pl:
        comparison_metrics.append(("net_profit", "صافي الربح", pl["net_profit"], pl_prev["net_profit"], pl_ly["net_profit"]))
    if show_expenses:
        comparison_metrics.append(("expenses", "المصاريف", exp["amount"], exp_prev["amount"], exp_ly["amount"]))
    comparison_metrics.append(("purchases", "المشتريات", pur["amount"], pur_prev["amount"], pur_ly["amount"]))

    top_employees = employees_table(filters, sort="sales", limit=4)
    top_debtors = debtors(filters, limit=3)
    top_suppliers = suppliers_by_purchases(filters, limit=3)
    best = top_products(filters, filters.date_from, filters.date_to, limit=1)
    stagnant = stagnant_products(30)
    counts = invoice_counts(filters)

    sections: dict[str, Any] = {
        "sales": {
            "gross": sales["gross"],
            "net": sales["net"],
            "invoices": sales["invoices"],
            "average": sales["average"],
            "change_pct": _pct(sales["net"], sales_prev["net"]),
        },
        "customers": {
            "credit_sales": sales["credit"],
            "collections": (flow["inflows"][0]["amount"] + flow["inflows"][1]["amount"]) if flow else None,
            "receivables": receivables["amount"],
            "top_debtors": top_debtors,
        },
        "purchases": {
            "total": pur["amount"],
            "supplier_payments": sum(r["amount"] for r in flow["outflows"] if r["key"] == "supplier_payments") if flow else None,
            "supplier_debts": int(calculate_supplier_debts()),
            "top_suppliers": top_suppliers,
        },
        "inventory": {
            "quantity": inventory["quantity"],
            "value": inventory["value"],
            "low_stock": inventory["low_stock"],
            "stagnant": len(stagnant),
            "best_seller": best[0] if best else None,
        },
        "invoices": counts,
        "employees": {"top": top_employees},
    }
    if pl:
        sections["profit"] = {
            "revenue": pl["net_revenue"],
            "cogs": pl["cogs"],
            "expenses": pl["operating_expenses"] + pl["other_expenses"],
            "net_profit": pl["net_profit"],
        }
    if show_expenses:
        top_cat = expense_breakdown(filters, "category")
        sections["expenses"] = {
            "total": exp["amount"],
            "count": exp["count"],
            "top_category": top_cat[0] if top_cat else None,
            "change_pct": _pct(exp["amount"], exp_prev["amount"]),
        }
    if show_cash and snapshot:
        t = snapshot["totals"]
        sections["cash"] = {
            "cash_in": t["cash_in"] - t["transfers_in"],
            "cash_out": t["cash_out"] - t["transfers_out"],
            "balance": t["closing"],
            "transfers": t["transfers_out"],
        }
    if show_profit and flow:
        sections["cashflow"] = {"inflow": flow["inflow"], "outflow": flow["outflow"], "net": flow["net"]}

    return {
        "filters": filters.as_dict(),
        "comparison_range": {
            "previous": [prev_from.isoformat(), prev_to.isoformat()],
            "last_year": [ly_from.isoformat(), ly_to.isoformat()],
        },
        "allowed": allowed,
        "employee_scoped": filters.employee_id is not None,
        "kpis": [k for k in kpis if k is not None],
        "comparison": [
            {"key": key, "label": label, "current": cur, "previous": prev, "last_year": ly}
            for key, label, cur, prev, ly in comparison_metrics
        ],
        "returns": returns,
        "sections": {k: v for k, v in sections.items() if allowed.get(k)},
    }


# ------------------------------------------------------------ section data ---


def _paginate(query, page: int, page_size: int):
    page = max(1, page)
    page_size = max(1, min(PAGE_SIZE_MAX, page_size))
    total = query.order_by(None).count()
    return query.limit(page_size).offset((page - 1) * page_size).all(), {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, -(-total // page_size)),
    }


def _employee_names(ids) -> dict[int, str]:
    from models.employee import Employee

    clean = {int(i) for i in ids if i}
    if not clean:
        return {}
    return {int(e.id): e.name for e in Employee.query.filter(Employee.id.in_(clean)).all()}


def _branch_names() -> dict[int, str]:
    from models.branch import Branch

    return {int(b.id): b.name for b in Branch.query.execution_options(skip_branch_scope=True).all()}


def _invoice_state(inv) -> str:
    if inv.status in CANCELED_STATUSES:
        return "ملغاة"
    if inv.status in RETURN_STATUSES or inv.payment_status in RETURN_STATUSES:
        return "مرتجعة"
    ps = (inv.payment_status or "").strip()
    if ps == "مسدد" or (not ps and inv.status in ("مسدد", "تم التوصيل")):
        return "مدفوعة"
    if ps == "جزئي":
        return "جزئية"
    return "آجلة"


def _invoice_row(inv, paid: int, branches: dict[int, str]) -> dict[str, Any]:
    total = int(inv.total or 0)
    discount = int(inv.discount_amount or 0)
    return {
        "id": int(inv.id),
        "date": inv.created_at.isoformat(sep=" ", timespec="minutes") if inv.created_at else None,
        "customer_id": inv.customer_id,
        "customer": inv.customer_name or "",
        "employee_id": inv.employee_id,
        "employee": inv.employee_name or "",
        "branch": branches.get(int(inv.branch_id or 0), ""),
        "gross": total + discount,
        "discount": discount,
        "total": total,
        "paid": paid,
        "remaining": max(0, total - paid),
        "sale_type": inv.sale_type or "",
        "status": inv.status or "",
        "state": _invoice_state(inv),
    }


def sales_breakdown(filters: ReportFilters, by: str, limit: int = 50) -> list[dict[str, Any]]:
    conds = booked_sale_conditions(filters, filters.date_from, filters.date_to)
    if by in ("day", "week", "month"):
        key = {
            "day": func.date(Invoice.created_at),
            "week": _fmt(Invoice.created_at, "%Y-W%W"),
            "month": _fmt(Invoice.created_at, "%Y-%m"),
        }[by]
        rows = (
            db.session.query(key, func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0))
            .filter(*conds)
            .group_by(key)
            .order_by(key)
            .all()
        )
        return [{"key": str(k), "label": str(k), "count": int(c or 0), "amount": int(a or 0)} for k, c, a in rows]
    if by in ("employee", "branch", "customer", "payment"):
        col = {
            "employee": Invoice.employee_id,
            "branch": Invoice.branch_id,
            "customer": Invoice.customer_id,
            "payment": Invoice.sale_type,
        }[by]
        label_col = {
            "employee": func.max(Invoice.employee_name),
            "branch": func.max(Invoice.branch_id),
            "customer": func.max(Invoice.customer_name),
            "payment": func.max(Invoice.sale_type),
        }[by]
        rows = (
            db.session.query(col, label_col, func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0))
            .filter(*conds)
            .group_by(col)
            .order_by(func.sum(Invoice.total).desc())
            .limit(limit)
            .all()
        )
        branches = _branch_names() if by == "branch" else {}
        payment_labels = {"cash": "نقدي", "credit": "آجل", "bank": "بنك", None: "غير محدد", "": "غير محدد"}

        def label(k, lbl):
            if by == "branch":
                return branches.get(int(k or 0), "بدون فرع")
            if by == "payment":
                return payment_labels.get(k, str(k))
            return lbl or "غير محدد"

        return [
            {"key": str(k) if k is not None else "", "label": label(k, lbl), "count": int(c or 0), "amount": int(a or 0)}
            for k, lbl, c, a in rows
        ]
    if by in ("product", "category"):
        rows = (
            _sale_items_query(
                filters,
                filters.date_from,
                filters.date_to,
                lambda layer: (
                    OrderItem.product_id,
                    func.max(OrderItem.product_name),
                    func.coalesce(func.sum(OrderItem.quantity), 0),
                    func.coalesce(func.sum(OrderItem.total), 0),
                ),
            )
            .group_by(OrderItem.product_id)
            .all()
        )
        if by == "product":
            rows = sorted(rows, key=lambda r: -int(r[3] or 0))[:limit]
            return [
                {"key": str(pid or ""), "label": name or "غير محدد", "count": int(q or 0), "amount": int(a or 0)}
                for pid, name, q, a in rows
            ]
        ids = [int(r[0]) for r in rows if r[0]]
        products = {int(p.id): p for p in Product.query.filter(Product.id.in_(ids or [-1])).all()}
        groups: dict[str, list[int]] = {}
        for pid, _name, q, a in rows:
            cat = product_category(products[int(pid)]) if pid and int(pid) in products else "بدون تصنيف"
            g_ = groups.setdefault(cat, [0, 0])
            g_[0] += int(q or 0)
            g_[1] += int(a or 0)
        return sorted(
            ({"key": k, "label": k, "count": v[0], "amount": v[1]} for k, v in groups.items()),
            key=lambda r: -r["amount"],
        )[:limit]
    raise ReportError("تجميع غير معروف")


def sales_report(filters: ReportFilters, page: int, page_size: int, by: str) -> dict[str, Any]:
    totals = sales_totals(filters, filters.date_from, filters.date_to)
    prev_from, prev_to = filters.previous()
    prev = sales_totals(filters, prev_from, prev_to)
    returns = returns_total(filters, filters.date_from, filters.date_to)
    items = _sale_items_query(
        filters, filters.date_from, filters.date_to, lambda layer: (func.coalesce(func.sum(OrderItem.quantity), 0),)
    ).scalar()
    show_cost = can_view("profit")
    cogs = cogs_total(filters, filters.date_from, filters.date_to) if show_cost else None
    paid = effective_paid_expr().label("paid")
    query = (
        db.session.query(Invoice, paid)
        .filter(*booked_sale_conditions(filters, filters.date_from, filters.date_to))
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
    )
    rows, pagination = _paginate(query, page, page_size)
    branches = _branch_names()
    return {
        "filters": filters.as_dict(),
        "metrics": {
            "gross": totals["gross"],
            "net": totals["net"],
            "invoices": totals["invoices"],
            "items": int(items or 0),
            "average": totals["average"],
            "discounts": totals["discounts"],
            "returns": returns["amount"],
            "returns_count": returns["count"],
            "cogs": cogs,
            "gross_profit": (totals["net"] - cogs) if cogs is not None else None,
            "change_pct": _pct(totals["net"], prev["net"]),
        },
        "breakdown": {"by": by, "rows": sales_breakdown(filters, by)},
        "rows": [_invoice_row(inv, int(p or 0), branches) for inv, p in rows],
        "pagination": pagination,
    }


def profit_report(filters: ReportFilters, grain: str = "month") -> dict[str, Any]:
    pl = profit_and_loss(filters, filters.date_from, filters.date_to)
    prev_from, prev_to = filters.previous()
    prev = profit_and_loss(filters, prev_from, prev_to)
    margins = {
        "gross_margin_pct": round(pl["gross_profit"] / pl["net_revenue"] * 100, 1) if pl["net_revenue"] else None,
        "net_margin_pct": round(pl["net_profit"] / pl["net_revenue"] * 100, 1) if pl["net_revenue"] else None,
    }
    if grain not in ("day", "month", "year"):
        grain = "month"
    if grain == "day" and (filters.date_to - filters.date_from).days > 92:
        grain = "month"
    trend = []
    for key in _bucket_keys(filters.date_from, filters.date_to, grain):
        if grain == "day":
            start = end = date.fromisoformat(key)
        elif grain == "month":
            y, m = int(key[:4]), int(key[5:7])
            start = date(y, m, 1)
            end = (date(y + (m == 12), 1 if m == 12 else m + 1, 1)) - timedelta(days=1)
        else:
            start, end = date(int(key), 1, 1), date(int(key), 12, 31)
        start, end = max(start, filters.date_from), min(end, filters.date_to)
        point = profit_and_loss(filters, start, end)
        trend.append({"key": key, "revenue": point["net_revenue"], "net_profit": point["net_profit"]})
    return {
        "filters": filters.as_dict(),
        "statement": pl,
        "previous": prev,
        "margins": margins,
        "change_pct": {k: _pct(pl[k], prev[k]) for k in ("net_revenue", "gross_profit", "net_profit")},
        "trend": trend,
    }


def expense_breakdown(filters: ReportFilters, by: str) -> list[dict[str, Any]]:
    from models.treasury_account import TreasuryAccount

    conds = _expense_conditions(filters, filters.date_from, filters.date_to)
    col = {
        "category": Expense.category,
        "employee": Expense.employee_id,
        "branch": Expense.branch_id,
        "account": Expense.treasury_account_id,
        "month": _fmt(Expense.expense_date, "%Y-%m"),
    }.get(by)
    if col is None:
        raise ReportError("تجميع غير معروف")
    rows = (
        db.session.query(col, func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
        .filter(*conds)
        .group_by(col)
        .order_by(func.sum(Expense.amount).desc())
        .all()
    )
    names: dict[int, str] = {}
    if by == "employee":
        names = _employee_names(k for k, _c, _a in rows)
    elif by == "branch":
        names = _branch_names()
    elif by == "account":
        names = {int(a.id): a.name for a in TreasuryAccount.query.all()}

    def label(k):
        if by in ("employee", "branch", "account"):
            return names.get(int(k or 0), "غير محدد")
        return str(k or "أخرى")

    return [{"key": str(k or ""), "label": label(k), "count": int(c or 0), "amount": int(a or 0)} for k, c, a in rows]


def expenses_report(filters: ReportFilters, page: int, page_size: int, by: str) -> dict[str, Any]:
    from models.treasury_account import TreasuryAccount

    totals = expenses_total(filters, filters.date_from, filters.date_to)
    prev_from, prev_to = filters.previous()
    prev = expenses_total(filters, prev_from, prev_to)
    query = Expense.query.filter(*_expense_conditions(filters, filters.date_from, filters.date_to)).order_by(
        Expense.expense_date.desc(), Expense.id.desc()
    )
    rows, pagination = _paginate(query, page, page_size)
    employees = _employee_names(e.employee_id for e in rows)
    branches = _branch_names()
    accounts = {int(a.id): a for a in TreasuryAccount.query.all()}
    return {
        "filters": filters.as_dict(),
        "metrics": {"total": totals["amount"], "count": totals["count"], "change_pct": _pct(totals["amount"], prev["amount"])},
        "breakdown": {"by": by, "rows": expense_breakdown(filters, by)},
        "rows": [
            {
                "id": int(e.id),
                "date": e.expense_date.isoformat() if e.expense_date else None,
                "category": e.category or "أخرى",
                "description": e.title or e.note or "",
                "amount": int(e.amount or 0),
                "employee": employees.get(int(e.employee_id or 0), ""),
                "branch": branches.get(int(e.branch_id or 0), ""),
                "account": accounts[int(e.treasury_account_id)].name if e.treasury_account_id in accounts else "",
                "payment_method": (
                    "بنك"
                    if e.treasury_account_id in accounts and not accounts[int(e.treasury_account_id)].is_cash
                    else "نقدي"
                ),
            }
            for e in rows
        ],
        "pagination": pagination,
    }


def cash_report(filters: ReportFilters, page: int, page_size: int) -> dict[str, Any]:
    from models.treasury_transfer import TreasuryTransfer

    snapshot = treasury_snapshot(filters)
    movements = sorted(snapshot["movements"], key=lambda m: (m.get("datetime") or datetime.combine(m["date"], datetime.min.time())), reverse=True)
    page = max(1, page)
    page_size = max(1, min(PAGE_SIZE_MAX, page_size))
    chunk = movements[(page - 1) * page_size : page * page_size]
    account_ids = [a["id"] for a in snapshot["accounts"]]
    names = {a["id"]: a["name"] for a in snapshot["accounts"]}
    transfers = (
        TreasuryTransfer.query.filter(
            _in_range(TreasuryTransfer.created_at, filters.date_from, filters.date_to),
            or_(TreasuryTransfer.from_account_id.in_(account_ids or [-1]), TreasuryTransfer.to_account_id.in_(account_ids or [-1])),
        )
        .order_by(TreasuryTransfer.created_at.desc())
        .limit(200)
        .all()
    )
    t = snapshot["totals"]
    return {
        "filters": filters.as_dict(),
        "metrics": {
            "cash_in": t["cash_in"] - t["transfers_in"],
            "cash_out": t["cash_out"] - t["transfers_out"],
            "opening": t["opening"],
            "closing": t["closing"],
            "transfers": t["transfers_out"],
        },
        "accounts": snapshot["accounts"],
        "rows": [
            {
                "date": (m.get("datetime") or m["date"]).isoformat(sep=" ", timespec="minutes")
                if isinstance(m.get("datetime"), datetime)
                else m["date"].isoformat(),
                "account": m["account_name"],
                "type": "داخل" if m["type"] == "cash_in" else "خارج",
                "reason": m.get("reason") or "",
                "reference": f"{m.get('reference_type') or ''} #{m.get('reference_id') or ''}".strip(),
                "invoice_id": m.get("invoice_id"),
                "description": m.get("description") or "",
                "cash_in": int(m["amount"] or 0) if m["type"] == "cash_in" else 0,
                "cash_out": int(m["amount"] or 0) if m["type"] != "cash_in" else 0,
                "balance": m.get("balance_after"),
                "is_transfer": (m.get("reason") or "") in TRANSFER_REASONS,
            }
            for m in chunk
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": len(movements),
            "total_pages": max(1, -(-len(movements) // page_size)),
        },
        "transfers": [
            {
                "id": int(tr.id),
                "date": tr.created_at.isoformat(sep=" ", timespec="minutes") if tr.created_at else None,
                "from": names.get(int(tr.from_account_id or 0), f"#{tr.from_account_id}"),
                "to": names.get(int(tr.to_account_id or 0), f"#{tr.to_account_id}"),
                "amount": int(tr.amount or 0),
                "note": tr.note or "",
            }
            for tr in transfers
        ],
    }


def debtors(filters: ReportFilters, limit: int = 10) -> list[dict[str, Any]]:
    remaining = func.coalesce(Invoice.total, 0) - effective_paid_expr()
    rows = (
        db.session.query(Invoice.customer_id, func.max(Invoice.customer_name), func.sum(remaining).label("debt"))
        .filter(*receivable_conditions(filters))
        .group_by(Invoice.customer_id)
        .order_by(func.sum(remaining).desc())
        .limit(limit)
        .all()
    )
    return [{"customer_id": cid, "name": name or "غير محدد", "amount": int(debt or 0)} for cid, name, debt in rows]


def customers_report(filters: ReportFilters, page: int, page_size: int, tab: str) -> dict[str, Any]:
    from models.customer import Customer

    sales = sales_totals(filters, filters.date_from, filters.date_to)
    receivables = receivables_total(filters)
    snapshot = treasury_snapshot(filters) if can_view("cash") or can_view("profit") else None
    collections = None
    if snapshot:
        collections = sum(
            int(m["amount"] or 0) for m in snapshot["movements"] if _classify(m) in ("sales_collected", "debt_collected")
        )
    today = date.today()
    remaining = (func.coalesce(Invoice.total, 0) - effective_paid_expr()).label("remaining")
    open_rows = db.session.query(Invoice, remaining).filter(*receivable_conditions(filters)).all()
    aging = {key: 0 for key, *_ in AGING_BUCKETS}
    for inv, rem in open_rows:
        days = (today - inv.created_at.date()).days if inv.created_at else 0
        aging[aging_bucket(days)] += int(rem or 0)
    metrics = {
        "credit_sales": sales["credit"],
        "collections": collections,
        "receivables": receivables["amount"],
        "due_today": aging["today"],
        "overdue": receivables["amount"] - aging["today"],
        "not_due": 0,
        "open_invoices": receivables["invoices"],
    }
    if tab == "debts":
        query = (
            db.session.query(Invoice, remaining)
            .filter(*receivable_conditions(filters))
            .order_by(Invoice.created_at.asc(), Invoice.id.asc())
        )
        rows, pagination = _paginate(query, page, page_size)
        phones = {
            int(c.id): c.phone or ""
            for c in Customer.query.filter(Customer.id.in_([inv.customer_id for inv, _ in rows if inv.customer_id] or [-1])).all()
        }
        data = []
        for inv, rem in rows:
            due = inv.created_at.date() if inv.created_at else today
            days = (today - due).days
            data.append(
                {
                    "invoice_id": int(inv.id),
                    "customer_id": inv.customer_id,
                    "customer": inv.customer_name or "",
                    "phone": phones.get(int(inv.customer_id or 0), ""),
                    "total": int(inv.total or 0),
                    "paid": int(inv.total or 0) - int(rem or 0),
                    "remaining": int(rem or 0),
                    "due_date": due.isoformat(),
                    "days_overdue": days,
                    "bucket": aging_bucket(days),
                }
            )
    else:
        paid = effective_paid_expr()
        booked = and_(
            Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
            stock_unlocked_filter(Invoice),
            _valid_invoice_payment_status_filter(),
        )
        scope = _invoice_scope(filters)
        query = (
            db.session.query(
                Invoice.customer_id,
                func.max(Invoice.customer_name),
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.total), 0),
                func.coalesce(func.sum(paid), 0),
                func.coalesce(
                    func.sum(case((Invoice.shipping_company_id.is_(None), func.coalesce(Invoice.total, 0) - paid), else_=0)),
                    0,
                ),
                func.max(Invoice.created_at),
            )
            .filter(booked, _in_range(Invoice.created_at, filters.date_from, filters.date_to), *scope)
            .group_by(Invoice.customer_id)
            .order_by(func.sum(Invoice.total).desc())
        )
        rows, pagination = _paginate(query, page, page_size)
        phones = {
            int(c.id): c.phone or ""
            for c in Customer.query.filter(Customer.id.in_([r[0] for r in rows if r[0]] or [-1])).all()
        }
        data = [
            {
                "customer_id": cid,
                "name": name or "غير محدد",
                "phone": phones.get(int(cid or 0), ""),
                "orders": int(count or 0),
                "purchases": int(total or 0),
                "paid": int(paid_sum or 0),
                "debt": max(0, int(debt or 0)),
                "last_purchase": str(last)[:16] if last else None,
            }
            for cid, name, count, total, paid_sum, debt, last in rows
        ]
    return {
        "filters": filters.as_dict(),
        "tab": tab,
        "metrics": metrics,
        "aging": [{"key": key, "label": label, "amount": aging[key]} for key, label, *_ in AGING_BUCKETS],
        "rows": data,
        "pagination": pagination,
    }


def suppliers_by_purchases(filters: ReportFilters, limit: int = 10) -> list[dict[str, Any]]:
    rows = (
        db.session.query(Purchase.supplier_id, func.count(Purchase.id), func.coalesce(func.sum(_purchase_amount()), 0))
        .filter(*_purchase_conditions(filters, filters.date_from, filters.date_to))
        .group_by(Purchase.supplier_id)
        .order_by(func.sum(_purchase_amount()).desc())
        .limit(limit)
        .all()
    )
    names = {int(s.id): s.name for s in Supplier.query.filter(Supplier.id.in_([r[0] for r in rows if r[0]] or [-1])).all()}
    return [
        {"supplier_id": sid, "name": names.get(int(sid or 0), "غير محدد"), "count": int(c or 0), "amount": int(a or 0)}
        for sid, c, a in rows
    ]


def purchases_report(filters: ReportFilters, page: int, page_size: int, tab: str) -> dict[str, Any]:
    from utils.supplier_accounting_repair import expected_supplier_totals

    totals = purchases_total(filters, filters.date_from, filters.date_to)
    supplier_debts = int(calculate_supplier_debts())
    metrics = {**totals, "supplier_debts": supplier_debts}
    if tab == "suppliers":
        query = Supplier.query.order_by(Supplier.name.asc())
        suppliers, pagination = _paginate(query, page, page_size)
        ids = [int(s.id) for s in suppliers]
        period = {
            int(sid): (int(c or 0), int(a or 0), last)
            for sid, c, a, last in db.session.query(
                Purchase.supplier_id,
                func.count(Purchase.id),
                func.coalesce(func.sum(_purchase_amount()), 0),
                func.max(func.coalesce(Purchase.purchase_date, Purchase.created_at)),
            )
            .filter(*_purchase_conditions(filters, filters.date_from, filters.date_to), Purchase.supplier_id.in_(ids or [-1]))
            .group_by(Purchase.supplier_id)
            .all()
        }
        rows = []
        for s in suppliers:
            debt, paid = expected_supplier_totals(int(s.id))
            count, amount, last = period.get(int(s.id), (0, 0, None))
            rows.append(
                {
                    "supplier_id": int(s.id),
                    "name": s.name,
                    "phone": s.phone or "",
                    "purchases": amount,
                    "invoices": count,
                    "total_paid": int(paid or 0),
                    "balance": max(0, int(debt or 0) - int(paid or 0)),
                    "last_purchase": str(last)[:10] if last else None,
                }
            )
    else:
        query = Purchase.query.filter(*_purchase_conditions(filters, filters.date_from, filters.date_to))
        if tab == "debts":
            query = query.filter(func.coalesce(Purchase.remaining_total, 0) > 0)
        query = query.order_by(func.coalesce(Purchase.purchase_date, Purchase.created_at).desc(), Purchase.id.desc())
        purchases, pagination = _paginate(query, page, page_size)
        names = {
            int(s.id): s.name
            for s in Supplier.query.filter(Supplier.id.in_([p.supplier_id for p in purchases if p.supplier_id] or [-1])).all()
        }
        rows = [
            {
                "purchase_id": int(p.id),
                "invoice_no": p.invoice_no or p.reference_no or f"#{p.id}",
                "date": str(p.purchase_date or p.created_at)[:10] if (p.purchase_date or p.created_at) else None,
                "supplier_id": p.supplier_id,
                "supplier": names.get(int(p.supplier_id or 0), ""),
                "amount": int(p.grand_total or p.total or 0),
                "paid": int(p.paid_total or 0),
                "remaining": int(p.remaining_total or 0),
                "status": p.status or "confirmed",
            }
            for p in purchases
        ]
    return {
        "filters": filters.as_dict(),
        "tab": tab,
        "metrics": metrics,
        "by_supplier": suppliers_by_purchases(filters, 10),
        "rows": rows,
        "pagination": pagination,
    }


def inventory_report(filters: ReportFilters, page: int, page_size: int, tab: str, search: str = "") -> dict[str, Any]:
    from models.stock_movement import StockMovement

    totals = inventory_totals()
    values = inventory_valuation()
    stagnant = stagnant_products(30)
    metrics = {
        **totals,
        "stagnant": len(stagnant),
        "stagnant_value": sum(r["value"] for r in stagnant),
        "stagnant_buckets": {
            str(days): {
                "count": sum(1 for r in stagnant if r["days"] >= days),
                "value": sum(r["value"] for r in stagnant if r["days"] >= days),
            }
            for days in (30, 60, 90, 180)
        },
    }
    if tab == "stagnant":
        start = (max(1, page) - 1) * page_size
        rows = stagnant[start : start + page_size]
        pagination = {"page": max(1, page), "page_size": page_size, "total": len(stagnant), "total_pages": max(1, -(-len(stagnant) // page_size))}
    elif tab == "movements":
        query = StockMovement.query.filter(_in_range(StockMovement.created_at, filters.date_from, filters.date_to)).order_by(
            StockMovement.created_at.desc(), StockMovement.id.desc()
        )
        moves, pagination = _paginate(query, page, page_size)
        names = {int(p.id): p.name for p in Product.query.filter(Product.id.in_([m.product_id for m in moves] or [-1])).all()}
        rows = [
            {
                "date": m.created_at.isoformat(sep=" ", timespec="minutes") if m.created_at else None,
                "product_id": m.product_id,
                "product": names.get(int(m.product_id or 0), ""),
                "type": m.movement_type,
                "direction": m.direction,
                "quantity": int(m.quantity or 0),
                "value": int(m.total_cost or 0),
                "source": f"{m.source_type or ''} #{m.source_id or ''}".strip(),
            }
            for m in moves
        ]
        type_totals = (
            db.session.query(StockMovement.movement_type, func.coalesce(func.sum(StockMovement.quantity), 0))
            .filter(_in_range(StockMovement.created_at, filters.date_from, filters.date_to))
            .group_by(StockMovement.movement_type)
            .all()
        )
        metrics["movement_types"] = [{"type": t or "", "quantity": int(q or 0)} for t, q in type_totals]
    else:
        query = Product.query.filter(Product.active.is_(True))
        if search.strip():
            like = f"%{search.strip()}%"
            query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like)))
        if tab == "low":
            query = query.filter(Product.quantity <= func.coalesce(Product.low_stock_threshold, 2))
            query = query.order_by(Product.quantity.asc(), Product.name.asc())
        else:
            query = query.order_by(Product.name.asc())
        products, pagination = _paginate(query, page, page_size)
        rows = []
        for p in products:
            qty = int(p.quantity or 0)
            value = values.get(int(p.id), {}).get("value", 0)
            threshold = int(p.low_stock_threshold if p.low_stock_threshold is not None else 2)
            rows.append(
                {
                    "product_id": int(p.id),
                    "name": p.name,
                    "sku": p.sku or "",
                    "category": product_category(p),
                    "quantity": qty,
                    "available": max(0, qty),
                    "average_cost": value // qty if qty > 0 else int(p.buy_price or 0),
                    "value": value,
                    "sale_price": int(p.sale_price or 0),
                    "threshold": threshold,
                    "shortage": max(0, threshold - qty),
                }
            )
    return {
        "filters": filters.as_dict(),
        "tab": tab,
        "metrics": metrics,
        "best_sellers": top_products(filters, filters.date_from, filters.date_to, 5),
        "rows": rows,
        "pagination": pagination,
    }


def invoice_counts(filters: ReportFilters) -> dict[str, int]:
    rows = (
        db.session.query(Invoice.status, Invoice.payment_status, func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0))
        .filter(_in_range(Invoice.created_at, filters.date_from, filters.date_to), *_invoice_scope(filters))
        .group_by(Invoice.status, Invoice.payment_status)
        .all()
    )
    counts = {"paid": 0, "partial": 0, "credit": 0, "cancelled": 0, "returned": 0, "total": 0, "amount": 0}
    for status, ps, count, amount in rows:
        state = _invoice_state(type("I", (), {"status": status, "payment_status": ps})())
        key = {"مدفوعة": "paid", "جزئية": "partial", "آجلة": "credit", "ملغاة": "cancelled", "مرتجعة": "returned"}[state]
        counts[key] += int(count or 0)
        counts["total"] += int(count or 0)
        if key not in ("cancelled", "returned"):
            counts["amount"] += int(amount or 0)
    return counts


def invoices_report(filters: ReportFilters, page: int, page_size: int, state: str) -> dict[str, Any]:
    counts = invoice_counts(filters)
    paid = effective_paid_expr().label("paid")
    conds = [_in_range(Invoice.created_at, filters.date_from, filters.date_to), *_invoice_scope(filters)]
    live = Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES)
    not_returned = or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(RETURN_STATUSES))
    state_filters = {
        "all": [],
        "paid": [live, not_returned, or_(Invoice.payment_status == "مسدد", and_(Invoice.payment_status.is_(None), Invoice.status.in_(("مسدد", "تم التوصيل"))))],
        "partial": [live, Invoice.payment_status == "جزئي"],
        "credit": [live, not_returned, or_(Invoice.payment_status.notin_(("مسدد", "جزئي")), and_(Invoice.payment_status.is_(None), Invoice.status.notin_(("مسدد", "تم التوصيل"))))],
        "cancelled": [Invoice.status.in_(CANCELED_STATUSES)],
        "returned": [or_(Invoice.status.in_(RETURN_STATUSES), Invoice.payment_status.in_(RETURN_STATUSES))],
    }
    if state not in state_filters:
        raise ReportError("حالة غير معروفة")
    query = db.session.query(Invoice, paid).filter(*conds, *state_filters[state]).order_by(Invoice.created_at.desc(), Invoice.id.desc())
    rows, pagination = _paginate(query, page, page_size)
    outstanding = (
        db.session.query(func.coalesce(func.sum(func.coalesce(Invoice.total, 0) - effective_paid_expr()), 0))
        .filter(*conds, live, not_returned)
        .scalar()
    )
    branches = _branch_names()
    return {
        "filters": filters.as_dict(),
        "state": state,
        "metrics": {**counts, "outstanding": int(outstanding or 0)},
        "rows": [_invoice_row(inv, int(p or 0), branches) for inv, p in rows],
        "pagination": pagination,
    }


def employees_table(filters: ReportFilters, sort: str = "sales", limit: int | None = None) -> list[dict[str, Any]]:
    conds = booked_sale_conditions(filters, filters.date_from, filters.date_to)
    rows = (
        db.session.query(
            Invoice.employee_id,
            func.max(Invoice.employee_name),
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.total), 0),
            func.coalesce(func.sum(Invoice.discount_amount), 0),
            func.coalesce(func.sum(effective_paid_expr()), 0),
        )
        .filter(*conds)
        .group_by(Invoice.employee_id)
        .all()
    )
    show_profit = can_view("profit")
    cogs: dict[int, int] = {}
    if show_profit:
        cogs = {
            int(eid or 0): int(v or 0)
            for eid, v in _sale_items_query(
                filters,
                filters.date_from,
                filters.date_to,
                lambda layer: (Invoice.employee_id, func.coalesce(func.sum(_order_item_cogs_expr(layer)), 0)),
            )
            .group_by(Invoice.employee_id)
            .all()
        }
    returned = or_(Invoice.status.in_(RETURN_STATUSES), Invoice.payment_status.in_(RETURN_STATUSES))
    returns = {
        int(eid or 0): int(a or 0)
        for eid, a in db.session.query(Invoice.employee_id, func.coalesce(func.sum(Invoice.total), 0))
        .filter(_in_range(Invoice.created_at, filters.date_from, filters.date_to), returned, *_invoice_scope(filters))
        .group_by(Invoice.employee_id)
        .all()
    }
    commissions: dict[int, int] = {}
    try:
        from models.employee_commission_line import EmployeeCommissionLine

        commissions = {
            int(eid or 0): int(a or 0)
            for eid, a in db.session.query(EmployeeCommissionLine.employee_id, func.coalesce(func.sum(EmployeeCommissionLine.amount), 0))
            .filter(_in_range(EmployeeCommissionLine.accrued_at, filters.date_from, filters.date_to))
            .group_by(EmployeeCommissionLine.employee_id)
            .all()
        }
    except Exception:  # commissions module not installed for this tenant
        db.session.rollback()
    names = _employee_names(r[0] for r in rows)
    data = []
    for eid, name, count, total, discounts, collected in rows:
        key = int(eid or 0)
        data.append(
            {
                "employee_id": eid,
                "name": names.get(key) or name or "غير محدد",
                "orders": int(count or 0),
                "sales": int(total or 0),
                "average": int(total or 0) // int(count) if count else 0,
                "collections": int(collected or 0),
                "discounts": int(discounts or 0),
                "returns": returns.get(key, 0),
                "profit": int(total or 0) - cogs.get(key, 0) if show_profit else None,
                "commission": commissions.get(key, 0),
            }
        )
    order_key = {"sales": "sales", "collections": "collections", "profit": "profit", "orders": "orders"}.get(sort, "sales")
    if order_key == "profit" and not show_profit:
        order_key = "sales"
    data.sort(key=lambda r: -(r[order_key] or 0))
    return data[:limit] if limit else data


def employees_report(filters: ReportFilters, sort: str) -> dict[str, Any]:
    rows = employees_table(filters, sort=sort)
    return {
        "filters": filters.as_dict(),
        "sort": sort,
        "show_profit": can_view("profit"),
        "rows": rows,
        "totals": {
            key: sum((r[key] or 0) for r in rows)
            for key in ("orders", "sales", "collections", "discounts", "returns", "commission")
        },
    }


def cashflow_report(filters: ReportFilters, grain: str) -> dict[str, Any]:
    snapshot = treasury_snapshot(filters)
    flow = cash_flow(snapshot)
    if grain not in ("day", "week", "month"):
        grain = "day"
    series: dict[str, list[int]] = {}
    for m in snapshot["movements"]:
        if _classify(m) == "transfer":
            continue
        d: date = m["date"]
        key = d.isoformat() if grain == "day" else (f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}" if grain == "week" else d.strftime("%Y-%m"))
        bucket = series.setdefault(key, [0, 0])
        bucket[0 if m["type"] == "cash_in" else 1] += int(m["amount"] or 0)
    return {
        "filters": filters.as_dict(),
        "flow": flow,
        "grain": grain,
        "series": [{"key": k, "inflow": v[0], "outflow": v[1], "net": v[0] - v[1]} for k, v in sorted(series.items())],
    }


def equity_report(filters: ReportFilters) -> dict[str, Any]:
    """«المركز المالي وأين ذهبت الأرباح».

    1. What the company owns now: assets − liabilities = owner's equity (current balances, the same figures as
       the company financial report).
    2. Where the period's profit went: from net profit to the actual change in cash, line by line. It is an
       identity — the lines always add up to the treasury's own change — so nothing is estimated.
    Employee filters do not apply (a balance sheet belongs to the company / branch, not to one employee).
    """
    from utils.financial_report_data import get_financial_report_data

    company = ReportFilters(period=filters.period, date_from=filters.date_from, date_to=filters.date_to,
                            branch_id=filters.branch_id)
    fin = get_financial_report_data("custom", company.date_from, company.date_to)
    assets = [
        {"key": "cash", "label": "النقد في الصناديق", "amount": int(fin["cash_balance"])},
        {"key": "banks", "label": "أرصدة البنوك والمحافظ", "amount": int(fin["bank_balance_total"])},
        {"key": "inventory", "label": "البضاعة في المخازن (بسعر الكلفة)", "amount": int(fin["inventory_value"])},
        {"key": "customers", "label": "ديون على الزبائن", "amount": int(fin["customer_receivables"])},
        {"key": "shipping", "label": "مستحقات على شركات النقل", "amount": int(fin["shipping_receivables"])},
        {"key": "fixed_assets", "label": "الأصول الثابتة (بعد الاستهلاك)", "amount": int(fin["fixed_assets_book_value"])},
        {"key": "savings", "label": "جمعيات مدفوعة لم تُستلم", "amount": int(fin["rotating_savings_asset"])},
    ]
    liabilities = [
        {"key": "suppliers", "label": "ديون للموردين", "amount": int(fin["supplier_debts"])},
        {"key": "savings", "label": "جمعيات مستلمة لم تُسدَّد", "amount": int(fin["rotating_savings_liability"])},
    ]
    total_assets = sum(a["amount"] for a in assets)
    total_liabilities = sum(row["amount"] for row in liabilities)
    equity = total_assets - total_liabilities

    pl = profit_and_loss(company, company.date_from, company.date_to)
    flow = cash_flow(treasury_snapshot(company))
    cash = {row["key"]: row["amount"] for row in flow["inflows"] + flow["outflows"]}
    bought = purchases_total(company, company.date_from, company.date_to)["amount"]
    # Each line = its effect on cash compared with the profit figure (+ adds cash, − takes it).
    lines = [
        ("non_cash", "مصاريف حُسبت من الربح بلا خروج نقد (استهلاك، تلف، رسوم)",
         pl["depreciation"] + pl["inventory_losses"] + pl["savings_fees"]),
        ("credit_sales", "بيع آجل لم يُقبض بعد — بقي عند الزبائن", -(pl["net_revenue"] - cash.get("sales_collected", 0))),
        ("old_debts", "تحصيل ديون قديمة من الزبائن", cash.get("debt_collected", 0)),
        ("stock_build", "بضاعة اشتريتها ولم تُبع بعد — تحولت إلى مخزون", -(bought - pl["cogs"])),
        ("supplier_credit", "مشتريات لم تُدفع بعد — غطّاها الموردون", bought - cash.get("supplier_payments", 0)),
        ("expenses_timing", "فرق توقيت المصاريف (مسجلة ≠ مدفوعة)",
         pl["operating_expenses"] - cash.get("expenses_paid", 0)),
        ("assets", "شراء أصول ثابتة", -cash.get("assets", 0)),
        ("owner", "سحوبات المالك", -cash.get("owner_withdrawals", 0)),
        ("capital", "إيداعات وتمويل (رأس مال أو قروض)", cash.get("deposits", 0)),
        ("other", "مقبوضات ومدفوعات أخرى", cash.get("other_in", 0) - cash.get("other_out", 0)),
    ]
    bridge = [{"key": k, "label": label, "amount": int(v)} for k, label, v in lines]
    explained = pl["net_profit"] + sum(b["amount"] for b in bridge)
    actual = int(flow["net"])
    # The lines above are an identity; any gap comes from data the cash ledger and the sales books record
    # differently (e.g. refunds of returns, movements without a reason) — shown, never hidden.
    gap = actual - explained
    if gap:
        bridge.append({"key": "unmatched", "label": "فرق بين دفتر الخزينة والمبيعات (مرتجعات مستردة نقداً وغيرها)",
                       "amount": int(gap)})
    profit = int(pl["net_profit"])
    went_to = {
        "customers": max(0, -bridge[1]["amount"]),
        "stock": max(0, -bridge[3]["amount"]),
        "assets": cash.get("assets", 0),
        "owner": cash.get("owner_withdrawals", 0),
    }
    return {
        "filters": company.as_dict(),
        "position": {
            "assets": assets,
            "liabilities": liabilities,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "equity": equity,
            "balanced": total_assets == total_liabilities + equity,
            "note": "حقوق الملكية = كل ما تملكه الشركة − كل ما عليها. أرصدة حالية، وليست ميزان مراجعة محاسبي مستقل.",
        },
        "profit": {
            "net_revenue": pl["net_revenue"],
            "cogs": pl["cogs"],
            "gross_profit": pl["gross_profit"],
            "operating_expenses": pl["operating_expenses"],
            "other_expenses": pl["other_expenses"],
            "net_profit": profit,
        },
        "bridge": bridge,
        "cash": {"opening": int(flow["opening"]), "net_change": actual, "closing": int(flow["closing"])},
        "went_to": went_to,
        "summary": _equity_summary(profit, went_to, actual),
    }


def _equity_summary(profit: int, went_to: dict[str, int], cash_change: int) -> list[str]:
    """Plain sentences for the owner: where the profit is now."""
    def money(v: int) -> str:
        return f"{abs(int(v)):,} د.ع"

    lines = [f"{'ربحت' if profit >= 0 else 'خسرت'} {money(profit)} في هذه الفترة (بعد الكلفة والمصاريف)."]
    labels = {"stock": "تحول إلى بضاعة في المخازن", "customers": "بقي ديناً عند الزبائن",
              "owner": "سحبه المالك", "assets": "صُرف على أصول ثابتة"}
    for key, label in labels.items():
        if went_to.get(key):
            lines.append(f"{money(went_to[key])} {label}.")
    lines.append(f"النقد في الصناديق والبنوك {'زاد' if cash_change >= 0 else 'نقص'} بمقدار {money(cash_change)}.")
    return lines


def section_report(section: str, filters: ReportFilters, args) -> dict[str, Any]:
    page = int(args.get("page") or 1)
    page_size = int(args.get("page_size") or 50)
    if section == "sales":
        return sales_report(filters, page, page_size, args.get("by") or "day")
    if section == "profit":
        return profit_report(filters, args.get("grain") or "month")
    if section == "expenses":
        return expenses_report(filters, page, page_size, args.get("by") or "category")
    if section == "cash":
        return cash_report(filters, page, page_size)
    if section == "customers":
        return customers_report(filters, page, page_size, args.get("tab") or "customers")
    if section == "purchases":
        return purchases_report(filters, page, page_size, args.get("tab") or "purchases")
    if section == "inventory":
        return inventory_report(filters, page, page_size, args.get("tab") or "stock", args.get("search") or "")
    if section == "invoices":
        return invoices_report(filters, page, page_size, args.get("state") or "all")
    if section == "employees":
        return employees_report(filters, args.get("sort") or "sales")
    if section == "cashflow":
        return cashflow_report(filters, args.get("grain") or "day")
    if section == "equity":
        return equity_report(filters)
    raise ReportError("التقرير غير موجود", 404)
