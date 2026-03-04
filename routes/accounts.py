from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from extensions import db
from sqlalchemy import func, or_
from models.account_transaction import AccountTransaction
from models.invoice import Invoice
from models.order_item import OrderItem
from models.expense import Expense
from models.employee import Employee

# =======================
# Accounting Calculations (الحسابات المحاسبية الصحيحة)
# =======================
from utils.accounting_calculations import (
    calculate_paid_sales,        # المبيعات المسددة
    calculate_paid_cogs,          # COGS المسدد
    calculate_total_expenses,     # المصاريف
    calculate_operational_profit,  # الربح التشغيلي
    calculate_net_profit           # صافي الربح (Accrual)
)

accounts_bp = Blueprint("accounts", __name__, url_prefix="/accounts")

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
    
    # Map old boolean column names to new RBAC string names
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

# ============================
# Accounts Page
# ============================
@accounts_bp.route("/", methods=["GET", "POST"])
def accounts():
    # فحص الصلاحية
    if not check_permission("can_see_accounts"):
        return redirect("/pos"), 403

    if request.method == "POST":
        tx = AccountTransaction(
            type=request.form["type"],
            amount=int(request.form["amount"]),
            note=request.form.get("note")
        )
        db.session.add(tx)
        db.session.commit()
        return redirect(url_for("accounts.accounts"))

    transactions = AccountTransaction.query.order_by(
        AccountTransaction.created_at.desc()
    ).all()

    # ==========================
    # تصحيح محاسبي: استبعاد حركات المخزون الافتتاحي من الحسابات المالية
    # السبب المحاسبي:
    # - المخزون الافتتاحي يُعتبر قيمة مخزون فقط (Asset)
    # - لا يؤثر على الرصيد المالي (Cash/Balance)
    # - يجب استبعاده من حساب الرصيد المالي
    # ==========================
    # فلترة الحركات المالية: استبعاد الحركات المتعلقة بالمخزون الافتتاحي
    financial_transactions = [
        t for t in transactions 
        if not (t.note and "مخزون افتتاحي" in t.note)
    ]
    
    # عرض الحركات المالية فقط (بدون حركات المخزون الافتتاحي)
    transactions_to_display = financial_transactions

    # ==========================
    # تصحيح محاسبي: اعتماد الصندوق كمصدر وحيد للرصيد النقدي
    # السبب المحاسبي:
    # - الصندوق (Cash) هو المصدر الوحيد الموثوق للرصيد النقدي
    # - صفحة الحسابات تُستخدم فقط لعرض الأرباح/الإيرادات/رأس المال
    # - لا تقوم صفحة الحسابات بحساب الرصيد النقدي (يُحسب من الصندوق فقط)
    # ==========================
    # حساب الإيداعات والسحوبات من الحركات المالية (للعرض فقط - ليس للرصيد)
    total_deposit = sum(
        t.amount for t in financial_transactions if t.type == "deposit"
    )

    total_withdraw = sum(
        t.amount for t in financial_transactions if t.type == "withdraw"
    )

    # ==========================
    # الرصيد النقدي يُحسب من الصندوق فقط (Cash Transactions)
    # استخدام حساب الصندوق كمصدر وحيد - منع الازدواجية
    # ==========================
    from utils.cash_calculations import calculate_cash_balance
    balance = calculate_cash_balance()  # الرصيد من الصندوق - المصدر الوحيد الموثوق

    # ===============================
    # حساب صافي الأرباح (باستخدام الدوال المحاسبية الصحيحة)
    # الصيغة المحاسبية الصحيحة:
    # صافي الربح = (المبيعات المسددة - المرتجعات) - COGS المسدد - المصاريف
    # ===============================
    # استخدام الدوال المحاسبية الصحيحة لفصل المفاهيم
    # السبب المحاسبي: ضمان فصل الإيرادات عن COGS عن المصاريف
    
    # المبيعات المسددة
    paid_sales = calculate_paid_sales()
    
    # COGS للطلبات المسددة
    # السبب المحاسبي: عند البيع، يُخصم COGS من المخزون
    total_cost = calculate_paid_cogs()
    
    # المصاريف
    # السبب المحاسبي: المصاريف حساب مستقل، لا تؤثر على المخزون أو رأس المال مباشرة
    total_expenses = calculate_total_expenses()
    
    # حساب الربح قبل المصاريف (Gross Profit)
    # السبب المحاسبي: الربح الإجمالي = الإيرادات - COGS (قبل المصاريف)
    gross_profit = paid_sales - total_cost
    
    # صافي الربح (Net Profit)
    # الصيغة المحاسبية الصحيحة: الربح = الإيرادات - COGS - المصاريف
    # ==========================
    # تصحيح محاسبي: الربح يُحسب فقط من المبيعات # CRUCIAL ACCOUNTING FIX
    # السبب المحاسبي:
    # - الربح = Sales - COGS (يُحسب فقط عند البيع)
    # - لا يُحسب من الحركات النقدية (قبض / صرف / إيداع)
    # - لا يُضاف تلقائياً إلى رأس المال (يُضاف فقط في نهاية الفترة المالية)
    # - الحركات النقدية تُستخدم لتحديث الصندوق فقط، لا تؤثر على الأرباح
    # ==========================
    net_profit = calculate_operational_profit()
    
    # ==========================
    # تم إزالة منطق إضافة الربح تلقائياً إلى رأس المال
    # السبب: الربح يُحسب فقط من المبيعات، ولا يجب إعادة حسابه من الحركات النقدية
    # ==========================

    # حساب نسب التحذير
    expense_ratio = (total_expenses / gross_profit * 100) if gross_profit > 0 else 0
    profit_ratio = (net_profit / paid_sales * 100) if paid_sales > 0 else 0
    
    # تحديد نوع التنبيه
    alert_type = None
    alert_message = None
    
    if net_profit < 0:
        # خسارة - المصاريف أعلى من الربح
        alert_type = "danger"
        alert_message = f"⚠️ تحذير: خسارة! المصاريف ({total_expenses:,} د.ع) أعلى من الربح ({gross_profit:,} د.ع)"
    elif expense_ratio >= 80:
        # المصاريف مقاربة للربح (80% أو أكثر)
        alert_type = "warning"
        alert_message = f"⚠️ تحذير: المصاريف ({total_expenses:,} د.ع) تمثل {expense_ratio:.1f}% من الربح ({gross_profit:,} د.ع) - قريبة جداً من الخسارة!"
    elif profit_ratio < 20 and paid_sales > 0:
        # الربح قليل (أقل من 20% من المبيعات)
        alert_type = "info"
        alert_message = f"💡 ملاحظة: الربح الصافي ({net_profit:,} د.ع) يمثل {profit_ratio:.1f}% فقط من المبيعات ({paid_sales:,} د.ع) - ربح قليل"
    
    return render_template(
        "accounts.html",
        transactions=transactions_to_display,  # عرض الحركات المالية فقط (بدون المخزون الافتتاحي)
        total_deposit=total_deposit,
        total_withdraw=total_withdraw,
        balance=balance,
        net_profit=net_profit,
        total_expenses=total_expenses,
        gross_profit=gross_profit,
        paid_sales=paid_sales,
        alert_type=alert_type,
        alert_message=alert_message
    )

# ============================
# Add Capital from Profit
# ============================
@accounts_bp.route("/add-capital-from-profit", methods=["POST"])
def add_capital_from_profit():
    """
    إضافة الربح لرأس المال (إغلاق الفترة المالية)
    
    ملاحظة محاسبية مهمة:
    - الربح لا يُضاف لرأس المال مباشرة إلا في نهاية الفترة المالية
    - هذه الوظيفة تُستخدم لإغلاق الفترة وإضافة الربح لرأس المال
    """
    # حساب صافي الأرباح (الصيغة المحاسبية: الإيرادات - COGS - المصاريف)
    # ملاحظة مهمة: هذا "قيد إغلاق فترة" وليس حركة كاش فعلية
    net_profit = calculate_net_profit()
    
    if net_profit <= 0:
        return jsonify({
            "success": False,
            "error": "لا يوجد ربح صافي لإضافته إلى رأس المال"
        }), 400
    
    # تسجيل حركة "غير نقدية" للمتابعة فقط (لا تؤثر على الصندوق)
    # يتم استبعادها من حساب الكاش عبر فلتر "غير نقدي" في cash_calculations
    tx = AccountTransaction(
        type="deposit",
        amount=int(net_profit),
        note=f"إغلاق فترة (غير نقدي) - زيادة رأس المال من صافي الأرباح ({net_profit:,} د.ع)"
    )
    db.session.add(tx)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": f"تم إضافة {net_profit:,} د.ع إلى رأس المال من صافي الأرباح",
        "amount": int(net_profit)
    })
