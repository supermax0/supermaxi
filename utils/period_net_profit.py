# -*- coding: utf-8 -*-
"""صافي الربح لفترة زمنية — إنشاء الطلب + تحصيل متناسب + مصاريف."""
from datetime import date

from sqlalchemy import or_
from sqlalchemy.sql import func

from extensions import db
from models.invoice import Invoice
from utils.cash_calculations import _effective_paid_amount
from utils.expense_queries import sum_posted_expenses
from utils.order_item_costs import exclude_delivery_fee_items


def net_profit_for_range(date_from: date, date_to: date) -> int:
    """
    صافي الربح للفترة — يطابق منطق تقارير `/api/index/reports`.

    - الفواتير بتاريخ إنشائها (created_at) ضمن الفترة؛ التحصيل الفعلي فقط.
    - COGS متناسب مع التحصيل؛ مصاريف Expense حسب expense_date (فعلية فقط).
    """
    from models.order_item import OrderItem

    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]

    period_invoices = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
        Invoice.created_at,
    ).filter(
        func.date(Invoice.created_at) >= date_from,
        func.date(Invoice.created_at) <= date_to,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        or_(
            Invoice.payment_status.is_(None),
            Invoice.payment_status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        ),
    ).all()

    cash_sales = sum(_effective_paid_amount(inv) for inv in period_invoices)
    sales_total = int(cash_sales)

    ratios = {}
    for inv in period_invoices:
        total = int(inv.total or 0)
        paid = _effective_paid_amount(inv)
        if total > 0 and paid > 0:
            ratios[int(inv.id)] = min(max(paid / total, 0.0), 1.0)

    cogs_period = 0
    if ratios:
        rows = db.session.query(
            OrderItem.invoice_id,
            func.sum(OrderItem.cost * OrderItem.quantity).label("cogs_sum"),
        ).filter(
            OrderItem.invoice_id.in_(list(ratios.keys())),
            exclude_delivery_fee_items(OrderItem),
        ).group_by(OrderItem.invoice_id).all()

        for invoice_id, cogs_sum in rows:
            if not cogs_sum:
                continue
            ratio = ratios.get(int(invoice_id), 0.0)
            cogs_period += int(round(float(cogs_sum) * ratio))

    expenses_period = sum_posted_expenses(date_from, date_to)

    return int(sales_total - cogs_period - expenses_period)


def net_profit_for_order_range(date_from: date, date_to: date) -> int:
    """
    صافي الربح على أساس إنشاء الطلب.

    يُستخدم لبطاقات الصفحة الرئيسية حتى يظهر ربح الطلب فور حالة «تم الطلب»،
    ولا يتأثر لاحقاً بحركات التحصيل كي لا يُحسب نفس الطلب مرتين.
    """
    from models.order_item import OrderItem
    from utils.payment_ledger import calendar_day_bounds_utc

    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]
    start_utc, _ = calendar_day_bounds_utc(date_from)
    _, end_utc = calendar_day_bounds_utc(date_to)

    period_invoices = db.session.query(
        Invoice.id,
        Invoice.total,
    ).filter(
        Invoice.created_at >= start_utc,
        Invoice.created_at < end_utc,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        or_(
            Invoice.payment_status.is_(None),
            Invoice.payment_status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        ),
    ).all()

    invoice_ids = [int(inv.id) for inv in period_invoices]
    sales_total = sum(int(inv.total or 0) for inv in period_invoices)

    cogs_period = 0
    if invoice_ids:
        cogs_period = db.session.query(
            func.sum(OrderItem.cost * OrderItem.quantity)
        ).filter(
            OrderItem.invoice_id.in_(invoice_ids),
            exclude_delivery_fee_items(OrderItem),
        ).scalar() or 0

    expenses_period = sum_posted_expenses(date_from, date_to)

    return int(sales_total - int(cogs_period or 0) - expenses_period)


def net_profit_for_order_calendar_day(day: date) -> int:
    """صافي ربح يوم واحد على أساس إنشاء الطلب."""
    return net_profit_for_order_range(day, day)


def expenses_sum_for_range(date_from: date, date_to: date) -> int:
    """مجموع المصاريف الفعلية ضمن الفترة (expense_date)."""
    return sum_posted_expenses(date_from, date_to)
