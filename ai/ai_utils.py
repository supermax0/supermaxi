# ai/ai_utils.py
"""
Utilities for the AI layer: OpenAI wrapper, validation, rate limiting, logging, and data collection.
- AI does NOT access the DB directly; this module provides a data collector that runs in app context
  and returns sanitized aggregates for the AI to analyze.
"""

import os
import logging
import time
from typing import Optional

logger = logging.getLogger("ai_layer")

# -----------------------------------------------------------------------------
# OpenAI wrapper: send prompt, get response, error handling. No API key in code.
# -----------------------------------------------------------------------------
OPENAI_TIMEOUT_SEC = 30
OPENAI_MODEL = "gpt-4o-mini"  # قابل للتغيير حسب الحساب؛ gpt-4o-mini أسرع وأرخص

def call_openai(messages: list, timeout_sec: int = OPENAI_TIMEOUT_SEC) -> tuple[bool, str]:
    """
    Sends messages to OpenAI API and returns (success, text_or_error).
    Uses env OPENAI_API_KEY. Handles timeout and errors.
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY".lower())
    if not api_key or not api_key.strip():
        # fallback: GlobalSetting (for whole system)
        try:
            from flask import g
            old_tenant = getattr(g, "tenant", None)
            g.tenant = None  # force core DB
            from models.core.global_setting import GlobalSetting
            api_key = (GlobalSetting.get_setting("OPENAI_API_KEY", "") or "").strip()
        except Exception:
            api_key = ""
        finally:
            try:
                g.tenant = old_tenant  # type: ignore[name-defined]
            except Exception:
                pass

    if not api_key or not api_key.strip():
        logger.warning("OPENAI_API_KEY not set")
        return False, "لم يتم تكوين مفتاح OpenAI. أضف OPENAI_API_KEY في متغيرات البيئة أو من إعدادات النظام."

    try:
        import openai
    except ImportError:
        logger.error("openai package not installed")
        return False, "حزمة openai غير مثبتة. قم بتثبيت: pip install openai"

    client = openai.OpenAI(api_key=api_key.strip())
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=2200,
            timeout=timeout_sec,
        )
        choice = response.choices[0] if response.choices else None
        if not choice or not getattr(choice, "message", None):
            return False, "استجابة فارغة من OpenAI."
        text = (choice.message.content or "").strip()
        return True, text
    except openai.APITimeoutError:
        logger.warning("OpenAI timeout")
        return False, "انتهت مهلة الطلب. جرّب تقليل الفترة أو إعادة المحاولة."
    except openai.APIError as e:
        logger.exception("OpenAI API error: %s", e)
        return False, f"خطأ في خدمة التحليل: {str(e)[:200]}"
    except Exception as e:
        logger.exception("OpenAI unexpected error: %s", e)
        return False, "حدث خطأ غير متوقع أثناء التحليل."


# -----------------------------------------------------------------------------
# Validation: allowed types and periods for /ai/analyze
# -----------------------------------------------------------------------------
ALLOWED_ANALYZE_TYPES = ("sales", "profit", "inventory", "report", "orders")
ALLOWED_PERIODS = (
    "today",
    "yesterday",
    "last_7_days",
    "this_week",
    "last_30_days",
    "this_month",
    "last_month",
    "this_year",
    "last_year",
    "custom",
)

def validate_analyze_params(analyze_type: Optional[str], period: Optional[str], custom_from=None, custom_to=None) -> tuple[bool, str]:
    """
    Validates type, period, and optional custom dates. Returns (ok, error_message).
    """
    if not analyze_type or str(analyze_type).strip().lower() not in ALLOWED_ANALYZE_TYPES:
        return False, "نوع التحليل غير صالح. القيم المسموحة: sales, profit, inventory, report, orders"
    if not period or str(period).strip().lower() not in ALLOWED_PERIODS:
        return False, "الفترة غير صالحة. راجع القائمة (اليوم، آخر 7، هذا الأسبوع، آخر 30 يوم، الشهور، سنة، مخصص)."
    if str(period).strip().lower() == "custom" and (not custom_from or not custom_to):
        return False, "عند اختيار فترة مخصصة يجب إرسال date_from و date_to"
    return True, ""


# -----------------------------------------------------------------------------
# Simple in-memory rate limit (per identifier: e.g. session_id or IP)
# -----------------------------------------------------------------------------
_rate_store = {}  # key -> list of timestamps
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SEC = 60

def check_rate_limit(identifier: str) -> tuple[bool, str]:
    """
    Returns (allowed, error_message). Uses sliding window: max RATE_LIMIT_REQUESTS per RATE_LIMIT_WINDOW_SEC.
    """
    now = time.time()
    if identifier not in _rate_store:
        _rate_store[identifier] = []
    times = _rate_store[identifier]
    # drop older than window
    times[:] = [t for t in times if now - t < RATE_LIMIT_WINDOW_SEC]
    if len(times) >= RATE_LIMIT_REQUESTS:
        return False, "تم تجاوز حد الطلبات. جرّب بعد دقيقة."
    times.append(now)
    return True, ""


# -----------------------------------------------------------------------------
# Overdue orders (تشغيلي — غير مرتبط بفترة التقرير) للمساعد المالي
# -----------------------------------------------------------------------------
def _snapshot_overdue_orders(*, min_days: int = 7, limit: int = 22) -> dict:
    """طلبات معلّقة (تم الطلب / جاري الشحن) متأخرة min_days+ يوماً؛ نفس منطق لوحة التحكم تقريباً."""
    from datetime import datetime
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload
    from models.invoice import Invoice
    from utils.order_status import PENDING_STATUSES

    now = datetime.utcnow()
    rows = (
        Invoice.query.options(joinedload(Invoice.customer))
        .filter(Invoice.status.in_(list(PENDING_STATUSES)))
        .filter(or_(Invoice.payment_status.is_(None), Invoice.payment_status != "مرتجع"))
        .order_by(Invoice.created_at.asc())
        .limit(320)
        .all()
    )
    items = []
    for inv in rows:
        ref = inv.scheduled_date or inv.created_at
        if not ref:
            continue
        if getattr(ref, "tzinfo", None) is not None:
            ref = ref.replace(tzinfo=None)
        try:
            days = (now - ref).days
        except Exception:
            continue
        if days < min_days:
            continue
        sev = "critical" if days >= 10 else "warning"
        phone = ""
        try:
            if inv.customer is not None:
                phone = (getattr(inv.customer, "phone", None) or "") or ""
        except Exception:
            phone = ""
        items.append(
            {
                "id": int(inv.id),
                "customer": (inv.customer_name or "").strip()[:80],
                "phone": str(phone).strip()[:24],
                "status": (inv.status or "").strip()[:40],
                "days_overdue": int(days),
                "severity": sev,
            }
        )
    items.sort(key=lambda x: (0 if x["severity"] == "critical" else 1, -x["days_overdue"], -x["id"]))
    items = items[:limit]
    crit = sum(1 for x in items if x["severity"] == "critical")
    warn = sum(1 for x in items if x["severity"] == "warning")
    return {"orders": items, "listed_count": len(items), "critical_count": crit, "warning_only_count": warn}


# -----------------------------------------------------------------------------
# Data collector: aggregates only, no raw DB exposure to AI. Runs in Flask app context.
# -----------------------------------------------------------------------------
def collect_context_data(period_type: str, custom_date_from=None, custom_date_to=None) -> dict:
    """
    Collects sanitized aggregate data for the given period. Must be called within Flask app context
    (e.g. from a route). Used by ai_service to build context for the AI; AI never touches DB.
    """
    from utils.date_periods import get_period_dates, get_period_label
    from collections import Counter
    from sqlalchemy import func
    from extensions import db
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.expense import Expense
    from utils.accounting_calculations import (
        calculate_inventory_value,
        calculate_supplier_debts,
        calculate_shipping_due,
    )

    date_from, date_to = get_period_dates(period_type, custom_date_from, custom_date_to)
    period_label = get_period_label(period_type, custom_date_from, custom_date_to)

    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]

    def effective_paid_amount(inv):
        total = int(getattr(inv, "total", 0) or 0)
        ps = getattr(inv, "payment_status", None)
        st = getattr(inv, "status", None)
        if ps == "مسدد" or st == "مسدد":
            return max(total, 0)
        if ps == "جزئي":
            paid = int(getattr(inv, "paid_amount", 0) or 0)
            if paid < 0:
                return 0
            return min(paid, total) if total > 0 else paid
        return 0

    period_invoices = Invoice.query.filter(
        func.date(Invoice.created_at) >= date_from,
        func.date(Invoice.created_at) <= date_to,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
    ).all()

    total_sales = sum(int(inv.total or 0) for inv in period_invoices)
    cash_sales = sum(effective_paid_amount(inv) for inv in period_invoices)
    credit_sales = max(0, total_sales - cash_sales)

    ratios = {}
    for inv in period_invoices:
        total = int(inv.total or 0)
        paid = effective_paid_amount(inv)
        if total > 0 and paid > 0:
            ratios[int(inv.id)] = min(max(paid / total, 0.0), 1.0)

    cogs_period = 0
    if ratios:
        rows = db.session.query(
            OrderItem.invoice_id,
            func.sum(OrderItem.cost * OrderItem.quantity).label("cogs_sum"),
        ).filter(OrderItem.invoice_id.in_(list(ratios.keys()))).group_by(OrderItem.invoice_id).all()
        for invoice_id, cogs_sum in rows:
            if cogs_sum:
                cogs_period += int(round(float(cogs_sum) * ratios.get(int(invoice_id), 0.0)))

    expenses_period = db.session.query(func.sum(Expense.amount)).filter(
        func.date(Expense.expense_date) >= date_from,
        func.date(Expense.expense_date) <= date_to,
    ).scalar() or 0

    period_profit = int(cash_sales - cogs_period - expenses_period)
    inventory_value = calculate_inventory_value()
    supplier_debts = calculate_supplier_debts()
    shipping_due = calculate_shipping_due()

    # Top / worst products by quantity sold in period (with revenue and margin hint)
    product_stats = {}
    for inv in period_invoices:
        for item in getattr(inv, "items", []) or []:
            pid = getattr(item, "product_id", None)
            name = getattr(item, "product_name", None) or "منتج"
            qty = int(getattr(item, "quantity", 0) or 0)
            price = int(getattr(item, "price", 0) or 0)
            cost = int(getattr(item, "cost", 0) or 0)
            rev = qty * price
            cogs_item = qty * cost
            margin = rev - cogs_item
            if pid not in product_stats:
                product_stats[pid] = {"name": name, "quantity_sold": 0, "revenue": 0, "cost": 0, "margin": 0}
            product_stats[pid]["quantity_sold"] += qty
            product_stats[pid]["revenue"] += rev
            product_stats[pid]["cost"] += cogs_item
            product_stats[pid]["margin"] += margin

    items_list = [
        {"name": v["name"], "quantity_sold": v["quantity_sold"], "revenue": v["revenue"], "margin": v["margin"]}
        for v in product_stats.values()
    ]
    items_list.sort(key=lambda x: x["revenue"], reverse=True)
    top_products = items_list[:10]
    worst_by_margin = sorted(items_list, key=lambda x: x["margin"])[:10]

    low_stock_count = Product.query.filter(Product.quantity <= 2).count()

    # توزيع حالات الطلبات داخل الفترة (كل الفواتير المنشأة في النطاق)
    orders_status_in_period: dict[str, int] = {}
    try:
        range_rows = Invoice.query.filter(
            func.date(Invoice.created_at) >= date_from,
            func.date(Invoice.created_at) <= date_to,
        ).all()
        orders_status_in_period = dict(Counter(((inv.status or "—").strip() or "—") for inv in range_rows).most_common(14))
    except Exception:
        orders_status_in_period = {}

    overdue_block: dict = {"orders": [], "listed_count": 0, "critical_count": 0, "warning_only_count": 0}
    try:
        overdue_block = _snapshot_overdue_orders()
    except Exception as ex:
        logger.warning("overdue snapshot for AI context failed: %s", ex)

    return {
        "period_label": period_label,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "sales": int(total_sales),
        "cash_sales": int(cash_sales),
        "credit_sales": int(credit_sales),
        "period_profit": int(period_profit),
        "cogs_period": int(cogs_period),
        "expenses_period": int(expenses_period),
        "inventory_value": int(inventory_value),
        "supplier_debts": int(supplier_debts),
        "shipping_due": int(shipping_due),
        "top_products": top_products,
        "worst_products_by_margin": worst_by_margin,
        "low_stock_count": int(low_stock_count),
        "invoices_count": len(period_invoices),
        "orders_status_in_period": orders_status_in_period,
        "overdue_orders": overdue_block.get("orders") or [],
        "overdue_orders_listed": int(overdue_block.get("listed_count") or 0),
        "overdue_orders_critical": int(overdue_block.get("critical_count") or 0),
        "overdue_orders_warning": int(overdue_block.get("warning_only_count") or 0),
    }
