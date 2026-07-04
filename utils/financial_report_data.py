"""
تجميع بيانات التقرير المالي الشامل من بيانات النظام فقط.
- لا تخمين؛ إذا لا توجد بيانات نُرجع صفر أو "لا يوجد".
- الفترة: شهري / ربع سنوي / سنوي أو نطاق مخصص.
- يُستخدم في صفحة التقرير المالي (/reports/financial).
"""

from datetime import date, timedelta
from calendar import monthrange
from sqlalchemy import func
from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.expense import Expense
from utils.order_status import CANCELED_STATUSES as ORDER_CANCELED_STATUSES
from utils.order_status import RETURN_STATUSES as ORDER_RETURN_STATUSES
from models.product import Product
from models.supplier import Supplier
from utils.date_periods import get_period_dates, get_period_label
from utils.accounting_calculations import (
    calculate_inventory_value,
    calculate_supplier_debts,
    calculate_shipping_due,
    calculate_accounts_receivable,
)
from utils.cash_calculations import calculate_cash_balance

RETURN_STATUSES = list(ORDER_RETURN_STATUSES)
CANCELED_STATUSES = list(ORDER_CANCELED_STATUSES)


def _fixed_assets_financial_summary(date_from, date_to):
    """ملخص الأصول الثابتة للتقرير المالي (يُتجاهل إن لم تُنشأ الجداول بعد)."""
    defaults = {
        "fixed_assets_book_value": 0,
        "fixed_assets_cost": 0,
        "fixed_assets_accumulated_depreciation": 0,
        "fixed_assets_depreciation_period": 0,
        "fixed_assets_active_count": 0,
    }
    try:
        from models.fixed_asset import FixedAsset
        from models.fixed_asset_depreciation import FixedAssetDepreciation

        active_statuses = ("active", "under_installation", "fully_depreciated", "draft")
        assets = FixedAsset.query.filter(FixedAsset.status.in_(active_statuses)).all()
        book_value = sum(int(a.book_value or 0) for a in assets)
        total_cost = sum(int(a.total_cost or 0) for a in assets)
        accumulated = sum(int(a.accumulated_depreciation or 0) for a in assets)
        active_count = sum(1 for a in assets if a.status == "active")

        dep_period = 0
        for row in FixedAssetDepreciation.query.filter_by(status="posted").all():
            period_start = date(row.period_year, row.period_month, 1)
            period_end = date(row.period_year, row.period_month, monthrange(row.period_year, row.period_month)[1])
            if period_end >= date_from and period_start <= date_to:
                dep_period += int(row.depreciation_amount or 0)

        return {
            "fixed_assets_book_value": int(book_value),
            "fixed_assets_cost": int(total_cost),
            "fixed_assets_accumulated_depreciation": int(accumulated),
            "fixed_assets_depreciation_period": int(dep_period),
            "fixed_assets_active_count": active_count,
        }
    except Exception:
        return defaults


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
        Invoice.payment_status.notin_(RETURN_STATUSES),
    ).all()

    total_revenue = sum(int(inv.total or 0) for inv in period_invoices)
    cash_sales = sum(_effective_paid_amount(inv) for inv in period_invoices)
    credit_sales = max(0, total_revenue - cash_sales)

    cogs_period = 0
    cogs_by_invoice = {}
    period_invoice_ids = [int(inv.id) for inv in period_invoices]
    if period_invoice_ids:
        rows = db.session.query(
            OrderItem.invoice_id,
            func.sum(OrderItem.cost * OrderItem.quantity).label("cogs_sum"),
        ).filter(OrderItem.invoice_id.in_(period_invoice_ids)).group_by(OrderItem.invoice_id).all()
        for invoice_id, cogs_sum in rows:
            if cogs_sum:
                inv_cogs = int(cogs_sum or 0)
                cogs_by_invoice[int(invoice_id)] = inv_cogs
                cogs_period += inv_cogs

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
            Invoice.payment_status.notin_(RETURN_STATUSES),
        ).all()
        prev_revenue = sum(int(inv.total or 0) for inv in prev_invoices)
        prev_cogs = 0
        prev_invoice_ids = [int(inv.id) for inv in prev_invoices]
        if prev_invoice_ids:
            prev_rows = db.session.query(
                OrderItem.invoice_id,
                func.sum(OrderItem.cost * OrderItem.quantity).label("cogs_sum"),
            ).filter(OrderItem.invoice_id.in_(prev_invoice_ids)).group_by(OrderItem.invoice_id).all()
            for invoice_id, cogs_sum in prev_rows:
                if cogs_sum:
                    prev_cogs += int(cogs_sum or 0)
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
    gross_margin_pct = round(gross_profit / total_revenue * 100, 1) if total_revenue else None
    profit_margin_pct = round(net_profit_period / total_revenue * 100, 1) if total_revenue else None
    expense_to_revenue_pct = round(expenses_period / total_revenue * 100, 1) if total_revenue else None

    fa_summary = _fixed_assets_financial_summary(date_from, date_to)
    fixed_assets_book_value = fa_summary["fixed_assets_book_value"]
    fixed_assets_depreciation_period = fa_summary["fixed_assets_depreciation_period"]

    total_assets = int(cash_balance + inventory_value + accounts_receivable + fixed_assets_book_value)
    total_liabilities = int(supplier_debts + shipping_due)
    liquidity_ratio = round(total_assets / total_liabilities, 2) if total_liabilities else None

    # ─── حقوق الملكية وموازنة الميزانية (الأصول = الالتزامات + حقوق الملكية) ───
    equity = int(total_assets - total_liabilities)

    # ─── التدفق النقدي الحقيقي للفترة (مقبوضات فعلية − مصاريف الفترة) ───
    cash_inflow = int(cash_sales)
    cash_outflow = int(expenses_period)
    net_cash_flow = int(cash_inflow - cash_outflow)

    # ─── الأفضل مبيعاً (Top Products) ───
    tp_rows = db.session.query(
        OrderItem.product_name,
        func.sum(OrderItem.quantity).label("qty"),
        func.sum(OrderItem.total).label("revenue"),
        func.sum(OrderItem.cost * OrderItem.quantity).label("cogs"),
    ).join(Invoice, Invoice.id == OrderItem.invoice_id).filter(
        func.date(Invoice.created_at) >= date_from,
        func.date(Invoice.created_at) <= date_to,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status.notin_(RETURN_STATUSES),
    ).group_by(OrderItem.product_name).order_by(func.sum(OrderItem.total).desc()).limit(10).all()
    top_products = [{
        "name": r.product_name or "غير محدد",
        "qty": int(r.qty or 0),
        "revenue": int(r.revenue or 0),
        "profit": int((r.revenue or 0) - (r.cogs or 0)),
    } for r in tp_rows]

    # ─── أفضل العملاء (Top Customers) ───
    tc_rows = db.session.query(
        Invoice.customer_name,
        func.count(Invoice.id).label("cnt"),
        func.sum(Invoice.total).label("total"),
    ).filter(
        func.date(Invoice.created_at) >= date_from,
        func.date(Invoice.created_at) <= date_to,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status.notin_(RETURN_STATUSES),
    ).group_by(Invoice.customer_name).order_by(func.sum(Invoice.total).desc()).limit(10).all()
    top_customers = [{
        "name": r.customer_name or "غير محدد",
        "count": int(r.cnt or 0),
        "total": int(r.total or 0),
    } for r in tc_rows]

    # ─── الموردون (أعلى الأرصدة المستحقة) ───
    ts_rows = Supplier.query.order_by(
        (Supplier.total_debt - Supplier.total_paid).desc()
    ).limit(10).all()
    top_suppliers = []
    for s in ts_rows:
        remaining = int((s.total_debt or 0) - (s.total_paid or 0))
        if remaining <= 0:
            continue
        top_suppliers.append({
            "name": s.name or "غير محدد",
            "total_debt": int(s.total_debt or 0),
            "total_paid": int(s.total_paid or 0),
            "remaining": remaining,
        })

    # ─── سلسلة زمنية للرسوم البيانية (يومية إذا الفترة قصيرة، شهرية إن طالت) ───
    span_days = (date_to - date_from).days
    bucket_by_month = span_days > 62

    def _bucket_key(d):
        return d.strftime("%Y-%m") if bucket_by_month else d.strftime("%Y-%m-%d")

    buckets = {}
    for inv in period_invoices:
        created = getattr(inv, "created_at", None)
        if created is None:
            continue
        d = created.date() if hasattr(created, "date") else created
        key = _bucket_key(d)
        b = buckets.setdefault(key, {"revenue": 0, "cogs": 0, "expenses": 0})
        b["revenue"] += int(inv.total or 0)
        b["cogs"] += int(cogs_by_invoice.get(int(inv.id), 0))

    exp_rows = db.session.query(
        Expense.expense_date,
        func.sum(Expense.amount).label("total"),
    ).filter(
        func.date(Expense.expense_date) >= date_from,
        func.date(Expense.expense_date) <= date_to,
    ).group_by(Expense.expense_date).all()
    for r in exp_rows:
        if not r.expense_date:
            continue
        d = r.expense_date.date() if hasattr(r.expense_date, "date") else r.expense_date
        key = _bucket_key(d)
        b = buckets.setdefault(key, {"revenue": 0, "cogs": 0, "expenses": 0})
        b["expenses"] += int(r.total or 0)

    chart_series = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        gp = b["revenue"] - b["cogs"]
        chart_series.append({
            "label": key,
            "revenue": b["revenue"],
            "gross_profit": gp,
            "expenses": b["expenses"],
            "net_profit": gp - b["expenses"],
        })

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
        "equity": equity,
        "equity_note": "حقوق الملكية = إجمالي الأصول − إجمالي الالتزامات (محسوبة من أرصدة النظام)",
        # تدفق نقدي
        "cash_inflow": cash_inflow,
        "cash_outflow": cash_outflow,
        "net_cash_flow": net_cash_flow,
        # مخزون
        "low_stock_count": low_stock_count,
        "zero_stock_count": zero_stock_count,
        # مقارنة
        "prev_label": prev_label,
        "growth_revenue_pct": growth_revenue_pct,
        "growth_profit_pct": growth_profit_pct,
        # نسب
        "gross_margin_pct": gross_margin_pct,
        "profit_margin_pct": profit_margin_pct,
        "expense_to_revenue_pct": expense_to_revenue_pct,
        "liquidity_ratio": liquidity_ratio,
        # جداول تفصيلية
        "top_products": top_products,
        "top_customers": top_customers,
        "top_suppliers": top_suppliers,
        # رسوم بيانية
        "chart_series": chart_series,
        # أصول ثابتة
        "fixed_assets_book_value": fixed_assets_book_value,
        "fixed_assets_cost": fa_summary["fixed_assets_cost"],
        "fixed_assets_accumulated_depreciation": fa_summary["fixed_assets_accumulated_depreciation"],
        "fixed_assets_depreciation_period": fixed_assets_depreciation_period,
        "fixed_assets_active_count": fa_summary["fixed_assets_active_count"],
    }
