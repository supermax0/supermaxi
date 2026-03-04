from flask import Blueprint, render_template, jsonify, session, redirect, request
from extensions import db
from sqlalchemy import func
from datetime import datetime

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
    calculate_shipping_due,            # مستحقات النقل (التزامات)
    calculate_total_sales_for_display  # إجمالي المبيعات (للعرض فقط)
)

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")

def check_permission(permission_name):
    """فحص الصلاحية - helper function"""
    if "user_id" not in session:
        return False
    employee = Employee.query.get(session["user_id"])
    if not employee or not employee.is_active:
        return False
    # Admin لديه جميع الصلاحيات
    if employee.role == "admin":
        return True
        
    perm_map = {
        "can_see_orders": "view_orders",
        "can_see_reports": "view_reports",
        "can_manage_inventory": "manage_inventory",
        "can_see_expenses": "view_expenses",
        "can_manage_suppliers": "manage_suppliers",
        "can_manage_customers": "manage_customers",
        "can_see_accounts": "view_accounts",
        "can_see_financial": "view_financial",
        "can_edit_price": "edit_price",
    }
    rbac_name = perm_map.get(permission_name, permission_name)
    return employee.has_permission(rbac_name)

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
    # ديون الموردين ومستحقات النقل
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

# ======================================================
# التقرير المالي الشامل (Financial Report)
# ======================================================
@reports_bp.route("/financial")
def financial_report():
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403

    period_type = request.args.get("period_type", "this_month")
    custom_date_from = request.args.get("date_from")
    custom_date_to = request.args.get("date_to")

    data = get_financial_report_data(period_type, custom_date_from, custom_date_to)
    settings = InvoiceSettings.query.first()
    company_name = (settings.company_name or "الشركة") if settings else "الشركة"
    data["company_name"] = company_name
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
    
    orders = Invoice.query.filter(
        Invoice.status != "ملغي"
    ).order_by(Invoice.created_at.desc()).limit(limit).all()

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
        if payment_status == "مسدد" or status == "مسدد":
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
