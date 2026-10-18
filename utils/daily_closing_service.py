"""Read-only aggregation and immutable snapshot logic for daily closing."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import session as flask_session
from sqlalchemy import func, or_

from extensions import db
from models.branch import Branch, BranchStock
from models.daily_closing import DailyClosingAuditLog, DailyClosingSnapshotHistory, DailySession
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from models.expense import Expense
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.order_item import OrderItem
from models.product import Product
from models.stock_movement import StockMovement
from models.shipping_report import ShippingReport
from models.treasury_account import TreasuryAccount
from utils.cash_calculations import _effective_paid_amount, get_cash_movements
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES


OUT_TYPES = {
    "sale": "sales",
    "order_sale": "sales",
    "delivery_out": "delivery_out",
    "transfer_out": "transfer_out",
    "damage": "damage",
    "internal_use": "internal_use",
    "purchase_return": "purchase_return",
    "purchase_reverse": "purchase_return",
    "order_deduct": "sales",
    "order_branch_reserve": "sales",
    "shipping_branch_reserve": "sales",
    "transfer_send": "transfer_out",
    "beauty_consume": "internal_use",
    "adjustment_out": "other",
    "unclassified_adjustment": "other",
}
IN_TYPES = {
    "purchase": "purchase",
    "purchase_receive": "purchase",
    "sale_return": "sale_return",
    "return": "sale_return",
    "transfer_in": "transfer_in",
    "delivery_return": "delivery_return",
    "order_restore": "sale_return",
    "order_restore_correction": "sale_return",
    "order_branch_release": "sale_return",
    "shipping_branch_release": "sale_return",
    "transfer_receive": "transfer_in",
    "purchase_reverse": "adjustment",
    "beauty_restore": "adjustment",
    "adjustment_in": "adjustment",
    "trade_in": "adjustment",
    "unclassified_adjustment": "adjustment",
}

IRAQ_TZ = ZoneInfo("Asia/Baghdad")


def company_key() -> str:
    return str(flask_session.get("tenant_slug") or "default")[:80]


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.min


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _window(daily: DailySession, end_at: datetime | None = None) -> tuple[datetime, datetime]:
    # Daily reports represent the full Iraqi business date. A manager may open
    # the closing screen late in the day, but sales and movements recorded
    # earlier that same day must still be included.
    local_start = datetime.combine(daily.business_date, time.min, tzinfo=IRAQ_TZ)
    local_end = local_start + timedelta(days=1)
    start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    day_end = local_end.astimezone(timezone.utc).replace(tzinfo=None)
    requested_end = daily.closed_at or end_at or datetime.utcnow()
    return start, min(requested_end, day_end)


def _money(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _stock_category(movement: StockMovement, courier_order_ids: set[int] | None = None) -> str:
    raw = (movement.movement_type or "").strip().lower()
    source_type = (movement.source_type or "").strip().lower()
    source_id = int(movement.source_id or 0)
    is_courier_order = source_id in (courier_order_ids or set()) and source_type in {
        "invoice", "order", "order_item",
    }
    if movement.direction == "out":
        if is_courier_order and raw in {"sale", "order_sale", "order_deduct", "order_branch_reserve", "shipping_branch_reserve"}:
            return "delivery_out"
        return OUT_TYPES.get(raw, "other")
    if is_courier_order and raw in {"sale_return", "return", "order_restore", "order_restore_correction", "order_branch_release", "shipping_branch_release"}:
        return "delivery_return"
    return IN_TYPES.get(raw, "adjustment")


def _agent_reports(daily: DailySession, start: datetime, end: datetime) -> list[ShippingReport]:
    query = ShippingReport.query.execution_options(skip_branch_scope=True).filter(
        ShippingReport.report_number.like("AGT-%"),
        ShippingReport.created_at >= start,
        ShippingReport.created_at <= end,
    )
    reports = query.order_by(ShippingReport.created_at, ShippingReport.id).all()
    if daily.branch_id is None:
        return reports

    scoped = []
    for report in reports:
        try:
            rows = json.loads(report.orders_data or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            rows = []
        order_ids = {
            int(row.get("id") or row.get("order_id"))
            for row in rows if isinstance(row, dict) and (row.get("id") or row.get("order_id"))
        }
        if not order_ids:
            continue
        has_branch_order = Invoice.query.execution_options(skip_branch_scope=True).filter(
            Invoice.id.in_(order_ids), Invoice.branch_id == daily.branch_id
        ).first()
        if has_branch_order:
            scoped.append(report)
    return scoped


def _agent_report_order_ids(daily: DailySession, start: datetime, end: datetime) -> set[int]:
    result: set[int] = set()
    for report in _agent_reports(daily, start, end):
        try:
            rows = json.loads(report.orders_data or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                result.add(int(row.get("id") or row.get("order_id")))
            except (TypeError, ValueError):
                continue
    return result


def _stock_data(daily: DailySession, start: datetime, end: datetime) -> dict:
    query = StockMovement.query.execution_options(skip_branch_scope=True).filter(
        StockMovement.created_at >= start, StockMovement.created_at <= end
    )
    if daily.branch_id is not None:
        query = query.filter(StockMovement.branch_id == daily.branch_id)
    rows = query.order_by(StockMovement.created_at, StockMovement.id).all()
    grouped: dict[int, dict] = {}
    courier_order_ids = _agent_report_order_ids(daily, start, end)
    details = []
    for movement in rows:
        product = movement.product
        pid = int(movement.product_id)
        item = grouped.setdefault(
            pid,
            {
                "product_id": pid,
                "product_name": product.name if product else f"مادة #{pid}",
                "sales": 0,
                "delivery_out": 0,
                "transfer_out": 0,
                "damage": 0,
                "internal_use": 0,
                "purchase_return": 0,
                "other_out": 0,
                "purchase": 0,
                "sale_return": 0,
                "transfer_in": 0,
                "delivery_return": 0,
                "adjustment": 0,
            },
        )
        category = _stock_category(movement, courier_order_ids)
        key = "other_out" if category == "other" else category
        item[key] = item.get(key, 0) + int(movement.quantity or 0)
        details.append(
            {
                "id": movement.id,
                "time": movement.created_at.isoformat(),
                "product_id": pid,
                "product_name": item["product_name"],
                "movement_type": movement.movement_type,
                "direction": movement.direction,
                "category": key,
                "quantity": int(movement.quantity or 0),
                "reference_type": movement.source_type,
                "reference_id": movement.source_id,
                "reference_line_id": movement.source_line_id,
            }
        )
    outgoing, incoming = [], []
    for item in grouped.values():
        item["total_out"] = sum(item[k] for k in ("sales", "delivery_out", "transfer_out", "damage", "internal_use", "purchase_return", "other_out"))
        item["total_in"] = sum(item[k] for k in ("purchase", "sale_return", "transfer_in", "delivery_return", "adjustment"))
        if item["total_out"]:
            outgoing.append(item)
        if item["total_in"]:
            incoming.append(item)
    return {
        "outgoing": sorted(outgoing, key=lambda row: (-row["total_out"], row["product_name"])),
        "incoming": sorted(incoming, key=lambda row: (-row["total_in"], row["product_name"])),
        "details": details,
    }


def _sales_data(daily: DailySession, start: datetime, end: datetime) -> dict:
    invoice_query = Invoice.query.execution_options(skip_branch_scope=True).filter(
        Invoice.created_at >= start, Invoice.created_at <= end
    )
    if daily.branch_id is not None:
        invoice_query = invoice_query.filter(Invoice.branch_id == daily.branch_id)
    invoices = invoice_query.order_by(Invoice.created_at, Invoice.id).all()
    active = [row for row in invoices if row.status not in tuple(CANCELED_STATUSES) + tuple(RETURN_STATUSES)]
    returned = [row for row in invoices if row.status in tuple(RETURN_STATUSES)]
    invoice_ids = [row.id for row in active]
    today_invoice_ids = {row.id for row in invoices}
    returned_ids = {row.id for row in returned}
    # Collections are selected by payment time, not invoice creation time.
    # This is essential for debt receipts paid today against an older invoice.
    payment_query = InvoicePaymentLedger.query.execution_options(skip_branch_scope=True).join(
        Invoice, Invoice.id == InvoicePaymentLedger.invoice_id
    ).filter(
        InvoicePaymentLedger.recorded_at >= start,
        InvoicePaymentLedger.recorded_at <= end,
    )
    if daily.branch_id is not None:
        payment_query = payment_query.filter(Invoice.branch_id == daily.branch_id)
    payments = payment_query.all()
    account_ids = {row.treasury_account_id for row in payments if row.treasury_account_id}
    accounts = {row.id: row for row in TreasuryAccount.query.filter(TreasuryAccount.id.in_(account_ids)).all()} if account_ids else {}
    paid_by = defaultdict(int)
    debt_paid_by = defaultdict(int)
    refund_by = defaultdict(int)
    for payment in payments:
        amount = _money(payment.amount_delta)
        method = (payment.payment_method or "").lower()
        account = accounts.get(payment.treasury_account_id)
        if account and account.account_type == "bank":
            bucket = "bank"
        elif method in {"card", "electronic", "بطاقة", "الكتروني", "إلكتروني"}:
            bucket = "electronic"
        else:
            bucket = "cash"
        if payment.invoice_id in invoice_ids:
            paid_by[bucket] += amount
        elif payment.invoice_id not in today_invoice_ids and amount > 0:
            debt_paid_by[bucket] += amount
        if payment.invoice_id in returned_ids and amount < 0:
            refund_by[bucket] += abs(amount)

    # Older sales screens may update ``paid_amount``/``payment_status`` without
    # creating a split-payment ledger row. The treasury module treats those as
    # default-cash receipts, so the daily report must use the same fallback.
    ledger_invoice_ids = set()
    if invoice_ids:
        ledger_invoice_ids = {
            int(row[0])
            for row in (
                db.session.query(InvoicePaymentLedger.invoice_id)
                .execution_options(skip_branch_scope=True)
                .filter(InvoicePaymentLedger.invoice_id.in_(invoice_ids))
                .distinct()
                .all()
            )
        }
    for invoice in active:
        if int(invoice.id) in ledger_invoice_ids:
            continue
        fallback_paid = _money(_effective_paid_amount(invoice))
        if fallback_paid > 0:
            paid_by["cash"] += min(fallback_paid, _money(invoice.total))

    gross_sales = sum(_money(row.total) for row in active)
    current_receipts = sum(paid_by.values())
    credit_sales = max(0, gross_sales - max(0, current_receipts))
    items = []
    if invoice_ids:
        items = OrderItem.query.filter(OrderItem.invoice_id.in_(invoice_ids)).all()
    cogs = sum(_money(row.cost) * int(row.quantity or 0) for row in items)
    discounts = sum(_money(row.discount_amount) for row in active)
    return_value = sum(_money(row.total) for row in returned)
    invoice_rows = [
        {
            "id": row.id,
            "time": row.created_at.isoformat() if row.created_at else "",
            "customer": row.customer_name,
            "status": row.status,
            "payment_status": row.payment_status,
            "total": _money(row.total),
            "paid": _money(row.paid_amount),
        }
        for row in invoices
    ]
    current_receipts = sum(max(0, value) for value in paid_by.values())
    debt_receipts = sum(max(0, value) for value in debt_paid_by.values())
    return {
        "orders_count": len(active),
        "total_sales": gross_sales,
        "cash_sales": max(0, paid_by["cash"]),
        "credit_sales": credit_sales,
        "electronic_sales": max(0, paid_by["electronic"]),
        "bank_sales": max(0, paid_by["bank"]),
        "current_receipts": current_receipts,
        "debt_receipts": debt_receipts,
        "received_today": current_receipts + debt_receipts,
        "unpaid_orders_count": sum(1 for row in active if _money(row.paid_amount) <= 0 and (row.payment_status or "") not in {"مسدد", "جزئي"}),
        "debt_receipts_by_method": dict(debt_paid_by),
        "return_refunds": dict(refund_by),
        "discounts": discounts,
        "returns": return_value,
        "cogs": cogs,
        "gross_profit": gross_sales - return_value - cogs,
        "invoices": invoice_rows,
    }


def _expense_data(daily: DailySession, start: datetime, end: datetime) -> dict:
    query = Expense.query.execution_options(skip_branch_scope=True).filter(
        Expense.created_at >= start, Expense.created_at <= end
    )
    if daily.branch_id is not None:
        query = query.filter(Expense.branch_id == daily.branch_id)
    rows = query.order_by(Expense.created_at, Expense.id).all()
    account_ids = {row.treasury_account_id for row in rows if row.treasury_account_id}
    accounts = {row.id: row for row in TreasuryAccount.query.filter(TreasuryAccount.id.in_(account_ids)).all()} if account_ids else {}
    employee_ids = {row.employee_id for row in rows if row.employee_id}
    employees = {
        row.id: row.name
        for row in Employee.query.execution_options(skip_branch_scope=True).filter(Employee.id.in_(employee_ids)).all()
    } if employee_ids else {}
    rendered = []
    cash_total = 0
    by_method = defaultdict(int)
    for row in rows:
        account = accounts.get(row.treasury_account_id)
        method = "صندوق" if bool(row.cash_posted) and (not account or account.account_type == "cash") else ("حساب بنكي" if account and account.account_type == "bank" else "أخرى")
        if method == "صندوق":
            cash_total += _money(row.amount)
        by_method[method] += _money(row.amount)
        rendered.append({
            "id": row.id,
            "time": row.created_at.isoformat() if row.created_at else "",
            "type": row.category or "مصروف",
            "description": row.title,
            "employee_id": row.employee_id,
            "employee_name": employees.get(row.employee_id) or "—",
            "payment_method": method,
            "amount": _money(row.amount),
        })
    return {
        "rows": rendered,
        "total": sum(row["amount"] for row in rendered),
        "cash_total": cash_total,
        "bank_total": by_method["حساب بنكي"],
        "other_total": by_method["أخرى"],
        "by_method": dict(by_method),
    }


def cash_opening_balance(branch_id: int, business_date: date) -> int:
    """Return the real cash-ledger balance immediately before the Iraqi day starts."""
    local_start = datetime.combine(business_date, time.min, tzinfo=IRAQ_TZ)
    start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    account_query = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter(
        TreasuryAccount.account_type == "cash", TreasuryAccount.is_active.is_(True),
        TreasuryAccount.branch_id == branch_id,
    )
    accounts = account_query.all()
    if accounts:
        from utils.treasury_calculations import get_treasury_movements

        movements = []
        for account in accounts:
            movements.extend(get_treasury_movements(account.id))
    else:
        movements = get_cash_movements()
    balance = 0
    for movement in movements:
        when = _dt(movement.get("datetime") or movement.get("date"))
        if when >= start:
            continue
        from utils.cash_movement_values import movement_amount
        amount = movement_amount(movement)
        balance += amount if movement.get("type") == "cash_in" else -amount
    return balance


def _cash_data(daily: DailySession, start: datetime, end: datetime) -> dict:
    ledger = []
    balance = _money(daily.opening_cash)
    account_query = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter(
        TreasuryAccount.account_type == "cash", TreasuryAccount.is_active.is_(True)
    )
    if daily.branch_id is not None:
        account_query = account_query.filter(TreasuryAccount.branch_id == daily.branch_id)
    cash_accounts = account_query.all()
    if cash_accounts:
        from utils.treasury_calculations import get_treasury_movements

        source_movements = []
        for account in cash_accounts:
            source_movements.extend(get_treasury_movements(account.id))
    else:
        # Legacy single-cash tenants have no branch-bound account yet.
        source_movements = get_cash_movements()
    for movement in source_movements:
        when = _dt(movement.get("datetime") or movement.get("date"))
        if when < start or when > end:
            continue
        from utils.cash_movement_values import movement_amount
        incoming = movement_amount(movement) if movement.get("type") == "cash_in" else 0
        outgoing = movement_amount(movement) if movement.get("type") == "cash_out" else 0
        balance += incoming - outgoing
        ledger.append({
            "time": when.isoformat(),
            "type": movement.get("reason") or movement.get("type_ar") or "حركة صندوق",
            "description": movement.get("description") or "",
            "reference_type": movement.get("reference_type") or "",
            "reference_id": movement.get("invoice_id") or movement.get("reference_id"),
            "in": incoming,
            "out": outgoing,
            "balance": balance,
        })
    for adj in sorted(getattr(daily, "adjustments", []) or [], key=lambda row: (row.created_at, row.id)):
        incoming = _money(adj.amount) if adj.direction == "in" else 0
        outgoing = _money(adj.amount) if adj.direction == "out" else 0
        balance += incoming - outgoing
        ledger.append({
            "time": adj.created_at.isoformat(), "type": adj.category,
            "description": adj.description, "reference_type": "daily_cash_adjustment",
            "reference_id": adj.reference, "in": incoming, "out": outgoing, "balance": balance,
        })
    ledger.sort(key=lambda row: row["time"])
    running = _money(daily.opening_cash)
    for row in ledger:
        running += row["in"] - row["out"]
        row["balance"] = running
    expected = running
    actual = daily.actual_closing_cash
    return {
        "opening": _money(daily.opening_cash),
        "total_in": sum(row["in"] for row in ledger),
        "total_out": sum(row["out"] for row in ledger),
        "expected": expected,
        "actual": actual,
        "variance": (int(actual) - expected) if actual is not None else None,
        "movements": ledger,
    }


def _cash_breakdown(cash: dict, sales: dict, expenses: dict) -> dict:
    supplier_payments = 0
    owner_withdrawals = 0
    customer_refunds = 0
    for row in cash.get("movements", []):
        outgoing = int(row.get("out") or 0)
        if not outgoing:
            continue
        text = " ".join(str(row.get(key) or "") for key in ("type", "description", "reference_type")).lower()
        if any(word in text for word in ("supplier", "purchase_payment", "مورد", "تجهيز")):
            supplier_payments += outgoing
        elif any(word in text for word in ("owner", "withdrawal", "صاحب", "سحب")):
            owner_withdrawals += outgoing
        elif any(word in text for word in ("customer_return", "refund", "مرتجع عميل", "استرجاع عميل")):
            customer_refunds += outgoing
    cash_sales = int(sales.get("cash_sales") or 0)
    debt_cash = int((sales.get("debt_receipts_by_method") or {}).get("cash") or 0)
    cash_expenses = int(expenses.get("cash_total") or 0)
    known_out = cash_expenses + supplier_payments + owner_withdrawals + customer_refunds
    return {
        "cash_sales": cash_sales,
        "debt_receipts": debt_cash,
        "other_in": max(0, int(cash.get("total_in") or 0) - cash_sales - debt_cash),
        "cash_expenses": cash_expenses,
        "supplier_payments": supplier_payments,
        "owner_withdrawals": owner_withdrawals,
        "customer_refunds": customer_refunds,
        "other_out": max(0, int(cash.get("total_out") or 0) - known_out),
    }


def _returns_data(sales: dict, stock: dict) -> dict:
    returned = [row for row in sales["invoices"] if row["status"] in tuple(RETURN_STATUSES)]
    total = sum(row["total"] for row in returned)
    returned_ids = {int(row["id"]) for row in returned}
    stock_rows = [
        row for row in stock.get("details", [])
        if row.get("direction") == "in" and row.get("category") == "sale_return"
        and int(row.get("reference_id") or 0) in returned_ids
    ]
    returned_to_stock = sum(int(row.get("quantity") or 0) for row in stock_rows)
    ordered_qty = 0
    if returned_ids:
        ordered_qty = int(
            db.session.query(func.coalesce(func.sum(OrderItem.quantity), 0))
            .filter(OrderItem.invoice_id.in_(returned_ids))
            .scalar() or 0
        )
    refunds = sales.get("return_refunds") or {}
    return {
        "count": len(returned), "value": total, "cash_refund": int(refunds.get("cash") or 0),
        "electronic_refund": int(refunds.get("electronic") or 0) + int(refunds.get("bank") or 0),
        "returned_to_stock": returned_to_stock,
        "not_returned_to_stock": max(0, ordered_qty - returned_to_stock),
        "stock_rows": stock_rows, "rows": returned,
    }


def _courier_data(daily: DailySession, start: datetime, end: datetime) -> list[dict]:
    """Count only the orders and item snapshots explicitly included in AGT reports."""
    reports = _agent_reports(daily, start, end)
    grouped = defaultdict(lambda: {"delivered": 0, "sold": 0, "returned": 0})
    for report in reports:
        try:
            rows = json.loads(report.orders_data or "[]")
            selections = json.loads(report.order_status_selections or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        try:
            agent_id = int(str(report.report_number).split("-")[1])
        except (TypeError, ValueError, IndexError):
            agent_id = 0
        agent = DeliveryAgent.query.execution_options(skip_branch_scope=True).filter_by(id=agent_id).first() if agent_id else None
        agent_name = (agent.name if agent else None) or str(report.shipping_company_name or "").replace("كشف المندوب:", "").strip() or "مندوب"
        order_ids = []
        for row in rows if isinstance(rows, list) else []:
            try:
                order_ids.append(int(row.get("id") or row.get("order_id")))
            except (AttributeError, TypeError, ValueError):
                continue
        invoices = {
            int(invoice.id): invoice
            for invoice in Invoice.query.execution_options(skip_branch_scope=True).filter(Invoice.id.in_(order_ids or [-1])).all()
        }
        fallback_items = defaultdict(list)
        if order_ids:
            for item in OrderItem.query.filter(OrderItem.invoice_id.in_(order_ids)).all():
                fallback_items[int(item.invoice_id)].append({"product_name": item.product_name, "quantity": item.quantity})
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                order_id = int(row.get("id") or row.get("order_id"))
            except (TypeError, ValueError):
                continue
            invoice = invoices.get(order_id)
            if daily.branch_id is not None and (not invoice or int(invoice.branch_id or 0) != int(daily.branch_id)):
                continue
            status = str((selections or {}).get(str(order_id)) or "").strip().lower()
            is_sold = status in {"واصل", "delivered", "استبدال", "replacement"}
            is_returned = status in {"ملغي", "canceled", "راجع", "مرتجع", "returned", "مؤجل", "delayed"}
            items = row.get("items") if isinstance(row.get("items"), list) else fallback_items.get(order_id, [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                product_name = str(item.get("product_name") or item.get("name") or "مادة").strip()
                amount = max(0, int(item.get("quantity") or 0))
                if not amount:
                    continue
                key = (agent_name, product_name)
                grouped[key]["delivered"] += amount
                if is_sold:
                    grouped[key]["sold"] += amount
                elif is_returned:
                    grouped[key]["returned"] += amount
    return [
        {"agent": key[0], "product": key[1], **value, "remaining": value["delivered"] - value["sold"] - value["returned"]}
        for key, value in sorted(grouped.items())
    ]


def refresh_inventory_counts(daily: DailySession, stock: dict | None = None) -> list[dict]:
    start, end = _window(daily)
    stock = stock or _stock_data(daily, start, end)
    movement_by_product = defaultdict(lambda: {"in": 0, "out": 0})
    for row in stock["details"]:
        movement_by_product[row["product_id"]][row["direction"]] += int(row["quantity"])
    product_ids = [row.product_id for row in daily.counts]
    quantities = {}
    if product_ids:
        for pid, qty in (
            db.session.query(BranchStock.product_id, BranchStock.quantity)
            .execution_options(skip_branch_scope=True)
            .filter(BranchStock.branch_id == daily.branch_id, BranchStock.product_id.in_(product_ids))
            .all()
        ):
            quantities[int(pid)] = int(qty or 0)
        for product in Product.query.execution_options(skip_branch_scope=True).filter(Product.id.in_(product_ids)).all():
            quantities.setdefault(product.id, int(product.quantity or 0))
    result = []
    for count in daily.counts:
        incoming = movement_by_product[count.product_id]["in"]
        outgoing = movement_by_product[count.product_id]["out"]
        expected = quantities.get(count.product_id, 0)
        opening = expected - incoming + outgoing
        count.opening_quantity = opening
        count.incoming_quantity = incoming
        count.outgoing_quantity = outgoing
        count.expected_quantity = expected
        count.variance = (count.actual_quantity - expected) if count.actual_quantity is not None else None
        result.append({
            "id": count.id, "product_id": count.product_id,
            "product_name": count.product.name if count.product else f"مادة #{count.product_id}",
            "opening": opening, "incoming": incoming, "outgoing": outgoing,
            "expected": expected, "actual": count.actual_quantity, "variance": count.variance,
            "notes": count.notes or "",
        })
    return result


def build_daily_closing_data(
    daily: DailySession,
    *,
    live: bool = True,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> dict:
    custom_period = period_start is not None or period_end is not None
    if daily.status == "closed" and daily.snapshot_json and not live and not custom_period:
        frozen = json.loads(daily.snapshot_json)
        frozen_cash = frozen.get("cash") or {}
        if "breakdown" not in frozen_cash:
            frozen_cash["breakdown"] = _cash_breakdown(
                frozen_cash, frozen.get("sales") or {}, frozen.get("expenses") or {}
            )
        frozen["cash"] = frozen_cash
        frozen_sales = frozen.get("sales") or {}
        frozen_sales.setdefault("current_receipts", sum(int(frozen_sales.get(key) or 0) for key in ("cash_sales", "electronic_sales", "bank_sales")))
        frozen_sales.setdefault("received_today", int(frozen_sales.get("current_receipts") or 0) + int(frozen_sales.get("debt_receipts") or 0))
        frozen_sales.setdefault("unpaid_orders_count", 0)
        frozen["sales"] = frozen_sales
        frozen_expenses = frozen.get("expenses") or {}
        frozen_expenses.setdefault("bank_total", 0)
        frozen_expenses.setdefault("other_total", 0)
        frozen_expenses.setdefault("by_method", {})
        frozen["expenses"] = frozen_expenses
        frozen.setdefault("period", {"start": frozen.get("session", {}).get("opened_at"), "end": frozen.get("session", {}).get("closed_at"), "is_custom": False})
        return frozen
    default_start, default_end = _window(daily)
    start = period_start or default_start
    end = period_end or default_end
    if start < default_start:
        start = default_start
    if end > default_end:
        end = default_end
    if end < start:
        end = start
    stock = _stock_data(daily, start, end)
    sales = _sales_data(daily, start, end)
    expenses = _expense_data(daily, start, end)
    cash = _cash_data(daily, start, end)
    cash["breakdown"] = _cash_breakdown(cash, sales, expenses)
    counts = refresh_inventory_counts(daily, stock)
    sales["net_profit"] = sales["gross_profit"] - expenses["total"]
    data = {
        "session": {
            "id": daily.id, "report_number": daily.report_number,
            "company_key": daily.company_key, "branch_id": daily.branch_id,
            "branch_name": daily.branch.name if daily.branch else f"فرع #{daily.branch_id}",
            "business_date": daily.business_date.isoformat(), "shift_name": daily.shift_name or "عام",
            "opened_at": daily.opened_at.isoformat(), "closed_at": daily.closed_at.isoformat() if daily.closed_at else None,
            "opened_by": daily.opener.name if daily.opener else str(daily.opened_by),
            "closed_by": daily.closer.name if daily.closer else None,
            "status": daily.status, "notes": daily.notes or "", "variance_reason": daily.variance_reason or "",
        },
        "sales": sales, "cash": cash, "expenses": expenses, "stock": stock,
        "inventory_counts": counts, "couriers": _courier_data(daily, start, end),
        "returns": _returns_data(sales, stock), "generated_at": datetime.utcnow().isoformat(),
        "period": {
            "start": start.isoformat(), "end": end.isoformat(),
            "is_custom": custom_period,
        },
    }
    data["source_fingerprint"] = source_fingerprint(data)
    return _jsonable(data)


def build_period_overview(
    *,
    branch_id: int | None,
    business_date: date,
    period_start: datetime,
    period_end: datetime,
    selected_product_ids: list[int] | None = None,
) -> dict:
    """Build a read-only report even when no closing session exists.

    ``branch_id=None`` intentionally means all branches in the current tenant.
    This report never creates a session and therefore cannot be closed or used
    to enter a physical cash/inventory count.
    """
    branch = None
    if branch_id is not None:
        branch = Branch.query.execution_options(skip_branch_scope=True).filter_by(id=branch_id, is_active=True).first()
        if branch is None:
            raise ValueError("الفرع غير موجود")
    context = SimpleNamespace(
        id=None,
        company_key=company_key(),
        branch_id=branch_id,
        branch=branch,
        business_date=business_date,
        report_number="عرض مباشر",
        shift_name="الفترة المختارة",
        opened_at=period_start,
        closed_at=period_end,
        opening_cash=0,
        actual_closing_cash=None,
        status="report",
        notes="",
        variance_reason="",
        adjustments=[],
        counts=[],
        opener=None,
        closer=None,
    )
    stock = _stock_data(context, period_start, period_end)
    sales = _sales_data(context, period_start, period_end)
    expenses = _expense_data(context, period_start, period_end)
    cash = _cash_data(context, period_start, period_end)
    cash["breakdown"] = _cash_breakdown(cash, sales, expenses)
    sales["net_profit"] = sales["gross_profit"] - expenses["total"]
    inventory_counts = []
    if branch_id is None:
        # The all-branches view is read-only, but it should still show the
        # current stock snapshot for every physical branch. Actual counting
        # and variance approval remain available only on a branch daily.
        stock_rows = BranchStock.query.execution_options(skip_branch_scope=True).all()
        product_ids = {int(row.product_id) for row in stock_rows}
        products = {
            int(product.id): product
            for product in Product.query.execution_options(skip_branch_scope=True).filter(Product.id.in_(product_ids or [-1])).all()
        }
        selected_ids = {int(value) for value in (selected_product_ids or [])}
        grouped_stock = {}
        for stock_row in stock_rows:
            product = products.get(int(stock_row.product_id))
            if not product or not product.active:
                continue
            barcode = str(product.barcode or "").strip().casefold()
            sku = str(product.sku or "").strip().casefold()
            group_id = str(product.catalog_group_id or "").strip()
            key = f"barcode:{barcode}" if barcode else (f"group:{group_id}" if group_id else (f"sku:{sku}" if sku else f"product:{product.id}"))
            row = grouped_stock.setdefault(key, {"product": product, "members": set(), "opening": 0, "quantity": 0})
            row["members"].add(int(product.id))
            row["opening"] += max(0, int(stock_row.opening_stock or 0))
            row["quantity"] += max(0, int(stock_row.quantity or 0))
        for index, grouped in enumerate(grouped_stock.values(), start=1):
            if selected_ids and not (grouped["members"] & selected_ids):
                continue
            product = grouped["product"]
            inventory_counts.append({
                "id": -index,
                "product_id": int(product.id),
                "product_name": product.name,
                "opening": grouped["opening"],
                "incoming": 0,
                "outgoing": 0,
                "expected": grouped["quantity"],
                "actual": None,
                "variance": None,
                "notes": "لقطة مخزون حالية لكل الفروع",
            })
    data = {
        "session": {
            "id": None,
            "report_number": "عرض مباشر",
            "company_key": context.company_key,
            "branch_id": branch_id,
            "branch_name": branch.name if branch else "كل الفروع",
            "business_date": business_date.isoformat(),
            "shift_name": "الفترة المختارة",
            "opened_at": period_start.isoformat(),
            "closed_at": period_end.isoformat(),
            "opened_by": "—",
            "closed_by": None,
            "status": "report",
            "notes": "",
            "variance_reason": "",
        },
        "sales": sales,
        "cash": cash,
        "expenses": expenses,
        "stock": stock,
        "inventory_counts": inventory_counts,
        "couriers": _courier_data(context, period_start, period_end),
        "returns": _returns_data(sales, stock),
        "generated_at": datetime.utcnow().isoformat(),
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat(), "is_custom": True},
        "is_overview": True,
    }
    data["source_fingerprint"] = source_fingerprint(data)
    return _jsonable(data)


def source_fingerprint(data: dict) -> str:
    stable = {
        "sales": data.get("sales"), "cash": data.get("cash"), "expenses": data.get("expenses"),
        "stock": data.get("stock"), "counts": data.get("inventory_counts"), "returns": data.get("returns"),
    }
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def audit(daily: DailySession, action: str, *, entity_type: str | None = None, entity_id: int | None = None,
          old: Any = None, new: Any = None, reason: str | None = None) -> None:
    db.session.add(DailyClosingAuditLog(
        daily_session_id=daily.id, company_key=daily.company_key, branch_id=daily.branch_id,
        action=action, entity_type=entity_type, entity_id=entity_id,
        user_id=flask_session.get("user_id"), user_name=flask_session.get("name"),
        old_value_json=json.dumps(_jsonable(old), ensure_ascii=False) if old is not None else None,
        new_value_json=json.dumps(_jsonable(new), ensure_ascii=False) if new is not None else None,
        reason=reason,
    ))


def close_session(daily: DailySession, *, actual_cash: int | None, variance_reason: str = "", force: bool = False) -> dict:
    previous_actual = daily.actual_closing_cash
    data = build_daily_closing_data(daily)
    if actual_cash is None and force:
        actual_cash = int(data["cash"]["expected"])
    if actual_cash is None:
        raise ValueError("أدخل الصندوق الفعلي قبل الإغلاق")
    daily.actual_closing_cash = int(actual_cash)
    variance = int(actual_cash) - int(data["cash"]["expected"])
    inventory_variances = [row for row in data["inventory_counts"] if row["variance"] not in (None, 0)]
    incomplete = [row for row in data["inventory_counts"] if row["actual"] is None]
    if incomplete and not force:
        raise ValueError("أكمل الجرد الفعلي لكل المواد المختارة قبل الإغلاق")
    if (variance or inventory_variances) and not variance_reason.strip() and not force:
        raise ValueError("سبب الفرق / الملاحظات مطلوب عند وجود فرق بالصندوق أو الجرد")
    now = datetime.utcnow()
    daily.closed_at = now
    daily.closed_by = flask_session.get("user_id")
    daily.expected_closing_cash = int(data["cash"]["expected"])
    daily.cash_variance = variance
    daily.variance_reason = variance_reason.strip() or None
    daily.status = "closed"
    data["session"]["closed_at"] = now.isoformat()
    data["session"]["closed_by"] = flask_session.get("name")
    data["session"]["status"] = "closed"
    data["session"]["variance_reason"] = daily.variance_reason or ""
    data["cash"]["actual"] = int(actual_cash)
    data["cash"]["variance"] = variance
    daily.source_fingerprint = source_fingerprint(data)
    data["source_fingerprint"] = daily.source_fingerprint
    daily.snapshot_json = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if previous_actual != daily.actual_closing_cash:
        audit(daily, "actual_cash_update", entity_type="daily_session", entity_id=daily.id, old=previous_actual, new=daily.actual_closing_cash)
    audit(daily, "force_close" if force else "close", old={"status": "open"}, new={"status": "closed", "cash_variance": variance}, reason=variance_reason or ("إغلاق إجباري" if force else None))
    return data


def archive_snapshot_for_reopen(daily: DailySession, *, reason: str) -> DailyClosingSnapshotHistory | None:
    if not daily.snapshot_json:
        return None
    version = int(daily.snapshot_version or 1)
    archived = DailyClosingSnapshotHistory(
        daily_session_id=daily.id,
        company_key=daily.company_key,
        branch_id=daily.branch_id,
        snapshot_version=version,
        snapshot_json=daily.snapshot_json,
        source_fingerprint=daily.source_fingerprint,
        closed_by=daily.closed_by,
        closed_at=daily.closed_at,
        archived_by=flask_session.get("user_id"),
        reopen_reason=reason,
    )
    db.session.add(archived)
    db.session.flush()
    daily.snapshot_version = version + 1
    return archived


def linked_data_changed(daily: DailySession) -> bool:
    if daily.status != "closed" or not daily.snapshot_json:
        return False
    live = build_daily_closing_data(daily, live=True)
    return source_fingerprint(live) != daily.source_fingerprint
