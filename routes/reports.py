from flask import Blueprint, render_template, jsonify, session, redirect, request
from extensions import db
from sqlalchemy import case, func, or_
from datetime import datetime, timedelta

# =======================
# Models
# =======================
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.shipping import ShippingCompany
from models.expense import Expense
from models.supplier import Supplier
from models.supplier_invoice import SupplierInvoice
from models.employee import Employee
from models.invoice_settings import InvoiceSettings
from models.page import Page
from utils.financial_report_data import get_financial_report_data

# =======================
# Accounting Calculations (الحسابات المحاسبية الصحيحة)
# =======================
from utils.accounting_calculations import (
    calculate_total_revenue,           # الإيرادات (المبيعات - المرتجعات)
    calculate_total_cogs,              # تكلفة البضاعة المباعة
    calculate_inventory_value,         # قيمة المخزون
    calculate_total_expenses,          # المصاريف
    calculate_total_returns,           # المرتجعات
    calculate_net_profit,              # صافي الربح (الإيرادات - COGS - المصاريف)
    calculate_operational_profit,      # الربح التشغيلي (من المبيعات المسددة)
    calculate_supplier_debts,          # ديون الموردين (التزامات)
    calculate_shipping_due,            # ذمم شركات النقل
    calculate_total_sales_for_display  # إجمالي المبيعات (للعرض فقط)
)
from utils.permission_checks import check_permission

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


RETURN_STATUSES = ("مرتجع", "راجع", "راجعة", "راجعه")
CANCELED_STATUSES = ("ملغي",)
DELIVERED_STATUSES = ("تم التوصيل", "مسدد", "واصل", "واصلة")


def _parse_monitor_date(value, fallback):
    if not value:
        return fallback
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return fallback


def _not_bad_status_condition():
    return (
        or_(Invoice.status.is_(None), ~Invoice.status.in_(RETURN_STATUSES + CANCELED_STATUSES)),
        or_(Invoice.payment_status.is_(None), ~Invoice.payment_status.in_(RETURN_STATUSES + CANCELED_STATUSES)),
    )


def _rate(part, total):
    return round((float(part or 0) / float(total or 1)) * 100, 1)


def _fmt_money(value):
    return f"{int(value or 0):,} د.ع"


def _build_monitor_data(date_from, date_to, min_orders, min_sales):
    valid_conditions = _not_bad_status_condition()
    delivered_condition = or_(
        Invoice.status.in_(DELIVERED_STATUSES),
        Invoice.payment_status.in_(("مسدد", "تم التوصيل")),
    )

    page_rows = (
        db.session.query(
            Invoice.page_id,
            func.count(Invoice.id).label("orders_count"),
            func.coalesce(
                func.sum(case((delivered_condition, 1), else_=0)),
                0,
            ).label("delivered_count"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            or_(
                                Invoice.status.in_(RETURN_STATUSES + CANCELED_STATUSES),
                                Invoice.payment_status.in_(RETURN_STATUSES + CANCELED_STATUSES),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("returned_count"),
            func.coalesce(
                func.sum(case((valid_conditions[0] & valid_conditions[1], Invoice.total), else_=0)),
                0,
            ).label("clean_sales"),
        )
        .filter(Invoice.created_at >= date_from, Invoice.created_at <= date_to)
        .group_by(Invoice.page_id)
        .all()
    )
    page_stats = {row.page_id: row for row in page_rows}

    pages = Page.query.order_by(Page.name).all()
    page_monitor = []
    total_page_orders = 0
    total_page_sales = 0

    for page in pages:
        row = page_stats.get(page.id)
        orders_count = int(getattr(row, "orders_count", 0) or 0)
        clean_sales = int(getattr(row, "clean_sales", 0) or 0)
        delivered_count = int(getattr(row, "delivered_count", 0) or 0)
        returned_count = int(getattr(row, "returned_count", 0) or 0)
        return_rate = _rate(returned_count, orders_count)
        delivered_rate = _rate(delivered_count, orders_count)

        if orders_count == 0:
            health = "خامد"
            health_class = "danger"
            note = "لا توجد طلبات ضمن الفترة"
        elif return_rate >= 30:
            health = "يحتاج متابعة"
            health_class = "warning"
            note = "نسبة الراجع/الإلغاء عالية"
        elif orders_count >= 3 and delivered_rate < 40:
            health = "توصيل ضعيف"
            health_class = "warning"
            note = "نسبة الوصول أقل من المطلوب"
        else:
            health = "مستقر"
            health_class = "success"
            note = "الأداء ضمن الطبيعي"

        total_page_orders += orders_count
        total_page_sales += clean_sales
        page_monitor.append(
            {
                "id": page.id,
                "name": page.name,
                "orders_count": orders_count,
                "sales": clean_sales,
                "sales_display": _fmt_money(clean_sales),
                "delivered_count": delivered_count,
                "delivered_rate": delivered_rate,
                "returned_count": returned_count,
                "return_rate": return_rate,
                "assigned_employees": ", ".join(emp.name for emp in page.employees.all()) or "غير محدد",
                "health": health,
                "health_class": health_class,
                "note": note,
            }
        )

    unassigned_row = page_stats.get(None)
    unassigned_orders = int(getattr(unassigned_row, "orders_count", 0) or 0)
    if unassigned_orders:
        unassigned_sales = int(getattr(unassigned_row, "clean_sales", 0) or 0)
        unassigned_returned = int(getattr(unassigned_row, "returned_count", 0) or 0)
        unassigned_delivered = int(getattr(unassigned_row, "delivered_count", 0) or 0)
        total_page_orders += unassigned_orders
        total_page_sales += unassigned_sales
        page_monitor.append(
            {
                "id": None,
                "name": "طلبات بدون بيج",
                "orders_count": unassigned_orders,
                "sales": unassigned_sales,
                "sales_display": _fmt_money(unassigned_sales),
                "delivered_count": unassigned_delivered,
                "delivered_rate": _rate(unassigned_delivered, unassigned_orders),
                "returned_count": unassigned_returned,
                "return_rate": _rate(unassigned_returned, unassigned_orders),
                "assigned_employees": "غير محدد",
                "health": "ناقص ربط",
                "health_class": "warning",
                "note": "طلبات لا تحتوي page_id",
            }
        )

    page_monitor.sort(key=lambda item: (item["health_class"] == "success", -item["orders_count"]))

    employee_rows = (
        db.session.query(
            Invoice.employee_id,
            func.count(Invoice.id).label("orders_count"),
            func.coalesce(func.sum(case((valid_conditions[0] & valid_conditions[1], Invoice.total), else_=0)), 0).label("sales"),
            func.coalesce(func.sum(case((delivered_condition, 1), else_=0)), 0).label("delivered_count"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            or_(
                                Invoice.status.in_(RETURN_STATUSES + CANCELED_STATUSES),
                                Invoice.payment_status.in_(RETURN_STATUSES + CANCELED_STATUSES),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("returned_count"),
            func.max(Invoice.created_at).label("last_order_at"),
        )
        .filter(Invoice.created_at >= date_from, Invoice.created_at <= date_to)
        .group_by(Invoice.employee_id)
        .all()
    )
    employee_stats = {row.employee_id: row for row in employee_rows}
    employees = (
        Employee.query
        .filter(Employee.is_active.is_(True), Employee.role != "admin")
        .order_by(Employee.name)
        .all()
    )
    employee_monitor = []
    weak_employees = []
    total_employee_orders = 0
    total_employee_sales = 0

    for employee in employees:
        row = employee_stats.get(employee.id)
        orders_count = int(getattr(row, "orders_count", 0) or 0)
        sales = int(getattr(row, "sales", 0) or 0)
        delivered_count = int(getattr(row, "delivered_count", 0) or 0)
        returned_count = int(getattr(row, "returned_count", 0) or 0)
        last_order_at = getattr(row, "last_order_at", None)
        reasons = []
        if orders_count < min_orders:
            reasons.append(f"طلبات أقل من {min_orders}")
        if min_sales > 0 and sales < min_sales:
            reasons.append(f"مبيعات أقل من {_fmt_money(min_sales)}")
        if orders_count > 0 and _rate(returned_count, orders_count) >= 30:
            reasons.append("راجع/إلغاء عالي")

        item = {
            "id": employee.id,
            "name": employee.name,
            "username": employee.username,
            "role": "مدير" if employee.role == "admin" else "كاشير",
            "orders_count": orders_count,
            "sales": sales,
            "sales_display": _fmt_money(sales),
            "delivered_count": delivered_count,
            "returned_count": returned_count,
            "return_rate": _rate(returned_count, orders_count),
            "last_order_at": last_order_at,
            "last_order_display": last_order_at.strftime("%Y-%m-%d %H:%M") if last_order_at else "لا يوجد",
            "status": "ضعيف" if reasons else "طبيعي",
            "status_class": "danger" if reasons else "success",
            "reason": "، ".join(reasons) if reasons else "الأداء ضمن الحد",
        }
        total_employee_orders += orders_count
        total_employee_sales += sales
        employee_monitor.append(item)
        if reasons:
            weak_employees.append(item)

    employee_monitor.sort(key=lambda item: (item["status_class"] == "success", item["orders_count"], item["sales"]))
    weak_employees.sort(key=lambda item: (item["orders_count"], item["sales"]))

    alerts = [
        page for page in page_monitor
        if page["health_class"] in ("danger", "warning")
    ][:8]

    return {
        "date_from": date_from,
        "date_to": date_to,
        "min_orders": min_orders,
        "min_sales": min_sales,
        "page_monitor": page_monitor,
        "employee_monitor": employee_monitor,
        "weak_employees": weak_employees,
        "alerts": alerts,
        "summary": {
            "pages_count": len(page_monitor),
            "page_orders": total_page_orders,
            "page_sales": total_page_sales,
            "page_sales_display": _fmt_money(total_page_sales),
            "employees_count": len(employee_monitor),
            "weak_employees_count": len(weak_employees),
            "employee_orders": total_employee_orders,
            "employee_sales": total_employee_sales,
            "employee_sales_display": _fmt_money(total_employee_sales),
        },
    }


# ======================================================
# Dashboard (Cards Only)
# ======================================================
@reports_bp.route("/")
def reports_dashboard():
    # فحص الصلاحية
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403

    # ===============================
    # حساب القيم المحاسبية الصحيحة
    # استخدام الدوال المحاسبية لضمان فصل المفاهيم
    # ===============================
    
    # إجمالي المبيعات (للعرض فقط - لا يُستخدم في الحسابات)
    # السبب المحاسبي: نعرضه للتقارير لكن الحسابات تستخدم الإيرادات (Revenue)
    total_sales = calculate_total_sales_for_display()
    
    # الإيرادات (Revenue) = المبيعات - المرتجعات
    # السبب المحاسبي: الإيرادات تُحسب من المبيعات بعد خصم المرتجعات
    # لا يتم خصم COGS أو المصاريف هنا (تُحسب في الربح)
    total_revenue = calculate_total_revenue()
    
    # قيمة المخزون (Inventory Value)
    # السبب المحاسبي: المخزون يُعتبر أصل (Asset) ولا يدخل ضمن رأس المال
    # قيمة المخزون = الكمية الحالية × سعر الشراء
    total_inventory_value = calculate_inventory_value()
    
    # المرتجعات (Returns)
    # السبب المحاسبي: المرتجعات تُخصم من الإيرادات وتعيد COGS للمخزون
    total_returns = calculate_total_returns()
    
    # المصاريف (Expenses)
    # السبب المحاسبي: المصاريف حساب مستقل، لا تؤثر على المخزون أو رأس المال مباشرة
    total_expenses = calculate_total_expenses()
    
    # ===============================
    # حساب الربح التشغيلي (Operational Profit)
    # الصيغة المحاسبية الصحيحة:
    # الربح = (المبيعات المسددة - المرتجعات) - COGS المسدد - المصاريف
    # ===============================
    # ملاحظة: الربح لا يُضاف لرأس المال مباشرة، فقط في نهاية الفترة المالية
    operational_profit = calculate_operational_profit()
    
    # ===============================
    # الالتزامات (Liabilities)
    # ديون الموردين. ذمم شركات النقل تُعامل كأصل/ذمم مدينة.
    # السبب المحاسبي: الالتزامات لا تؤثر على الربح إلا عند الدفع
    # ===============================
    supplier_debts = calculate_supplier_debts()

    return render_template(
        "reports.html",
        total_sales=total_sales,
        total_expenses=total_expenses,
        inventory_value=total_inventory_value,
        returned_total=total_returns,
        profit=operational_profit,
        supplier_debts=supplier_debts
    )


@reports_bp.route("/monitor")
def pages_employees_monitor():
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403

    now = datetime.utcnow()
    default_from = now - timedelta(days=30)
    date_from = _parse_monitor_date(request.args.get("date_from"), default_from).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    date_to = _parse_monitor_date(request.args.get("date_to"), now).replace(
        hour=23,
        minute=59,
        second=59,
        microsecond=999999,
    )
    if date_from > date_to:
        date_from, date_to = date_to.replace(hour=0, minute=0, second=0, microsecond=0), date_from.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )

    min_orders = max(0, request.args.get("min_orders", 5, type=int) or 0)
    min_sales = max(0, request.args.get("min_sales", 0, type=int) or 0)
    data = _build_monitor_data(date_from, date_to, min_orders, min_sales)

    return render_template("reports_monitor.html", **data)

# ======================================================
# التقرير المالي الشامل (Financial Report)
# ======================================================
@reports_bp.route("/financial")
def financial_report():
    if not (check_permission("view_financial") or check_permission("can_see_reports")):
        return redirect("/pos"), 403

    period_type = request.args.get("period_type", "this_month")
    custom_date_from = request.args.get("date_from")
    custom_date_to = request.args.get("date_to")

    data = get_financial_report_data(period_type, custom_date_from, custom_date_to)
    settings = InvoiceSettings.query.first()

    def _pick(*vals):
        for v in vals:
            if v is not None and str(v).strip() != "":
                return v
        return None

    if settings:
        data["company_name"] = _pick(
            getattr(settings, "report_company_name", None),
            settings.company_name,
        ) or "الشركة"
        show_logo = getattr(settings, "report_show_logo", True)
        data["report_logo"] = _pick(
            getattr(settings, "report_logo_path", None),
            settings.logo_path,
        ) if show_logo else None
        data["report_address"] = _pick(
            getattr(settings, "report_address", None),
            settings.company_address,
        )
        data["report_phone"] = _pick(
            getattr(settings, "report_phone", None),
            settings.company_phone,
        )
        data["report_footer"] = _pick(
            getattr(settings, "report_footer_text", None),
        ) or "نظام المحاسبة - تقرير رسمي للطباعة"
    else:
        data["company_name"] = "الشركة"
        data["report_logo"] = None
        data["report_address"] = None
        data["report_phone"] = None
        data["report_footer"] = "نظام المحاسبة - تقرير رسمي للطباعة"

    data["report_generated_at"] = datetime.utcnow()

    return render_template("reports_financial.html", **data)


# ======================================================
# Sales Report (تفصيلي)
# ======================================================
@reports_bp.route("/sales")
def sales_report():
    # فحص الصلاحية
    if not check_permission("can_see_reports"):
        return jsonify({"error": "Unauthorized"}), 403
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    branch_id = request.args.get("branch_id", type=int)
    
    query = Invoice.query.filter(Invoice.status != "ملغي")
    if branch_id:
        query = query.filter(Invoice.branch_id == branch_id)
    orders = query.order_by(Invoice.created_at.desc()).limit(limit).all()

    return jsonify([
        {
            "رقم الفاتورة": o.id,
            "الزبون": o.customer_name,
            "المبلغ": o.total,
            "الحالة": o.status,
            "الدفع": o.payment_status,
            "التاريخ": o.created_at.strftime("%Y-%m-%d")
        } for o in orders
    ])

# ======================================================
# Profit Report (حسب المنتجات)
# ======================================================
@reports_bp.route("/profit")
def profit_report():
    # فحص الصلاحية
    if not check_permission("can_see_reports"):
        return jsonify({"error": "Unauthorized"}), 403
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    
    rows = []

    items = OrderItem.query.limit(limit).all()
    for i in items:
        rows.append({
            "المنتج": i.product_name,
            "الكمية": i.quantity,
            "سعر البيع": i.price,
            "سعر التكلفة": i.cost,
            "الربح الإجمالي": (i.price - i.cost) * i.quantity
        })

    return jsonify(rows)

# ======================================================
# Expenses Report (تفصيلي + نسبة)
# ======================================================
@reports_bp.route("/expenses")
def expenses_report():
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    
    total_sales = db.session.query(
        func.sum(Invoice.total)
    ).filter(Invoice.status != "ملغي").scalar() or 1

    expenses = Expense.query.order_by(
        Expense.expense_date.desc()
    ).limit(limit).all()

    details = []
    total_expenses = 0

    for e in expenses:
        total_expenses += e.amount
        details.append({
            "العنوان": e.title,
            "الفئة": e.category,
            "المبلغ": e.amount,
            "النسبة من المبيعات %": round((e.amount / total_sales) * 100, 2),
            "التاريخ": e.expense_date.strftime("%Y-%m-%d")
        })

    return jsonify({
        "إجمالي المصاريف": total_expenses,
        "تفاصيل": details
    })

# ======================================================
# Inventory Report
# ======================================================
@reports_bp.route("/inventory")
def inventory_report():
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    
    products = Product.query.order_by(Product.name).limit(limit).all()

    return jsonify([
        {
            "المنتج": p.name,
            "الكمية": p.quantity,
            "سعر الشراء": p.buy_price,
            "القيمة الإجمالية": p.quantity * p.buy_price
        } for p in products
    ])

# ======================================================
# Returned Orders
# ======================================================
@reports_bp.route("/returned")
def returned_report():
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    
    # توحيد حالات المرتجع (status / payment_status)
    orders = Invoice.query.filter(
        or_(
            Invoice.status.in_(["مرتجع", "راجع", "راجعة"]),
            Invoice.payment_status == "مرتجع"
        )
    ).order_by(Invoice.created_at.desc()).limit(limit).all()

    return jsonify([
        {
            "رقم الفاتورة": o.id,
            "الزبون": o.customer_name,
            "المبلغ": o.total,
            "التاريخ": o.created_at.strftime("%Y-%m-%d")
        } for o in orders
    ])

# ======================================================
# Shipping Companies Report (مستحقات فقط)
# ======================================================
@reports_bp.route("/shipping")
def shipping_report():

    result = []

    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]

    def effective_paid_amount(order: Invoice) -> int:
        total = int(getattr(order, "total", 0) or 0)
        payment_status = getattr(order, "payment_status", None)
        status = getattr(order, "status", None)
        if payment_status in ("مرتجع", "ملغي", "راجع", "راجعة") or status in (
            "مرتجع",
            "ملغي",
            "راجع",
            "راجعة",
        ):
            return 0
        if payment_status == "مسدد" or status in ("مسدد", "تم التوصيل"):
            return max(total, 0)
        if payment_status == "جزئي":
            paid_amount = int(getattr(order, "paid_amount", 0) or 0)
            if paid_amount < 0:
                return 0
            return min(paid_amount, total) if total > 0 else paid_amount
        return 0

    def remaining_amount(order: Invoice) -> int:
        total = int(getattr(order, "total", 0) or 0)
        remaining = total - effective_paid_amount(order)
        return remaining if remaining > 0 else 0

    companies = ShippingCompany.query.all()
    for c in companies:
        orders = Invoice.query.filter(
            Invoice.shipping_company_id == c.id,
            Invoice.status != "ملغي"
        ).all()

        # المستحق = المتبقي (يدعم الدفع الجزئي) مع استبعاد الملغي/المرتجع
        due = sum(
            remaining_amount(o) for o in orders
            if o.payment_status != "مرتجع"
            and o.status not in (CANCELED_STATUSES + RETURN_STATUSES)
            and remaining_amount(o) > 0
        )

        result.append({
            "شركة النقل": c.name,
            "عدد الطلبات": len(orders),
            "المستحق": due
        })

    return jsonify(result)

# ======================================================
# Suppliers Report (ديون فقط)
# ======================================================
@reports_bp.route("/suppliers")
def suppliers_report():

    result = []

    suppliers = Supplier.query.all()
    for s in suppliers:
        # حساب الدين من الحقول المباشرة في Supplier
        total_debt = s.total_debt or 0
        total_paid = s.total_paid or 0
        remaining = total_debt - total_paid

        # فقط الموردين الذين لديهم ديون
        if remaining > 0:
            result.append({
                "المورد": s.name or "—",
                "الهاتف": s.phone or "—",
                "إجمالي الدين": f"{total_debt:,} د.ع",
                "المدفوع": f"{total_paid:,} د.ع",
                "المتبقي": f"{remaining:,} د.ع"
            })

    # ترتيب حسب المتبقي (الأكبر أولاً)
    result.sort(key=lambda x: int(x["المتبقي"].replace(" د.ع", "").replace(",", "")), reverse=True)

    return jsonify(result)
