"""FINORA read service and policy executor; MCP never queries the DB itself."""
from __future__ import annotations

import base64
import json
import time
from jsonschema import Draft202012Validator
from flask import g, session
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy import or_, func

from extensions import db
from models.customer import Customer
from models.delivery_agent import DeliveryAgent
from models.shipping_report import ShippingReport
from models.customer_credit import CustomerCreditPlan
from models.invoice import Invoice
from models.product import Product
from models.purchase import Purchase
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from modules.finora_ai.context import FinoraAuthContext, reject_identity_override
from modules.finora_ai.models import FinoraAIToolCall
from modules.finora_ai.language import normalize
from modules.finora_ai import report_tools
from utils.ai_assistant_tools import (
    tool_get_customers_receivables,
    tool_get_low_stock,
    tool_get_order_details,
    tool_get_product_stock,
    tool_get_sales_summary,
    tool_get_supplier_debts,
    tool_get_supplier_statement,
    tool_get_expenses,
    tool_get_top_products,
    tool_get_shipping_companies_dues,
    tool_search_orders,
    tool_search_products,
)
from utils.cash_calculations import _effective_paid_amount, calculate_cash_balance
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
from utils.agent_report_helpers import get_report_order_ids, serialize_pending_report


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _limit(args: dict, default=20, maximum=50) -> int:
    return max(1, min(_int(args.get("limit"), default), maximum))


def _offset(cursor) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(base64.urlsafe_b64decode(str(cursor) + "===").decode("ascii")))
    except Exception:
        raise ValueError("Invalid pagination cursor")


def _cursor(value: int | None) -> str | None:
    if value is None:
        return None
    return base64.urlsafe_b64encode(str(value).encode("ascii")).decode("ascii").rstrip("=")


def _page(items: list, offset: int, limit: int, total: int) -> dict:
    next_offset = offset + len(items)
    return {
        "items": items,
        "count": len(items),
        "next_cursor": _cursor(next_offset) if next_offset < total else None,
    }


def _customer(args: dict) -> Customer | None:
    customer_id = _int(args.get("customer_id"))
    return Customer.query.get(customer_id) if customer_id else None


def _name_match(column, term: str):
    # Arabic spelling/diacritics normalization happens on both sides. It does
    # not pick an identity: multiple matching records still require selection.
    folded = column
    for old, new in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ـ", "")):
        folded = func.replace(folded, old, new)
    for mark in "ًٌٍَُِّْ":
        folded = func.replace(folded, mark, "")
    value = normalize(term).replace("ة", "ه").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return folded.ilike(f"%{value}%", escape="\\")


def search_customer(args: dict, _scope: dict) -> dict:
    term = str(args.get("query") or args.get("name") or args.get("phone") or "").strip()
    customer_id = _int(args.get("customer_id"))
    if not term and not customer_id:
        raise ValueError("Provide a name, phone, or customer_id")
    query = Customer.query
    if customer_id:
        query = query.filter(Customer.id == customer_id)
    if term:
        like = f"%{term}%"
        query = query.filter(
            or_(_name_match(Customer.name, term), Customer.phone.ilike(like), Customer.phone2.ilike(like))
        )
    total = query.count()
    limit, offset = _limit(args), _offset(args.get("cursor"))
    rows = query.order_by(Customer.name.asc(), Customer.id.asc()).offset(offset).limit(limit).all()
    return _page(
        [
            {
                "customer_id": row.id,
                "name": row.name,
                "phone": row.phone,
                "phone2": row.phone2 or "",
                "city": row.city or "",
            }
            for row in rows
        ],
        offset,
        limit,
        total,
    )


def get_customer(args: dict, _scope: dict) -> dict:
    row = _customer(args)
    if not row:
        raise LookupError("Customer not found")
    return {
        "customer_id": row.id,
        "name": row.name,
        "phone": row.phone,
        "phone2": row.phone2 or "",
        "city": row.city or "",
        "address": row.address or "",
        # Notes are intentionally excluded: they are untrusted and unnecessary here.
    }


def _customer_invoices(customer_id: int):
    from modules.receipts.services.source_summary import _base_open_invoice_filter
    return Invoice.query.filter(Invoice.customer_id == customer_id, _base_open_invoice_filter())


def get_customer_balance(args: dict, _scope: dict) -> dict:
    row = _customer(args)
    if not row:
        raise LookupError("Customer not found")
    invoices = _customer_invoices(row.id).all()
    total = sum(_int(invoice.total) for invoice in invoices)
    paid = sum(_effective_paid_amount(invoice) for invoice in invoices)
    invoice_due = sum(max(0, _int(invoice.total) - _effective_paid_amount(invoice)) for invoice in invoices)
    # Linked plans are synchronized into their invoices by the existing credit
    # service. Only unlinked opening/manual plans are added, avoiding duplicates.
    # The customer was fetched through the authorized tenant/branch scope first.
    unlinked_plans = CustomerCreditPlan.query.filter_by(customer_id=row.id, invoice_id=None).all()
    credit_due = sum(plan.remaining for plan in unlinked_plans)
    return {
        "customer_id": row.id,
        "name": row.name,
        "invoiced": total,
        "paid": paid,
        "invoice_balance_due": invoice_due,
        "unlinked_credit_balance_due": credit_due,
        "balance_due": invoice_due + credit_due,
        "balance_scope": "retail_invoices_and_unlinked_customer_credit",
        "excluded_modules": ["wholesale"],
        "currency": "IQD",
    }


def get_customer_statement(args: dict, _scope: dict) -> dict:
    row = _customer(args)
    if not row:
        raise LookupError("Customer not found")
    query = Invoice.query.filter(Invoice.customer_id == row.id)
    total = query.count()
    limit, offset = _limit(args, 20, 50), _offset(args.get("cursor"))
    invoices = query.order_by(Invoice.created_at.desc(), Invoice.id.desc()).offset(offset).limit(limit).all()
    page = _page(
        [
            {
                "order_id": item.id,
                "date": item.created_at.isoformat() if item.created_at else None,
                "status": item.status,
                "payment_status": item.payment_status,
                "total": _int(item.total),
                "paid": _effective_paid_amount(item),
                "remaining": max(0, _int(item.total) - _effective_paid_amount(item)),
            }
            for item in invoices
        ], offset, limit, total,
    )
    page.update({"customer_id": row.id, "name": row.name, "currency": "IQD"})
    return page


def get_product(args: dict, scope: dict) -> dict:
    product = Product.query.get(_int(args.get("product_id")))
    if not product:
        raise LookupError("Product not found")
    data = {
        "product_id": product.id,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "current_stock": _int(product.quantity),
        "minimum_stock": _int(product.low_stock_threshold, 5),
        "selling_price": _int(product.sale_price),
        "active": bool(product.active),
        "currency": "IQD",
    }
    if scope.get("cost"):
        data["cost"] = _int(product.buy_price)
    return data


def search_products(args: dict, scope: dict) -> dict:
    term = str(args.get("query") or "").strip()
    if not term:
        raise ValueError("Provide a product name, SKU, or barcode")
    like = f"%{term}%"
    query = Product.query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like)))
    total = query.count()
    offset, limit = _offset(args.get("cursor")), _limit(args)
    rows = query.order_by(Product.id.asc()).offset(offset).limit(limit).all()
    items = []
    for row in rows:
        item = {"product_id": row.id, "name": row.name, "sku": row.sku or "", "barcode": row.barcode or "",
                "current_stock": _int(row.quantity), "selling_price": _int(row.sale_price), "active": bool(row.active)}
        if scope.get("cost"):
            item["cost"] = _int(row.buy_price)
        items.append(item)
    return _page(items, offset, limit, total)


def search_orders(args: dict, scope: dict) -> dict:
    from utils.permission_checks import get_current_employee, allowed_order_statuses_for
    from utils.ai_assistant_tools import _utc_window
    employee = get_current_employee()
    query = Invoice.query.join(Customer, Invoice.customer_id == Customer.id).filter(
        or_(Invoice.is_draft.is_(False), Invoice.is_draft.is_(None)), Invoice.deleted_at.is_(None))
    if employee.role != "admin":
        statuses = allowed_order_statuses_for(employee)
        query = query.filter(Invoice.status.in_(statuses))
    for key in ("status", "payment_status"):
        if args.get(key):
            query = query.filter(getattr(Invoice, key) == args[key])
    if args.get("customer"):
        query = query.filter(Invoice.customer_name.ilike(f"%{args['customer']}%"))
    if args.get("query"):
        term = str(args["query"])
        like = f"%{term}%"
        query = query.filter(or_(Invoice.id == _int(term, -1), Invoice.barcode.ilike(like),
                                Invoice.customer_name.ilike(like), Customer.phone.ilike(like),
                                Customer.phone2.ilike(like), Customer.city.ilike(like), Customer.address.ilike(like)))
    if args.get("branch_id"):
        query = query.filter(Invoice.branch_id == args["branch_id"])
    if args.get("date_from") or args.get("date_to"):
        start, end, _ = _utc_window(args.get("date_from"), args.get("date_to"), default_today=False)
        query = query.filter(Invoice.created_at >= start, Invoice.created_at < end)
    offset, limit = _offset(args.get("cursor")), _limit(args)
    total = query.count()
    rows = query.order_by(Invoice.id.desc()).offset(offset).limit(limit).all()
    return _page([{ "order_id": row.id, "customer": row.customer_name, "status": row.status,
                   "payment_status": row.payment_status, "total": _int(row.total), "paid": _effective_paid_amount(row),
                   "created_at": row.created_at.isoformat() if row.created_at else None } for row in rows], offset, limit, total)


def latest_order(_args: dict, scope: dict) -> dict:
    results = search_orders({"limit": 1}, scope)["items"]
    if not results:
        raise LookupError("No accessible orders found")
    return tool_get_order_details({"invoice_id": results[0]["order_id"]}, scope)


def search_supplier(args: dict, _scope: dict) -> dict:
    term = str(args.get("query") or args.get("name") or args.get("phone") or "").strip()
    if not term:
        raise ValueError("Provide supplier name or phone")
    like = f"%{term}%"
    query = Supplier.query.filter(
        or_(_name_match(Supplier.name, term), Supplier.phone.ilike(like), Supplier.phone2.ilike(like))
    )
    total = query.count()
    limit, offset = _limit(args), _offset(args.get("cursor"))
    rows = query.order_by(Supplier.name.asc(), Supplier.id.asc()).offset(offset).limit(limit).all()
    return _page(
        [{"supplier_id": r.id, "name": r.name, "phone": r.phone or "", "address": r.address or ""} for r in rows],
        offset, limit, total,
    )


def get_supplier_balance(args: dict, _scope: dict) -> dict:
    row = Supplier.query.get(_int(args.get("supplier_id")))
    if not row:
        raise LookupError("Supplier not found")
    return {
        "supplier_id": row.id,
        "name": row.name,
        "total_debt": _int(row.total_debt),
        "total_paid": _int(row.total_paid),
        "balance_due": max(0, _int(row.total_debt) - _int(row.total_paid)),
        "currency": "IQD",
    }


def supplier_statement(args: dict, scope: dict) -> dict:
    if not args.get("supplier_id"):
        raise ValueError("Choose a supplier_id from search_supplier first")
    result = tool_get_supplier_statement(args, scope)
    result["currency"] = "IQD"
    return result


def daily_sales(args: dict, scope: dict) -> dict:
    return tool_get_sales_summary({**args, "date_from": None, "date_to": None}, scope)


def cash_balance(_args: dict, _scope: dict) -> dict:
    return {"balance": _int(calculate_cash_balance()), "currency": "IQD", "as_of": datetime.utcnow().isoformat() + "Z"}


def receivables(args: dict, scope: dict) -> dict:
    result = tool_get_customers_receivables(args, scope)
    result["currency"] = "IQD"
    return result


def payables(_args: dict, scope: dict) -> dict:
    result = tool_get_supplier_debts({}, scope)
    result["currency"] = "IQD"
    return result


def _no_cost(value):
    if isinstance(value, dict):
        return {k: _no_cost(v) for k, v in value.items() if k not in {"cost", "buy_price", "last_purchase_price"}}
    if isinstance(value, list):
        return [_no_cost(v) for v in value]
    return value


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    permissions: tuple[str, ...]
    handler: Callable[[dict, dict], dict]
    exposes_cost: bool = False


def _object(properties=None, required=None):
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


SEARCH = {
    "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}, "cursor": {"type": "string"}
}
CUSTOMER_ID = {"customer_id": {"type": "integer"}}
SUPPLIER_ID = {"supplier_id": {"type": "integer"}}
PRODUCT_ID = {"product_id": {"type": "integer"}}


def search_delivery_agents(args: dict, _scope: dict) -> dict:
    term = str(args.get("query") or "").strip()
    query = DeliveryAgent.query
    if term:
        query = query.filter(or_(_name_match(DeliveryAgent.name, term), DeliveryAgent.phone.ilike(f"%{term}%")))
    rows = query.order_by(DeliveryAgent.name, DeliveryAgent.id).limit(_limit(args)).all()
    return {"items": [{"agent_id": row.id, "name": row.name, "is_active": bool(row.is_active)} for row in rows], "count": len(rows)}


def _read_agent_reports(query, limit: int) -> dict:
    # Reuse the exact page calculations, without sync/save helpers. Report
    # snapshots must not bypass automatic Invoice branch isolation.
    reports = []
    for report in query.order_by(ShippingReport.created_at.desc(), ShippingReport.id.desc()).limit(limit).all():
        ids = set(get_report_order_ids(report))
        if ids and Invoice.query.filter(Invoice.id.in_(ids)).count() != len(ids):
            continue
        row = serialize_pending_report(report)
        row["is_executed"] = bool(report.is_executed)
        reports.append(row)
    return {"reports": reports, "count": len(reports), "scope": "عرض محدود للكشوف المطابقة، وليس رصيد ذمة نهائيًا ولا إثبات استلام نقد. مبلغ الواصل بكشف غير منفذ هو مبلغ ينتظر التنفيذ وفق صفحة الكشوف؛ لا تجمع إجماليات الكشوف كرصد للمندوب."}


def delivery_agent_reports(args: dict, _scope: dict) -> dict:
    agent = DeliveryAgent.query.get(_int(args.get("agent_id")))
    if not agent:
        raise LookupError("المندوب غير موجود ضمن نطاق صلاحياتك")
    query = ShippingReport.query.filter(ShippingReport.report_number.like(f"AGT-{agent.id}-%"))
    if args.get("pending_only", True):
        query = query.filter(ShippingReport.is_executed.is_(False))
    result = _read_agent_reports(query, _limit(args))
    result.update(agent_id=agent.id, agent_name=agent.name)
    return result


def agent_report(args: dict, _scope: dict) -> dict:
    query = ShippingReport.query.filter(ShippingReport.report_number == args["report_number"])
    result = _read_agent_reports(query, 1)
    if not result["reports"]:
        raise LookupError("الكشف غير موجود ضمن نطاق صلاحياتك")
    return result


def pending_agent_reports(args: dict, _scope: dict) -> dict:
    return _read_agent_reports(ShippingReport.query.filter(ShippingReport.report_number.like("AGT-%"), ShippingReport.is_executed.is_(False)), _limit(args))


TOOLS = {
    spec.name: spec for spec in (
        ToolSpec("search_customer", "Search customers by name, partial phone, or id.", _object({**SEARCH, "name": {"type": "string"}, "phone": {"type": "string"}, **CUSTOMER_ID}), ("manage_customers",), search_customer),
        ToolSpec("get_customer", "Get the minimum identity and contact fields for one customer.", _object(CUSTOMER_ID, ["customer_id"]), ("manage_customers",), get_customer),
        ToolSpec("get_customer_balance", "Get a customer's current balance from FINORA invoices.", _object(CUSTOMER_ID, ["customer_id"]), ("manage_customers", "view_accounts", "view_financial"), get_customer_balance),
        ToolSpec("get_customer_statement", "Get a paginated customer statement.", _object({**CUSTOMER_ID, "limit": SEARCH["limit"], "cursor": SEARCH["cursor"]}, ["customer_id"]), ("manage_customers", "view_accounts", "view_financial"), get_customer_statement),
        ToolSpec("search_orders", "Search orders by number, customer, phone, address, status, branch, or date.", _object({**SEARCH, "customer": {"type": "string"}, "status": {"type": "string"}, "payment_status": {"type": "string"}, "branch_id": {"type": "integer"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}}), ("view_orders",), search_orders),
        ToolSpec("get_order", "Get one order and its items.", _object({"invoice_id": {"type": "integer"}}, ["invoice_id"]), ("view_orders",), tool_get_order_details, True),
        ToolSpec("search_products", "Search products by name, SKU, or barcode.", _object(SEARCH, ["query"]), ("manage_inventory",), search_products, True),
        ToolSpec("get_product", "Get one product and its current stock.", _object(PRODUCT_ID, ["product_id"]), ("manage_inventory",), get_product, True),
        ToolSpec("get_product_stock", "Get current, reserved and available product stock.", _object(PRODUCT_ID, ["product_id"]), ("manage_inventory",), tool_get_product_stock, True),
        ToolSpec("get_low_stock", "List low-stock products.", _object({"branch_id": {"type": "integer"}, "limit": SEARCH["limit"]}), ("manage_inventory",), tool_get_low_stock),
        ToolSpec("search_supplier", "Search suppliers by name or phone.", _object(SEARCH, ["query"]), ("manage_suppliers",), search_supplier),
        ToolSpec("get_supplier_balance", "Get the current supplier payable balance.", _object(SUPPLIER_ID, ["supplier_id"]), ("manage_suppliers", "view_accounts", "view_financial"), get_supplier_balance),
        ToolSpec("get_supplier_statement", "Get supplier purchases and payments.", _object(SUPPLIER_ID, ["supplier_id"]), ("manage_suppliers", "view_accounts", "view_financial"), supplier_statement),
        ToolSpec("get_daily_sales", "Get today's sales summary in Baghdad time.", _object(), ("view_reports", "view_financial"), daily_sales),
        ToolSpec("get_sales_summary", "Get an aggregated sales summary for a period.", _object({"date_from": {"type": "string"}, "date_to": {"type": "string"}, "branch_id": {"type": "integer"}, "group_by": {"type": "string", "enum": ["day", "branch", "employee", "status", "page"]}}), ("view_reports", "view_financial"), tool_get_sales_summary),
        ToolSpec("get_cash_balance", "Get the current FINORA cash balance.", _object(), ("view_accounts", "view_financial"), cash_balance),
        ToolSpec("get_receivables_summary", "Get customer receivables summary.", _object({"limit": SEARCH["limit"]}), ("view_reports", "view_financial", "view_accounts"), receivables),
        ToolSpec("get_payables_summary", "Get supplier payables summary.", _object(), ("view_financial", "view_accounts", "manage_suppliers"), payables),
        ToolSpec("get_latest_order", "Get the newest accessible order with date, employee, status and items.", _object(), ("view_orders",), latest_order, True),
        ToolSpec("get_expenses", "Read posted expenses, totals and category breakdown for a period.", _object({"date_from": {"type": "string"}, "date_to": {"type": "string"}, "category": {"type": "string"}, "limit": SEARCH["limit"]}), ("view_expenses",), tool_get_expenses),
        ToolSpec("get_top_products", "Read top-selling products and profit; requires profit permission.", _object({"date_from": {"type": "string"}, "date_to": {"type": "string"}, "by": {"type": "string", "enum": ["quantity", "revenue", "profit"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}), ("view_profit",), tool_get_top_products),
        ToolSpec("get_shipping_dues", "Read amounts owed to FINORA by shipping companies, not debts FINORA owes.", _object(), ("view_financial",), tool_get_shipping_companies_dues),
        ToolSpec("search_delivery_agents", "Find delivery agents / المندوب by partial name or phone. Return candidates, never infer identity from an old order. If several match, ask the user to choose.", _object({"query": {"type": "string", "maxLength": 150}, "limit": SEARCH["limit"]}), ("view_agents",), search_delivery_agents),
        ToolSpec("get_delivery_agent_reports", "Read a chosen agent's AGT reports / كشوف المندوب and delivered, returned, postponed and pending amounts using the existing report page. Default to unexecuted reports. These are NOT a consolidated debt balance or proof of cash receipt; explain this scope when asked شكد باقي على المندوب.", _object({"agent_id": {"type": "integer", "minimum": 1}, "pending_only": {"type": "boolean"}, "limit": SEARCH["limit"]}, ["agent_id"]), ("view_agents",), delivery_agent_reports),
        ToolSpec("get_agent_report", "Read a specific AGT delivery-agent report, its execution status and financial status breakdown. AGT numbers are report identifiers, NOT order numbers.", _object({"report_number": {"type": "string", "pattern": "^AGT-[0-9]+-[A-Za-z0-9-]+$", "maxLength": 50}}, ["report_number"]), ("view_agents",), agent_report),
        ToolSpec("get_pending_agent_reports", "Read the pending-execution agent report queue / كشوف المندوب بانتظار التنفيذ. Use for general queue questions, not an unnamed individual agent's balance.", _object({"limit": SEARCH["limit"]}), ("view_agents",), pending_agent_reports),
        ToolSpec("get_period_comparison", "Compare a period with the previous period or the same period last year: sales, collections, returns, and profit when permitted. period=today|yesterday|this_week|this_month|last_month|this_year|custom (custom needs date_from/date_to).", _object({**report_tools.PERIOD_ARGS, "compare_to": {"type": "string", "enum": ["previous", "last_year"]}}), ("view_reports",), report_tools.period_comparison),
        ToolSpec("get_sales_breakdown", "Break down net sales for a period by branch, employee, payment type, customer, product, category, day or month. Use by=branch to compare branches.", _object({**report_tools.PERIOD_ARGS, "by": {"type": "string", "enum": ["branch", "employee", "payment", "customer", "product", "category", "day", "month"]}, "limit": report_tools.LIMIT}), ("view_reports",), report_tools.sales_breakdown),
        ToolSpec("get_purchases_summary", "Read confirmed purchases for a period: totals, paid, remaining, top suppliers and recent purchase invoices. unpaid_only lists invoices with a remaining amount.", _object({**report_tools.PERIOD_ARGS, "unpaid_only": {"type": "boolean"}, "limit": report_tools.LIMIT}), ("view_reports",), report_tools.purchases_summary),
        ToolSpec("get_receivables_aging", "Read customer debt aging (today, 1-30, 31-60, 61-90, 90+ days) and the oldest open invoices.", _object({"branch_id": report_tools.BRANCH, "limit": report_tools.LIMIT}), ("view_reports",), report_tools.receivables_aging),
        ToolSpec("get_sales_returns", "Read sales returns for a period: count, amount, return rate and recent return documents.", _object({**report_tools.PERIOD_ARGS, "limit": report_tools.LIMIT}), ("view_reports",), report_tools.sales_returns),
        ToolSpec("get_overdue_installments", "List overdue customer installments (الأقساط المتأخرة) with days late and remaining amount; optionally for one customer_id.", _object({**CUSTOMER_ID, "limit": report_tools.LIMIT}), ("manage_customers", "view_accounts", "view_financial"), report_tools.overdue_installments),
        ToolSpec("get_stagnant_products", "List in-stock products not sold for at least min_days days (المنتجات الراكدة).", _object({"min_days": {"type": "integer", "minimum": 7, "maximum": 365}, "limit": report_tools.LIMIT}), ("manage_inventory", "view_reports"), report_tools.stagnant_products),
        ToolSpec("get_product_movements", "Read one product's stock movement history (purchases, sales, returns, adjustments). Choose product_id from search_products first.", _object({**PRODUCT_ID, "branch_id": report_tools.BRANCH, "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, ["product_id"]), ("manage_inventory",), report_tools.product_movements),
    )
}


def _scope(context: FinoraAuthContext) -> dict:
    return {
        "orders": context.allows("view_orders"),
        "inventory": context.allows("manage_inventory"),
        "suppliers": context.allows("manage_suppliers"),
        "reports": context.allows("view_reports"),
        "financial": context.allows("view_financial", "view_accounts"),
        "cost": context.allows("view_profit", "view_financial"),
        "expenses": context.allows("view_expenses"),
    }


TOOL_OUTPUT_SCHEMA = {
    "type": "object", "oneOf": [
        {"type": "object", "required": ["success", "data", "meta"],
         "properties": {"success": {"const": True}, "data": {},
                        "meta": {"type": "object", "required": ["tool", "timestamp", "currency", "read_only"],
                                 "properties": {"tool": {"type": "string"}, "timestamp": {"type": "string"},
                                                "currency": {"const": "IQD"}, "read_only": {"const": True}},
                                 "additionalProperties": False}}, "additionalProperties": False},
        {"type": "object", "required": ["success", "error"],
         "properties": {"success": {"const": False},
                        "error": {"type": "object", "required": ["code", "message"],
                                  "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
                                  "additionalProperties": False}}, "additionalProperties": False}
    ]
}


def list_tools(context: FinoraAuthContext) -> list[dict]:
    return [
        {"name": spec.name, "description": spec.description, "inputSchema": spec.parameters,
         "outputSchema": TOOL_OUTPUT_SCHEMA, "annotations": {"readOnlyHint": True, "destructiveHint": False}}
        for spec in TOOLS.values()
        if context.allows(*spec.permissions) and _tool_enabled(spec.name)
    ]


def _tool_enabled(name: str) -> bool:
    from modules.finora_ai.settings import current_settings
    flags = current_settings().get_flags()
    if not flags.get("mcp_enabled", True):
        return False
    accounting_tools = {"get_delivery_agent_reports", "get_agent_report", "get_pending_agent_reports", "get_expenses", "get_top_products", "get_shipping_dues", "get_customer_balance", "get_customer_statement", "get_supplier_balance", "get_supplier_statement",
                        "get_cash_balance", "get_receivables_summary", "get_payables_summary",
                        "get_period_comparison", "get_purchases_summary", "get_receivables_aging", "get_overdue_installments"}
    return name not in accounting_tools or flags.get("ai_accounting_tools_enabled", True)


def execute_tool(
    context: FinoraAuthContext,
    name: str,
    arguments: dict | None,
    *,
    conversation_id: int | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    started = time.perf_counter()
    args = arguments if arguments is not None else {}
    if getattr(g, "tenant", None) != context.tenant_slug:
        return {"success": False, "error": {"code": "TENANT_CONTEXT_MISMATCH", "message": "Authentication context mismatch"}}
    if not isinstance(args, dict):
        return {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Tool arguments must be an object."}}
    audit = FinoraAIToolCall(
        tenant_slug=context.tenant_slug, user_id=context.user_id, conversation_id=conversation_id,
        provider=provider, model=model, tool_name=str(name), result_status="started",
    )
    safe_audit_args = {key: value for key, value in args.items() if key not in {"api_key", "token", "password", "secret", "authorization"}}
    audit.set_arguments(safe_audit_args)
    db.session.add(audit)
    try:
        reject_identity_override(args)
        spec = TOOLS.get(name)
        if not spec:
            raise KeyError("Unknown tool")
        if not _tool_enabled(name):
            raise PermissionError("Tool disabled by feature policy")
        validation_errors = list(Draft202012Validator(spec.parameters).iter_errors(args))
        if validation_errors:
            raise ValueError("Arguments do not match the tool schema")
        for key in ("date_from", "date_to"):
            if args.get(key):
                try:
                    datetime.fromisoformat(args[key])
                except (ValueError, TypeError):
                    raise ValueError("Dates must use ISO format")
        if not context.allows(*spec.permissions):
            audit.result_status, audit.error_code = "denied", "PERMISSION_DENIED"
            result = {"success": False, "error": {"code": "PERMISSION_DENIED", "message": "You do not have permission to use this tool."}}
        else:
            scope = _scope(context)
            if name == "get_order":
                from utils.permission_checks import employee_can_access_order, get_current_employee
                order = Invoice.query.get(_int(args.get("invoice_id")))
                if order and not employee_can_access_order(get_current_employee(), order):
                    raise PermissionError("Order status access denied")
            data = spec.handler(args, scope)
            if isinstance(data, dict) and (data.get("error") or data.get("restricted")):
                raise LookupError("Requested FINORA data is unavailable")
            if spec.exposes_cost and not scope["cost"]:
                data = _no_cost(data)
            audit.result_status = "success"
            result = {"success": True, "data": data, "meta": {"tool": name, "timestamp": datetime.utcnow().isoformat() + "Z", "currency": "IQD", "read_only": True}}
    except KeyError:
        audit.result_status, audit.error_code = "failed", "TOOL_NOT_FOUND"
        result = {"success": False, "error": {"code": "TOOL_NOT_FOUND", "message": "The requested tool is not available."}}
    except PermissionError:
        audit.result_status, audit.error_code = "denied", "PERMISSION_DENIED"
        result = {"success": False, "error": {"code": "PERMISSION_DENIED", "message": "You do not have permission to access this record."}}
    except ValueError as exc:
        audit.result_status, audit.error_code = "failed", "VALIDATION_ERROR"
        result = {"success": False, "error": {"code": "VALIDATION_ERROR", "message": str(exc)}}
    except LookupError as exc:
        audit.result_status, audit.error_code = "failed", "NOT_FOUND"
        result = {"success": False, "error": {"code": "NOT_FOUND", "message": str(exc)}}
    except Exception:
        db.session.rollback()
        db.session.add(audit)
        audit.result_status, audit.error_code = "failed", "TOOL_EXECUTION_FAILED"
        result = {"success": False, "error": {"code": "TOOL_EXECUTION_FAILED", "message": "The FINORA service could not complete this request."}}
    audit.duration_ms = int((time.perf_counter() - started) * 1000)
    audit.completed_at = datetime.utcnow()
    db.session.commit()
    return result
