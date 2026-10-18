"""
تجميع بيانات التقرير المالي الشامل من بيانات النظام فقط.
- لا تخمين؛ إذا لا توجد بيانات نُرجع صفر أو "لا يوجد".
- الفترة: شهري / ربع سنوي / سنوي أو نطاق مخصص.
- يُستخدم في صفحة التقرير المالي (/reports/financial).
"""

from datetime import date, timedelta
from calendar import monthrange
from sqlalchemy import func, or_, and_, true
from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.expense import Expense
from utils.cash_movement_values import movement_amount
from utils.business_time import business_date, utc_period_filter
from utils.order_status import CANCELED_STATUSES as ORDER_CANCELED_STATUSES
from utils.order_status import RETURN_STATUSES as ORDER_RETURN_STATUSES
from models.product import Product
from models.supplier import Supplier
from utils.date_periods import get_period_dates, get_period_label
from utils.accounting_calculations import (
    _order_item_cogs_expr,
    _order_item_layer_costs_subquery,
    booked_sale_filter,
    calculate_inventory_value,
    calculate_supplier_debts,
    calculate_shipping_due,
    calculate_shipping_opening_balance,
    calculate_accounts_receivable,
    invoice_cogs_by_ids,
)
from utils.expense_queries import posted_expense_filter, sum_posted_expenses
from utils.order_item_costs import exclude_delivery_fee_items
from utils.order_stock_lock import stock_unlocked_filter
from utils.treasury_calculations import (
    calculate_total_liquidity,
    calculate_treasury_balance,
    get_treasury_movements,
    list_treasury_accounts,
)

RETURN_STATUSES = list(ORDER_RETURN_STATUSES)
CANCELED_STATUSES = list(ORDER_CANCELED_STATUSES)


def _rotating_savings_financial_summary(date_from, date_to):
    """ملخص الجمعيات للتقرير المالي.

    أرصدة الأصل والالتزام لقطة حالية، أما المدفوع والمستلم والرسوم فهي
    حركات الفترة المختارة حتى لا تُخلط الأرقام التراكمية بقائمة دخل الفترة.
    """
    defaults = {
        "rotating_savings_paid": 0,
        "rotating_savings_received": 0,
        "rotating_savings_liability": 0,
        "rotating_savings_asset": 0,
        "rotating_savings_fees": 0,
        "rotating_savings_active_count": 0,
    }
    try:
        from utils.rotating_savings_service import financial_summary
        from models.account_transaction import AccountTransaction
        from models.rotating_savings import (
            RotatingSaving,
            RotatingSavingPayment,
            RotatingSavingReceipt,
        )

        data = financial_summary()
        if not data:
            return defaults
        asset_total = sum(
            int(s.asset_balance or 0)
            for s in RotatingSaving.query.filter(RotatingSaving.deleted_at.is_(None)).all()
        )
        period_paid = int(
            db.session.query(func.coalesce(func.sum(RotatingSavingPayment.amount), 0))
            .filter(
                RotatingSavingPayment.status == "paid",
                RotatingSavingPayment.payment_date >= date_from,
                RotatingSavingPayment.payment_date <= date_to,
            )
            .scalar()
            or 0
        )
        period_fees = int(
            db.session.query(func.coalesce(func.sum(AccountTransaction.amount), 0))
            .filter(
                AccountTransaction.type == "withdraw",
                AccountTransaction.note.like("جمعية/سلفة دوّارة — دفع رسوم —%"),
                func.date(AccountTransaction.created_at) >= date_from,
                func.date(AccountTransaction.created_at) <= date_to,
            )
            .scalar()
            or 0
        )
        period_received = int(
            db.session.query(func.coalesce(func.sum(RotatingSavingReceipt.received_amount), 0))
            .filter(
                RotatingSavingReceipt.reversed_at.is_(None),
                RotatingSavingReceipt.receipt_date >= date_from,
                RotatingSavingReceipt.receipt_date <= date_to,
            )
            .scalar()
            or 0
        )
        return {
            "rotating_savings_paid": period_paid,
            "rotating_savings_received": period_received,
            "rotating_savings_liability": data.get("total_liability", 0),
            "rotating_savings_asset": asset_total,
            "rotating_savings_fees": period_fees,
            "rotating_savings_active_count": data.get("active_count", 0),
        }
    except Exception:
        return defaults


def _credit_plan_financial_summary():
    """ملخص الأجل/الأقساط — يُتجاهل إن لم تُنشأ الجداول بعد."""
    defaults = {
        "installment_debt_total": 0,
        "installment_debt_unlinked": 0,
        "installment_debt_linked": 0,
        "installment_active_plans": 0,
    }
    try:
        from utils.customer_credit_service import credit_plan_financial_summary

        return {**defaults, **credit_plan_financial_summary()}
    except Exception:
        return defaults


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

        active_statuses = ("active", "under_installation", "fully_depreciated")
        assets = FixedAsset.query.filter(
            FixedAsset.status.in_(active_statuses),
            FixedAsset.acquisition_journal_entry_id.isnot(None),
        ).all()
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
    if hasattr(inv, "report_settled"):
        return int(inv.report_settled)
    total = int(getattr(inv, "total", 0) or 0)
    ps = getattr(inv, "payment_status", None)
    st = getattr(inv, "status", None)
    if getattr(inv, "is_stock_locked", False):
        return 0
    if ps in ("مرتجع", "ملغي", "راجع", "راجعة") or st in ("مرتجع", "ملغي", "راجع", "راجعة"):
        return 0
    if ps == "مسدد":
        return max(total, 0)
    if ps == "جزئي":
        paid = int(getattr(inv, "paid_amount", 0) or 0)
        if paid < 0:
            return 0
        return min(paid, total) if total > 0 else paid
    if ps == "غير مسدد":
        return 0
    if not ps and st in ("مسدد", "تم التوصيل"):
        return max(total, 0)
    return 0


def _valid_invoice_payment_status_filter():
    return and_(
        or_(
            Invoice.payment_status.is_(None),
            Invoice.payment_status.notin_(RETURN_STATUSES + CANCELED_STATUSES),
        ),
        booked_sale_filter(),
    )


def _comparison_period(period_type, date_from, date_to):
    """Return a fair prior comparison range and its display label."""
    if period_type == "this_month":
        prev_month_end = date_from - timedelta(days=1)
        prev_start = prev_month_end.replace(day=1)
        elapsed_days = (date_to - date_from).days
        prev_end = min(prev_start + timedelta(days=elapsed_days), prev_month_end)
        return prev_start, prev_end, "الفترة المماثلة من الشهر الماضي"
    if period_type == "this_year":
        prev_start = date(date_from.year - 1, date_from.month, date_from.day)
        try:
            prev_end = date(date_to.year - 1, date_to.month, date_to.day)
        except ValueError:
            prev_end = date(
                date_to.year - 1,
                date_to.month,
                monthrange(date_to.year - 1, date_to.month)[1],
            )
        return prev_start, prev_end, "الفترة المماثلة من السنة الماضية"
    if period_type == "last_month":
        prev_end = date_from - timedelta(days=1)
        return prev_end.replace(day=1), prev_end, "الشهر السابق له"

    period_days = (date_to - date_from).days + 1
    prev_end = date_from - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    return prev_start, prev_end, "الفترة السابقة المماثلة"


def get_financial_report_data(period_type="this_month", custom_date_from=None, custom_date_to=None):
    """
    يجمع كل أرقام التقرير المالي للفترة المحددة.
    المرتجعات: فقط من بيانات النظام، بدون تقدير.
    """
    date_from, date_to = get_period_dates(period_type, custom_date_from, custom_date_to)
    period_label = get_period_label(period_type, custom_date_from, custom_date_to)
    from modules.sales_returns.facts import available, exists_expr
    from modules.sales_returns.reporting import period_activity
    legacy_only = ~exists_expr(Invoice) if available() else true()
    return_activity = period_activity(date_from, date_to)

    # ─── فواتير الفترة (استبعاد ملغي/مرتجع) ───
    period_invoices = Invoice.query.filter(
        utc_period_filter(Invoice.created_at, date_from, date_to),
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        stock_unlocked_filter(Invoice),
        _valid_invoice_payment_status_filter(),
        legacy_only,
    ).all()

    cogs_period = 0
    cogs_by_invoice = {}
    period_invoice_ids = [int(inv.id) for inv in period_invoices]
    if period_invoice_ids:
        cogs_by_invoice = invoice_cogs_by_ids(period_invoice_ids)
    period_invoices.extend(return_activity["invoices"])
    cogs_by_invoice.update(return_activity["cogs"])
    cogs_period = sum(cogs_by_invoice.values())
    total_revenue = sum(int(inv.total or 0) for inv in period_invoices)
    cash_sales = sum(_effective_paid_amount(inv) for inv in period_invoices)
    credit_sales = total_revenue - cash_sales

    expenses_period_raw = db.session.query(
        Expense.category,
        func.sum(Expense.amount).label("total"),
    ).filter(
        posted_expense_filter(),
        func.date(Expense.expense_date) >= date_from,
        func.date(Expense.expense_date) <= date_to,
    ).group_by(Expense.category).all()

    expenses_period = sum(int(r.total or 0) for r in expenses_period_raw)
    expenses_breakdown = [{"category": r.category or "أخرى", "amount": int(r.total or 0)} for r in expenses_period_raw]

    fa_summary = _fixed_assets_financial_summary(date_from, date_to)
    rs_summary = _rotating_savings_financial_summary(date_from, date_to)
    fixed_assets_book_value = fa_summary["fixed_assets_book_value"]
    fixed_assets_depreciation_period = fa_summary["fixed_assets_depreciation_period"]
    from utils.inventory_writeoff_totals import inventory_writeoff_loss
    inventory_losses_period=inventory_writeoff_loss(date_from,date_to)
    non_cash_expenses_period = int(fixed_assets_depreciation_period) + inventory_losses_period
    other_operating_expenses_period = int(rs_summary["rotating_savings_fees"])
    total_operating_expenses_period = int(
        expenses_period + non_cash_expenses_period + other_operating_expenses_period
    )
    net_profit_period = int(
        total_revenue - cogs_period - total_operating_expenses_period
    )

    # ─── أرصدة كما في نهاية الفترة (نستخدم الحالية من النظام) ───
    treasury_accounts = list_treasury_accounts()
    treasury_balances = [
        {
            "account_id": int(acc.id),
            "name": acc.name,
            "account_type": acc.account_type,
            "is_cash": bool(acc.is_cash),
            "is_default": bool(acc.is_default),
            "balance": int(calculate_treasury_balance(acc.id)),
        }
        for acc in treasury_accounts
    ]
    cash_balance = sum(row["balance"] for row in treasury_balances if row["is_cash"])

    # Bank definitions are mirrored across branches.  Present the physical
    # account once in the company report and aggregate the balances of its
    # branch rows; otherwise the same bank/card appears as duplicate lines.
    bank_by_name = {}
    for row in treasury_balances:
        if row["is_cash"]:
            continue
        key = (
            str(row.get("account_type") or "bank").strip().casefold(),
            str(row.get("name") or "").strip().casefold(),
        )
        existing = bank_by_name.get(key)
        if existing is None:
            bank_by_name[key] = dict(row)
        else:
            existing["balance"] = int(existing["balance"]) + int(row["balance"])
    bank_balances = list(bank_by_name.values())
    bank_balance_total = sum(row["balance"] for row in bank_balances)
    total_liquidity = int(calculate_total_liquidity())
    from utils.branch_mode import independent_branches_enabled
    if not independent_branches_enabled():
        # Use the same deduplicated account rows shown in this report.
        total_liquidity = int(cash_balance + bank_balance_total)
    inventory_value = calculate_inventory_value()
    cc_summary = _credit_plan_financial_summary()
    installment_debt_total = cc_summary["installment_debt_total"]
    installment_debt_unlinked = cc_summary["installment_debt_unlinked"]
    installment_debt_linked = cc_summary["installment_debt_linked"]
    installment_active_plans = cc_summary["installment_active_plans"]

    # ذمم الفواتير المباشرة تستبعد طلبات شركات النقل من مصدر الحساب.
    customer_invoice_receivables = calculate_accounts_receivable()
    supplier_debts = calculate_supplier_debts()
    shipping_receivables = calculate_shipping_due()
    shipping_opening_balance = calculate_shipping_opening_balance()
    shipping_orders_receivable = max(int(shipping_receivables or 0) - int(shipping_opening_balance or 0), 0)
    # أقساط بدون فاتورة (افتتاحي/يدوي) تُضاف للذمم — المرتبطة بفاتورة محسوبة ضمن الفواتير
    customer_receivables = int(customer_invoice_receivables + installment_debt_unlinked)
    # الرصيد الموحّد المستخدم في إجمالي الأصول: العملاء + النقل، مرة واحدة لكل منهما.
    accounts_receivable = int(customer_receivables + shipping_receivables)

    # ─── المخزون: عدد مواد ناقصة وراكدة (تعريف بسيط) ───
    if independent_branches_enabled():
        zero_stock_count = Product.query.filter(Product.active.is_(True), Product.quantity <= 0).count()
        low_stock_count = Product.query.filter(
            Product.active.is_(True), Product.quantity > 0,
            Product.quantity <= func.coalesce(Product.low_stock_threshold, 2),
        ).count()
    else:
        shared_product_rows = Product.query.filter(Product.active.is_(True)).all()
        shared_groups = {}
        for product in shared_product_rows:
            barcode = str(product.barcode or "").strip().casefold()
            sku = str(product.sku or "").strip().casefold()
            group_id = str(product.catalog_group_id or "").strip()
            key = f"barcode:{barcode}" if barcode else (f"group:{group_id}" if group_id else (f"sku:{sku}" if sku else f"product:{product.id}"))
            shared_groups.setdefault(key, []).append(product)
        shared_quantities = []
        for members in shared_groups.values():
            quantity = sum(max(0, int(getattr(item, "quantity", 0) or 0)) for item in members)
            threshold = min(int(getattr(item, "low_stock_threshold", 2) or 2) for item in members)
            shared_quantities.append((quantity, threshold))
        zero_stock_count = sum(1 for quantity, _threshold in shared_quantities if quantity <= 0)
        low_stock_count = sum(1 for quantity, threshold in shared_quantities if 0 < quantity <= threshold)

    # ─── الفترة السابقة للمقارنة (نمو/تراجع) ───
    prev_label = None
    prev_revenue = None
    prev_profit = None
    growth_revenue_pct = None
    growth_profit_pct = None
    prev_start, prev_end, prev_label = _comparison_period(
        period_type, date_from, date_to
    )

    if prev_start and prev_end:
        prev_invoices = Invoice.query.filter(
            utc_period_filter(Invoice.created_at, prev_start, prev_end),
            Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
            stock_unlocked_filter(Invoice),
            _valid_invoice_payment_status_filter(),
            legacy_only,
        ).all()
        previous_activity = period_activity(prev_start, prev_end)
        prev_revenue = sum(int(inv.total or 0) for inv in prev_invoices)
        prev_revenue += sum(int(inv.total or 0) for inv in previous_activity["invoices"])
        prev_cogs = 0
        prev_invoice_ids = [int(inv.id) for inv in prev_invoices]
        if prev_invoice_ids:
            prev_cogs = sum(invoice_cogs_by_ids(prev_invoice_ids).values())
        prev_cogs += sum(previous_activity["cogs"].values())
        prev_expenses = sum_posted_expenses(prev_start, prev_end)
        prev_fa = _fixed_assets_financial_summary(prev_start, prev_end)
        prev_rs = _rotating_savings_financial_summary(prev_start, prev_end)
        prev_profit = int(
            prev_revenue
            - prev_cogs
            - prev_expenses
            - int(prev_fa["fixed_assets_depreciation_period"])
            - int(prev_rs["rotating_savings_fees"])
            - inventory_writeoff_loss(prev_start,prev_end)
        )
        if prev_revenue:
            growth_revenue_pct = round((total_revenue - prev_revenue) / prev_revenue * 100, 1)
        if prev_profit != 0 and net_profit_period is not None:
            growth_profit_pct = round((net_profit_period - prev_profit) / abs(prev_profit) * 100, 1)

    # ─── تحليل مالي بسيط ───
    gross_profit = int(total_revenue - cogs_period)
    gross_margin_pct = round(gross_profit / total_revenue * 100, 1) if total_revenue else None
    profit_margin_pct = round(net_profit_period / total_revenue * 100, 1) if total_revenue else None
    expense_to_revenue_pct = (
        round(total_operating_expenses_period / total_revenue * 100, 1)
        if total_revenue
        else None
    )
    collection_rate_pct = round(cash_sales / total_revenue * 100, 1) if total_revenue else None

    total_assets = int(
        total_liquidity
        + inventory_value
        + accounts_receivable
        + fixed_assets_book_value
        + rs_summary["rotating_savings_asset"]
    )
    total_liabilities = int(supplier_debts + rs_summary["rotating_savings_liability"])
    current_assets = int(
        total_liquidity
        + inventory_value
        + accounts_receivable
        + rs_summary["rotating_savings_asset"]
    )
    working_capital = int(current_assets - total_liabilities)
    current_ratio = round(current_assets / total_liabilities, 2) if total_liabilities else None
    debt_to_assets_pct = (
        round(total_liabilities / total_assets * 100, 1) if total_assets else None
    )
    # Compatibility for callers that still use the old key.  The old formula
    # incorrectly included fixed assets in a ratio labelled as liquidity.
    liquidity_ratio = current_ratio

    # ─── حقوق الملكية وموازنة الميزانية (الأصول = الالتزامات + حقوق الملكية) ───
    equity = int(total_assets - total_liabilities)

    # ─── التدفق النقدي من دفتر الخزينة خلال الفترة ───
    # يشمل كل القبوضات والمدفوعات المسجلة، بصرف النظر عن تاريخ إنشاء الفاتورة.
    # التحويلات الداخلية بين الصندوق والبنوك تُستبعد لأنها لا تغيّر سيولة الشركة.
    cash_flow_totals = {"cash_in": 0, "cash_out": 0}
    cash_flow_by_reason = {}
    for account in treasury_accounts:
        for movement in get_treasury_movements(account.id, date_from, date_to):
            reason = (movement.get("reason") or "حركة أخرى").strip()
            if reason in ("تحويل وارد", "تحويل صادر"):
                continue
            direction = movement.get("type")
            if direction not in cash_flow_totals:
                continue
            amount = movement_amount(movement)
            cash_flow_totals[direction] += amount
            key = (direction, reason)
            cash_flow_by_reason[key] = cash_flow_by_reason.get(key, 0) + amount

    cash_inflow = int(cash_flow_totals["cash_in"])
    cash_outflow = int(cash_flow_totals["cash_out"])
    net_cash_flow = int(cash_inflow - cash_outflow)
    cash_flow_breakdown = [
        {"direction": direction, "reason": reason, "amount": int(amount)}
        for (direction, reason), amount in sorted(
            cash_flow_by_reason.items(),
            key=lambda item: (item[0][0], -item[1], item[0][1]),
        )
    ]

    # ─── الأفضل مبيعاً (Top Products) ───
    tp_layer_costs = _order_item_layer_costs_subquery()
    tp_rows = db.session.query(
        OrderItem.product_id,
        OrderItem.product_name,
        func.sum(OrderItem.quantity).label("qty"),
        func.sum(OrderItem.total).label("revenue"),
        func.sum(_order_item_cogs_expr(tp_layer_costs)).label("cogs"),
    ).outerjoin(
        tp_layer_costs, tp_layer_costs.c.order_item_id == OrderItem.id
    ).join(Invoice, Invoice.id == OrderItem.invoice_id).filter(
        utc_period_filter(Invoice.created_at, date_from, date_to),
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        stock_unlocked_filter(Invoice),
        _valid_invoice_payment_status_filter(),
        exclude_delivery_fee_items(OrderItem),
        legacy_only,
    ).group_by(OrderItem.product_id, OrderItem.product_name).all()
    product_totals = {}
    products = [{"product_id": r.product_id, "name": r.product_name, "qty": int(r.qty or 0),
        "revenue": int(r.revenue or 0), "cogs": int(r.cogs or 0)} for r in tp_rows] + return_activity["products"]
    for row in products:
        item = product_totals.setdefault((row["product_id"], row["name"]), {
            "name": row["name"] or "غير محدد", "qty": 0, "revenue": 0, "profit": 0})
        item["qty"] += row["qty"]
        item["revenue"] += row["revenue"]
        item["profit"] += row["revenue"] - row["cogs"]
    top_products = sorted(product_totals.values(), key=lambda row: row["revenue"], reverse=True)[:10]

    # ─── أفضل العملاء (Top Customers) ───
    tc_rows = db.session.query(
        Invoice.customer_name,
        func.count(Invoice.id).label("cnt"),
        func.sum(Invoice.total).label("total"),
    ).filter(
        utc_period_filter(Invoice.created_at, date_from, date_to),
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        stock_unlocked_filter(Invoice),
        _valid_invoice_payment_status_filter(),
        legacy_only,
    ).group_by(Invoice.customer_name).all()
    customer_totals = {r.customer_name: {"name": r.customer_name or "غير محدد", "count": int(r.cnt or 0),
        "total": int(r.total or 0)} for r in tc_rows}
    for inv in return_activity["invoices"]:
        row = customer_totals.setdefault(inv.customer_name, {"name": inv.customer_name or "غير محدد", "count": 0, "total": 0})
        row["count"] += inv.report_sale_count
        row["total"] += inv.total
    top_customers = sorted(customer_totals.values(), key=lambda row: row["total"], reverse=True)[:10]

    # ─── أفضل الموظفين والبيجات ───
    employee_totals = {}
    page_totals = {}
    for inv in period_invoices:
        inv_id = int(inv.id)
        inv_total = int(inv.total or 0)
        inv_profit = int(inv_total - cogs_by_invoice.get(inv_id, 0))

        employee_key = int(inv.employee_id or 0)
        employee_name = (inv.employee_name or "").strip() or "غير محدد"
        employee_row = employee_totals.setdefault(
            employee_key,
            {"name": employee_name, "count": 0, "total": 0, "profit": 0},
        )
        if employee_name != "غير محدد":
            employee_row["name"] = employee_name
        employee_row["count"] += getattr(inv, "report_sale_count", 1)
        employee_row["total"] += inv_total
        employee_row["profit"] += inv_profit

        page_key = int(inv.page_id or 0)
        page_name = (inv.page_name or "").strip()
        if not page_name and getattr(inv, "page", None):
            page_name = (inv.page.name or "").strip()
        page_row = page_totals.setdefault(
            page_key,
            {"name": page_name or "غير محدد", "count": 0, "total": 0, "profit": 0},
        )
        if page_name:
            page_row["name"] = page_name
        page_row["count"] += getattr(inv, "report_sale_count", 1)
        page_row["total"] += inv_total
        page_row["profit"] += inv_profit

    top_employees = sorted(
        employee_totals.values(),
        key=lambda row: (row["total"], row["profit"], row["count"]),
        reverse=True,
    )[:10]
    top_pages = sorted(
        page_totals.values(),
        key=lambda row: (row["total"], row["profit"], row["count"]),
        reverse=True,
    )[:10]

    # ─── الموردون (أعلى الأرصدة المستحقة) ───
    try:
        from utils.supplier_accounting_repair import expected_supplier_totals
    except Exception:
        expected_supplier_totals = None

    ts_rows = Supplier.query.all()
    top_suppliers = []
    supplier_groups = {}
    for s in ts_rows:
        if expected_supplier_totals:
            expected_debt, expected_paid = expected_supplier_totals(int(s.id))
        else:
            expected_debt = int(s.total_debt or 0)
            expected_paid = int(s.total_paid or 0)
        key = " ".join(str(s.name or "").strip().casefold().replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").split()) or f"supplier:{s.id}"
        if not independent_branches_enabled():
            row = supplier_groups.setdefault(key, {"name": s.name or "غير محدد", "total_debt": 0, "total_paid": 0})
            row["total_debt"] += int(expected_debt or 0)
            row["total_paid"] += int(expected_paid or 0)
            continue
        remaining = int(expected_debt - expected_paid)
        if remaining <= 0:
            continue
        top_suppliers.append({
            "name": s.name or "غير محدد",
            "total_debt": int(expected_debt),
            "total_paid": int(expected_paid),
            "remaining": remaining,
        })
    if not independent_branches_enabled():
        top_suppliers = []
        for row in supplier_groups.values():
            remaining = int(row["total_debt"] - row["total_paid"])
            if remaining > 0:
                top_suppliers.append({**row, "remaining": remaining})
    top_suppliers = sorted(top_suppliers, key=lambda row: row["remaining"], reverse=True)[:10]

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
        d = business_date(created)
        key = _bucket_key(d)
        b = buckets.setdefault(key, {"revenue": 0, "cogs": 0, "expenses": 0})
        b["revenue"] += int(inv.total or 0)
        b["cogs"] += int(cogs_by_invoice.get(int(inv.id), 0))

    exp_rows = db.session.query(
        Expense.expense_date,
        func.sum(Expense.amount).label("total"),
    ).filter(
        posted_expense_filter(),
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

    number_checks = [
        {
            "label": "تقسيم مبيعات الفترة",
            "ok": int(cash_sales + credit_sales) == int(total_revenue),
            "formula": "الإيرادات = المسدّد + غير المحصّل",
        },
        {
            "label": "إجمالي الربح",
            "ok": int(total_revenue - cogs_period) == int(gross_profit),
            "formula": "الإيرادات − تكلفة البضاعة",
        },
        {
            "label": "صافي الربح",
            "ok": int(gross_profit - total_operating_expenses_period) == int(net_profit_period),
            "formula": "إجمالي الربح − جميع مصاريف الفترة",
        },
        {
            "label": "تفصيل السيولة",
            "ok": int(cash_balance + bank_balance_total) == int(total_liquidity),
            "formula": "الصندوق + البنوك",
        },
        {
            "label": "تجميع الأصول",
            "ok": int(
                total_liquidity
                + inventory_value
                + accounts_receivable
                + fixed_assets_book_value
                + rs_summary["rotating_savings_asset"]
            ) == int(total_assets),
            "formula": "السيولة + المخزون + الذمم + الأصول الأخرى",
        },
        {
            "label": "المعادلة المعروضة",
            "ok": int(total_liabilities + equity) == int(total_assets),
            "formula": "الأصول = الالتزامات + صافي الأصول",
        },
    ]

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
        "non_cash_expenses_period": non_cash_expenses_period,
        "inventory_losses_period": inventory_losses_period,
        "other_operating_expenses_period": other_operating_expenses_period,
        "total_operating_expenses_period": total_operating_expenses_period,
        "expenses_breakdown": expenses_breakdown,
        "net_profit_period": net_profit_period,
        "invoices_count": sum(getattr(inv, "report_sale_count", 1) for inv in period_invoices),
        "return_documents": return_activity["returns"],
        "return_documents_count": len(return_activity["returns"]),
        "return_credit_period": sum(row["credit"] for row in return_activity["returns"]),
        # ميزانية / أرصدة
        "cash_balance": int(cash_balance),
        "bank_balances": bank_balances,
        "bank_balance_total": int(bank_balance_total),
        "total_liquidity": int(total_liquidity),
        "treasury_balances": treasury_balances,
        "inventory_value": int(inventory_value),
        "accounts_receivable": int(accounts_receivable),
        "customer_receivables": int(customer_receivables),
        "supplier_debts": int(supplier_debts),
        "shipping_due": 0,
        "shipping_receivables": int(shipping_receivables),
        "shipping_orders_receivable": int(shipping_orders_receivable),
        "shipping_opening_balance": int(shipping_opening_balance),
        "total_assets": total_assets,
        "current_assets": current_assets,
        "total_liabilities": total_liabilities,
        "working_capital": working_capital,
        "equity": equity,
        "equity_note": "صافي الأصول = إجمالي الأصول − إجمالي الالتزامات؛ ليس تحققاً مستقلاً من ميزان مراجعة عام",
        # تدفق نقدي
        "cash_inflow": cash_inflow,
        "cash_outflow": cash_outflow,
        "net_cash_flow": net_cash_flow,
        "cash_flow_breakdown": cash_flow_breakdown,
        # مخزون
        "low_stock_count": low_stock_count,
        "zero_stock_count": zero_stock_count,
        # مقارنة
        "prev_label": prev_label,
        "prev_revenue": prev_revenue,
        "prev_profit": prev_profit,
        "growth_revenue_pct": growth_revenue_pct,
        "growth_profit_pct": growth_profit_pct,
        # نسب
        "gross_margin_pct": gross_margin_pct,
        "profit_margin_pct": profit_margin_pct,
        "expense_to_revenue_pct": expense_to_revenue_pct,
        "collection_rate_pct": collection_rate_pct,
        "current_ratio": current_ratio,
        "liquidity_ratio": liquidity_ratio,
        "debt_to_assets_pct": debt_to_assets_pct,
        # جداول تفصيلية
        "top_products": top_products,
        "top_customers": top_customers,
        "top_employees": top_employees,
        "top_pages": top_pages,
        "top_suppliers": top_suppliers,
        # رسوم بيانية
        "chart_series": chart_series,
        "number_checks": number_checks,
        "number_checks_passed": sum(1 for check in number_checks if check["ok"]),
        # أصول ثابتة
        "fixed_assets_book_value": fixed_assets_book_value,
        "fixed_assets_cost": fa_summary["fixed_assets_cost"],
        "fixed_assets_accumulated_depreciation": fa_summary["fixed_assets_accumulated_depreciation"],
        "fixed_assets_depreciation_period": fixed_assets_depreciation_period,
        "fixed_assets_active_count": fa_summary["fixed_assets_active_count"],
        # جمعيات وسلف دوّارة
        "rotating_savings_paid": rs_summary["rotating_savings_paid"],
        "rotating_savings_received": rs_summary["rotating_savings_received"],
        "rotating_savings_liability": rs_summary["rotating_savings_liability"],
        "rotating_savings_asset": rs_summary["rotating_savings_asset"],
        "rotating_savings_fees": rs_summary["rotating_savings_fees"],
        "rotating_savings_active_count": rs_summary["rotating_savings_active_count"],
        # الأجل والأقساط
        "installment_debt_total": installment_debt_total,
        "installment_debt_unlinked": installment_debt_unlinked,
        "installment_debt_linked": installment_debt_linked,
        "installment_active_plans": installment_active_plans,
    }
