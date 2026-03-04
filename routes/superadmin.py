import os
import shutil
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, g, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db
from extensions_tenant import init_tenant_db, get_tenant_engine, clear_tenant_engine
from models.core.super_admin import SuperAdmin
from models.core.payment_request import PaymentRequest
from models.core.tenant import Tenant
from models.core.subscription_plan import SubscriptionPlan

superadmin_bp = Blueprint("superadmin", __name__, url_prefix="/superadmin")

def is_superadmin():
    return session.get("is_superadmin") is True

@superadmin_bp.before_request
def require_superadmin():
    # Force Core DB usage for all superadmin routes
    g.tenant = None
    
    open_routes = ["/superadmin/login"]
    if request.path not in open_routes and not is_superadmin():
        return redirect(url_for("superadmin.login"))

@superadmin_bp.context_processor
def inject_superadmin_data():
    if is_superadmin():
        pending_count = PaymentRequest.query.filter_by(status="pending").count()
        return dict(pending_count=pending_count)
    return dict(pending_count=0)

@superadmin_bp.route("/login", methods=["GET", "POST"])
def login():
    if is_superadmin():
        return redirect(url_for("superadmin.dashboard"))
        
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        admin = SuperAdmin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            session["is_superadmin"] = True
            session["superadmin_id"] = admin.id
            return redirect(url_for("superadmin.dashboard"))
            
        flash("بيانات الدخول غير صحيحة")
        
    return render_template("superadmin_login.html")

@superadmin_bp.route("/logout")
def logout():
    session.pop("is_superadmin", None)
    session.pop("superadmin_id", None)
    return redirect(url_for("superadmin.login"))

@superadmin_bp.route("/")
def dashboard():
    pending_count = PaymentRequest.query.filter_by(status="pending").count()
    active_tenants = Tenant.query.filter_by(is_active=True).count()
    total_revenue_query = db.session.query(db.func.sum(PaymentRequest.amount)).filter_by(status="approved").scalar()
    total_revenue = total_revenue_query if total_revenue_query else 0
    rejected_count = PaymentRequest.query.filter_by(status="rejected").count()
    
    recent_requests = PaymentRequest.query.order_by(PaymentRequest.created_at.desc()).limit(5).all()
    
    return render_template("admin_dashboard.html", 
        pending_count=pending_count, 
        active_tenants=active_tenants, 
        total_revenue=total_revenue,
        rejected_count=rejected_count,
        recent_requests=recent_requests
    )

@superadmin_bp.route("/requests")
def requests_list():
    requests = PaymentRequest.query.order_by(PaymentRequest.created_at.desc()).all()
    return render_template("payment_requests.html", requests=requests)

@superadmin_bp.route("/requests/<int:req_id>/approve", methods=["POST"])
def approve_request(req_id):
    payment_req = PaymentRequest.query.get_or_404(req_id)
    if payment_req.status != "pending":
        flash("هذا الطلب تمت معالجته مسبقاً")
        return redirect(url_for("superadmin.requests_list"))
        
    # Check if tenant slug already exists
    existing_tenant = Tenant.query.filter_by(slug=payment_req.tenant_name).first()
    if existing_tenant:
        flash("يوجد شركة مسجلة بهذا المعرف مسبقاً. يرجى رفض الطلب أو تعديل اسم الشركة.")
        return redirect(url_for("superadmin.requests_list"))
        
    # 1. Update Request
    payment_req.status = "approved"
    
    # 2. Create Tenant in Core DB
    db_path = f"tenants/{payment_req.tenant_name}.db"
    new_tenant = Tenant(
        name=payment_req.tenant_name.upper(), 
        slug=payment_req.tenant_name,
        db_path=db_path,
        is_active=True,
        subscription_end_date=datetime.utcnow() + timedelta(days=30)
    )
    db.session.add(new_tenant)
    db.session.commit()
    
    # 3. Create Tenant Database & Run init_tenant_db
    try:
        init_tenant_db(payment_req.tenant_name)
        
        # 4. Create an Admin Employee in the NEW Tenant DB
        engine = get_tenant_engine(payment_req.tenant_name)
        from sqlalchemy.orm import sessionmaker
        SessionLocal = sessionmaker(bind=engine)
        tenant_session = SessionLocal()
        
        from models.employee import Employee
        default_password = "password123" # A default password for them to login with
        
        admin_employee = Employee(
            name=payment_req.owner_name,
            username="admin", 
            password=generate_password_hash(default_password),
            role="admin",
            salary=0,
            is_active=True
        )
        tenant_session.add(admin_employee)
        tenant_session.commit()
        tenant_session.close()
        
        flash(f"تم تفعيل الشركة بنجاح مع اسم مستخدم admin وكلمة مرور: {default_password}")
        
    except Exception as e:
        db.session.rollback()
        flash(f"حدث خطأ أثناء تهيئة قاعدة بيانات الشركة: {str(e)}")
        
    return redirect(url_for("superadmin.requests_list"))

@superadmin_bp.route("/requests/<int:req_id>/reject", methods=["POST"])
def reject_request(req_id):
    payment_req = PaymentRequest.query.get_or_404(req_id)
    payment_req.status = "rejected"
    db.session.commit()
    flash("تم رفض الطلب بنجاح.")
    return redirect(url_for("superadmin.requests_list"))

@superadmin_bp.route("/tenants")
def tenants_list():
    tenants = Tenant.query.all()
    return render_template("tenant_list.html", tenants=tenants)


@superadmin_bp.route("/tenants/details/<slug>")
def tenant_details(slug):
    from flask import jsonify
    try:
        slug_clean = (slug or "").strip().lower()
        tenant = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
        if not tenant:
            return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404
        g.tenant = tenant.slug
        from models.employee import Employee
        from models.tenant import Tenant as TenantModel
        admin_emp = Employee.query.filter(Employee.role == "admin").first()
        if not admin_emp:
            admin_emp = Employee.query.filter_by(username="admin").first()
        tenant_row = TenantModel.query.first()
        g.tenant = None
        admin_username = admin_emp.username if admin_emp else "—"
        admin_name = admin_emp.name if admin_emp else "—"
        plan_key = tenant_row.plan_key if tenant_row else "basic"
        plan_name = tenant_row.plan_name if tenant_row else "الخطة الأساسية"
        return jsonify({
            "ok": True,
            "name": tenant.name,
            "slug": tenant.slug,
            "db_path": tenant.db_path,
            "is_active": tenant.is_active,
            "created_at": tenant.created_at.strftime("%Y-%m-%d %H:%M") if tenant.created_at else "—",
            "subscription_end_date": tenant.subscription_end_date.strftime("%Y-%m-%d") if tenant.subscription_end_date else "—",
            "admin_username": admin_username,
            "admin_name": admin_name,
            "admin_password": None,
            "plan_key": plan_key,
            "plan_name": plan_name,
        })
    except Exception as e:
        g.tenant = None
        current_app.logger.exception("tenant_details")
        return jsonify({"ok": False, "error": str(e)}), 500


@superadmin_bp.route("/tenants/reset-password/<slug>", methods=["POST"])
def tenant_reset_password(slug):
    from flask import jsonify
    import secrets
    from sqlalchemy.orm import sessionmaker
    slug_clean = (slug or "").strip().lower()
    tenant = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
    if not tenant:
        return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404
    try:
        data = request.get_json() or {}
        new_password = data.get("password")
        if not new_password:
            return jsonify({"ok": False, "error": "كلمة المرور مطلوبة"}), 400

        engine = get_tenant_engine(tenant.slug)
        SessionLocal = sessionmaker(bind=engine)
        tenant_session = SessionLocal()
        from models.employee import Employee
        admin_emp = tenant_session.query(Employee).filter(Employee.role == "admin").first()
        if not admin_emp:
            admin_emp = tenant_session.query(Employee).filter_by(username="admin").first()
        if not admin_emp:
            tenant_session.close()
            return jsonify({"ok": False, "error": "لم يتم العثور على حساب المدير"}), 404
            
        admin_emp.password = generate_password_hash(new_password)
        tenant_session.commit()
        tenant_session.close()
        return jsonify({"ok": True, "message": "تم تغيير كلمة المرور بنجاح"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@superadmin_bp.route("/tenants/reset-db/<slug>", methods=["POST"])
def tenant_reset_db(slug):
    from flask import jsonify
    from sqlalchemy.orm import sessionmaker
    slug_clean = (slug or "").strip().lower()
    tenant = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
    if not tenant:
        return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404
        
    try:
        # 1. Clear engine cache to free file locks
        clear_tenant_engine(tenant.slug)
        
        # 2. Delete physical .db file
        if os.path.exists(tenant.db_path):
            os.remove(tenant.db_path)
            
        # 3. Re-initialize database schema and defaults
        init_tenant_db(tenant.slug)
        
        # 4. Create default admin account
        engine = get_tenant_engine(tenant.slug)
        SessionLocal = sessionmaker(bind=engine)
        tenant_session = SessionLocal()
        
        from models.employee import Employee
        from models.tenant import Tenant as TenantModel
        from utils.plan_limits import get_plan
        
        # Fresh start with basic plan
        plan_key = "basic"
        plan = get_plan(plan_key)
        
        tenant_row = TenantModel(
            name=tenant.name,
            plan_key=plan_key,
            plan_name=plan["name"],
            monthly_price=plan.get("price_monthly", 0),
            is_active=True,
            subscription_end=tenant.subscription_end_date,
        )
        tenant_session.add(tenant_row)
        tenant_session.flush()
        
        admin_employee = Employee(
            name=tenant.name,
            username="admin",
            password=generate_password_hash("password123"),
            role="admin",
            salary=0,
            is_active=True,
            tenant_id=tenant_row.id
        )
        tenant_session.add(admin_employee)
        tenant_session.commit()
        tenant_session.close()
        
        return jsonify({"ok": True, "message": "تمت إعادة تعيين قاعدة البيانات بنجاح. كلمة مرور الأدمن الافتراضية: password123"})
    except Exception as e:
        current_app.logger.exception(f"Error resetting database for {slug}")
        return jsonify({"ok": False, "error": str(e)}), 500



@superadmin_bp.route("/tenants/create", methods=["GET", "POST"])
def tenants_create():
    from models.core.global_setting import GlobalSetting
    
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        slug = (request.form.get("slug") or "").strip().lower()
        owner_name = (request.form.get("owner_name") or "").strip()
        trial_days_val = request.form.get("trial_days") or ""
        
        if not name or not slug:
            flash("اسم الشركة والمعرف (Slug) مطلوبان.", "error")
            return redirect(url_for("superadmin.tenants_create"))
        
        # Slug: حروف إنجليزية وأرقام وشرطة فقط
        import re
        slug = re.sub(r"[^a-z0-9\-]", "", slug)
        if not slug:
            flash("المعرف يجب أن يحتوي على حروف إنجليزية أو أرقام أو شرطة فقط.", "error")
            return redirect(url_for("superadmin.tenants_create"))
        
        existing = Tenant.query.filter_by(slug=slug).first()
        if existing:
            flash(f"معرف الشركة «{slug}» مستخدم مسبقاً. اختر معرفاً آخر.", "error")
            return redirect(url_for("superadmin.tenants_create"))
        
        try:
            trial_days = int(trial_days_val) if trial_days_val else int(GlobalSetting.get_setting("TRIAL_DAYS", "14"))
        except ValueError:
            trial_days = 14
        
        trial_days = max(1, min(365, trial_days))
        db_path = f"tenants/{slug}.db"
        
        new_tenant = Tenant(
            name=name.upper(),
            slug=slug,
            db_path=db_path,
            is_active=True,
            subscription_end_date=datetime.utcnow() + timedelta(days=trial_days),
        )
        db.session.add(new_tenant)
        db.session.commit()
        
        try:
            init_tenant_db(slug)
            engine = get_tenant_engine(slug)
            from sqlalchemy.orm import sessionmaker
            SessionLocal = sessionmaker(bind=engine)
            tenant_session = SessionLocal()
            from models.employee import Employee
            from models.tenant import Tenant as TenantModel
            from utils.plan_limits import get_plan
            plan = get_plan("basic")
            tenant_row = TenantModel(
                name=name.upper(),
                plan_key="basic",
                plan_name=plan["name"],
                monthly_price=plan.get("price_monthly", 0),
                is_active=True,
                subscription_end=new_tenant.subscription_end_date,
            )
            tenant_session.add(tenant_row)
            tenant_session.flush()
            default_password = request.form.get("admin_password", "").strip() or "password123"
            admin_display_name = owner_name or name
            admin_employee = Employee(
                name=admin_display_name,
                username="admin",
                password=generate_password_hash(default_password),
                role="admin",
                salary=0,
                is_active=True,
                tenant_id=tenant_row.id,
            )
            tenant_session.add(admin_employee)
            tenant_session.commit()
            tenant_session.close()
            
            flash(
                f"تم إنشاء الشركة «{name}» بنجاح. الدخول: معرف الشركة = {slug}، المستخدم = admin، كلمة المرور = {default_password}",
                "success",
            )
        except Exception as e:
            db.session.rollback()
            flash(f"حدث خطأ أثناء تهيئة قاعدة بيانات الشركة: {str(e)}", "error")
            return redirect(url_for("superadmin.tenants_create"))
        
        return redirect(url_for("superadmin.tenants_list"))
    
    trial_days_default = "14"
    try:
        from models.core.global_setting import GlobalSetting
        trial_days_default = GlobalSetting.get_setting("TRIAL_DAYS", "14")
    except Exception:
        pass
    
    return render_template("superadmin_create_tenant.html", trial_days_default=trial_days_default)


@superadmin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    from models.core.global_setting import GlobalSetting
    
    if request.method == "POST":
        # Save settings
        app_name = request.form.get("APP_NAME", "Finora System")
        trial_days = request.form.get("TRIAL_DAYS", "14")
        zaincash_secret = request.form.get("ZAINCASH_SECRET", "")
        zaincash_merchant = request.form.get("ZAINCASH_MERCHANT", "")
        
        GlobalSetting.set_setting("APP_NAME", app_name, "اسم النظام العام للمنصة")
        GlobalSetting.set_setting("TRIAL_DAYS", trial_days, "عدد أيام التجربة المجانية للشركات")
        GlobalSetting.set_setting("ZAINCASH_SECRET", zaincash_secret, "كلمة سر حساب مركز زين كاش")
        GlobalSetting.set_setting("ZAINCASH_MERCHANT", zaincash_merchant, "رقم تعريف تاجر زين كاش")
        
        # إعدادات الإشعارات (SMS/Email)
        GlobalSetting.set_setting("NOTIFY_EMAIL_ENABLED", "1" if request.form.get("NOTIFY_EMAIL_ENABLED") else "0", "تفعيل إشعارات البريد")
        GlobalSetting.set_setting("SMTP_HOST", request.form.get("SMTP_HOST", ""), "خادم SMTP")
        GlobalSetting.set_setting("SMTP_PORT", request.form.get("SMTP_PORT", "587"), "منفذ SMTP")
        GlobalSetting.set_setting("SMTP_USER", request.form.get("SMTP_USER", ""), "مستخدم SMTP")
        GlobalSetting.set_setting("SMTP_PASSWORD", request.form.get("SMTP_PASSWORD", ""), "كلمة مرور SMTP")
        GlobalSetting.set_setting("SMTP_FROM", request.form.get("SMTP_FROM", ""), "عنوان المرسل الافتراضي")
        GlobalSetting.set_setting("NOTIFY_SMS_ENABLED", "1" if request.form.get("NOTIFY_SMS_ENABLED") else "0", "تفعيل إشعارات SMS")
        GlobalSetting.set_setting("SMS_API_URL", request.form.get("SMS_API_URL", ""), "رابط أو مفتاح API للرسائل النصية")
        GlobalSetting.set_setting("SMS_SENDER", request.form.get("SMS_SENDER", ""), "اسم أو رقم مرسل SMS")
        
        flash("تم حفظ الإعدادات بنجاح!", "success")
        return redirect(url_for("superadmin.settings"))
        
    # GET Request - Load Settings
    settings_data = {
        "app_name": GlobalSetting.get_setting("APP_NAME", "Finora System"),
        "trial_days": GlobalSetting.get_setting("TRIAL_DAYS", "14"),
        "zaincash_secret": GlobalSetting.get_setting("ZAINCASH_SECRET", ""),
        "zaincash_merchant": GlobalSetting.get_setting("ZAINCASH_MERCHANT", ""),
        "notify_email_enabled": GlobalSetting.get_setting("NOTIFY_EMAIL_ENABLED", "0") == "1",
        "smtp_host": GlobalSetting.get_setting("SMTP_HOST", ""),
        "smtp_port": GlobalSetting.get_setting("SMTP_PORT", "587"),
        "smtp_user": GlobalSetting.get_setting("SMTP_USER", ""),
        "smtp_password": GlobalSetting.get_setting("SMTP_PASSWORD", ""),
        "smtp_from": GlobalSetting.get_setting("SMTP_FROM", ""),
        "notify_sms_enabled": GlobalSetting.get_setting("NOTIFY_SMS_ENABLED", "0") == "1",
        "sms_api_url": GlobalSetting.get_setting("SMS_API_URL", ""),
        "sms_sender": GlobalSetting.get_setting("SMS_SENDER", ""),
    }
    
    return render_template("superadmin_settings.html", settings=settings_data)


# دليل الصفحات — روابط لكل القوالب والصفحات في النظام
PAGES_GUIDE = [
    {
        "title": "لوحة الإدارة العليا (Super Admin)",
        "icon": "fa-user-shield",
        "links": [
            ("/superadmin/", "لوحة القيادة (Dashboard)", "admin_dashboard.html"),
            ("/superadmin/requests", "طلبات ZainCash", "payment_requests.html"),
            ("/superadmin/tenants", "الشركات المسجلة", "tenant_list.html"),
            ("/superadmin/tenants/create", "إنشاء شركة جديدة", "superadmin_create_tenant.html"),
            ("/superadmin/settings", "إعدادات النظام", "superadmin_settings.html"),
            ("/superadmin/links", "دليل الصفحات — كل الروابط", "superadmin_links.html"),
            ("/superadmin/login", "تسجيل دخول المدير", "superadmin_login.html"),
        ],
    },
    {
        "title": "الصفحات العامة والهبوط",
        "icon": "fa-globe",
        "links": [
            ("/", "الصفحة الرئيسية (بدون شركة)", "index.html / dashbord.html"),
            ("/landing", "صفحة الهبوط (Landing)", "landing.html"),
            ("/privacy", "سياسة الخصوصية", "privacy.html"),
            ("/terms", "شروط الخدمة", "terms.html"),
            ("/login", "تسجيل دخول الشركة", "login.html"),
            ("/signup", "إنشاء حساب شركة", "signup.html"),
            ("/pricing", "الأسعار", "pricing.html"),
            ("/payment", "صفحة الدفع", "payment.html"),
            ("/upgrade", "ترقية مطلوبة", "upgrade_required.html"),
            ("/payment/success", "دفع ناجح", "payment_success.html"),
            ("/payments/checkout", "ZainCash Checkout", "zaincash_checkout.html"),
            ("/payment_failed", "دفع فاشل", "payment_failed.html"),
            ("/mock_gateway", "بوابة تجريبية", "mock_gateway.html"),
        ],
    },
    {
        "title": "نقطة البيع والطلبات",
        "icon": "fa-cash-register",
        "links": [
            ("/pos", "نقطة البيع (POS)", "pos.html"),
            ("/pos/login", "دخول POS", "pos_login.html"),
            ("/orders/", "الطلبات — الكل", "orders.html"),
            ("/orders/ordered", "الطلبات — تم الطلب", "orders.html"),
            ("/orders/shipping", "الطلبات — قيد التوصيل", "orders.html"),
            ("/orders/cancelled", "الطلبات — ملغاة", "orders.html"),
            ("/orders/reports", "تقارير الطلبات", "orders_reports.html"),
            ("/orders/print-batch", "طباعة دفعة", "print_batch.html"),
            ("/orders/print-report-page", "طباعة تقرير", "print_report.html"),
            ("/orders/print-items-report-page", "تقرير الأصناف", "print_items_report.html"),
            ("/orders/invoice/<id>", "فاتورة (معرف الطلب)", "invoice.html"),
        ],
    },
    {
        "title": "المخزون والمشتريات",
        "icon": "fa-boxes",
        "links": [
            ("/inventory", "المخزون", "inventory.html"),
            ("/inventory/audit", "جرد المخزون", "inventory_audit.html"),
            ("/inventory/ledger", "دفتر المخزون", "inventory_ledger.html"),
            ("/inventory/report/<id>", "تقرير صنف", "inventory_report.html"),
            ("/purchases", "المشتريات", "purchases.html"),
            ("/suppliers", "الموردون", "suppliers.html"),
            ("/suppliers/<id>", "تفاصيل مورد", "supplier_details.html"),
        ],
    },
    {
        "title": "الحسابات والنقدية والمصروفات",
        "icon": "fa-wallet",
        "links": [
            ("/accounts", "الحسابات", "accounts.html"),
            ("/cash", "النقدية", "cash.html"),
            ("/expenses", "المصروفات", "expenses.html"),
        ],
    },
    {
        "title": "الزبائن والموظفين والصلاحيات",
        "icon": "fa-users",
        "links": [
            ("/customers", "الزبائن", "customers.html"),
            ("/employees", "الموظفون", "employees.html"),
            ("/employees/pages/<id>", "صفحات موظف", "pages.html"),
            ("/admin/permissions/roles", "أدوار الصلاحيات", "admin/permissions/roles.html"),
            ("/admin/permissions/employee/<id>/roles", "صلاحيات موظف", "admin/permissions/employee_roles.html"),
        ],
    },
    {
        "title": "الشحن والتوصيل والمناديب",
        "icon": "fa-truck",
        "links": [
            ("/shipping", "شركات الشحن", "shipping.html"),
            ("/delivery/archive", "أرشيف التوصيل", "delivery_archive.html"),
            ("/delivery/reports", "تقارير التوصيل", "shipping_reports_archive.html"),
            ("/delivery/report/<id>", "تقرير توصيل", "shipping_report_view.html"),
            ("/delivery/login", "دخول مندوب التوصيل", "shipping_login.html"),
            ("/delivery/dashboard", "لوحة المندوب", "shipping.html (dashboard)"),
            ("/delivery-agent/login", "دخول مندوب (Agent)", "delivery_agent/login.html"),
            ("/delivery-agent/dashboard", "لوحة مندوب Agent", "delivery_agent/dashboard.html"),
            ("/agents", "المناديب (Agents)", "agents.html"),
            ("/agents/<id>/reports", "تقارير مندوب", "agent_reports.html"),
        ],
    },
    {
        "title": "التقارير والمالية",
        "icon": "fa-chart-line",
        "links": [
            ("/reports", "التقارير", "reports.html"),
            ("/reports/financial", "التقرير المالي", "reports_financial.html"),
            ("/reports/sales", "مبيعات", "reports.html"),
            ("/reports/profit", "أرباح", "reports.html"),
            ("/reports/expenses", "مصروفات", "reports.html"),
            ("/reports/inventory", "مخزون", "reports.html"),
            ("/reports/shipping", "شحن", "reports.html"),
            ("/reports/suppliers", "موردون", "reports.html"),
        ],
    },
    {
        "title": "الإعدادات والواجهة",
        "icon": "fa-cog",
        "links": [
            ("/settings", "الإعدادات", "settings.html"),
            ("/settings/system", "إعدادات النظام والموظفين", "system_settings.html"),
            ("/settings/invoice", "إعدادات الفاتورة", "invoice_settings.html"),
            ("/settings/appearance", "مظهر الفاتورة", "settings_appearance.html"),
        ],
    },
    {
        "title": "الصفحات والرسائل والمساعد",
        "icon": "fa-file-alt",
        "links": [
            ("/pages", "الصفحات (قائمة)", "pages.html"),
            ("/messages", "الرسائل", "messages.html"),
            ("/assistant", "المساعد الذكي", "assistant/dashboard.html"),
            ("/assistant/chat", "محادثة المساعد", "assistant/chat.html"),
            ("/assistant/under-development", "قيد التطوير", "assistant/under_development.html"),
        ],
    },
    {
        "title": "أخطاء وطباعة وعام",
        "icon": "fa-link",
        "links": [
            ("/404", "صفحة 404", "404.html"),
            ("/500", "صفحة 500", "500.html"),
            ("/profile", "الملف الشخصي", "profile.html"),
        ],
    },
]


@superadmin_bp.route("/links")
def links_guide():
    return render_template("superadmin_links.html", pages_guide=PAGES_GUIDE)

@superadmin_bp.route("/plans")
def plans_list():
    plans = SubscriptionPlan.query.all()
    # If no plans in DB, we should probably seed them from utils/plan_limits.py or show empty
    return render_template("superadmin_plans.html", plans=plans)

@superadmin_bp.route("/plans/edit/<int:plan_id>", methods=["GET", "POST"])
def edit_plan(plan_id):
    plan = SubscriptionPlan.query.get_or_404(plan_id)
    if request.method == "POST":
        plan.name = request.form.get("name")
        plan.price_monthly = int(request.form.get("price_monthly", 0))
        plan.price_yearly = int(request.form.get("price_yearly", 0))
        
        orig_m = request.form.get("original_price_monthly")
        plan.original_price_monthly = int(orig_m) if orig_m and orig_m.strip() else None
        
        orig_y = request.form.get("original_price_yearly")
        plan.original_price_yearly = int(orig_y) if orig_y and orig_y.strip() else None
        
        max_users = request.form.get("max_users")
        plan.max_users = int(max_users) if max_users and max_users.strip() else None
        
        max_orders = request.form.get("max_orders_monthly")
        plan.max_orders_monthly = int(max_orders) if max_orders and max_orders.strip() else None
        
        # Features
        features = {}
        # Get list of all possible features from request
        all_features = [
            "orders", "pos", "inventory", "customers", "cashflow", "printing",
            "expenses", "suppliers", "purchases", "shipping", "reports_adv",
            "rbac", "agents", "accounts", "ai_assistant", "messages"
        ]
        for feat in all_features:
            features[feat] = True if request.form.get(f"feat_{feat}") else False
            
        plan.set_features(features)
        db.session.commit()
        flash(f"تم تحديث الخطة «{plan.name}» بنجاح")
        return redirect(url_for("superadmin.plans_list"))
        
    return render_template("superadmin_edit_plan.html", plan=plan)

@superadmin_bp.route("/plans/seed", methods=["POST"])
def seed_plans():
    """Seed plans from PLAN_DEFINITIONS if empty"""
    from utils.plan_limits import PLAN_DEFINITIONS
    added = 0
    for key, data in PLAN_DEFINITIONS.items():
        existing = SubscriptionPlan.query.filter_by(plan_key=key).first()
        if not existing:
            new_p = SubscriptionPlan(
                plan_key=key,
                name=data["name"],
                price_monthly=data["price_monthly"],
                price_yearly=data["price_yearly"],
                max_users=data["max_users"],
                max_orders_monthly=data["max_orders_monthly"]
            )
            new_p.set_features(data["features"])
            db.session.add(new_p)
            added += 1
    db.session.commit()
    flash(f"تم إضافة {added} خطط افتراضية")
    return redirect(url_for("superadmin.plans_list"))

@superadmin_bp.route("/tenants/toggle-status/<slug>", methods=["POST"])
def tenant_toggle_status(slug):
    from flask import jsonify
    try:
        slug_clean = (slug or "").strip().lower()
        tenant = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
        if not tenant:
            return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404
        
        tenant.is_active = not tenant.is_active
        db.session.commit()
        
        status_text = "تفعيل" if tenant.is_active else "تعطيل"
        return jsonify({"ok": True, "message": f"تم {status_text} الشركة بنجاح", "is_active": tenant.is_active})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@superadmin_bp.route("/tenants/delete/<slug>", methods=["POST"])
def tenant_delete(slug):
    from flask import jsonify
    try:
        slug_clean = (slug or "").strip().lower()
        tenant = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
        if not tenant:
            return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404
        
        # 1. Delete associated database file
        if os.path.exists(tenant.db_path):
            try:
                os.remove(tenant.db_path)
            except Exception as e:
                print(f"Error deleting db file: {e}")
                
        # 2. Clear engine cache
        clear_tenant_engine(tenant.slug)
        
        # 3. Delete from Core DB
        db.session.delete(tenant)
        db.session.commit()
        
        return jsonify({"ok": True, "message": "تم حذف الشركة وقاعدة البيانات الخاصة بها نهائياً"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@superadmin_bp.route("/tenants/update-plan/<slug>", methods=["POST"])
def tenant_update_plan(slug):
    from flask import request, jsonify
    from datetime import datetime
    from sqlalchemy.orm import sessionmaker
    from extensions_tenant import get_tenant_engine, clear_tenant_engine
    from models.tenant import Tenant as TenantSpecific
    from utils.plan_limits import get_plan
    
    try:
        data = request.get_json()
        plan_key = data.get("plan_key")
        subscription_end_str = data.get("subscription_end")
        
        if not plan_key:
            return jsonify({"ok": False, "error": "مفتاح الخطة مطلوب"}), 400
            
        slug_clean = (slug or "").strip().lower()
        tenant_core = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
        if not tenant_core:
            return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404
            
        # Parse date
        sub_end_dt = None
        if subscription_end_str:
            try:
                sub_end_dt = datetime.fromisoformat(subscription_end_str.replace('Z', '+00:00'))
            except:
                return jsonify({"ok": False, "error": "تنسيق التاريخ غير صحيح"}), 400
        
        # 1. Update Core DB
        tenant_core.subscription_end_date = sub_end_dt
        db.session.commit()
        
        # 2. Update Tenant DB
        engine = get_tenant_engine(tenant_core.slug)
        SessionLocal = sessionmaker(bind=engine)
        tenant_session = SessionLocal()
        
        try:
            tenant_spec = tenant_session.query(TenantSpecific).first()
            if tenant_spec:
                plan_info = get_plan(plan_key)
                tenant_spec.plan_key = plan_key
                tenant_spec.plan_name = plan_info.get("name", "خطة مخصصة")
                tenant_spec.subscription_end = sub_end_dt
                tenant_session.commit()
        except Exception as te:
            tenant_session.rollback()
            return jsonify({"ok": False, "error": f"فشل تحديث قاعدة بيانات الشركة: {str(te)}"}), 500
        finally:
            tenant_session.close()
            
        # 3. Clear engine cache to reflect changes
        clear_tenant_engine(tenant_core.slug)
        
        return jsonify({"ok": True, "message": "تم تحديث خطة الاشتراك بنجاح"})
        
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
