from flask import Blueprint, render_template, jsonify, request, session, redirect
from sqlalchemy.sql import func
from sqlalchemy import or_
from datetime import date, timedelta, datetime
import json
import json

from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.shipping import ShippingCompany
from models.supplier import Supplier
from models.customer import Customer
from models.expense import Expense
from models.delivery_agent import DeliveryAgent
from models.account_transaction import AccountTransaction
from models.tenant import Tenant
from models.employee import Employee

# =======================
# Accounting Calculations (الحسابات المحاسبية الصحيحة)
# =======================
from utils.accounting_calculations import (
    calculate_total_revenue,           # الإيرادات (المبيعات - المرتجعات)
    calculate_inventory_value,         # قيمة المخزون
    calculate_total_expenses,          # المصاريف
    calculate_supplier_debts,          # ديون الموردين (التزامات)
    calculate_shipping_due,            # مستحقات النقل (التزامات)
    calculate_total_sales_for_display  # إجمالي المبيعات (للعرض فقط)
)
from utils.date_periods import get_period_dates, get_period_label
from utils.cash_calculations import calculate_cash_balance

index_bp = Blueprint("index", __name__)

# خطط الاشتراك من قاعدة البيانات (للصفحة الرئيسية والتسجيل) — fallback إذا كانت الجداول فارغة
FALLBACK_PLANS = {
    "basic": {"key": "basic", "name": "الخطة الأساسية", "price_monthly": 25000, "price_yearly": 250000},
    "pro": {"key": "pro", "name": "الخطة المتقدمة", "price_monthly": 45000, "price_yearly": 450000},
    "enterprise": {"key": "enterprise", "name": "خطة الشركات", "price_monthly": 90000, "price_yearly": 900000},
}


def get_public_plans():
    """جلب خطط الاشتراك من قاعدة البيانات الأساسية (Core) للاستخدام في الهبوط والتسجيل."""
    from flask import g
    from models.core.subscription_plan import SubscriptionPlan
    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        rows = SubscriptionPlan.query.all()
        by_key = {}
        for p in rows:
            pm = getattr(p, "price_monthly", 0) or 0
            py = getattr(p, "price_yearly", 0) or 0
            om = getattr(p, "original_price_monthly", None)
            oy = getattr(p, "original_price_yearly", None)
            by_key[p.plan_key] = {
                "key": p.plan_key,
                "name": p.name,
                "price_monthly": pm,
                "price_yearly": py,
                "original_price_monthly": int(om) if om is not None else None,
                "original_price_yearly": int(oy) if oy is not None else None,
            }
        return by_key if by_key else None
    except Exception:
        return None
    finally:
        g.tenant = old_tenant


def _increment_landing_visits():
    """زيادة عدّاد زيارات صفحة الهبوط (إجمالي + زيارات اليوم) في قاعدة البيانات الأساسية."""
    try:
        from flask import g
        from models.system_analytics import SystemAnalytics

        old_tenant = getattr(g, "tenant", None)
        g.tenant = None

        today_key = date.today().isoformat()

        row = SystemAnalytics.query.filter_by(
            analysis_type="landing",
            title="landing_page_visits"
        ).first()

        if not row:
            daily = {today_key: 1}
            row = SystemAnalytics(
                analysis_type="landing",
                title="landing_page_visits",
                description="عدد زيارات صفحة الهبوط العامة",
                severity="info",
                affected_count=1,
                related_data=json.dumps({"daily": daily}),
            )
            db.session.add(row)
        else:
            # إجمالي الزيارات
            row.affected_count = (row.affected_count or 0) + 1
            # زيارات اليوم (داخل related_data.daily)
            try:
                data = json.loads(row.related_data) if row.related_data else {}
            except Exception:
                data = {}
            daily = data.get("daily", {})
            daily[today_key] = int(daily.get(today_key, 0)) + 1
            data["daily"] = daily
            row.related_data = json.dumps(data)

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[landing] failed to record visit: {e}")
    finally:
        try:
            g.tenant = old_tenant
        except Exception:
            pass


# =================================================
# PAGE (الرئيسية)
# =================================================
@index_bp.route("/")
def index():
    # إذا لم يكن مسجل دخول، عرض صفحة الهبوط (landing) التي أصبح اسمها index.html
    if "user_id" not in session:
        _increment_landing_visits()
        landing_plans = get_public_plans() or FALLBACK_PLANS
        return render_template("index.html", landing_plans=landing_plans)
    
    # إذا كان مسجل دخول (آدمن أو كاشير)
    if session.get("role") == "cashier":
        return render_template("dashbord.html", is_cashier=True, show_data=False)
        
    return render_template(
        "dashbord.html",
        employee_name=session.get("name", "")
    )


# =================================================
# Landing Page (تحويل لرابط الصفحة الجديدة)
# =================================================
@index_bp.route("/landing")
def landing():
    _increment_landing_visits()
    return redirect("/")


# =================================================
# Privacy & Terms (سياسة الخصوصية والشروط)
# =================================================
@index_bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@index_bp.route("/terms")
def terms():
    return render_template("terms.html")


# =================================================
# Contact Form (نموذج الاتصال)
# =================================================
@index_bp.route("/contact", methods=["POST"])
def contact():
    try:
        name = request.form.get("name")
        phone = request.form.get("phone")
        message = request.form.get("message")
        
        from utils.email_helper import send_contact_email
        email_sent = send_contact_email(name, phone, message)
        
        from flask import flash
        if email_sent:
            flash("شكراً لتواصلك معنا يا " + name + "! تم استلام رسالتك بنجاح وسنتواصل معك قريباً.")
        else:
            flash("شكراً لتواصلك معنا يا " + name + "! تم استلام طلبك بنجاح.")
            
        return redirect("/#contact")
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"❌ CONTACT FORM ERROR: {error_msg}")
        print(traceback.format_exc())
        
        from flask import flash
        # Show error directly to user to aid debugging
        flash(f"حدث خطأ أثناء الإرسال: {error_msg}")
        return redirect("/#contact")


# =================================================
# Upgrade Required (ترقية مطلوبة)
# =================================================
@index_bp.route("/upgrade")
def upgrade():
    return render_template("upgrade_required.html")



# =================================================
# SaaS Login (تسجيل الدخول المركزي)
# =================================================
@index_bp.route("/login", methods=["GET", "POST"])
def login():
    from werkzeug.security import check_password_hash
    
    if request.method == "GET":
        if "user_id" in session:
            # توجيه تلقائي إذا كان مسجل دخول
            return redirect("/" if session.get("role") == "admin" else "/pos")
        return render_template("login.html")

    # POST: التحقق من البيانات
    tenant_slug = request.form.get("tenant_slug", "").strip().lower()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not tenant_slug or not username or not password:
        return render_template("login.html", error="الرجاء إدخال معرف الشركة، اسم المستخدم، وكلمة المرور")

    # 1. Verify tenant in Core DB (g.tenant is None so it queries core.db)
    from models.core.tenant import Tenant as CoreTenant
    from flask import g
    core_tenant = CoreTenant.query.filter_by(slug=tenant_slug).first()
    
    if not core_tenant:
        return render_template("login.html", error="الشركة غير موجودة. تأكد من معرف الشركة.")
    
    if not core_tenant.is_active:
        return render_template("login.html", error="اشتراك هذه الشركة غير مفعل أو تم إيقافه.")

    # 2. Switch to Tenant DB and verify user (اسم المستخدم بدون اعتبار لحالة الأحرف)
    g.tenant = core_tenant.slug

    # تأكيد وجود أعمدة profile_pic / language / theme_preference في جدول employee
    try:
        from routes.employees import _ensure_employee_profile_schema
        _ensure_employee_profile_schema()
    except Exception as e:
        # لا نمنع تسجيل الدخول إذا فشل سكريبت الهجرة؛ سيتم تسجيل الخطأ فقط في اللوج
        print(f"[login] employee profile schema ensure failed: {e}")

    emp = Employee.query.filter(db.func.lower(Employee.username) == username.lower()).first()

    if not emp or not check_password_hash(emp.password, password):
        return render_template("login.html", error="بيانات الدخول غير صحيحة")

    if not emp.is_active:
        return render_template("login.html", error="هذا الحساب معطل، يرجى التواصل مع الإدارة")

    # تسجيل الجلسة (استخدام slug من قاعدة البيانات لضمان التطابق)
    session.clear()
    session.permanent = True  # استخدام PERMANENT_SESSION_LIFETIME (مثلاً 7 أيام)
    session["tenant_slug"] = core_tenant.slug
    session["user_id"] = emp.id
    session["name"] = emp.name
    session["role"] = emp.role
    session["tenant_id"] = emp.tenant_id
    
    # جلب معلومات الخطة
    if emp.tenant_id:
        from models.tenant import Tenant as _Tenant
        t = _Tenant.query.get(emp.tenant_id)
        if t:
            session["plan_key"] = t.plan_key

    # التوجيه حسب الدور
    if emp.role == "admin":
        return redirect("/")
    else:
        return redirect("/pos")


@index_bp.route("/login/<tenant_slug>", methods=["GET", "POST"])
def login_tenant(tenant_slug):
    """
    مسار مختصر لتسجيل دخول شركة محددة عبر رابط خاص:
    مثال: https://finora.company/login/super
    بحيث لا يحتاج المستخدم لإدخال معرف الشركة يدوياً.
    """
    tenant_slug = (tenant_slug or "").strip().lower()
    if request.method == "GET":
        # إذا مسجل دخول بالفعل، توجيه مباشر
        if "user_id" in session and session.get("tenant_slug") == tenant_slug:
            return redirect("/" if session.get("role") == "admin" else "/pos")
        # إعادة استخدام نفس صفحة login لكن مع تمرير tenant في الـ query (للـ placeholder وللقيمة)
        return render_template("login.html", fixed_tenant_slug=tenant_slug)

    # POST: نستخدم نفس منطق login الأساسي لكن مع tenant_slug من الـ path إذا لم يرسل في الـ form
    if not request.form.get("tenant_slug"):
        # حقن الـ slug في النموذج بحيث تعمل دالة login العادية كما هي
        from werkzeug.datastructures import ImmutableMultiDict
        form = request.form.to_dict(flat=True)
        form["tenant_slug"] = tenant_slug
        request.form = ImmutableMultiDict(form)
    return login()


# =================================================
# Logout (تسجيل الخروج)
# =================================================
@index_bp.route("/logout")
def logout():
    tenant_slug = session.get("tenant_slug")
    session.clear()
    if tenant_slug:
        return redirect(f"/login?tenant={tenant_slug}")
    return redirect("/login")


# =================================================
# SaaS Pricing Page (خطط الاشتراك)
# =================================================
@index_bp.route("/pricing")
def pricing():
    from models.core.subscription_plan import SubscriptionPlan
    from flask import g
    
    # Force Core DB access
    old_tenant = getattr(g, 'tenant', None)
    g.tenant = None
    try:
        db_plans = SubscriptionPlan.query.all()
        plans = []
        for p in db_plans:
            plans.append({
                "key": p.plan_key,
                "name": p.name,
                "price": p.price_monthly,
                "original_price": p.original_price_monthly,
                "description": "خطة " + p.name,
                "features": [
                    f"{p.max_users if p.max_users else 'غير محدود'} مستخدمين",
                    f"حتى {p.max_orders_monthly if p.max_orders_monthly else 'غير محدود'} فاتورة شهرياً",
                    "تشمل المخزون" if p.get_features().get("inventory") else "بدون مخزون",
                    "تشمل المساعد الذكي" if p.get_features().get("ai_assistant") else "بدون مساعد ذكي"
                ]
            })
    finally:
        g.tenant = old_tenant

    if not plans:
        # Fallback to hardcoded if DB empty
        plans = [
            {"key": "basic", "name": "الخطة الأساسية", "price": 25000, "description": "مناسبة للمشاريع الصغيرة", "features": ["5 مستخدمين", "1,000 فاتورة"]},
            {"key": "pro", "name": "الخطة المتقدمة", "price": 45000, "description": "للمتاجر النامية", "features": ["15 مستخدم", "10,000 فاتورة"]},
            {"key": "enterprise", "name": "خطة الشركات", "price": 90000, "description": "للشركات الكبيرة", "features": ["غير محدود", "غير محدود"]}
        ]
        
    return render_template("pricing.html", plans=plans)
 
 
# =================================================
# Payment & Checkout (الدفع وإتمام الاشتراك)
# =================================================
@index_bp.route("/payment")
def payment():
    plan_key = request.args.get("plan", "basic")
    billing = request.args.get("billing", "monthly")
    
    # تحضير بيانات الخطة للعرض
    PLANS = {
        "basic": {"name": "الخطة الأساسية", "price": 25000 if billing == "monthly" else 250000},
        "pro": {"name": "الخطة المتقدمة", "price": 45000 if billing == "monthly" else 450000},
        "enterprise": {"name": "خطة الشركات", "price": 90000 if billing == "monthly" else 900000},
    }
    plan = PLANS.get(plan_key, PLANS["basic"])
    
    return render_template("payment.html", plan=plan, plan_key=plan_key, billing=billing)


@index_bp.route("/payment/process", methods=["POST"])
def payment_process():
    # محاكاة بنجاح العملية
    return jsonify({"success": True, "redirect": "/payment/success"})


@index_bp.route("/payment/success")
def payment_success():
    from datetime import datetime
    return render_template("payment_success.html", datetime=datetime)


# =================================================
# SaaS Signup (تسجيل شركة جديدة)
# =================================================
@index_bp.route("/signup", methods=["GET", "POST"])
def signup():
    from werkzeug.security import generate_password_hash

    PLANS = get_public_plans() or FALLBACK_PLANS

    if request.method == "GET":
        plan_key    = request.args.get("plan", "basic")
        billing     = request.args.get("billing", "monthly")  # monthly | yearly
        plan        = PLANS.get(plan_key, PLANS.get("basic", FALLBACK_PLANS["basic"]))
        return render_template("signup.html",
            selected_plan=plan,
            plans=list(PLANS.values()),
            plans_dict=PLANS,
            billing=billing)

    # ── POST: إنشاء Tenant + Admin ──────────────────────────
    company_name = request.form.get("company_name", "").strip()
    contact_name = request.form.get("contact_name", "").strip()
    email        = request.form.get("email", "").strip()
    phone        = request.form.get("phone", "").strip()
    username     = request.form.get("username", "").strip()
    password     = request.form.get("password", "").strip()
    password2    = request.form.get("password2", "").strip()
    plan_key     = request.form.get("plan_key", "basic")
    billing      = request.form.get("billing", "monthly")

    plan = PLANS.get(plan_key, PLANS.get("basic", FALLBACK_PLANS["basic"]))

    def render_err(msg):
        return render_template("signup.html",
            selected_plan=plan, plans=list(PLANS.values()), plans_dict=PLANS,
            billing=billing, error=msg, form=request.form)

    # Validation
    if not company_name:
        return render_err("الرجاء إدخال اسم الشركة أو المشروع")
    if not contact_name:
        return render_err("الرجاء إدخال اسمك (صاحب الحساب)")
    if not username:
        return render_err("الرجاء إدخال اسم المستخدم")
    if len(username) < 3:
        return render_err("اسم المستخدم يجب أن يكون 3 أحرف على الأقل")
    if not password:
        return render_err("الرجاء إدخال كلمة المرور")
    if len(password) < 6:
        return render_err("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
    if password != password2:
        return render_err("كلمة المرور وتأكيدها غير متطابقتين")

    if Employee.query.filter_by(username=username).first():
        return render_err("اسم المستخدم مستخدم مسبقاً — الرجاء اختيار اسم آخر")

    try:
        # إنشاء Tenant
        monthly_price = plan["price_monthly"]
        tenant = Tenant(
            name=company_name,
            contact_name=contact_name,
            contact_email=email or None,
            contact_phone=phone or None,
            plan_key=plan["key"],
            plan_name=plan["name"],
            monthly_price=monthly_price,
            is_active=True,
        )
        months = 12 if billing == "yearly" else 1
        tenant.extend_subscription_months(months)
        db.session.add(tenant)
        db.session.flush()

        # إنشاء Admin
        hashed_pw = generate_password_hash(password)
        admin = Employee(
            name=contact_name,
            username=username,
            password=hashed_pw,
            role="admin",
            tenant_id=tenant.id,
        )
        db.session.add(admin)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return render_err(f"حدث خطأ أثناء إنشاء الحساب، يرجى المحاولة مجدداً. ({str(e)})")

    # تسجيل الجلسة
    session.permanent = True
    session["user_id"]  = admin.id
    session["name"]     = admin.name
    session["role"]     = admin.role
    session["tenant_id"] = tenant.id

    # توجيه لصفحة الدفع لإتمام الاشتراك
    return redirect(f"/payment?plan={plan_key}&billing={billing}")

# =================================================
# REPORT CARDS (TOP)
# =================================================
@index_bp.route("/api/index/reports")
def index_reports():
    # ===============================
    # الحصول على الفترة الزمنية (افتراضي: آخر 30 يوم من السنة الحالية)
    # ===============================
    period_type = request.args.get("period_type", "last_30_days")
    custom_date_from = request.args.get("date_from")
    custom_date_to = request.args.get("date_to")
    
    # حساب تواريخ الفترة
    date_from, date_to = get_period_dates(period_type, custom_date_from, custom_date_to)
    
    # ===============================
    # حساب القيم المحاسبية الصحيحة للفترة الزمنية
    # استخدام الدوال المحاسبية لضمان فصل المفاهيم
    # ===============================
    
    from sqlalchemy import and_
    
    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]
    
    def effective_paid_amount(inv: Invoice) -> int:
        total = int(getattr(inv, "total", 0) or 0)
        payment_status = getattr(inv, "payment_status", None)
        status = getattr(inv, "status", None)
        if payment_status == "مسدد" or status == "مسدد":
            return max(total, 0)
        if payment_status == "جزئي":
            paid_amount = int(getattr(inv, "paid_amount", 0) or 0)
            if paid_amount < 0:
                return 0
            return min(paid_amount, total) if total > 0 else paid_amount
        return 0
    
    # إجمالي المبيعات/التحصيل/الذمم للفترة
    # تصحيح محاسبي: دعم الدفع الجزئي + استبعاد (راجع/مرتجع/ملغي)
    period_invoices = Invoice.query.filter(
        func.date(Invoice.created_at) >= date_from,
        func.date(Invoice.created_at) <= date_to,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
    ).all()

    total_sales = sum(int(inv.total or 0) for inv in period_invoices)
    cash_sales = sum(effective_paid_amount(inv) for inv in period_invoices)
    credit_sales = sum(
        max(int(inv.total or 0) - effective_paid_amount(inv), 0)
        for inv in period_invoices
    )
    
    # المبيعات الواصلة والمسددة فقط للفترة (للعرض)
    # السبب المحاسبي: تُستخدم للتقارير فقط، لا تؤثر على حساب الربح مباشرة
    delivered_paid_sales = db.session.query(
        func.sum(Invoice.total)
    ).filter(
        func.date(Invoice.created_at) >= date_from,
        func.date(Invoice.created_at) <= date_to,
        or_(
            # الحالة الأولى: واصل ومسدد بشكل منفصل
            and_(
                Invoice.status == "تم التوصيل",
                Invoice.payment_status == "مسدد"
            ),
            # الحالة الثانية: status = "مسدد" (يعني واصل ومسدد معاً)
            Invoice.status == "مسدد"
        )
    ).scalar() or 0
    
    # حساب الأرباح للفترة (Cash-basis تقريباً):
    # التحصيل الفعلي - COGS المتناسب مع التحصيل - مصاريف الفترة
    sales_total = int(cash_sales)

    # COGS للفترة (متناسب مع التحصيل عند الدفع الجزئي)
    from models.order_item import OrderItem
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
        ).filter(
            OrderItem.invoice_id.in_(list(ratios.keys()))
        ).group_by(OrderItem.invoice_id).all()

        for invoice_id, cogs_sum in rows:
            if not cogs_sum:
                continue
            ratio = ratios.get(int(invoice_id), 0.0)
            cogs_period += int(round(float(cogs_sum) * ratio))
    
    # المصاريف للفترة
    expenses_period = db.session.query(func.sum(Expense.amount)).filter(
        func.date(Expense.expense_date) >= date_from,
        func.date(Expense.expense_date) <= date_to
    ).scalar() or 0
    
    # الربح الصافي للفترة = التحصيل - COGS المتناسب - المصاريف
    period_profit = int(sales_total - cogs_period - expenses_period)

    # قيمة المخزون (Inventory Value)
    # السبب المحاسبي: المخزون يُعتبر أصل (Asset) ولا يدخل ضمن رأس المال
    # قيمة المخزون = الكمية الحالية × سعر الشراء
    inventory_value = calculate_inventory_value()

    # الالتزامات (Liabilities)
    # ديون الموردين ومستحقات النقل
    # السبب المحاسبي: الالتزامات لا تؤثر على الربح إلا عند الدفع
    supplier_debts = calculate_supplier_debts()
    shipping_due = calculate_shipping_due()

    # المصاريف (Expenses)
    # السبب المحاسبي: المصاريف حساب مستقل، لا تؤثر على المخزون أو رأس المال مباشرة
    expenses = calculate_total_expenses()

    # ===============================
    # إسنحاقات مندوب التوصيل
    # حساب مجموع الطلبات المرتبطة بمندوبي التوصيل
    # التي تم التوصيل عليها أو تم تسديدها
    # باستثناء الطلبات الموجودة في كشوفات منفذة
    # ===============================
    from models.shipping_report import ShippingReport
    
    # جلب جميع الطلبات المرتبطة بمندوبي التوصيل
    agent_orders = Invoice.query.filter(
        Invoice.delivery_agent_id.isnot(None),
        Invoice.status.in_(["تم التوصيل", "مسدد", "جاري الشحن"]),
        Invoice.status != "ملغي",
        Invoice.status != "راجع"
    ).all()
    
    # جلب جميع الطلبات الموجودة في كشوفات منفذة
    executed_reports = ShippingReport.query.filter_by(is_executed=True).all()
    executed_order_ids = set()
    
    for report in executed_reports:
        if report.orders_data:
            try:
                orders_data = json.loads(report.orders_data)
                for order_data in orders_data:
                    order_id = order_data.get("id") or order_data.get("order_id")
                    if order_id:
                        executed_order_ids.add(int(order_id))
            except:
                pass
    
    # حساب إجمالي الإسنحاقات (مجموع الطلبات المرتبطة بمندوبي التوصيل)
    # باستثناء الطلبات الموجودة في كشوفات منفذة
    agent_commissions = sum(
        o.total for o in agent_orders 
        if o.id not in executed_order_ids
    ) or 0
    
    # الرصيد النقدي الحالي (الكاش) - هذا إجمالي وليس للفترة
    # السبب المحاسبي: الكاش هو رصيد تراكمي، لا يُحسب لفترة معينة
    # لكن يمكن عرض حركات الكاش للفترة إذا لزم الأمر لاحقاً
    cash_balance = calculate_cash_balance()
    
    # قيمة المخزون (Inventory Value) - هذا إجمالي وليس للفترة
    # السبب المحاسبي: المخزون يُعتبر أصل (Asset) ولا يدخل ضمن رأس المال
    # قيمة المخزون = الكمية الحالية × سعر الشراء
    inventory_value = calculate_inventory_value()

    # الالتزامات (Liabilities) - هذا إجمالي وليس للفترة
    # ديون الموردين ومستحقات النقل
    # السبب المحاسبي: الالتزامات لا تؤثر على الربح إلا عند الدفع
    supplier_debts = calculate_supplier_debts()
    shipping_due = calculate_shipping_due()

    # المصاريف (Expenses) - هذا إجمالي وليس للفترة
    # السبب المحاسبي: المصاريف حساب مستقل، لا تؤثر على المخزون أو رأس المال مباشرة
    expenses = calculate_total_expenses()

    return jsonify({
        "period_type": period_type,
        "period_label": get_period_label(period_type, custom_date_from, custom_date_to),
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "cash_balance": int(cash_balance),  # الرصيد النقدي الحالي
        "sales": int(total_sales),  # إجمالي المبيعات للفترة
        "cash_sales": int(cash_sales),  # المبيعات النقدية للفترة
        "credit_sales": int(credit_sales),  # المبيعات الآجلة للفترة
        "period_profit": int(period_profit),  # الأرباح للفترة
        "delivered_paid_sales": int(delivered_paid_sales),  # المبيعات الواصلة والمسددة للفترة
        "inventory": int(inventory_value),  # قيمة المخزون (إجمالي)
        "debts": int(supplier_debts),  # ديون الموردين (إجمالي)
        "shipping": int(shipping_due),  # مستحقات النقل (إجمالي)
        "expenses": int(expenses),  # المصاريف (إجمالي)
        "expenses_period": int(expenses_period),  # المصاريف للفترة
        "agent_commissions": int(agent_commissions)  # إسنحاقات المندوبين (إجمالي)
    })

# =================================================
# ORDER STATUS COUNTERS
# =================================================
@index_bp.route("/api/index/orders-count")
def index_orders_count():
    # حساب المرتجع والملغي معاً
    returned_count = Invoice.query.filter(
        or_(
            Invoice.status == "راجع",
            Invoice.status == "ملغي",
            Invoice.payment_status == "مرتجع"
        )
    ).count()
    
    return jsonify({
        "all": Invoice.query.count(),
        "ordered": Invoice.query.filter_by(status="تم الطلب").count(),
        "shipping": Invoice.query.filter_by(status="جاري الشحن").count(),
        "delivered": Invoice.query.filter_by(status="تم التوصيل").count(),
        "paid": Invoice.query.filter_by(status="مسدد").count(),
        "returned": returned_count
    })

# =================================================
# TODAY PROFIT
# مبيعات اليوم - كلفة الشراء
# =================================================
@index_bp.route("/api/index/today-profit")
def index_today_profit():
    """
    حساب ربح اليوم
    الصيغة المحاسبية: الربح = المبيعات المسددة - COGS (لليوم فقط)
    ملاحظة: هذا للعرض فقط، لا يشمل المصاريف
    """
    today = date.today()
    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]

    def effective_paid_amount(inv: Invoice) -> int:
        total = int(getattr(inv, "total", 0) or 0)
        payment_status = getattr(inv, "payment_status", None)
        status = getattr(inv, "status", None)
        if payment_status == "مسدد" or status == "مسدد":
            return max(total, 0)
        if payment_status == "جزئي":
            paid_amount = int(getattr(inv, "paid_amount", 0) or 0)
            if paid_amount < 0:
                return 0
            return min(paid_amount, total) if total > 0 else paid_amount
        return 0

    day_invoices = Invoice.query.filter(
        func.date(Invoice.created_at) == today,
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
    ).all()

    # المبيعات المسددة فعلياً (تشمل الجزئي)
    sales = sum(effective_paid_amount(inv) for inv in day_invoices)

    # COGS متناسب مع التحصيل (تقريب)
    ratios = {}
    for inv in day_invoices:
        total = int(inv.total or 0)
        paid = effective_paid_amount(inv)
        if total > 0 and paid > 0:
            ratios[int(inv.id)] = min(max(paid / total, 0.0), 1.0)

    cost = 0
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
            cost += int(round(float(cogs_sum) * ratios.get(int(invoice_id), 0.0)))

    # الربح = المبيعات - COGS
    # ملاحظة: هذا الربح الإجمالي (Gross Profit) بدون المصاريف
    return jsonify({
        "profit": int(int(sales) - int(cost))
    })

# =================================================
# SEARCH ORDERS (BY RECEIPT NUMBER OR PHONE)
# =================================================
@index_bp.route("/api/index/search")
def index_search():
    q = request.args.get("q", "").strip()

    if not q:
        return jsonify([])

    # تحويل الأرقام العربية إلى إنجليزية للتحقق
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    english_digits = '0123456789'
    q_normalized = q
    for i, arabic_digit in enumerate(arabic_digits):
        q_normalized = q_normalized.replace(arabic_digit, english_digits[i])
    
    # التحقق إذا كان الإدخال رقم فقط (مطابقة كاملة لرقم الفاتورة)
    # يجب أن يكون الرقم فقط بدون أي أحرف أو مسافات
    if q_normalized.isdigit():
        # إذا كان رقم فقط (مثل "1")، ابحث عن مطابقة كاملة لرقم الفاتورة فقط
        # هذا يضمن أن "1" يبحث فقط عن الطلب رقم 1 وليس 10 أو 11
        invoice_id = int(q_normalized)
        orders = Invoice.query.join(Customer).filter(
            Invoice.id == invoice_id
        ).order_by(
            Invoice.id.desc()
        ).limit(100).all()
    else:
        # إذا لم يكن رقم فقط، ابحث في أرقام الهاتف فقط
        # استخرج الأرقام من النص إذا كان هناك أرقام
        import re
        # البحث عن أرقام إنجليزية أو عربية
        numbers = re.findall(r'[\d٠١٢٣٤٥٦٧٨٩]+', q)
        
        if numbers:
            # إذا كان هناك أرقام في النص، ابحث في أرقام الهاتف التي تحتوي على هذه الأرقام
            phone_filters = []
            for num in numbers:
                # تحويل الأرقام العربية إلى إنجليزية للبحث
                num_normalized = num
                for i, arabic_digit in enumerate(arabic_digits):
                    num_normalized = num_normalized.replace(arabic_digit, english_digits[i])
                phone_filters.append(Customer.phone.like(f"%{num_normalized}%"))
                phone_filters.append(Customer.phone2.like(f"%{num_normalized}%"))
            
            orders = Invoice.query.join(Customer).filter(
                or_(*phone_filters)
            ).order_by(
                Invoice.id.desc()
            ).limit(100).all()
        else:
            # إذا لم يكن هناك أرقام (مثل "طلب")، لا تبحث في شيء
            # البحث يبقى في صفحة البحث ولا ينتقل لبحث آخر
            orders = []

    return jsonify([
        {
            "id": o.id,
            "phone": o.customer.phone if o.customer else "",
            "customer": o.customer.name if o.customer else "",
            "total": o.total,
            "status": o.status
        }
        for o in orders
    ])

# =================================================
# EXECUTE ORDER ACTION
# =================================================
@index_bp.route("/api/index/execute", methods=["POST"])
def index_execute():
    data = request.get_json() or {}

    order_id = data.get("id")
    action = data.get("action")

    invoice = Invoice.query.get(order_id)
    if not invoice:
        return jsonify({"error": "ORDER_NOT_FOUND"}), 404

    if action == "ordered":
        invoice.status = "تم الطلب"
        invoice.shipping_company_id = None

    elif action == "shipping":
        invoice.status = "جاري الشحن"

    elif action == "delivered":
        invoice.status = "تم التوصيل"

    elif action == "paid":
        invoice.status = "مسدد"
        invoice.shipping_status = "تم التسديد"

    elif action == "returned":
        invoice.status = "راجع"

    else:
        return jsonify({"error": "INVALID_ACTION"}), 400

    db.session.commit()
    return jsonify({"success": True})

# =================================================
# BULK EXECUTE ORDERS
# =================================================
@index_bp.route("/api/index/execute-bulk", methods=["POST"])
def index_execute_bulk():
    data = request.get_json() or {}
    orders = data.get("orders", [])
    
    if not orders:
        return jsonify({"success": False, "error": "لا توجد طلبات محددة"}), 400
    
    executed = 0
    errors = []
    
    for order_data in orders:
        order_id = order_data.get("id")
        action = order_data.get("action")
        
        if not order_id or not action:
            errors.append(f"طلب {order_id}: بيانات غير كاملة")
            continue
        
        invoice = Invoice.query.get(order_id)
        if not invoice:
            errors.append(f"طلب {order_id}: غير موجود")
            continue
        
        try:
            if action == "ordered":
                invoice.status = "تم الطلب"
                invoice.shipping_company_id = None
            elif action == "shipping":
                invoice.status = "جاري الشحن"
            elif action == "delivered":
                invoice.status = "تم التوصيل"
            elif action == "paid":
                # ==========================
                # تصحيح محاسبي: الطلب الواصل يتم تسديده بشكل صحيح
                # ==========================
                invoice.status = "مسدد"
                invoice.payment_status = "مسدد"  # تأكيد حالة الدفع
                invoice.shipping_status = "تم التسديد"
            elif action == "returned":
                invoice.status = "راجع"
            else:
                errors.append(f"طلب {order_id}: إجراء غير صحيح")
                continue
            
            executed += 1
        except Exception as e:
            errors.append(f"طلب {order_id}: {str(e)}")
            continue
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "executed": executed,
        "total": len(orders),
        "errors": errors if errors else None
    })

# =================================================
# CHARTS DATA (LAST 7 DAYS)
# =================================================
@index_bp.route("/api/index/charts")
def index_charts():
    labels = []
    sales = []
    profit = []
    
    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]
    
    def effective_paid_amount(inv: Invoice) -> int:
        total = int(getattr(inv, "total", 0) or 0)
        payment_status = getattr(inv, "payment_status", None)
        status = getattr(inv, "status", None)
        if payment_status == "مسدد" or status == "مسدد":
            return max(total, 0)
        if payment_status == "جزئي":
            paid_amount = int(getattr(inv, "paid_amount", 0) or 0)
            if paid_amount < 0:
                return 0
            return min(paid_amount, total) if total > 0 else paid_amount
        return 0

    for i in range(6, -1, -1):
        d = date.today() - timedelta(days=i)
        labels.append(d.strftime("%m/%d"))

        day_invoices = Invoice.query.filter(
            func.date(Invoice.created_at) == d,
            Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
            Invoice.payment_status != "مرتجع",
        ).all()
        
        # المبيعات المسددة فعلياً (تشمل الجزئي)
        day_sales = sum(effective_paid_amount(inv) for inv in day_invoices)
        
        # COGS متناسب مع التحصيل (تقريب)
        ratios = {}
        for inv in day_invoices:
            total = int(inv.total or 0)
            paid = effective_paid_amount(inv)
            if total > 0 and paid > 0:
                ratios[int(inv.id)] = min(max(paid / total, 0.0), 1.0)
        
        day_cost = 0
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
                day_cost += int(round(float(cogs_sum) * ratios.get(int(invoice_id), 0.0)))

        sales.append(int(day_sales))
        # الربح = المبيعات - COGS (ربح إجمالي بدون المصاريف)
        profit.append(int(int(day_sales) - int(day_cost)))

    status_data = {
        "ordered": Invoice.query.filter_by(status="تم الطلب").count(),
        "shipping": Invoice.query.filter_by(status="جاري الشحن").count(),
        "delivered": Invoice.query.filter_by(status="تم التوصيل").count(),
        "paid": Invoice.query.filter_by(status="مسدد").count(),
        "returned": Invoice.query.filter(
            or_(
                Invoice.status == "راجع",
                Invoice.status == "ملغي",
                Invoice.payment_status == "مرتجع"
            )
        ).count()
    }

    return jsonify({
        "labels": labels,
        "sales": sales,
        "profit": profit,
        "status": status_data
    })

# =================================================
# ALERTS (Enhanced)
# =================================================
@index_bp.route("/api/index/alerts")
def index_alerts():
    """تنبيهات لوحة التحكم — يُرجع دائماً JSON لتفادي خطأ التحليل في الواجهة."""
    alerts = []
    try:
        # تنبيهات المخزون
        low_stock = Product.query.filter(Product.quantity <= 2).count()
        if low_stock:
            alerts.append({
                "type": "warning",
                "icon": "⚠️",
                "message": f"يوجد {low_stock} منتج مخزونها قليل",
                "action": "/inventory"
            })

        # تنبيهات الربح والمصاريف
        from utils.accounting_calculations import (
            calculate_paid_sales,
            calculate_paid_cogs,
            calculate_total_expenses,
            calculate_operational_profit
        )
        paid_sales = calculate_paid_sales()
        total_cost = calculate_paid_cogs()
        total_expenses = calculate_total_expenses()
        gross_profit = paid_sales - total_cost
        net_profit = calculate_operational_profit()
        expense_ratio = (total_expenses / gross_profit * 100) if gross_profit > 0 else 0
        profit_ratio = (net_profit / paid_sales * 100) if paid_sales > 0 else 0

        if net_profit < 0:
            alerts.append({
                "type": "danger",
                "icon": "🚨",
                "message": f"خسارة! المصاريف ({total_expenses:,} د.ع) أعلى من الربح ({gross_profit:,} د.ع)",
                "action": "/accounts"
            })
        elif expense_ratio >= 80 and gross_profit > 0:
            alerts.append({
                "type": "warning",
                "icon": "⚠️",
                "message": f"المصاريف ({total_expenses:,} د.ع) تمثل {expense_ratio:.1f}% من الربح ({gross_profit:,} د.ع) - قريبة جداً من الخسارة!",
                "action": "/accounts"
            })
        elif profit_ratio < 20 and paid_sales > 0:
            alerts.append({
                "type": "info",
                "icon": "💡",
                "message": f"الربح الصافي ({net_profit:,} د.ع) يمثل {profit_ratio:.1f}% فقط من المبيعات ({paid_sales:,} د.ع) - ربح قليل",
                "action": "/accounts"
            })

        pending_orders = Invoice.query.filter(Invoice.status == "تم الطلب").count()
        if pending_orders > 10:
            alerts.append({
                "type": "warning",
                "icon": "📦",
                "message": f"يوجد {pending_orders} طلب معلق",
                "action": "/orders"
            })

        shipping_due = calculate_shipping_due()
        if shipping_due > 100000:
            alerts.append({
                "type": "info",
                "icon": "🚚",
                "message": f"مستحقات النقل عالية: {shipping_due} د.ع",
                "action": "/shipping"
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
    return jsonify(alerts)

# =================================================
# CHECK FOR NEW ORDERS (Real-time notifications)
# =================================================
@index_bp.route("/api/index/new-orders")
def check_new_orders():
    # الحصول على آخر طلب تم إنشاؤه
    last_order = Invoice.query.order_by(
        Invoice.created_at.desc()
    ).first()
    
    if not last_order:
        return jsonify({
            "new_orders": [],
            "last_order_id": None
        })
    
    # الحصول على الطلبات الجديدة (آخر 5 دقائق)
    from datetime import datetime, timedelta
    five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
    
    new_orders = Invoice.query.filter(
        Invoice.created_at >= five_minutes_ago
    ).order_by(Invoice.created_at.desc()).limit(10).all()
    
    return jsonify({
        "new_orders": [
            {
                "id": o.id,
                "customer": o.customer_name,
                "total": o.total,
                "status": o.status,
                "time": o.created_at.strftime("%H:%M")
            }
            for o in new_orders
        ],
        "last_order_id": last_order.id,
        "timestamp": datetime.utcnow().isoformat()
    })

# =================================================
# AGENT DUES DETAILS
# =================================================
@index_bp.route("/api/index/agent-dues-details")
def agent_dues_details():
    # الحصول على جميع الطلبات المرتبطة بمندوبي التوصيل
    # التي تم التوصيل عليها أو تم تسديدها أو جاري الشحن
    # باستثناء الطلبات الموجودة في كشوفات منفذة (نفس منطق index_reports)
    from models.shipping_report import ShippingReport
    
    # جلب جميع الطلبات المرتبطة بمندوبي التوصيل
    orders = Invoice.query.filter(
        Invoice.delivery_agent_id.isnot(None),
        Invoice.status.in_(["تم التوصيل", "مسدد", "جاري الشحن"])
    ).order_by(Invoice.created_at.desc()).limit(100).all()
    
    # جلب جميع الطلبات الموجودة في كشوفات منفذة
    executed_reports = ShippingReport.query.filter_by(is_executed=True).all()
    executed_order_ids = set()
    
    for report in executed_reports:
        if report.orders_data:
            try:
                orders_data = json.loads(report.orders_data)
                for order_data in orders_data:
                    order_id = order_data.get("id") or order_data.get("order_id")
                    if order_id:
                        executed_order_ids.add(int(order_id))
            except:
                pass
    
    # تصفية الطلبات لاستبعاد الطلبات الموجودة في كشوفات منفذة
    orders = [o for o in orders if o.id not in executed_order_ids]
    
    total = sum(o.total for o in orders)
    count = len(orders)
    average = total / count if count > 0 else 0
    
    return jsonify({
        "total": int(total),
        "count": count,
        "average": int(average),
        "orders": [
            {
                "id": o.id,
                "customer": o.customer.name if o.customer else o.customer_name or "—",
                "agent": o.delivery_agent.name if o.delivery_agent else "—",
                "total": int(o.total),
                "date": o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "—",
                "status": o.status
            }
            for o in orders
        ]
    })

# =================================================
# DELIVERED PAID SALES DETAILS
# =================================================
@index_bp.route("/api/index/delivered-paid-details")
def delivered_paid_details():
    # الحصول على جميع الطلبات الواصلة والمسددة
    # الحالات الممكنة:
    # 1. status == "تم التوصيل" AND payment_status == "مسدد"
    # 2. status == "مسدد" (يعني واصل ومسدد معاً)
    from sqlalchemy import and_
    orders = Invoice.query.filter(
        or_(
            # الحالة الأولى: واصل ومسدد بشكل منفصل
            and_(
                Invoice.status == "تم التوصيل",
                Invoice.payment_status == "مسدد"
            ),
            # الحالة الثانية: status = "مسدد" (يعني واصل ومسدد معاً)
            Invoice.status == "مسدد"
        )
    ).order_by(Invoice.created_at.desc()).limit(100).all()
    
    total = sum(o.total for o in orders)
    count = len(orders)
    average = total / count if count > 0 else 0
    
    return jsonify({
        "total": int(total),
        "count": count,
        "average": int(average),
        "orders": [
            {
                "id": o.id,
                "customer": o.customer.name if o.customer else o.customer_name or "—",
                "total": int(o.total),
                "date": o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "—",
                "status": "واصل ومسدد"
            }
            for o in orders
        ]
    })

# =================================================
# ADD EXPENSE (Quick Add)
# =================================================
@index_bp.route("/api/index/add-expense", methods=["POST"])
def add_expense():
    data = request.get_json() or {}
    
    title = data.get("title", "").strip()
    category = data.get("category", "").strip()
    amount = data.get("amount")
    note = data.get("note", "").strip()
    expense_date = data.get("expense_date")
    
    if not title:
        return jsonify({"success": False, "error": "الرجاء إدخال عنوان المصروف"}), 400
    
    if not category:
        return jsonify({"success": False, "error": "الرجاء اختيار فئة المصروف"}), 400
    
    try:
        amount = int(float(amount))
        if amount <= 0:
            return jsonify({"success": False, "error": "المبلغ يجب أن يكون أكبر من صفر"}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "المبلغ غير صحيح"}), 400
    
    try:
        if expense_date:
            expense_date_obj = datetime.strptime(expense_date, "%Y-%m-%d").date()
        else:
            expense_date_obj = date.today()
    except ValueError:
        expense_date_obj = date.today()
    
    try:
        # إنشاء المصروف
        expense = Expense(
            title=title,
            category=category,
            amount=amount,
            note=note,
            expense_date=expense_date_obj
        )
        db.session.add(expense)
        
        # خصم المبلغ من رأس المال تلقائياً
        withdraw_tx = AccountTransaction(
            type="withdraw",
            amount=amount,
            note=f"مصروف: {title} ({category})" + (f" - {note}" if note else "")
        )
        db.session.add(withdraw_tx)
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "تم إضافة المصروف بنجاح"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"حدث خطأ: {str(e)}"}), 500
