"""
تجميع بيانات التقرير المالي الشامل من بيانات النظام فقط.
- لا تخمين؛ إذا لا توجد بيانات نُرجع صفر أو "لا يوجد".
- الفترة: شهري / ربع سنوي / سنوي أو نطاق مخصص.
- يُستخدم في صفحة التقرير المالي (/reports/financial).
"""

from datetime import date, timedelta
from sqlalchemy import func
from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.expense import Expense
from models.product import Product
from utils.date_periods import get_period_dates, get_period_label
from utils.accounting_calculations import (
    calculate_inventory_value,
    calculate_supplier_debts,
    calculate_shipping_due,
    calculate_accounts_receivable,
)
from utils.cash_calculations import calculate_cash_balance

RETURN_STATUSES = ["مرتجع"]
CANCELED_STATUSES = ["ملغي"]


def _effective_paid_amount(inv):
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


def get_financial_report_data(period_type="this_month", custom_date_from=None, custom_date_to=None):
    """
    يجمع كل أرقام التقرير المالي للفترة المحددة.
    المرتجعات: فقط من بيانات النظام، بدون تقدير.
    """
    date_from, date_to = get_period_dates(period_type, custom_date_from, custom_date_to)
    period_label = get_period_label(period_type, custom_date_from, custom_date_to)

    # ─── فواتير الفترة (استبعاد ملغي/مرتجع) ───
    period_invoices = Invoice.query.filter(
        func.date(Invoice.created_at) >= date_from,
        func.date(Invoice.created_at) <= date_to,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
    ).all()

    total_revenue = sum(int(inv.total or 0) for inv in period_invoices)
    cash_sales = sum(_effective_paid_amount(inv) for inv in period_invoices)
    credit_sales = max(0, total_revenue - cash_sales)

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
        ).filter(OrderItem.invoice_id.in_(list(ratios.keys()))).group_by(OrderItem.invoice_id).all()
        for invoice_id, cogs_sum in rows:
            if cogs_sum:
                cogs_period += int(round(float(cogs_sum) * ratios.get(int(invoice_id), 0.0)))

    expenses_period_raw = db.session.query(
        Expense.category,
        func.sum(Expense.amount).label("total"),
    ).filter(
        func.date(Expense.expense_date) >= date_from,
        func.date(Expense.expense_date) <= date_to,
    ).group_by(Expense.category).all()

    expenses_period = sum(int(r.total or 0) for r in expenses_period_raw)
    expenses_breakdown = [{"category": r.category or "أخرى", "amount": int(r.total or 0)} for r in expenses_period_raw]

    net_profit_period = int(total_revenue - cogs_period - expenses_period)

    # ─── أرصدة كما في نهاية الفترة (نستخدم الحالية من النظام) ───
    cash_balance = calculate_cash_balance()
    inventory_value = calculate_inventory_value()
    accounts_receivable = calculate_accounts_receivable()
    supplier_debts = calculate_supplier_debts()
    shipping_due = calculate_shipping_due()

    # ─── المخزون: عدد مواد ناقصة وراكدة (تعريف بسيط) ───
    low_stock_count = Product.query.filter(Product.quantity <= 2).count()
    zero_stock_count = Product.query.filter(Product.quantity <= 0).count()

    # ─── الفترة السابقة للمقارنة (نمو/تراجع) ───
    prev_label = None
    growth_revenue_pct = None
    growth_profit_pct = None
    if period_type == "this_month":
        first_this = date_to.replace(day=1)
        prev_end = first_this - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        prev_label = get_period_label("last_month", None, None)
    elif period_type == "this_year":
        prev_start = date(date_to.year - 1, 1, 1)
        prev_end = date(date_to.year - 1, 12, 31)
        prev_label = "السنة الماضية"
    else:
        prev_start = prev_end = None

    if prev_start and prev_end:
        prev_invoices = Invoice.query.filter(
            func.date(Invoice.created_at) >= prev_start,
            func.date(Invoice.created_at) <= prev_end,
            Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
            Invoice.payment_status != "مرتجع",
        ).all()
        prev_revenue = sum(int(inv.total or 0) for inv in prev_invoices)
        prev_ratios = {}
        for inv in prev_invoices:
            t = int(inv.total or 0)
            p = _effective_paid_amount(inv)
            if t > 0 and p > 0:
                prev_ratios[int(inv.id)] = min(max(p / t, 0.0), 1.0)
        prev_cogs = 0
        if prev_ratios:
            prev_rows = db.session.query(
                OrderItem.invoice_id,
                func.sum(OrderItem.cost * OrderItem.quantity).label("cogs_sum"),
            ).filter(OrderItem.invoice_id.in_(list(prev_ratios.keys()))).group_by(OrderItem.invoice_id).all()
            for invoice_id, cogs_sum in prev_rows:
                if cogs_sum:
                    prev_cogs += int(round(float(cogs_sum) * prev_ratios.get(int(invoice_id), 0.0)))
        prev_expenses = db.session.query(func.sum(Expense.amount)).filter(
            func.date(Expense.expense_date) >= prev_start,
            func.date(Expense.expense_date) <= prev_end,
        ).scalar() or 0
        prev_profit = int(prev_revenue - prev_cogs - prev_expenses)
        if prev_revenue and total_revenue:
            growth_revenue_pct = round((total_revenue - prev_revenue) / prev_revenue * 100, 1)
        if prev_profit != 0 and net_profit_period is not None:
            growth_profit_pct = round((net_profit_period - prev_profit) / abs(prev_profit) * 100, 1)

    # ─── تحليل مالي بسيط ───
    gross_profit = int(total_revenue - cogs_period)
    profit_margin_pct = round(net_profit_period / total_revenue * 100, 1) if total_revenue else None
    expense_to_revenue_pct = round(expenses_period / total_revenue * 100, 1) if total_revenue else None
    total_assets = int(cash_balance + inventory_value + accounts_receivable)
    total_liabilities = int(supplier_debts + shipping_due)
    liquidity_ratio = round(total_assets / total_liabilities, 2) if total_liabilities else None

    return {
        "period_label": period_label,
        "date_from": date_from,
        "date_to": date_to,
        "period_type": period_type,
        # دخل الفترة
        "total_revenue": int(total_revenue),
        "cash_sales": int(cash_sales),
        "credit_sales": int(credit_sales),
        "cogs_period": int(cogs_period),
        "gross_profit": gross_profit,
        "expenses_period": int(expenses_period),
        "expenses_breakdown": expenses_breakdown,
        "net_profit_period": net_profit_period,
        "invoices_count": len(period_invoices),
        # ميزانية / أرصدة
        "cash_balance": int(cash_balance),
        "inventory_value": int(inventory_value),
        "accounts_receivable": int(accounts_receivable),
        "supplier_debts": int(supplier_debts),
        "shipping_due": int(shipping_due),
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "equity_note": "محسوب من رصيد النشاط (الأصول − الالتزامات) إن وُجدت بيانات قيود",  # للنظام الحالي
        # مخزون
        "low_stock_count": low_stock_count,
        "zero_stock_count": zero_stock_count,
        # مقارنة
        "prev_label": prev_label,
        "growth_revenue_pct": growth_revenue_pct,
        "growth_profit_pct": growth_profit_pct,
        # نسب
        "profit_margin_pct": profit_margin_pct,
        "expense_to_revenue_pct": expense_to_revenue_pct,
        "liquidity_ratio": liquidity_ratio,
    }
