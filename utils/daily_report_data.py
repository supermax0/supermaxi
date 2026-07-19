from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_

from extensions import db
from models.daily_audit import DailyAudit
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from utils.order_item_costs import exclude_delivery_fee_items
from utils.invoice_schema_guard import ensure_invoice_schema
from utils.order_item_schema_guard import ensure_order_item_schema
from utils.purchase_schema_guard import ensure_purchase_schema
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
from utils.order_stock_lock import stock_unlocked_filter
from utils.treasury_calculations import (
    calculate_treasury_balance,
    get_treasury_movements,
    list_treasury_accounts,
)
from utils.treasury_helpers import get_default_cash_account


def parse_report_date(raw_value: str | None) -> date:
    if not raw_value:
        return date.today()
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.today()


def _int(value) -> int:
    return int(value or 0)


def _movement_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return date.today()
    return date.today()


def _movement_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d")
            except ValueError:
                return datetime.combine(date.today(), time.min)
    return datetime.combine(date.today(), time.min)


def _movement_minute(movement: dict) -> int:
    movement_dt = _movement_datetime(movement.get("datetime") or movement.get("date"))
    return movement_dt.hour * 60 + movement_dt.minute


def _movement_time_label(movement: dict) -> str:
    return _movement_datetime(movement.get("datetime") or movement.get("date")).strftime("%H:%M")


def _summarize_by_reason(movements: list[dict]) -> list[dict]:
    totals: dict[str, int] = defaultdict(int)
    for movement in movements:
        reason = movement.get("reason") or "غير محدد"
        totals[reason] += _int(movement.get("amount"))
    return [
        {"reason": reason, "amount": amount}
        for reason, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def _cash_summary_for_day(report_date: date) -> dict:
    cash_account = get_default_cash_account()
    all_movements = get_treasury_movements(cash_account.id)
    all_movements.sort(key=lambda row: (_movement_datetime(row.get("datetime") or row.get("date")), row.get("reference_type") or "", row.get("reference_id") or 0))

    opening_balance = 0
    day_movements = []
    for movement in all_movements:
        movement_day = _movement_date(movement.get("date"))
        if movement_day < report_date:
            opening_balance = _int(movement.get("balance_after"))
        elif movement_day == report_date:
            day_movements.append(movement)

    cash_in_movements = [row for row in day_movements if row.get("type") == "cash_in"]
    cash_out_movements = [row for row in day_movements if row.get("type") == "cash_out"]
    cash_in = sum(_int(row.get("amount")) for row in cash_in_movements)
    cash_out = sum(_int(row.get("amount")) for row in cash_out_movements)
    closing_balance = opening_balance + cash_in - cash_out
    if day_movements:
        closing_balance = _int(day_movements[-1].get("balance_after"))

    treasury_accounts = []
    for account in list_treasury_accounts():
        treasury_accounts.append(
            {
                "id": account.id,
                "name": account.name,
                "type": account.account_type,
                "balance": calculate_treasury_balance(account.id),
                "is_default": account.is_default,
            }
        )

    return {
        "cash_account": cash_account,
        "opening_balance": opening_balance,
        "cash_in": cash_in,
        "cash_out": cash_out,
        "net_cash": cash_in - cash_out,
        "closing_balance": closing_balance,
        "movement_count": len(day_movements),
        "cash_in_movements": cash_in_movements,
        "cash_out_movements": cash_out_movements,
        "cash_in_by_reason": _summarize_by_reason(cash_in_movements),
        "cash_out_by_reason": _summarize_by_reason(cash_out_movements),
        "timeline_movements": [
            {
                "minute": _movement_minute(row),
                "time": _movement_time_label(row),
                "type": row.get("type"),
                "reason": row.get("reason") or "",
                "amount": _int(row.get("amount")),
                "balance_after": _int(row.get("balance_after")),
                "reference_type": row.get("reference_type") or "",
                "reference_id": row.get("reference_id"),
                "description": row.get("description") or "",
            }
            for row in day_movements
        ],
        "treasury_accounts": treasury_accounts,
    }


def _products_out_for_day(report_date: date) -> list[dict]:
    start = datetime.combine(report_date, time.min)
    end = start + timedelta(days=1)
    blocked_statuses = list(CANCELED_STATUSES | RETURN_STATUSES)

    rows = (
        db.session.query(
            OrderItem.product_id.label("product_id"),
            func.coalesce(Product.name, OrderItem.product_name).label("product_name"),
            func.coalesce(OrderItem.variant_color, "").label("variant_color"),
            func.sum(OrderItem.quantity).label("quantity"),
            func.sum(OrderItem.total).label("total_sales"),
            func.sum(OrderItem.cost * OrderItem.quantity).label("total_cost"),
            func.count(func.distinct(OrderItem.invoice_id)).label("invoice_count"),
        )
        .join(Invoice, Invoice.id == OrderItem.invoice_id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .filter(
            Invoice.created_at >= start,
            Invoice.created_at < end,
            or_(Invoice.status.is_(None), Invoice.status.notin_(blocked_statuses)),
            or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(blocked_statuses)),
            stock_unlocked_filter(Invoice),
            exclude_delivery_fee_items(OrderItem),
        )
        .group_by(OrderItem.product_id, func.coalesce(Product.name, OrderItem.product_name), func.coalesce(OrderItem.variant_color, ""))
        .order_by(func.sum(OrderItem.quantity).desc())
        .all()
    )

    return [
        {
            "product_id": row.product_id,
            "product_name": row.product_name or "منتج",
            "variant_color": row.variant_color or "",
            "quantity": _int(row.quantity),
            "total_sales": _int(row.total_sales),
            "total_cost": _int(row.total_cost),
            "invoice_count": _int(row.invoice_count),
        }
        for row in rows
    ]


def _products_in_for_day(report_date: date) -> list[dict]:
    status_filter = or_(
        Purchase.status.is_(None),
        ~Purchase.status.in_(["draft", "cancelled", "canceled", "ملغي"]),
    )
    item_total = func.coalesce(PurchaseItem.line_total, PurchaseItem.final_unit_cost * PurchaseItem.quantity, 0)

    rows = (
        db.session.query(
            PurchaseItem.product_id.label("product_id"),
            Product.name.label("product_name"),
            func.coalesce(PurchaseItem.variant_color, "").label("variant_color"),
            func.sum(PurchaseItem.quantity).label("quantity"),
            func.sum(item_total).label("total_cost"),
            func.count(func.distinct(PurchaseItem.purchase_id)).label("purchase_count"),
        )
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .outerjoin(Product, Product.id == PurchaseItem.product_id)
        .filter(Purchase.purchase_date == report_date, status_filter)
        .group_by(PurchaseItem.product_id, Product.name, func.coalesce(PurchaseItem.variant_color, ""))
        .all()
    )

    grouped: dict[tuple[int | None, str, str], dict] = {}
    for row in rows:
        key = (row.product_id, row.product_name or "منتج", row.variant_color or "")
        grouped[key] = {
            "product_id": row.product_id,
            "product_name": row.product_name or "منتج",
            "variant_color": row.variant_color or "",
            "quantity": _int(row.quantity),
            "total_cost": _int(row.total_cost),
            "purchase_count": _int(row.purchase_count),
        }

    item_purchase_ids = db.session.query(PurchaseItem.purchase_id).distinct()
    legacy_rows = (
        db.session.query(
            Purchase.product_id.label("product_id"),
            Product.name.label("product_name"),
            func.sum(Purchase.quantity).label("quantity"),
            func.sum(Purchase.total).label("total_cost"),
            func.count(Purchase.id).label("purchase_count"),
        )
        .outerjoin(Product, Product.id == Purchase.product_id)
        .filter(Purchase.purchase_date == report_date, status_filter, ~Purchase.id.in_(item_purchase_ids))
        .group_by(Purchase.product_id, Product.name)
        .all()
    )
    for row in legacy_rows:
        key = (row.product_id, row.product_name or "منتج", "")
        existing = grouped.setdefault(
            key,
            {
                "product_id": row.product_id,
                "product_name": row.product_name or "منتج",
                "variant_color": "",
                "quantity": 0,
                "total_cost": 0,
                "purchase_count": 0,
            },
        )
        existing["quantity"] += _int(row.quantity)
        existing["total_cost"] += _int(row.total_cost)
        existing["purchase_count"] += _int(row.purchase_count)

    return sorted(grouped.values(), key=lambda row: row["quantity"], reverse=True)


def build_daily_report_data(report_date: date) -> dict:
    ensure_invoice_schema()
    ensure_order_item_schema()
    ensure_purchase_schema()
    audit = DailyAudit.query.filter_by(report_date=report_date).first()
    cash = _cash_summary_for_day(report_date)
    products_out = _products_out_for_day(report_date)
    products_in = _products_in_for_day(report_date)

    return {
        "report_date": report_date,
        "prev_date": report_date - timedelta(days=1),
        "next_date": report_date + timedelta(days=1),
        "generated_at": datetime.utcnow(),
        "audit": audit,
        "audit_status": audit.status if audit else "pending",
        "audit_status_label": audit.status_label if audit else "بانتظار التدقيق",
        "cash": cash,
        "products_out": products_out,
        "products_in": products_in,
        "products_out_total_qty": sum(row["quantity"] for row in products_out),
        "products_in_total_qty": sum(row["quantity"] for row in products_in),
        "products_out_total_sales": sum(row["total_sales"] for row in products_out),
        "products_in_total_cost": sum(row["total_cost"] for row in products_in),
    }


def list_daily_audit_archive(limit: int = 90):
    return (
        DailyAudit.query.order_by(DailyAudit.report_date.desc(), DailyAudit.id.desc())
        .limit(int(limit))
        .all()
    )
