# -*- coding: utf-8 -*-
"""صافي الربح لفترة زمنية — إنشاء الطلب + تحصيل متناسب + مصاريف."""
from datetime import date

from sqlalchemy.sql import func

from extensions import db
from models.expense import Expense
from models.invoice import Invoice
from utils.cash_calculations import _effective_paid_amount


def net_profit_for_range(date_from: date, date_to: date) -> int:
    """
    صافي الربح للفترة — يطابق منطق تقارير `/api/index/reports`.

    - الفواتير بتاريخ إنشائها (created_at) ضمن الفترة؛ التحصيل الفعلي فقط.
    - COGS متناسب مع التحصيل؛ مصاريف Expense حسب expense_date.
    """
    from models.order_item import OrderItem

    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]

    period_invoices = Invoice.query.filter(
        func.date(Invoice.created_at) >= date_from,
        func.date(Invoice.created_at) <= date_to,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
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
            OrderItem.invoice_id.in_(list(ratios.keys()))
        ).group_by(OrderItem.invoice_id).all()

        for invoice_id, cogs_sum in rows:
            if not cogs_sum:
                continue
            ratio = ratios.get(int(invoice_id), 0.0)
            cogs_period += int(round(float(cogs_sum) * ratio))

    expenses_period = db.session.query(func.sum(Expense.amount)).filter(
        Expense.expense_date.isnot(None),
        func.date(Expense.expense_date) >= date_from,
        func.date(Expense.expense_date) <= date_to,
    ).scalar() or 0

    return int(sales_total - cogs_period - int(expenses_period or 0))


def expenses_sum_for_range(date_from: date, date_to: date) -> int:
    """مجموع المصاريف ضمن الفترة (expense_date)."""
    total = db.session.query(func.sum(Expense.amount)).filter(
        Expense.expense_date.isnot(None),
        func.date(Expense.expense_date) >= date_from,
        func.date(Expense.expense_date) <= date_to,
    ).scalar() or 0
    return int(total or 0)
