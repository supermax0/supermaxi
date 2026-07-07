"""AI assistant orchestration, Excel audit parsing, and approved action execution."""
from __future__ import annotations

import json
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import current_app, has_request_context, session
from sqlalchemy import func, inspect, or_, text
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from extensions import db
from models.ai_assistant_control import (
    AIActionItem,
    AIActionPlan,
    AIAuditRun,
    AIChatMessage,
    AIChatSession,
    AIScheduledAudit,
    AIToolCallLog,
    AIUploadedFile,
)
from models.branch import Branch, BranchStock, StockTransfer, StockTransferLine
from models.employee import Employee
from models.invoice import Invoice
from models.message import Message
from models.order_item import OrderItem
from models.product import Product
from models.role import Permission
from models.shipping import ShippingCompany
from models.supplier import Supplier
from models.system_alert import SystemAlert
from models.system_analytics import SystemAnalytics
from utils.audit_accounting_integrity import _ensure_audit_schema, audit_accounting_integrity
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.cash_calculations import _effective_paid_amount
from utils.delivery_expense_service import sync_delivery_expense_for_invoice
from utils.order_lifecycle import OrderLifecycleError, process_order_cancel, process_order_return
from utils.branch_stock_service import (
    BranchStockError,
    adjust_branch_stock,
    get_branch_stock,
    sync_product_total,
    transfer_deduct,
    transfer_receive,
)
from utils.inventory_movements import get_product_inventory_movements
from utils.order_item_costs import exclude_delivery_fee_items
from utils.activity_logger import log_activity
from utils.payment_ledger import append_payment_ledger_delta
from utils.permission_checks import employee_can
from utils.product_schema_guard import ensure_product_schema
from utils.supplier_accounting_repair import audit_and_repair_supplier_ledgers


AI_PERMISSION_DEFS = [
    ("use_ai_assistant", "استخدام مساعد Finora الذكي"),
    ("approve_ai_actions", "الموافقة على خطط المساعد الذكي وتنفيذها"),
    ("manage_ai_schedules", "إدارة دوريات تحليل المساعد الذكي"),
    ("view_ai_audit_logs", "رؤية سجل أدوات ومراجعات المساعد الذكي"),
]

RESERVED_ORDER_STATUSES = ("تم الطلب", "جاري الشحن")
ALLOWED_UPLOAD_EXTENSIONS = {".xlsx", ".xlsm"}


def ensure_ai_permissions() -> None:
    created = False
    for name, description in AI_PERMISSION_DEFS:
        if not Permission.query.filter_by(name=name).first():
            db.session.add(Permission(name=name, description=description, created_at=datetime.utcnow()))
            created = True
    if created:
        db.session.commit()


def ensure_ai_assistant_schema() -> None:
    """Create assistant tables and seed permissions for deployments without migrations."""
    from models import ai_assistant_control  # noqa: F401

    bind = db.session.get_bind()
    db.Model.metadata.create_all(
        bind=bind,
        tables=[
            AIChatSession.__table__,
            AIChatMessage.__table__,
            AIUploadedFile.__table__,
            AIActionPlan.__table__,
            AIActionItem.__table__,
            AIScheduledAudit.__table__,
            AIAuditRun.__table__,
            AIToolCallLog.__table__,
        ],
    )
    _ensure_message_schema_for_ai_alerts()
    ensure_ai_permissions()


def _ensure_message_schema_for_ai_alerts() -> None:
    """AI critical alerts write internal messages; keep legacy tenant DBs compatible."""
    try:
        bind = db.session.get_bind()
        inspector = inspect(bind)
        if "message" not in inspector.get_table_names():
            return
        columns = {col["name"] for col in inspector.get_columns("message")}
        additions = {
            "file_type": "ALTER TABLE message ADD COLUMN file_type VARCHAR(50)",
            "file_path": "ALTER TABLE message ADD COLUMN file_path VARCHAR(500)",
            "file_name": "ALTER TABLE message ADD COLUMN file_name VARCHAR(255)",
            "is_edited": "ALTER TABLE message ADD COLUMN is_edited BOOLEAN DEFAULT 0",
            "reply_to_id": "ALTER TABLE message ADD COLUMN reply_to_id INTEGER",
        }
        changed = False
        for column, stmt in additions.items():
            if column not in columns:
                db.session.execute(text(stmt))
                changed = True
        if changed:
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("failed to ensure message schema for AI alerts")


def _json_dumps(data: Any) -> str:
    return json.dumps(data or {}, ensure_ascii=False)


def _current_employee_id() -> int | None:
    if has_request_context():
        return session.get("user_id")
    return None


def _serialize_plan(plan: AIActionPlan | None) -> dict | None:
    return plan.to_dict() if plan else None


def _log_tool(
    tool_name: str,
    *,
    session_id: int | None = None,
    plan_id: int | None = None,
    employee_id: int | None = None,
    mode: str = "read",
    input_data: dict | None = None,
    output_data: dict | None = None,
    status: str = "success",
    error: str | None = None,
) -> None:
    try:
        row = AIToolCallLog(
            session_id=session_id,
            plan_id=plan_id,
            employee_id=employee_id,
            tool_name=tool_name[:120],
            mode=mode,
            status=status,
            error_message=error,
        )
        row.set_input(input_data or {})
        row.set_output(output_data or {})
        db.session.add(row)
    except Exception:
        current_app.logger.exception("failed to log AI tool call")


def get_or_create_chat_session(employee_id: int | None, session_id: int | None = None) -> AIChatSession:
    if session_id:
        existing = AIChatSession.query.get(session_id)
        if existing and (existing.employee_id == employee_id or employee_id is None):
            return existing
    chat = AIChatSession(employee_id=employee_id, title="محادثة مساعد Finora")
    chat.set_context({"source": "assistant_chat"})
    db.session.add(chat)
    db.session.flush()
    return chat


def add_chat_message(chat: AIChatSession, role: str, content: str, metadata: dict | None = None) -> AIChatMessage:
    msg = AIChatMessage(session_id=chat.id, role=role, content=content or "")
    msg.set_metadata(metadata or {})
    db.session.add(msg)
    chat.updated_at = datetime.utcnow()
    db.session.flush()
    return msg


def _money(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _assistant_read_scope(employee_id: int | None = None) -> dict:
    employee = Employee.query.get(employee_id) if employee_id else None
    if not employee:
        return {
            "full": True,
            "orders": True,
            "reports": True,
            "financial": True,
            "inventory": True,
            "suppliers": True,
            "shipping": True,
            "order_manage": True,
        }
    is_admin = employee.role == "admin"
    return {
        "full": is_admin,
        "orders": is_admin or employee_can(employee, "view_orders"),
        "reports": is_admin or employee_can(employee, "view_reports"),
        "financial": is_admin or employee_can(employee, "view_financial") or employee_can(employee, "view_accounts"),
        "inventory": is_admin or employee_can(employee, "manage_inventory"),
        "suppliers": is_admin or employee_can(employee, "manage_suppliers"),
        "shipping": is_admin or employee_can(employee, "view_shipping") or employee_can(employee, "manage_shipping"),
        "order_manage": is_admin or employee_can(employee, "manage_orders"),
    }


def _restricted(label: str = "غير متاح حسب صلاحياتك") -> dict:
    return {"restricted": True, "message": label}


def collect_system_snapshot(employee_id: int | None = None) -> dict:
    _ensure_audit_schema()
    ensure_product_schema()
    ensure_branch_schema()
    scope = _assistant_read_scope(employee_id)
    try:
        from utils.accounting_calculations import (
            calculate_shipping_due,
            calculate_shipping_opening_balance,
            calculate_supplier_debts,
        )

        supplier_debts = _money(calculate_supplier_debts())
        shipping_receivables = _money(calculate_shipping_due())
        shipping_opening_balance = _money(calculate_shipping_opening_balance())
    except Exception:
        supplier_debts = 0
        shipping_receivables = 0
        shipping_opening_balance = 0
    total_products = Product.query.count() if scope["inventory"] else None
    active_products = Product.query.filter_by(active=True).count() if scope["inventory"] else None
    branches = Branch.query.order_by(Branch.name.asc()).all() if scope["inventory"] else []
    stock_value = (
        db.session.query(func.coalesce(func.sum(Product.quantity * Product.buy_price), 0)).scalar() or 0
        if scope["inventory"] and (scope["financial"] or scope["reports"])
        else None
    )
    orders_by_status = (
        dict(db.session.query(Invoice.status, func.count(Invoice.id)).group_by(Invoice.status).all())
        if scope["orders"]
        else {}
    )
    recent_sales = (
        db.session.query(func.coalesce(func.sum(Invoice.total), 0))
        .filter(
            Invoice.created_at >= datetime.utcnow() - timedelta(days=30),
            Invoice.status.notin_(["ملغي", "مرتجع", "راجع", "راجعة"]),
        )
        .scalar()
        or 0
        if scope["reports"] or scope["financial"]
        else None
    )
    negative_margin_count = (
        db.session.query(OrderItem.id)
        .join(Invoice, Invoice.id == OrderItem.invoice_id)
        .filter(
            Invoice.status.notin_(["ملغي", "مرتجع", "راجع", "راجعة"]),
            OrderItem.cost > OrderItem.price,
        )
        .count()
        if scope["financial"] or scope["reports"]
        else None
    )
    reserved = _reserved_stock_map() if scope["inventory"] else {}
    financial_data = {}
    if scope["financial"] or scope["suppliers"]:
        financial_data["supplier_debts"] = supplier_debts
    if scope["financial"] or scope["shipping"]:
        financial_data["shipping_receivables"] = shipping_receivables
        financial_data["shipping_opening_balance_receivable"] = shipping_opening_balance
        financial_data["shipping_note"] = "مستحقات شركات النقل ذمم مدينة لصالح الشركة، وليست ديناً على الشركة."
    if scope["financial"]:
        try:
            from utils.cash_calculations import get_cash_summary

            cash_summary = get_cash_summary()
            financial_data["cash"] = {
                "balance": _money(cash_summary.get("current_balance")),
                "total_in": _money(cash_summary.get("total_in")),
                "total_out": _money(cash_summary.get("total_out")),
                "movements_count": int(cash_summary.get("movements_count") or 0),
                "audit_rule": "أي حركة صندوق يدوية بلا سبب/ملاحظة تعتبر مشبوهة وتحتاج مراجعة قبل اعتمادها.",
            }
        except Exception as exc:
            financial_data["cash"] = {"error": str(exc)}
    if not financial_data:
        financial_data = _restricted()
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "permission_scope": scope,
        "products": (
            {"total": total_products, "active": active_products, "stock_value": _money(stock_value)}
            if scope["inventory"]
            else _restricted()
        ),
        "branches": [{"id": b.id, "name": b.name, "code": b.code} for b in branches],
        "orders_by_status": {str(k or "غير محدد"): int(v or 0) for k, v in orders_by_status.items()} if scope["orders"] else _restricted(),
        "reserved_stock_lines": len(reserved) if scope["inventory"] else None,
        "recent_30d_sales": _money(recent_sales) if recent_sales is not None else None,
        "negative_margin_count": int(negative_margin_count or 0) if negative_margin_count is not None else None,
        "known_accounting_rules": [
            "الجرد الفعلي يشمل الطلبات بحالة تم الطلب وجاري الشحن، والقابل للبيع = الجرد الفعلي - المحجوز.",
            "سعر المنتج داخل الفاتورة يجب أن يبقى سعر بيع المنتج المخزني ولا يتغير بسبب أجرة التوصيل.",
            "أجرة التوصيل لا تنضاف على سعر المنتج؛ تخصم/تحاسب لاحقاً عند التسديد حسب سياسة النظام.",
            "مستحقات شركات النقل ذمم مدينة لصالح الشركة وليست ديناً على الشركة.",
            "حركة الصندوق اليدوية بدون ملاحظة/سبب واضحة علامة خطأ إدخال.",
            "أي تنفيذ تعديل يحتاج خطة وموافقة أدمن، ولا ينفذ GPT مباشرة.",
        ],
        "financial": financial_data,
    }


def _reserved_stock_map() -> dict[tuple[int, int], int]:
    """Reserved physical stock by (branch_id, product_id) for ordered/in-shipping orders."""
    default_branch = get_default_branch()
    default_branch_id = default_branch.id if default_branch else None
    rows = (
        db.session.query(
            func.coalesce(OrderItem.fulfillment_branch_id, Invoice.branch_id).label("branch_id"),
            OrderItem.product_id,
            func.coalesce(func.sum(OrderItem.quantity), 0).label("qty"),
        )
        .join(Invoice, Invoice.id == OrderItem.invoice_id)
        .filter(Invoice.status.in_(RESERVED_ORDER_STATUSES))
        .filter(OrderItem.product_id.isnot(None))
        .filter(exclude_delivery_fee_items(OrderItem))
        .group_by(func.coalesce(OrderItem.fulfillment_branch_id, Invoice.branch_id), OrderItem.product_id)
        .all()
    )
    out: dict[tuple[int, int], int] = {}
    for row in rows:
        branch_id = int(row.branch_id or default_branch_id or 0)
        if not branch_id:
            continue
        out[(branch_id, int(row.product_id))] = int(row.qty or 0)
    return out


_QUERY_STOP_WORDS = {
    "شنو", "ليش", "هذا", "هاي", "هسه", "اكو", "اكو", "على", "عن", "من", "الى", "إلى", "في", "بي", "بيه",
    "مال", "ممكن", "تقرير", "تحليل", "حلل", "شوف", "تاكد", "تأكد", "نقص", "زايد", "فرع", "شركة", "قطعة", "قطعه",
    "قطع", "شاشة", "الشاشة", "شاشه", "الشاشه", "شاشات", "الشاشات", "موديل", "حجم", "جرد", "مخزون", "طلبات", "طلب", "حالة", "ضروري", "راجع",
    "صار", "صارت", "النوع", "نوع", "طلبته", "منه", "بفرع", "بالفرع", "بشاشه", "بالشاشه", "موجود", "بس",
    "زياده", "زيادة", "زائد", "الزياده", "الزيادة", "ليشكو", "شكد", "شكتلة", "شنطاني",
    "شوفي", "شوفلي", "وحده", "واحده", "منتج", "المنتج", "للمنتج", "لمنتج",
}


def _normalize_query_token(raw: str) -> str:
    term = (raw or "").strip().lower()
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ة": "ه",
    }
    for old, new in replacements.items():
        term = term.replace(old, new)
    for prefix in ("بال", "وال", "لل", "ال"):
        if term.startswith(prefix) and len(term) > len(prefix) + 2:
            term = term[len(prefix):]
            break
    for prefix in ("ب", "ل", "و"):
        if term.startswith(prefix) and len(term) > 4:
            term = term[1:]
            break
    return term


def _query_terms(message: str) -> list[str]:
    text_value = re.sub(r"[^\w\u0600-\u06FF]+", " ", message or "").strip()
    terms: list[str] = []
    for raw in text_value.split():
        term = _normalize_query_token(raw)
        if len(term) < 2 or term in _QUERY_STOP_WORDS:
            continue
        if term not in terms:
            terms.append(term)
    return terms[:10]


def _collect_query_evidence(message: str, scope: dict | None = None) -> dict:
    """Collect concrete DB rows related to the user's question.

    This keeps the assistant grounded: product/branch stock, reserved orders,
    recent invoices, and inventory movements are sent as evidence instead of
    letting GPT infer from a high-level summary.
    """
    scope = scope or _assistant_read_scope(None)
    evidence: dict[str, Any] = {"terms": _query_terms(message)}
    if not evidence["terms"]:
        return evidence

    if not scope.get("inventory"):
        evidence["inventory"] = _restricted("تفاصيل المخزون تحتاج صلاحية المخزون.")
        return evidence

    terms = evidence["terms"]
    branches = Branch.query.order_by(Branch.name.asc()).all()
    branch_matches = []
    branch_term_ids: set[str] = set()
    for branch in branches:
        haystack = _normalize_query_token(f"{branch.name or ''} {branch.code or ''}")
        matched = [term for term in terms if term in haystack]
        if matched:
            branch_matches.append(branch)
            branch_term_ids.update(matched)
    if not branch_matches and len(branches) == 1:
        branch_matches = branches

    target_branch_ids = [branch.id for branch in branch_matches]
    product_terms = [term for term in terms if term not in branch_term_ids]
    product_filters = []
    for term in product_terms:
        like = f"%{term}%"
        product_filters.extend(
            [
                Product.name.ilike(like),
                Product.sku.ilike(like),
                Product.barcode.ilike(like),
            ]
        )
    product_candidates = (
        Product.query.filter(or_(*product_filters))
        .order_by(Product.active.desc(), Product.name.asc())
        .limit(20)
        .all()
        if product_filters
        else []
    )

    scored_products: list[tuple[int, Product]] = []
    for product in product_candidates:
        haystack = _normalize_query_token(f"{product.name or ''} {product.sku or ''} {product.barcode or ''}")
        score = 0
        for term in product_terms:
            if term in haystack:
                score += 2 if term.isdigit() else 3
        if score:
            scored_products.append((score, product))
    scored_products.sort(key=lambda item: (-item[0], item[1].name or ""))
    if scored_products:
        best_score = scored_products[0][0]
        if best_score >= 5:
            products = [product for score, product in scored_products if score == best_score][:3]
        else:
            products = [product for _score, product in scored_products[:5]]
    else:
        products = []

    reserved = _reserved_stock_map()
    product_rows = []
    for product in products:
        branch_rows = []
        stock_query = BranchStock.query.filter_by(product_id=product.id)
        if target_branch_ids:
            stock_query = stock_query.filter(BranchStock.branch_id.in_(target_branch_ids))
        stock_rows = stock_query.order_by(BranchStock.branch_id.asc()).all()
        stock_by_branch_id = {row.branch_id: row for row in stock_rows}
        visible_branches = branch_matches or branches
        for branch in visible_branches:
            row = stock_by_branch_id.get(branch.id)
            qty = int(row.quantity or 0) if row else 0
            reserved_qty = int(reserved.get((branch.id, product.id), 0) or 0)
            branch_rows.append(
                {
                    "branch_id": branch.id,
                    "branch_name": branch.name,
                    "system_qty": qty,
                    "reserved_ordered_or_shipping": reserved_qty,
                    "salable_qty": qty - reserved_qty,
                    "opening_stock": int(row.opening_stock or 0) if row else 0,
                }
            )
        recent_orders = []
        if scope.get("orders"):
            order_branch_expr = func.coalesce(OrderItem.fulfillment_branch_id, Invoice.branch_id)
            order_query = (
                db.session.query(OrderItem, Invoice, Branch)
                .join(Invoice, Invoice.id == OrderItem.invoice_id)
                .outerjoin(Branch, Branch.id == order_branch_expr)
                .filter(OrderItem.product_id == product.id)
                .filter(Invoice.status.in_(["تم الطلب", "جاري الشحن", "تم التوصيل", "واصل", "تم التسليم"]))
            )
            if target_branch_ids:
                order_query = order_query.filter(order_branch_expr.in_(target_branch_ids))
            order_rows = order_query.order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(10).all()
            for item, invoice, branch in order_rows:
                recent_orders.append(
                    {
                        "invoice_id": invoice.id,
                        "status": invoice.status,
                        "payment_status": invoice.payment_status,
                        "branch_id": (branch.id if branch else None),
                        "branch_name": (branch.name if branch else "غير محدد"),
                        "quantity": int(item.quantity or 0),
                        "unit_price": int(item.price or 0),
                        "line_total": int(item.total or 0),
                        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
                        "shipping_barcode": invoice.shipping_barcode or "",
                    }
                )
        movements = []
        movement_branch_id = branch_matches[0].id if len(branch_matches) == 1 else None
        try:
            raw_movements = get_product_inventory_movements(product.id, branch_id=movement_branch_id)
            for movement in raw_movements[-8:]:
                movements.append(
                    {
                        "date": str(movement.get("date") or ""),
                        "type": movement.get("type_ar") or movement.get("type") or "",
                        "in": int(movement.get("quantity_in") or 0),
                        "out": int(movement.get("quantity_out") or 0),
                        "balance_after": int(movement.get("balance_after") or 0),
                        "reference": f"{movement.get('reference_type') or ''}#{movement.get('reference_id') or ''}",
                        "description": movement.get("description") or "",
                    }
                )
        except Exception as exc:
            movements.append({"error": str(exc)})

        product_rows.append(
            {
                "product_id": product.id,
                "name": product.name,
                "sku": product.sku or "",
                "barcode": product.barcode or "",
                "active": bool(product.active),
                "total_quantity": int(product.quantity or 0),
                "buy_price": int(product.buy_price or 0),
                "sale_price": int(product.sale_price or 0),
                "branch_stock": branch_rows,
                "recent_orders": recent_orders,
                "recent_movements": movements,
            }
        )

    if product_rows:
        evidence["products"] = product_rows
        evidence["branch_matches"] = [{"id": b.id, "name": b.name, "code": b.code} for b in branch_matches]
        evidence["scope_note"] = (
            "، ".join(b.name for b in branch_matches if b.name)
            if branch_matches
            else "كل الفروع"
        )
    else:
        low_rows = (
            db.session.query(Product, BranchStock, Branch)
            .join(BranchStock, BranchStock.product_id == Product.id)
            .join(Branch, Branch.id == BranchStock.branch_id)
            .filter(Product.active == True)  # noqa: E712
            .filter(BranchStock.quantity <= BranchStock.low_stock_threshold)
            .order_by(BranchStock.quantity.asc(), Product.name.asc())
            .limit(12)
            .all()
        )
        evidence["low_stock_samples"] = [
            {
                "product_id": product.id,
                "product_name": product.name,
                "branch_id": branch.id,
                "branch_name": branch.name,
                "qty": int(stock.quantity or 0),
                "threshold": int(stock.low_stock_threshold or 0),
            }
            for product, stock, branch in low_rows
        ]
    return evidence


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _find_header_row(ws) -> tuple[int, dict[str, int]]:
    aliases = {
        "branch_id": {"رقم الفرع", "branch id", "branch_id"},
        "product_id": {"رقم المنتج", "product id", "product_id"},
        "branch_name": {"الفرع", "branch"},
        "product_name": {"المنتج", "product", "اسم المنتج"},
        "sku": {"sku", "SKU"},
        "barcode": {"الباركود", "barcode"},
        "system_qty": {"كمية النظام بالفرع", "كمية النظام", "system qty", "system_qty"},
        "actual_qty": {"الكمية الفعلية", "الجرد الفعلي", "actual qty", "actual_qty"},
        "note": {"ملاحظة الجرد", "ملاحظة", "note"},
    }
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 40)):
        cells = {_normalize_text(cell.value): cell.column for cell in row if _normalize_text(cell.value)}
        lower_cells = {key.lower(): col for key, col in cells.items()}
        found: dict[str, int] = {}
        for field, names in aliases.items():
            for name in names:
                if name in cells:
                    found[field] = cells[name]
                    break
                if name.lower() in lower_cells:
                    found[field] = lower_cells[name.lower()]
                    break
        if "product_id" in found and "actual_qty" in found:
            return row[0].row, found
    raise ValueError("لم أجد أعمدة الجرد المطلوبة داخل ملف Excel")


def parse_inventory_audit_workbook(file_path: str) -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(file_path, data_only=False, read_only=True)
    ws = wb["الجرد"] if "الجرد" in wb.sheetnames else wb[wb.sheetnames[0]]
    header_row, columns = _find_header_row(ws)
    rows: list[dict] = []
    errors: list[str] = []

    def cell_value(row, field):
        idx = columns.get(field)
        if not idx:
            return None
        return row[idx - 1].value

    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
        product_id_raw = cell_value(row, "product_id")
        actual_raw = cell_value(row, "actual_qty")
        if product_id_raw in (None, "") and actual_raw in (None, ""):
            continue
        try:
            product_id = int(float(product_id_raw))
        except (TypeError, ValueError):
            continue
        branch_id = None
        branch_id_raw = cell_value(row, "branch_id")
        try:
            branch_id = int(float(branch_id_raw)) if branch_id_raw not in (None, "") else None
        except (TypeError, ValueError):
            branch_id = None
        try:
            actual_qty = int(float(actual_raw)) if actual_raw not in (None, "") else None
        except (TypeError, ValueError):
            errors.append(f"كمية فعلية غير صالحة للمنتج {product_id}: {actual_raw}")
            continue
        try:
            system_qty = int(float(cell_value(row, "system_qty") or 0))
        except (TypeError, ValueError):
            system_qty = 0
        rows.append(
            {
                "branch_id": branch_id,
                "product_id": product_id,
                "branch_name": _normalize_text(cell_value(row, "branch_name")),
                "product_name": _normalize_text(cell_value(row, "product_name")),
                "sku": _normalize_text(cell_value(row, "sku")),
                "barcode": _normalize_text(cell_value(row, "barcode")),
                "system_qty_file": system_qty,
                "actual_qty": actual_qty,
                "note": _normalize_text(cell_value(row, "note")),
            }
        )
    return {"sheet": ws.title, "rows": rows, "errors": errors, "row_count": len(rows)}


def save_uploaded_file(file_storage: FileStorage, *, employee_id: int | None, session_id: int | None = None) -> AIUploadedFile:
    if not file_storage or not file_storage.filename:
        raise ValueError("لم يتم اختيار ملف")
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError("ارفع ملف Excel بصيغة .xlsx أو .xlsm")

    upload_root = Path(current_app.root_path) / "uploads" / "ai_assistant" / datetime.utcnow().strftime("%Y%m%d")
    upload_root.mkdir(parents=True, exist_ok=True)
    original = file_storage.filename
    safe_name = secure_filename(original) or f"audit{ext}"
    stored_name = f"{datetime.utcnow().strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"
    stored_path = upload_root / stored_name
    file_storage.save(stored_path)

    uploaded = AIUploadedFile(
        session_id=session_id,
        employee_id=employee_id,
        original_name=original,
        stored_path=str(stored_path),
        size_bytes=stored_path.stat().st_size,
        file_type="inventory_audit",
    )
    try:
        parsed = parse_inventory_audit_workbook(str(stored_path))
        preview_rows = parsed["rows"][:8]
        uploaded.status = "parsed"
        uploaded.set_preview(
            {
                "row_count": parsed["row_count"],
                "errors": parsed["errors"][:10],
                "rows": preview_rows,
            }
        )
    except Exception as exc:
        uploaded.status = "error"
        uploaded.error_message = str(exc)
        uploaded.set_preview({"error": str(exc)})
    db.session.add(uploaded)
    db.session.flush()
    _log_tool(
        "excel.parse_inventory_audit",
        session_id=session_id,
        employee_id=employee_id,
        input_data={"filename": original},
        output_data=uploaded.get_preview(),
        status="success" if uploaded.status == "parsed" else "error",
        error=uploaded.error_message,
    )
    return uploaded


def _product_label(product: Product | None, fallback: str = "") -> str:
    return (product.name if product else fallback) or "منتج غير معروف"


def _branch_label(branch: Branch | None, fallback: str = "") -> str:
    return (branch.name if branch else fallback) or "فرع غير معروف"


def build_inventory_reconcile_plan(
    upload_ids: list[int],
    *,
    employee_id: int | None,
    session_id: int | None = None,
) -> tuple[AIActionPlan | None, dict]:
    ensure_product_schema()
    ensure_branch_schema()
    uploads = AIUploadedFile.query.filter(AIUploadedFile.id.in_(upload_ids)).all() if upload_ids else []
    parsed_rows: list[dict] = []
    parse_errors: list[str] = []
    for uploaded in uploads:
        if uploaded.status != "parsed":
            parse_errors.append(f"{uploaded.original_name}: {uploaded.error_message or 'غير مقروء'}")
            continue
        parsed = parse_inventory_audit_workbook(uploaded.stored_path)
        parse_errors.extend(parsed.get("errors") or [])
        parsed_rows.extend(parsed.get("rows") or [])

    if not parsed_rows:
        return None, {"errors": parse_errors or ["لا توجد أسطر جرد فعلية مقروءة"], "rows": 0}

    reserved = _reserved_stock_map()
    branches_by_id = {b.id: b for b in Branch.query.all()}
    products_by_id = {p.id: p for p in Product.query.all()}
    default_branch = get_default_branch()

    diffs: dict[tuple[int, int], dict] = {}
    issues: list[dict] = []
    for row in parsed_rows:
        product_id = int(row["product_id"])
        product = products_by_id.get(product_id)
        if not product:
            issues.append({"severity": "warning", "message": f"المنتج رقم {product_id} موجود بالملف وغير موجود بالنظام"})
            continue
        branch_id = row.get("branch_id") or (default_branch.id if default_branch else None)
        if not branch_id:
            issues.append({"severity": "critical", "message": f"لا يمكن تحديد فرع المنتج {product.name}"})
            continue
        actual_qty = row.get("actual_qty")
        if actual_qty is None:
            continue
        actual_qty = int(actual_qty)
        reserved_qty = int(reserved.get((int(branch_id), product_id), 0))
        target_salable = actual_qty - reserved_qty
        current_salable = get_branch_stock(int(branch_id), product_id)
        if target_salable < 0:
            issues.append(
                {
                    "severity": "critical",
                    "branch_id": branch_id,
                    "product_id": product_id,
                    "message": f"الحجز ({reserved_qty}) أكبر من الجرد الفعلي ({actual_qty}) للمنتج {product.name}",
                }
            )
            continue
        diff = target_salable - current_salable
        if diff:
            diffs[(int(branch_id), product_id)] = {
                "branch_id": int(branch_id),
                "product_id": product_id,
                "actual_qty": actual_qty,
                "reserved_qty": reserved_qty,
                "target_salable": target_salable,
                "current_salable": current_salable,
                "diff": diff,
                "file_note": row.get("note") or "",
            }

    plan = AIActionPlan(
        session_id=session_id,
        created_by_id=employee_id,
        title="خطة تسوية جرد المخزون",
        plan_type="inventory_reconcile",
        status="draft",
        summary="خطة مقترحة فقط. لا يتم تعديل المخزون إلا بعد موافقة الأدمن وتنفيذ الخطة.",
        risk_level="high" if issues else "medium",
    )
    plan.set_impact(
        {
            "uploads": [u.original_name for u in uploads],
            "parsed_rows": len(parsed_rows),
            "issues": issues[:80],
            "rule": "الجرد الفعلي يشمل تم الطلب وجاري الشحن؛ القابل للبيع = الجرد الفعلي - المحجوز.",
        }
    )
    db.session.add(plan)
    db.session.flush()

    positives = [dict(v) for v in diffs.values() if v["diff"] > 0]
    negatives = [dict(v) for v in diffs.values() if v["diff"] < 0]
    positives.sort(key=lambda x: (x["product_id"], -x["diff"]))
    negatives.sort(key=lambda x: (x["product_id"], x["diff"]))

    transfer_count = 0
    for pos in positives:
        needed = int(pos["diff"])
        for neg in [n for n in negatives if n["product_id"] == pos["product_id"] and int(n["diff"]) < 0]:
            if needed <= 0:
                break
            available_extra = abs(int(neg["diff"]))
            qty = min(needed, available_extra)
            if qty <= 0:
                continue
            product = products_by_id.get(pos["product_id"])
            from_branch = branches_by_id.get(neg["branch_id"])
            to_branch = branches_by_id.get(pos["branch_id"])
            item = AIActionItem(
                plan_id=plan.id,
                item_type="inventory_transfer",
                target_type="product",
                target_id=pos["product_id"],
                title=f"تحويل {qty} من {_branch_label(from_branch)} إلى {_branch_label(to_branch)}",
                description=f"نقل فرق جرد للمنتج {_product_label(product)} بدل تسوية منفصلة.",
            )
            item.set_before(
                {
                    "from_branch_stock": get_branch_stock(neg["branch_id"], pos["product_id"]),
                    "to_branch_stock": get_branch_stock(pos["branch_id"], pos["product_id"]),
                }
            )
            item.set_after(
                {
                    "from_branch_stock": get_branch_stock(neg["branch_id"], pos["product_id"]) - qty,
                    "to_branch_stock": get_branch_stock(pos["branch_id"], pos["product_id"]) + qty,
                }
            )
            item.set_payload(
                {
                    "from_branch_id": neg["branch_id"],
                    "to_branch_id": pos["branch_id"],
                    "product_id": pos["product_id"],
                    "quantity": qty,
                    "reason": "تسوية فرق جرد بواسطة مساعد Finora",
                }
            )
            db.session.add(item)
            transfer_count += 1
            needed -= qty
            pos["diff"] -= qty
            neg["diff"] += qty

    adjustment_count = 0
    for data in positives + negatives:
        adjustment = int(data["diff"])
        if adjustment == 0:
            continue
        product = products_by_id.get(data["product_id"])
        branch = branches_by_id.get(data["branch_id"])
        action = "زيادة" if adjustment > 0 else "نقص"
        item = AIActionItem(
            plan_id=plan.id,
            item_type="stock_adjustment",
            target_type="branch_stock",
            target_id=data["product_id"],
            title=f"تسوية {action} {abs(adjustment)} من {_product_label(product)} في {_branch_label(branch)}",
            description="تسوية متبقي فرق الجرد بعد احتساب المحجوز وجاري الشحن والتحويلات الممكنة.",
        )
        before_qty = get_branch_stock(data["branch_id"], data["product_id"])
        item.set_before(
            {
                "branch_stock": before_qty,
                "actual_physical": data["actual_qty"],
                "reserved_orders": data["reserved_qty"],
                "target_salable": data["target_salable"],
            }
        )
        item.set_after({"branch_stock": max(0, before_qty + adjustment)})
        item.set_payload(
            {
                "branch_id": data["branch_id"],
                "product_id": data["product_id"],
                "adjustment": adjustment,
                "reason": "تسوية فرق جرد بواسطة مساعد Finora",
                "file_note": data.get("file_note") or "",
            }
        )
        db.session.add(item)
        adjustment_count += 1

    if transfer_count == 0 and adjustment_count == 0:
        plan.summary = "لم أجد فروقات قابلة للتنفيذ بعد احتساب المحجوز وجاري الشحن."
    else:
        plan.summary = f"الخطة تحتوي {transfer_count} تحويل و{adjustment_count} تسوية مخزون."

    _log_tool(
        "inventory.build_reconcile_plan",
        session_id=session_id,
        plan_id=plan.id,
        employee_id=employee_id,
        input_data={"upload_ids": upload_ids},
        output_data={"items": transfer_count + adjustment_count, "issues": len(issues), "errors": parse_errors[:20]},
        mode="plan",
    )
    return plan, {"errors": parse_errors, "issues": issues, "items": transfer_count + adjustment_count}


def _extract_order_ids(message: str) -> list[int]:
    text = message or ""
    text = re.sub(r"(?:باركود|barcode)\s*[:：]?\s*[\w\-]+", " ", text, flags=re.IGNORECASE)

    ids: list[int] = []
    explicit_patterns = (
        r"#\s*(\d{1,8})",
        r"(?:طلب|الطلب|فاتورة|الفاتورة|رقم)\s*#?\s*(\d{1,8})",
    )

    for pattern in explicit_patterns:
        for raw in re.findall(pattern, text):
            try:
                value = int(raw)
            except ValueError:
                continue
            if value > 0 and value not in ids:
                ids.append(value)

    if ids:
        return ids[:25]

    for raw in re.findall(r"(?<![\w\-])(\d{1,8})(?![\w\-])", text):
        try:
            value = int(raw)
        except ValueError:
            continue
        if value > 0 and value not in ids:
            ids.append(value)
    return ids[:25]


def _detect_order_action(message: str) -> str | None:
    text = message or ""
    if any(word in text for word in ("سدد", "تسديد", "مسدد", "تحصيل", "ادفع", "دفع الطلب")):
        return "mark_paid"
    if any(word in text for word in ("الغاء", "إلغاء", "ألغي", "لغي", "ملغي", "احذف الطلب")):
        return "cancel"
    if any(word in text for word in ("ارجاع", "إرجاع", "رجع", "راجع", "مرتجع", "رجيع")):
        return "return"
    return None


def build_order_action_plan(
    message: str,
    *,
    employee_id: int | None,
    session_id: int | None = None,
) -> AIActionPlan | None:
    action = _detect_order_action(message)
    order_ids = _extract_order_ids(message)
    if not action or not order_ids:
        return None

    _ensure_audit_schema()
    orders = Invoice.query.filter(Invoice.id.in_(order_ids)).order_by(Invoice.id.asc()).all()
    if not orders:
        return None

    action_label = {
        "mark_paid": "تسديد",
        "cancel": "إلغاء",
        "return": "إرجاع",
    }.get(action, action)
    plan = AIActionPlan(
        session_id=session_id,
        created_by_id=employee_id,
        title=f"خطة {action_label} طلبات",
        plan_type="order_action",
        status="draft",
        summary=f"خطة مقترحة لـ {action_label} {len(orders)} طلب. التنفيذ يحتاج موافقة أدمن.",
        risk_level="high" if action in {"cancel", "return"} else "medium",
    )
    missing = sorted(set(order_ids) - {int(o.id) for o in orders})
    plan.set_impact(
        {
            "requested_order_ids": order_ids,
            "missing_order_ids": missing,
            "action": action,
            "note": "التنفيذ يستخدم نفس منطق الطلبات الرسمي مع سجل التحصيل/المخزون.",
        }
    )
    db.session.add(plan)
    db.session.flush()

    barcode_match = re.search(r"(?:باركود|barcode)\s*[:：]?\s*([A-Za-z0-9\\-_/]+)", message or "", flags=re.IGNORECASE)
    scanned_barcode = barcode_match.group(1).strip() if barcode_match else ""

    for order in orders:
        before = {
            "status": order.status,
            "payment_status": order.payment_status,
            "paid_amount": int(order.paid_amount or 0),
            "total": int(order.total or 0),
        }
        after = dict(before)
        if action == "mark_paid":
            after.update({"status": "تم التوصيل", "payment_status": "مسدد", "paid_amount": int(order.total or 0)})
        elif action == "cancel":
            after.update({"status": "ملغي", "payment_status": "ملغي", "paid_amount": 0})
        elif action == "return":
            after.update({"status": "مرتجع", "payment_status": "مرتجع", "paid_amount": 0})
        item = AIActionItem(
            plan_id=plan.id,
            item_type="order_update",
            target_type="invoice",
            target_id=order.id,
            title=f"{action_label} الطلب #{order.id}",
            description=f"الزبون: {order.customer_name or '-'} | المبلغ: {int(order.total or 0):,} د.ع",
        )
        item.set_before(before)
        item.set_after(after)
        item.set_payload(
            {
                "invoice_id": order.id,
                "action": action,
                "barcode": scanned_barcode,
            }
        )
        db.session.add(item)

    _log_tool(
        "orders.build_action_plan",
        session_id=session_id,
        plan_id=plan.id,
        employee_id=employee_id,
        input_data={"message": message, "order_ids": order_ids},
        output_data={"orders": len(orders), "missing": missing, "action": action},
        mode="plan",
    )
    return plan


def build_supplier_ledger_plan(*, employee_id: int | None, session_id: int | None = None) -> AIActionPlan | None:
    report = audit_and_repair_supplier_ledgers(dry_run=True).to_dict()
    differences = report.get("differences") or []
    if not differences:
        return None

    plan = AIActionPlan(
        session_id=session_id,
        created_by_id=employee_id,
        title="خطة إصلاح أرصدة الموردين",
        plan_type="supplier_ledger_fix",
        status="draft",
        summary=f"وجدت {len(differences)} مورد يحتاج تصحيح. التنفيذ يحتاج موافقة أدمن.",
        risk_level="high",
    )
    plan.set_impact(report)
    db.session.add(plan)
    db.session.flush()

    for diff in differences[:200]:
        supplier_id = int(diff["supplier_id"])
        item = AIActionItem(
            plan_id=plan.id,
            item_type="supplier_ledger_fix",
            target_type="supplier",
            target_id=supplier_id,
            title=f"تصحيح رصيد المورد {diff.get('name') or supplier_id}",
            description=(
                f"الدين {int(diff.get('current_debt') or 0):,} -> {int(diff.get('expected_debt') or 0):,}، "
                f"المدفوع {int(diff.get('current_paid') or 0):,} -> {int(diff.get('expected_paid') or 0):,}"
            ),
        )
        item.set_before(
            {
                "total_debt": int(diff.get("current_debt") or 0),
                "total_paid": int(diff.get("current_paid") or 0),
                "remaining": int(diff.get("current_remaining") or 0),
            }
        )
        item.set_after(
            {
                "total_debt": int(diff.get("expected_debt") or 0),
                "total_paid": int(diff.get("expected_paid") or 0),
                "remaining": int(diff.get("expected_remaining") or 0),
            }
        )
        item.set_payload(
            {
                "supplier_id": supplier_id,
                "expected_debt": int(diff.get("expected_debt") or 0),
                "expected_paid": int(diff.get("expected_paid") or 0),
            }
        )
        db.session.add(item)

    _log_tool(
        "suppliers.build_ledger_fix_plan",
        session_id=session_id,
        plan_id=plan.id,
        employee_id=employee_id,
        output_data={"differences": len(differences)},
        mode="plan",
    )
    return plan


def build_shipping_opening_balance_plan(
    message: str,
    *,
    employee_id: int | None,
    session_id: int | None = None,
) -> AIActionPlan | None:
    text = message or ""
    if not any(word in text for word in ("شركة النقل", "شركات النقل", "شحن", "النقل")):
        return None
    amount_match = re.search(r"(\d[\d,]{4,})", text)
    if not amount_match:
        return None
    target_amount = int(amount_match.group(1).replace(",", ""))

    company = None
    id_match = re.search(r"(?:شركة النقل|شحن|النقل)\s*(?:رقم)?\s*#?\s*(\d+)", text)
    if id_match:
        company = ShippingCompany.query.get(int(id_match.group(1)))
    if not company:
        companies = ShippingCompany.query.order_by(ShippingCompany.id.asc()).all()
        if len(companies) == 1:
            company = companies[0]
    if not company:
        return None

    plan = AIActionPlan(
        session_id=session_id,
        created_by_id=employee_id,
        title="خطة تعديل رصيد افتتاحي لشركة نقل",
        plan_type="shipping_opening_balance_fix",
        status="draft",
        summary=f"تعديل رصيد {company.name} الافتتاحي إلى {target_amount:,} د.ع كذمة مدينة لصالح الشركة.",
        risk_level="high",
    )
    plan.set_impact(
        {
            "shipping_company_id": company.id,
            "shipping_company": company.name,
            "meaning": "هذا الرصيد ذمة إلنا عند شركة النقل وليس ديناً علينا.",
        }
    )
    db.session.add(plan)
    db.session.flush()

    item = AIActionItem(
        plan_id=plan.id,
        item_type="shipping_opening_balance_fix",
        target_type="shipping_company",
        target_id=company.id,
        title=f"تعديل رصيد {company.name}",
        description=f"الرصيد الافتتاحي {int(company.opening_balance or 0):,} -> {target_amount:,} د.ع",
    )
    item.set_before({"opening_balance": int(company.opening_balance or 0)})
    item.set_after({"opening_balance": target_amount})
    item.set_payload({"shipping_company_id": company.id, "opening_balance": target_amount})
    db.session.add(item)
    _log_tool(
        "shipping.build_opening_balance_plan",
        session_id=session_id,
        plan_id=plan.id,
        employee_id=employee_id,
        input_data={"message": message},
        output_data={"shipping_company_id": company.id, "opening_balance": target_amount},
        mode="plan",
    )
    return plan


def _get_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("openai_api_key") or ""
    if key.strip():
        return key.strip()
    try:
        from flask import g
        old_tenant = getattr(g, "tenant", None)
        g.tenant = None
        from models.core.global_setting import GlobalSetting

        key = (GlobalSetting.get_setting("OPENAI_API_KEY", "") or "").strip()
        g.tenant = old_tenant
    except Exception:
        key = ""
    return key


def _assistant_response_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "key_points": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "next_steps": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "needs_admin_approval": {"type": "boolean"},
        },
        "required": ["answer", "evidence", "key_points", "risks", "next_steps", "needs_admin_approval"],
    }


def _safe_json_loads(text_value: str) -> dict | None:
    if not text_value:
        return None
    try:
        parsed = json.loads(text_value)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", text_value, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _format_structured_ai_reply(data: dict | None, fallback: str = "") -> str:
    if not data:
        return (fallback or "").strip()
    lines: list[str] = []
    answer = _normalize_text(data.get("answer"))
    if answer:
        lines.append(answer)
    sections = [
        ("الأدلة من النظام", data.get("evidence")),
        ("النقاط المهمة", data.get("key_points")),
        ("المخاطر", data.get("risks")),
        ("الخطوات المقترحة", data.get("next_steps")),
    ]
    for title, values in sections:
        if not isinstance(values, list) or not values:
            continue
        clean_values = [_normalize_text(v) for v in values if _normalize_text(v)]
        if not clean_values:
            continue
        lines.append(f"\n{title}:")
        lines.extend(f"- {value}" for value in clean_values[:8])
    if data.get("needs_admin_approval"):
        lines.append("\nأي تعديل فعلي يحتاج خطة وموافقة أدمن قبل التنفيذ.")
    return "\n".join(lines).strip() or (fallback or "").strip()


def _call_openai_narrative(message: str, snapshot: dict, local_findings: dict | None = None) -> tuple[bool, str]:
    key = _get_openai_key()
    if not key:
        return False, "مفتاح OpenAI غير مكوّن، لذلك استخدمت التحليل المحلي فقط."
    try:
        import openai
    except ImportError:
        return False, "حزمة openai غير مثبتة، لذلك استخدمت التحليل المحلي فقط."

    model = os.environ.get("FINORA_AI_MODEL") or os.environ.get("OPENAI_ANALYSIS_MODEL") or "gpt-4o-mini"
    system_text = (
        "أنت مساعد Finora الإداري. جاوب بالعربية العراقية المختصرة. "
        "لا تدّعي تنفيذ أي تعديل. أي تعديل لازم يكون خطة موافقة أدمن. "
        "اعتمد فقط على بيانات system_snapshot وlocal_findings. إذا local_findings.query_evidence موجود، "
        "لازم تذكر أرقام الأدلة منه مثل product_id، invoice_id، الفرع، الكمية، المحجوز، وآخر الحركات. "
        "إذا local_findings.query_evidence.branch_matches يحتوي فرع محدد، احصر الطلبات والحركات والاستنتاج بهذا الفرع فقط. "
        "ممنوع تقول 'ممكن' أو 'احتمال' كسبب رئيسي إذا ماكو دليل في query_evidence؛ قل 'ما عندي دليل كافي' واذكر شنو لازم نفحص. "
        "افصل بوضوح بين الاستنتاج المثبت من الأرقام وبين المخاطر المحتملة التي تحتاج فحص إضافي. "
        "لا تخترع اسم منتج أو فرع أو رقم طلب غير موجود في البيانات المعطاة. "
        "انتبه لقواعد Finora الخاصة: الجرد الفعلي يشمل تم الطلب وجاري الشحن، "
        "وسعر المنتج في الفاتورة لا يتغير بسبب أجرة التوصيل، ومبالغ شركات النقل ذمم إلنا وليست ديناً علينا، "
        "وحركة الصندوق اليدوية بلا سبب تعتبر خطأ إدخال محتمل. "
        "أرجع JSON مطابق للمخطط: answer, evidence, key_points, risks, next_steps, needs_admin_approval."
    )
    payload = {
        "user_message": message,
        "system_snapshot": snapshot,
        "local_findings": local_findings or {},
        "tool_policy": {
            "read_tools": [
                "system_snapshot",
                "accounting_audit",
                "inventory_audit_excel",
                "orders_lookup",
                "supplier_ledger_audit",
                "shipping_company_audit",
            ],
            "plan_tools": [
                "inventory_reconcile_plan",
                "order_action_plan",
                "supplier_ledger_fix_plan",
                "shipping_opening_balance_plan",
            ],
            "execution_rule": "GPT لا ينفذ الأدوات. التنفيذ يتم فقط لخطة approved داخل النظام.",
        },
    }
    schema = _assistant_response_schema()
    client = None
    try:
        client = openai.OpenAI(api_key=key)
        if hasattr(client, "responses"):
            try:
                response = client.responses.create(
                    model=model,
                    instructions=system_text,
                    input=json.dumps(payload, ensure_ascii=False),
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "finora_assistant_reply",
                            "schema": schema,
                            "strict": True,
                        }
                    },
                    max_output_tokens=1800,
                    timeout=30,
                )
            except TypeError:
                response = client.responses.create(
                    model=model,
                    instructions=system_text,
                    input=json.dumps(payload, ensure_ascii=False),
                    max_output_tokens=1800,
                    timeout=30,
                )
            text = getattr(response, "output_text", "") or ""
            return True, _format_structured_ai_reply(_safe_json_loads(text), text or "تم تحليل البيانات.")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_text},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "finora_assistant_reply",
                    "strict": True,
                    "schema": schema,
                },
            },
            max_tokens=1600,
            timeout=30,
        )
        choice = response.choices[0] if response.choices else None
        text = choice.message.content if choice and choice.message else ""
        return True, _format_structured_ai_reply(_safe_json_loads(text or ""), text or "")
    except Exception as exc:
        current_app.logger.warning("OpenAI structured narrative failed: %s", exc)
        if client is None:
            return False, "تعذر تهيئة اتصال GPT، رجعت لك التحليل المحلي وخطة التنفيذ إن وجدت."
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                max_tokens=1600,
                timeout=30,
            )
            choice = response.choices[0] if response.choices else None
            text = choice.message.content if choice and choice.message else ""
            return True, _format_structured_ai_reply(_safe_json_loads(text or ""), text or "")
        except Exception as fallback_exc:
            current_app.logger.warning("OpenAI narrative fallback failed: %s", fallback_exc)
            return False, "تعذر الاتصال بـ GPT، رجعت لك التحليل المحلي وخطة التنفيذ إن وجدت."


def handle_chat_send(
    *,
    employee_id: int | None,
    message: str,
    session_id: int | None = None,
    upload_ids: list[int] | None = None,
) -> dict:
    chat = get_or_create_chat_session(employee_id, session_id)
    add_chat_message(chat, "user", message, {"upload_ids": upload_ids or []})
    upload_ids = [int(x) for x in (upload_ids or []) if str(x).isdigit()]

    scope = _assistant_read_scope(employee_id)
    snapshot = collect_system_snapshot(employee_id=employee_id)
    local_findings: dict[str, Any] = {"snapshot": snapshot}
    query_evidence = _collect_query_evidence(message or "", scope)
    if query_evidence.get("products") or query_evidence.get("low_stock_samples"):
        local_findings["query_evidence"] = query_evidence
    plan = None

    wants_inventory_plan = bool(upload_ids) or any(word in (message or "") for word in ("جرد", "فروقات", "فرق", "حول", "نقص", "زايد"))
    if wants_inventory_plan and upload_ids and scope["inventory"]:
        plan, plan_meta = build_inventory_reconcile_plan(upload_ids, employee_id=employee_id, session_id=chat.id)
        local_findings["inventory_plan"] = plan_meta
    elif wants_inventory_plan and upload_ids:
        local_findings["inventory_plan"] = {"restricted": True, "message": "تحليل وتنفيذ الجرد يحتاج صلاحية إدارة المخزون."}

    order_plan = build_order_action_plan(message, employee_id=employee_id, session_id=chat.id) if scope["order_manage"] else None
    if order_plan:
        plan = order_plan
        local_findings["order_plan"] = {"id": order_plan.id, "items": len(order_plan.items)}
    elif _detect_order_action(message) and not scope["order_manage"]:
        local_findings["order_plan"] = {"restricted": True, "message": "اقتراح تسديد/إلغاء/إرجاع الطلب يحتاج صلاحية إدارة الطلبات."}

    if any(word in (message or "") for word in ("مورد", "موردين", "الموردين", "ديون المورد")) and scope["suppliers"]:
        supplier_plan = build_supplier_ledger_plan(employee_id=employee_id, session_id=chat.id)
        if supplier_plan:
            plan = supplier_plan
            local_findings["supplier_plan"] = {"id": supplier_plan.id, "items": len(supplier_plan.items)}
    elif any(word in (message or "") for word in ("مورد", "موردين", "الموردين", "ديون المورد")):
        local_findings["supplier_plan"] = {"restricted": True, "message": "تحليل أرصدة الموردين يحتاج صلاحية الموردين."}

    shipping_plan = build_shipping_opening_balance_plan(message, employee_id=employee_id, session_id=chat.id) if scope["shipping"] else None
    if shipping_plan:
        plan = shipping_plan
        local_findings["shipping_plan"] = {"id": shipping_plan.id, "items": len(shipping_plan.items)}
    elif any(word in (message or "") for word in ("نقل", "شحن", "شركة النقل", "شركات النقل")) and not scope["shipping"]:
        local_findings["shipping_plan"] = {"restricted": True, "message": "تحليل شركات النقل يحتاج صلاحية الشحن."}

    if any(word in (message or "") for word in ("محاسبي", "حساب", "هامش", "سالب", "تقرير", "اخطاء", "أخطاء", "صندوق", "كاش", "نقد", "فروقات")) and (scope["financial"] or scope["reports"]):
        audit = audit_accounting_integrity(limit=120)
        local_findings["accounting_audit"] = audit.get("summary", {})
        local_findings["accounting_audit_samples"] = {
            "stock_imbalances": (audit.get("stock_imbalances") or [])[:5],
            "invoice_total_mismatches": (audit.get("invoice_total_mismatches") or [])[:5],
            "negative_margin_items": (audit.get("negative_margin_items") or [])[:5],
            "status_inconsistencies": (audit.get("status_inconsistencies") or [])[:5],
        }
        _log_tool(
            "accounting.audit_integrity",
            session_id=chat.id,
            employee_id=employee_id,
            input_data={"limit": 120},
            output_data=audit.get("summary", {}),
        )
    elif any(word in (message or "") for word in ("محاسبي", "حساب", "هامش", "سالب", "تقرير", "اخطاء", "أخطاء", "صندوق", "كاش", "نقد", "فروقات")):
        local_findings["accounting_audit"] = {"restricted": True, "message": "التدقيق المحاسبي يحتاج صلاحية التقارير أو المالية."}

    ok, ai_text = _call_openai_narrative(message, snapshot, local_findings)
    if not ai_text:
        ai_text = "حللت البيانات المحلية. إذا تريد تنفيذ أي تغيير راجع خطة التنفيذ واضغط موافقة أدمن ثم تنفيذ."
    evidence_text = _local_evidence_text(local_findings.get("query_evidence") or {})
    if evidence_text and "الأدلة المحلية المباشرة" not in ai_text:
        ai_text = f"{evidence_text}\n\nالاستنتاج:\n{ai_text}"
    if plan:
        ai_text = f"{ai_text}\n\nتم إنشاء خطة تنفيذ #{plan.id}: {plan.summary}"
    elif not ok:
        ai_text = f"{ai_text}\n\n{_local_summary_text(local_findings)}"

    add_chat_message(chat, "assistant", ai_text, {"action_plan_id": plan.id if plan else None, "local_findings": local_findings})
    db.session.commit()
    return {
        "success": True,
        "session_id": chat.id,
        "reply": ai_text,
        "action_plan": _serialize_plan(plan),
        "local_findings": local_findings,
    }


def _local_summary_text(findings: dict) -> str:
    snap = findings.get("snapshot") or {}
    products = snap.get("products") or {}
    orders = snap.get("orders_by_status") or {}
    financial = snap.get("financial") or {}
    lines = [
        f"المنتجات: {products.get('active', 0)} نشط من {products.get('total', 0)}.",
        f"قيمة المخزون: {products.get('stock_value', 0):,} د.ع.",
        f"طلبات تم الطلب: {orders.get('تم الطلب', 0)}، جاري الشحن: {orders.get('جاري الشحن', 0)}.",
        f"ديون الموردين: {financial.get('supplier_debts', 0):,} د.ع، ذمم شركات النقل إلنا: {financial.get('shipping_receivables', 0):,} د.ع.",
    ]
    if findings.get("accounting_audit"):
        audit = findings["accounting_audit"]
        lines.append(
            f"تدقيق محاسبي: اختلاف مخزون {audit.get('stock_imbalances_count', 0)}، فواتير مختلفة {audit.get('invoice_total_mismatches_count', 0)}، هوامش سالبة {audit.get('negative_margin_items_count', 0)}."
        )
    evidence_text = _local_evidence_text(findings.get("query_evidence") or {})
    if evidence_text:
        lines.append(evidence_text)
    return "\n".join(lines)


def _local_evidence_text(evidence: dict) -> str:
    products = evidence.get("products") or []
    if products:
        lines = ["\nالأدلة المحلية المباشرة:"]
        if evidence.get("scope_note"):
            lines.append(f"- نطاق التحليل: {evidence.get('scope_note')}.")
        for product in products[:3]:
            lines.append(
                f"- المنتج #{product.get('product_id')}: {product.get('name')} | إجمالي المخزون {product.get('total_quantity', 0)} | شراء {product.get('buy_price', 0):,} | بيع {product.get('sale_price', 0):,}."
            )
            for stock in (product.get("branch_stock") or [])[:4]:
                lines.append(
                    f"  - {stock.get('branch_name')}: نظام {stock.get('system_qty', 0)}، محجوز/جاري الشحن {stock.get('reserved_ordered_or_shipping', 0)}، قابل للبيع {stock.get('salable_qty', 0)}."
                )
            orders = product.get("recent_orders") or []
            if orders:
                order_bits = [
                    f"#{o.get('invoice_id')} {o.get('status')} {o.get('branch_name')} كمية {o.get('quantity')}"
                    for o in orders[:5]
                ]
                lines.append("  - آخر الطلبات: " + " | ".join(order_bits))
            movements = product.get("recent_movements") or []
            if movements:
                move_bits = [
                    f"{m.get('date')} {m.get('type')} +{m.get('in', 0)}/-{m.get('out', 0)} رصيد {m.get('balance_after', 0)} ({m.get('reference')})"
                    for m in movements[-5:]
                    if not m.get("error")
                ]
                if move_bits:
                    lines.append("  - آخر الحركات: " + " | ".join(move_bits))
        return "\n".join(lines)
    low_stock = evidence.get("low_stock_samples") or []
    if low_stock:
        lines = ["\nعينات منخفضة المخزون من النظام:"]
        for row in low_stock[:8]:
            lines.append(
                f"- {row.get('product_name')} في {row.get('branch_name')}: {row.get('qty')} قطعة، حد التنبيه {row.get('threshold')}."
            )
        return "\n".join(lines)
    return ""


def approve_action_plan(plan_id: int, *, employee_id: int, note: str | None = None) -> AIActionPlan:
    plan = AIActionPlan.query.get_or_404(plan_id)
    if plan.status not in {"draft", "rejected"}:
        raise ValueError("هذه الخطة ليست بانتظار الموافقة")
    plan.status = "approved"
    plan.approved_by_id = employee_id
    plan.approved_at = datetime.utcnow()
    plan.approval_note = note
    _log_tool("action_plan.approve", plan_id=plan.id, employee_id=employee_id, mode="approve")
    db.session.commit()
    return plan


def reject_action_plan(plan_id: int, *, employee_id: int, reason: str | None = None) -> AIActionPlan:
    plan = AIActionPlan.query.get_or_404(plan_id)
    if plan.status == "executed":
        raise ValueError("لا يمكن رفض خطة منفذة")
    plan.status = "rejected"
    plan.rejection_reason = reason or "رفض من الأدمن"
    _log_tool("action_plan.reject", plan_id=plan.id, employee_id=employee_id, mode="reject", input_data={"reason": reason or ""})
    db.session.commit()
    return plan


def validate_action_plan(plan_id: int) -> dict:
    plan = AIActionPlan.query.get_or_404(plan_id)
    errors: list[str] = []
    warnings: list[str] = []
    item_results: list[dict] = []
    for item in plan.items:
        if item.status == "executed":
            item_results.append({"item_id": item.id, "status": "skipped", "message": "منفذ مسبقاً"})
            continue
        result = _preflight_action_item(item)
        item_results.append({"item_id": item.id, **result})
        errors.extend(result.get("errors") or [])
        warnings.extend(result.get("warnings") or [])
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "items": item_results,
    }


def execute_action_plan(plan_id: int, *, employee_id: int) -> AIActionPlan:
    plan = AIActionPlan.query.get_or_404(plan_id)
    if plan.status != "approved":
        raise ValueError("لا يمكن التنفيذ قبل موافقة الأدمن")
    validation = validate_action_plan(plan_id)
    if not validation["ok"]:
        _log_tool(
            "action_plan.preflight_failed",
            plan_id=plan.id,
            employee_id=employee_id,
            mode="validate",
            output_data=validation,
            status="error",
            error="; ".join(validation["errors"][:5]),
        )
        raise ValueError("فشل فحص الخطة قبل التنفيذ: " + " | ".join(validation["errors"][:5]))
    results: list[dict] = []
    try:
        for item in plan.items:
            if item.status == "executed":
                continue
            result = _execute_action_item(item, employee_id=employee_id)
            item.status = "executed"
            item.executed_at = datetime.utcnow()
            item.set_result(result)
            results.append({"item_id": item.id, **result})
        plan.status = "executed"
        plan.executed_by_id = employee_id
        plan.executed_at = datetime.utcnow()
        plan.set_execution_result({"items": results})
        log_activity(
            "execute",
            "ai_assistant",
            f"تنفيذ خطة مساعد Finora #{plan.id}: {plan.title}",
            entity_type="ai_action_plan",
            entity_id=plan.id,
            payload=plan.to_dict(),
            commit=False,
        )
        _log_tool("action_plan.execute", plan_id=plan.id, employee_id=employee_id, mode="execute", output_data={"items": len(results)})
        db.session.commit()
        return plan
    except Exception:
        db.session.rollback()
        raise


def _preflight_action_item(item: AIActionItem) -> dict:
    payload = item.get_payload()
    before = item.get_before()
    errors: list[str] = []
    warnings: list[str] = []

    def changed(label: str, current, expected) -> None:
        if str(current) != str(expected):
            errors.append(f"{item.title}: تغير {label} من {expected} إلى {current} بعد إنشاء الخطة")

    if item.item_type == "inventory_transfer":
        from_branch_id = int(payload.get("from_branch_id") or 0)
        to_branch_id = int(payload.get("to_branch_id") or 0)
        product_id = int(payload.get("product_id") or 0)
        qty = int(payload.get("quantity") or 0)
        if qty <= 0:
            errors.append(f"{item.title}: كمية التحويل غير صالحة")
        from_stock = get_branch_stock(from_branch_id, product_id)
        to_stock = get_branch_stock(to_branch_id, product_id)
        if "from_branch_stock" in before:
            changed("مخزون الفرع المصدر", from_stock, before.get("from_branch_stock"))
        if "to_branch_stock" in before:
            changed("مخزون الفرع الهدف", to_stock, before.get("to_branch_stock"))
        if from_stock < qty:
            errors.append(f"{item.title}: المخزون الحالي في الفرع المصدر ({from_stock}) أقل من كمية التحويل ({qty})")

    elif item.item_type == "stock_adjustment":
        branch_id = int(payload.get("branch_id") or 0)
        product_id = int(payload.get("product_id") or 0)
        adjustment = int(payload.get("adjustment") or 0)
        current = get_branch_stock(branch_id, product_id)
        if "branch_stock" in before:
            changed("مخزون الفرع", current, before.get("branch_stock"))
        if current + adjustment < 0:
            errors.append(f"{item.title}: التسوية تجعل المخزون سالباً ({current + adjustment})")

    elif item.item_type == "order_update":
        invoice = Invoice.query.get(int(payload.get("invoice_id") or 0))
        if not invoice:
            errors.append(f"{item.title}: الطلب غير موجود")
        else:
            changed("حالة الطلب", invoice.status, before.get("status"))
            changed("حالة الدفع", invoice.payment_status, before.get("payment_status"))
            changed("المبلغ المسدد", int(invoice.paid_amount or 0), int(before.get("paid_amount") or 0))
            action = payload.get("action")
            if action == "cancel" and (invoice.status or "").strip() != "تم الطلب":
                errors.append(f"{item.title}: الإلغاء مسموح فقط للطلبات بحالة تم الطلب")
            if action == "return" and not (payload.get("barcode") or "").strip():
                errors.append(f"{item.title}: الإرجاع يحتاج باركود داخل الخطة")
            if action == "mark_paid" and (invoice.status or "").strip() in {"ملغي", "مرتجع", "راجع", "راجعة"}:
                errors.append(f"{item.title}: لا يمكن تسديد طلب ملغي أو راجع")

    elif item.item_type == "supplier_ledger_fix":
        supplier = Supplier.query.get(int(payload.get("supplier_id") or 0))
        if not supplier:
            errors.append(f"{item.title}: المورد غير موجود")
        else:
            changed("دين المورد", int(supplier.total_debt or 0), int(before.get("total_debt") or 0))
            changed("مدفوع المورد", int(supplier.total_paid or 0), int(before.get("total_paid") or 0))

    elif item.item_type == "shipping_opening_balance_fix":
        company = ShippingCompany.query.get(int(payload.get("shipping_company_id") or 0))
        if not company:
            errors.append(f"{item.title}: شركة النقل غير موجودة")
        else:
            changed("الرصيد الافتتاحي", int(company.opening_balance or 0), int(before.get("opening_balance") or 0))

    elif item.item_type == "review_task":
        warnings.append(f"{item.title}: مهمة مراجعة فقط ولا تعدل بيانات")

    else:
        errors.append(f"{item.title}: نوع إجراء غير مدعوم ({item.item_type})")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _execute_action_item(item: AIActionItem, *, employee_id: int) -> dict:
    payload = item.get_payload()
    if item.item_type == "inventory_transfer":
        from_branch_id = int(payload["from_branch_id"])
        to_branch_id = int(payload["to_branch_id"])
        product_id = int(payload["product_id"])
        qty = int(payload["quantity"])
        if qty <= 0:
            raise ValueError("كمية التحويل غير صالحة")
        transfer_deduct(from_branch_id, [(product_id, qty)], sync_product=False)
        transfer_receive(to_branch_id, [(product_id, qty)], sync_product=False)
        sync_product_total(product_id)
        transfer = StockTransfer(
            transfer_no=f"AI-TR-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{item.id}",
            from_branch_id=from_branch_id,
            to_branch_id=to_branch_id,
            status="received",
            note=payload.get("reason") or "تحويل مقترح من مساعد Finora",
            created_by_id=employee_id,
            received_by_id=employee_id,
            sent_at=datetime.utcnow(),
            received_at=datetime.utcnow(),
        )
        db.session.add(transfer)
        db.session.flush()
        db.session.add(
            StockTransferLine(
                transfer_id=transfer.id,
                product_id=product_id,
                quantity=qty,
                quantity_received=qty,
            )
        )
        return {"transfer_id": transfer.id, "product_id": product_id, "quantity": qty}

    if item.item_type == "stock_adjustment":
        branch_id = int(payload["branch_id"])
        product_id = int(payload["product_id"])
        adjustment = int(payload["adjustment"])
        before = get_branch_stock(branch_id, product_id)
        adjust_branch_stock(branch_id, product_id, adjustment, sync_product=True)
        after = get_branch_stock(branch_id, product_id)
        return {"branch_id": branch_id, "product_id": product_id, "before": before, "after": after, "adjustment": adjustment}

    if item.item_type == "order_update":
        invoice = Invoice.query.get(int(payload["invoice_id"]))
        if not invoice:
            raise ValueError("الطلب غير موجود")
        before = {"status": invoice.status, "payment_status": invoice.payment_status, "paid_amount": invoice.paid_amount}
        action = payload.get("action")
        prev_effective_paid = _effective_paid_amount(invoice)
        if action == "mark_paid":
            invoice.payment_status = "مسدد"
            invoice.paid_amount = int(invoice.total or 0)
            if invoice.status not in {"تم التوصيل", "مرتجع", "راجع", "راجعة"}:
                invoice.status = "تم التوصيل"
            from utils.order_shipping import apply_shipping_fee_on_paid_invoice

            apply_shipping_fee_on_paid_invoice(invoice)
        elif action == "cancel":
            process_order_cancel(invoice)
        elif action == "return":
            barcode = (payload.get("barcode") or "").strip()
            if not barcode:
                raise ValueError("إرجاع الطلب يحتاج باركود الطلب أو باركود شركة النقل داخل الخطة")
            process_order_return(invoice, barcode)
        else:
            raise ValueError("نوع تعديل الطلب غير مدعوم")
        delta_pay = _effective_paid_amount(invoice) - prev_effective_paid
        append_payment_ledger_delta(invoice.id, delta_pay)
        sync_delivery_expense_for_invoice(invoice)
        after = {"status": invoice.status, "payment_status": invoice.payment_status, "paid_amount": invoice.paid_amount}
        return {"invoice_id": invoice.id, "before": before, "after": after}

    if item.item_type == "supplier_ledger_fix":
        supplier = Supplier.query.get(int(payload["supplier_id"]))
        if not supplier:
            raise ValueError("المورد غير موجود")
        before = {
            "total_debt": int(supplier.total_debt or 0),
            "total_paid": int(supplier.total_paid or 0),
        }
        supplier.total_debt = int(payload["expected_debt"])
        supplier.total_paid = int(payload["expected_paid"])
        after = {
            "total_debt": int(supplier.total_debt or 0),
            "total_paid": int(supplier.total_paid or 0),
        }
        return {"supplier_id": supplier.id, "before": before, "after": after}

    if item.item_type == "shipping_opening_balance_fix":
        company = ShippingCompany.query.get(int(payload["shipping_company_id"]))
        if not company:
            raise ValueError("شركة النقل غير موجودة")
        before = {"opening_balance": int(company.opening_balance or 0)}
        company.opening_balance = int(payload["opening_balance"])
        after = {"opening_balance": int(company.opening_balance or 0)}
        return {"shipping_company_id": company.id, "before": before, "after": after}

    if item.item_type == "review_task":
        return {"review_only": True, "message": "هذه مهمة مراجعة فقط ولا تعدل بيانات النظام."}

    raise ValueError(f"نوع إجراء غير مدعوم: {item.item_type}")


def run_ai_audit(
    *,
    audit_type: str = "comprehensive",
    schedule_id: int | None = None,
    employee_id: int | None = None,
) -> AIAuditRun:
    run = AIAuditRun(schedule_id=schedule_id, run_type=audit_type, status="running")
    db.session.add(run)
    db.session.flush()
    try:
        result: dict[str, Any] = {"snapshot": collect_system_snapshot()}
        result["financial_labels"] = {
            "supplier_debts": "التزامات على الشركة للموردين",
            "shipping_receivables": "ذمم مدينة إلنا عند شركات النقل",
        }
        if audit_type in {"accounting", "comprehensive", "inventory", "orders"}:
            result["accounting"] = audit_accounting_integrity(limit=200)
        issue_count = 0
        if result.get("accounting"):
            summary = result["accounting"].get("summary") or {}
            issue_count = sum(
                int(summary.get(key, 0) or 0)
                for key in (
                    "stock_imbalances_count",
                    "status_inconsistencies_count",
                    "invoice_total_mismatches_count",
                    "negative_margin_items_count",
                )
            )
            if issue_count:
                review_plan = _build_audit_review_plan(
                    audit_type=audit_type,
                    summary=summary,
                    employee_id=employee_id,
                    schedule_id=schedule_id,
                )
                run.action_plan_id = review_plan.id
        severity = "critical" if issue_count >= 10 else ("warning" if issue_count else "success")
        title = "تدقيق مساعد Finora"
        summary_text = f"اكتشف التدقيق {issue_count} ملاحظة." if issue_count else "لم يجد التدقيق أخطاء حرجة."
        analytics = SystemAnalytics(
            analysis_type=f"ai_{audit_type}",
            title=title,
            description=summary_text,
            severity=severity,
            affected_count=issue_count,
            related_data=_json_dumps(result),
        )
        db.session.add(analytics)
        schedule = AIScheduledAudit.query.get(schedule_id) if schedule_id else None
        alert_created = False
        if _severity_reaches_threshold(severity, schedule.severity_threshold if schedule else "warning"):
            alert_created = _add_ai_alert_once(
                title=title,
                message=summary_text,
                severity=severity,
                related_id=run.id,
            )
        if severity == "critical" and alert_created:
            _notify_admins_internal(f"{title}: {summary_text}")
        run.status = "completed"
        run.summary = summary_text
        run.set_result(result)
        run.finished_at = datetime.utcnow()
        if schedule:
            schedule.last_run_at = datetime.utcnow()
            schedule.next_run_at = datetime.utcnow() + timedelta(minutes=int(schedule.interval_minutes or 1440))
        _log_tool("scheduled_audit.run", employee_id=employee_id, input_data={"audit_type": audit_type}, output_data={"issues": issue_count})
        db.session.commit()
        return run
    except Exception as exc:
        db.session.rollback()
        run = AIAuditRun.query.get(run.id) if run.id else run
        if run:
            run.status = "failed"
            run.summary = str(exc)
            run.finished_at = datetime.utcnow()
            db.session.add(run)
            db.session.commit()
        raise


def list_schedules() -> list[dict]:
    return [s.to_dict() for s in AIScheduledAudit.query.order_by(AIScheduledAudit.created_at.desc()).all()]


def create_or_update_schedule(data: dict, *, employee_id: int | None) -> AIScheduledAudit:
    raw_schedule_id = data.get("id")
    try:
        schedule_id = int(raw_schedule_id) if raw_schedule_id not in (None, "") else None
    except (TypeError, ValueError):
        schedule_id = None
    schedule = AIScheduledAudit.query.get(schedule_id) if schedule_id else None
    if not schedule:
        schedule = AIScheduledAudit(created_by_id=employee_id)
        db.session.add(schedule)
    schedule.name = (data.get("name") or "تدقيق دوري").strip()[:180]
    audit_type = (data.get("audit_type") or "comprehensive").strip()
    if audit_type not in {"comprehensive", "accounting", "inventory", "orders", "suppliers", "shipping"}:
        audit_type = "comprehensive"
    schedule.audit_type = audit_type
    try:
        interval_minutes = int(data.get("interval_minutes") or 1440)
    except (TypeError, ValueError):
        interval_minutes = 1440
    schedule.interval_minutes = max(15, interval_minutes)
    severity_threshold = (data.get("severity_threshold") or "warning").strip()
    if severity_threshold not in {"info", "warning", "critical"}:
        severity_threshold = "warning"
    schedule.severity_threshold = severity_threshold
    schedule.is_active = bool(data.get("is_active", True))
    schedule.set_settings(data.get("settings") or {})
    if not schedule.next_run_at:
        schedule.next_run_at = datetime.utcnow() + timedelta(minutes=schedule.interval_minutes)
    db.session.commit()
    return schedule


def run_due_scheduled_audits(limit: int = 5) -> int:
    now = datetime.utcnow()
    schedules = (
        AIScheduledAudit.query.filter_by(is_active=True)
        .filter((AIScheduledAudit.next_run_at.is_(None)) | (AIScheduledAudit.next_run_at <= now))
        .order_by(AIScheduledAudit.next_run_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )
    count = 0
    for schedule in schedules:
        try:
            run_ai_audit(audit_type=schedule.audit_type, schedule_id=schedule.id)
            count += 1
        except Exception:
            current_app.logger.exception("AI scheduled audit failed for schedule %s", schedule.id)
    return count


def _build_audit_review_plan(
    *,
    audit_type: str,
    summary: dict,
    employee_id: int | None,
    schedule_id: int | None,
) -> AIActionPlan:
    issue_map = [
        ("stock_imbalances_count", "مراجعة فروقات المخزون", "طابق branch_stock مع product.quantity وحركات المخزون."),
        ("status_inconsistencies_count", "مراجعة حالات الطلبات", "راجع الطلبات ذات الحالة أو الدفع غير المتناسق."),
        ("invoice_total_mismatches_count", "مراجعة إجماليات الفواتير", "راجع فواتير يختلف مجموع عناصرها عن الإجمالي المحفوظ."),
        ("negative_margin_items_count", "مراجعة الهوامش السالبة", "راجع أسعار الشراء/البيع للمنتجات التي تظهر بخسارة."),
    ]
    total_issues = sum(int(summary.get(key, 0) or 0) for key, _, _ in issue_map)
    plan = AIActionPlan(
        created_by_id=employee_id,
        title=f"خطة مراجعة تدقيق {audit_type}",
        plan_type="scheduled_audit_review",
        status="draft",
        summary="خطة مراجعة مقترحة من الدورية. لا تنفذ أي تعديل تلقائياً.",
        risk_level="high" if total_issues >= 10 else "medium",
    )
    plan.set_impact(
        {
            "audit_type": audit_type,
            "schedule_id": schedule_id,
            "summary": summary,
            "note": "هذه خطة مراجعة؛ أي إصلاح فعلي يحتاج خطة تنفيذ منفصلة وموافقة أدمن.",
        }
    )
    db.session.add(plan)
    db.session.flush()
    created_items = 0
    for key, title, description in issue_map:
        count = int(summary.get(key, 0) or 0)
        if not count:
            continue
        item = AIActionItem(
            plan_id=plan.id,
            item_type="review_task",
            target_type="ai_audit",
            target_id=None,
            title=f"{title}: {count}",
            description=description,
        )
        item.set_before({"count": count, "source": key})
        item.set_after({"expected": "مراجعة بشرية أو إنشاء خطة إصلاح منفصلة"})
        item.set_payload({"audit_key": key, "audit_type": audit_type})
        db.session.add(item)
        created_items += 1
    _log_tool(
        "scheduled_audit.build_review_plan",
        plan_id=plan.id,
        employee_id=employee_id,
        input_data={"audit_type": audit_type},
        output_data={"items": created_items, "summary": summary},
        mode="plan",
    )
    return plan


def _severity_reaches_threshold(severity: str, threshold: str | None) -> bool:
    order = {"success": 0, "info": 1, "warning": 2, "critical": 3}
    severity_value = order.get((severity or "info").lower(), 1)
    threshold_value = order.get((threshold or "warning").lower(), 2)
    return severity_value >= threshold_value and severity_value > 0


def _add_ai_alert_once(*, title: str, message: str, severity: str, related_id: int | None) -> bool:
    if severity not in {"critical", "warning", "info"}:
        return False
    recent_cutoff = datetime.utcnow() - timedelta(hours=6)
    existing = (
        SystemAlert.query.filter_by(alert_type="ai_audit", title=title, message=message, is_dismissed=False)
        .filter(SystemAlert.created_at >= recent_cutoff)
        .first()
    )
    if existing:
        return False
    db.session.add(
        SystemAlert(
            alert_type="ai_audit",
            title=title,
            message=message,
            priority="high" if severity == "critical" else ("medium" if severity == "warning" else "low"),
            related_type="ai_audit_run",
            related_id=related_id,
        )
    )
    return True


def _notify_admins_internal(content: str) -> None:
    admins = Employee.query.filter_by(role="admin", is_active=True).limit(10).all()
    for admin in admins:
        db.session.add(
            Message(
                sender_id=admin.id,
                receiver_id=admin.id,
                content=content,
                file_type=None,
                is_read=False,
            )
        )
