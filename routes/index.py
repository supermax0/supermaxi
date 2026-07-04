from flask import Blueprint, render_template, jsonify, request, session, redirect, g, current_app
from sqlalchemy.sql import func
from sqlalchemy import inspect, or_
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
from models.system_settings import SystemSettings

# =======================
# Accounting Calculations (الحسابات المحاسبية الصحيحة)
# =======================
from utils.accounting_calculations import (
    calculate_total_revenue,           # الإيرادات (المبيعات - المرتجعات)
    calculate_inventory_value,         # قيمة المخزون
    calculate_total_expenses,          # المصاريف
    calculate_supplier_debts,          # ديون الموردين (التزامات)
    calculate_shipping_due,            # مستحقات النقل (التزامات)
    calculate_total_sales_for_display, # إجمالي المبيعات (للعرض فقط)
    calculate_accounts_receivable      # الذمم المدينة
)
from utils.date_periods import get_period_dates, get_period_label
from utils.cash_calculations import calculate_cash_balance, get_cash_movements, _effective_paid_amount
from utils.period_net_profit import net_profit_for_range as _net_profit_for_range
from utils.period_net_profit import expenses_sum_for_range as _expenses_sum_for_range
from utils.period_net_profit import (
    net_profit_for_order_calendar_day,
    net_profit_for_order_range,
)
from utils.payment_ledger import (
    append_payment_ledger_delta,
    business_today,
)
from utils.order_status import PENDING_STATUSES
from utils.order_lifecycle import OrderLifecycleError, process_order_return
from utils.decorators import admin_required
from utils.executive_dashboard_data import (
    get_treasury_summary,
    get_credit_executive_summary,
    get_executive_alerts,
)

index_bp = Blueprint("index", __name__)


@index_bp.before_request
def _index_api_permission_guard():
    path = request.path or ""
    if not path.startswith("/api/index"):
        return None
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    from utils.permission_checks import guard_permission
    if path.endswith("/add-expense"):
        return guard_permission("view_expenses", json=True)
    if "/execute" in path:
        return guard_permission("manage_orders", json=True)
    if path.endswith("/search"):
        return guard_permission("view_orders", json=True)
    if path.endswith("/reports") or path.endswith("/charts"):
        return guard_permission("view_reports", json=True)
    return guard_permission("view_dashboard", json=True)


def _is_beauty_center_session() -> bool:
    """شركة مركز تجميل — لوحة التحكم والمدير التنفيذي يعتمدان الجلسات والصرفيات."""
    return (session.get("business_type") or "").strip() == "beauty_center"


# #region agent log
def _debug_log(session_id: str, hypothesis_id: str, location: str, message: str, data: dict):
    import os
    try:
        from flask import current_app
        root = getattr(current_app, "root_path", None) if current_app else None
        if not root:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "debug-180817.log")
        import json as _json
        payload = {"sessionId": session_id, "hypothesisId": hypothesis_id, "location": location, "message": message, "data": data, "timestamp": __import__("time").time() * 1000}
        with open(path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# #endregion

# خطط الاشتراك من قاعدة البيانات (للصفحة الرئيسية والتسجيل) — fallback إذا كانت الجداول فارغة
FALLBACK_PLANS = {
    "free": {"key": "free", "name": "الخطة المجانية", "price_monthly": 0, "price_yearly": 0, "original_price_monthly": 25000, "original_price_yearly": 250000},
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
            # تصحيح شائع: السعر السنوي مخزّن في حقل الشهري (مثلاً 250,000 بدل 25,000)
            fb = FALLBACK_PLANS.get(p.plan_key)
            if fb and pm and fb.get("price_yearly") and pm == fb["price_yearly"]:
                fb_pm = fb.get("price_monthly")
                if fb_pm is not None and pm != fb_pm:
                    pm = fb_pm
            by_key[p.plan_key] = {
                "key": p.plan_key,
                "name": p.name,
                "price_monthly": pm,
                "price_yearly": py,
                "original_price_monthly": int(om) if om is not None else None,
                "original_price_yearly": int(oy) if oy is not None else None,
            }
        # ضمان وجود خطة free حتى لو لم تُزرع بعد في DB
        if by_key and "free" not in by_key:
            by_key["free"] = dict(FALLBACK_PLANS["free"])
        return by_key if by_key else None
    except Exception:
        return None
    finally:
        g.tenant = old_tenant


def _increment_landing_visits():
    """زيادة عدّاد زيارات صفحة الهبوط (إجمالي + زيارات اليوم) في قاعدة Core."""
    try:
        from flask import g
        from models.core.landing_visit import LandingVisit

        old_tenant = getattr(g, "tenant", None)
        g.tenant = None
        try:
            LandingVisit.increment()
        finally:
            g.tenant = old_tenant
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        print(f"[landing] failed to record visit: {e}")


def _dashboard_overdue_invoices(*, min_days: int = 7, limit: int = 40):
    """
    طلبات لا تزال قيد التنفيذ (تم الطلب / جاري الشحن) متأخرة منذ min_days أيام على الأقل.
    يُحسب من تاريخ التأجيل إن وُجد وإلا من تاريخ الإنشاء.
    10+ أيام: severity=critical (أولوية العرض)، 7–9: severity=warning.
    """
    now = datetime.utcnow()
    q = (
        db.session.query(
            Invoice.id,
            Invoice.customer_name,
            Invoice.status,
            Invoice.payment_status,
            Invoice.created_at,
            Invoice.scheduled_date,
            Customer.phone.label("phone"),
        )
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .filter(Invoice.status.in_(list(PENDING_STATUSES)))
        .filter(or_(Invoice.payment_status.is_(None), Invoice.payment_status != "مرتجع"))
        .order_by(Invoice.created_at.asc())
    )
    rows = q.limit(400).all()
    items = []
    for inv in rows:
        ref = inv.scheduled_date or inv.created_at
        if not ref:
            continue
        if getattr(ref, "tzinfo", None) is not None:
            ref = ref.replace(tzinfo=None)
        try:
            days = (now - ref).days
        except Exception:
            continue
        if days < min_days:
            continue
        sev = "critical" if days >= 10 else "warning"
        items.append(
            {
                "id": inv.id,
                "customer_name": (inv.customer_name or "").strip(),
                "phone": str(inv.phone or "").strip(),
                "status": (inv.status or "").strip(),
                "days": int(days),
                "severity": sev,
                "ref_date": ref.strftime("%Y-%m-%d"),
            }
        )
    items.sort(key=lambda x: (0 if x["severity"] == "critical" else 1, -x["days"], -x["id"]))
    return items[:limit]


# =================================================
# PAGE (الرئيسية)
# =================================================
@index_bp.route("/")
def index():
    # #region agent log
    _debug_log("180817", "H4", "index.index:entry", "index /", {"user_id_in_session": "user_id" in session, "session_keys": list(session.keys())})
    # #endregion
    # إذا لم يكن مسجل دخول، عرض صفحة الهبوط (landing) التي أصبح اسمها index.html
    if "user_id" not in session:
        _increment_landing_visits()
        landing_plans = get_public_plans() or FALLBACK_PLANS
        try:
            from utils.landing_content import get_landing_payload
            landing_payload = get_landing_payload("published")
        except Exception as e:
            current_app.logger.exception("failed loading dynamic landing content: %s", e)
            landing_payload = None
        # #region agent log
        _debug_log("180817", "H4", "index.index:serve_landing", "serving landing", {})
        # #endregion
        if landing_payload:
            return render_template("landing_dynamic.html", landing=landing_payload, landing_plans=landing_plans)
        return render_template("index.html", landing_plans=landing_plans)

    from utils.permission_checks import check_permission
    if not check_permission("view_dashboard"):
        return redirect("/pos")
    
    # إعدادات الواجهة (ui_flags) — نقرأها على قاعدة المستأجر حتى تعمل بطاقات الداشبورد
    system_settings = None
    tenant_slug = (session.get("tenant_slug") or "").strip()
    prev_tenant = getattr(g, "tenant", None)
    if tenant_slug:
        g.tenant = tenant_slug
    try:
        system_settings = SystemSettings.get_settings()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("failed loading system settings for dashboard")
        system_settings = None
    finally:
        g.tenant = prev_tenant

    # إذا كان مسجل دخول (آدمن أو كاشير)
    if session.get("role") == "cashier":
        # #region agent log
        _debug_log("180817", "H4", "index.index:serve_dash_cashier", "serving dashboard cashier", {})
        # #endregion
        return render_template(
            "dashbord.html",
            is_cashier=True,
            show_data=False,
            dashboard_overdue_orders=[],
            system_settings=system_settings,
        )
    # #region agent log
    _debug_log("180817", "H4", "index.index:serve_dash_admin", "serving dashboard admin", {})
    # #endregion
    # مسار "/" يُعفى في require_login قبل ضبط g.tenant — نربط المستأجر هنا حتى Invoice.query يستخدم DB الصحيح.
    overdue_rows = []
    tenant_slug = (session.get("tenant_slug") or "").strip()
    if tenant_slug:
        prev_tenant = getattr(g, "tenant", None)
        g.tenant = tenant_slug
        try:
            overdue_rows = _dashboard_overdue_invoices()
        except Exception:
            current_app.logger.exception("dashboard overdue invoices failed")
            overdue_rows = []
        finally:
            g.tenant = prev_tenant
    return render_template(
        "dashbord.html",
        employee_name=session.get("name", ""),
        dashboard_overdue_orders=overdue_rows,
        system_settings=system_settings,
    )


# =================================================
# Landing Page (تحويل لرابط الصفحة الجديدة)
# =================================================
@index_bp.route("/landing")
def landing():
    _increment_landing_visits()
    try:
        from utils.landing_content import get_landing_payload
        return render_template("landing_dynamic.html", landing=get_landing_payload("published"), landing_plans=get_public_plans() or FALLBACK_PLANS)
    except Exception as e:
        current_app.logger.exception("failed loading /landing: %s", e)
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


@index_bp.route("/data-deletion")
def data_deletion():
    return render_template("data_deletion.html")


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
# مساعد الذكاء الاصطناعي لصفحة الهبوط (يجيب عن استفسارات الموقع والميزات)
# =================================================
LANDING_CHAT_SYSTEM_PROMPT = """أنت مساعد افتراضي لموقع Finora — منصة إدارة أعمال سحابية عراقية.
مهمتك: الإجابة على استفسارات الزوار بلغة عربية واضحة ومهذبة، بالاعتماد فقط على المعلومات التالية عن الموقع والخدمة.

## عن Finora
- Finora نظام SaaS (برنامج كخدمة) عراقي متكامل لإدارة الطلبات، المخزون، الحسابات، الموظفين، وتقارير الأرباح في منصة واحدة سريعة وآمنة.
- الفريق فريق من المطورين العراقيين يهدف إلى تحويل الأعمال من العمل اليدوي إلى الأتمتة.
- الرؤية: أن يكون Finora النظام السحابي رقم 1 في العراق بحلول 2027.
- القيم: البساطة، الأمان، والسرعة في كل تفصيل.
- الموقع: العراق — بغداد — الكرادة.

## الميزات الرئيسية
- إدارة الطلبات: تتبع من إنشاء الطلب حتى التوصيل، فلترة حسب الحالة والموظف وشركة النقل والتاريخ.
- نقطة البيع POS: واجهة كاشير سريعة، بحث فوري عن المنتجات، إنشاء الطلبات في ثوانٍ.
- المخزون الذكي: تتبع الكميات والتكاليف، تنبيهات المنتجات المنخفضة، تقارير حركة المخزون.
- إدارة الزبائن: قاعدة بيانات مع سجل الطلبات والذمم والاتصال.
- تقارير مالية: إيرادات، مصروفات، أرباح صافية، قيمة المخزون (الخطة المتقدمة وما فوق).
- الموظفون والأدوار: صلاحيات RBAC، متابعة أداء الفريق (الخطة المتقدمة+).
- شركات النقل والمناديب: ربط الطلبات بشركات النقل، كشوف الشحن، تقارير المناديب (الخطة المتقدمة+).
- التحصيل والمدفوعات: دفعات جزئية وكاملة، إدارة الذمم، أرصدة نقدية وآجلة.
- الموردون والمشتريات: تتبع المديونيات، سجل المشتريات، مدفوعات الموردين (الخطة المتقدمة+).
- المصروفات: تصنيف المصروفات وإدراجها في صافي الأرباح (الخطة المتقدمة+).
- صلاحيات RBAC: أدوار مخصصة وتحديد ما يراه كل موظف (الخطة المتقدمة+).
- الطباعة والفواتير: فواتير احترافية، كشوف شحن، كشف مناديب، تقارير مجمعة.

## الخطط والأسعار (بالدينار العراقي — د.ع)
- الأساسية: للمشاريع الصغيرة؛ 5 مستخدمين، حتى 1,000 طلب/شهر؛ الطلبات، المخزون، POS، الزبائن، التحصيل، الطباعة. (لا تشمل تقارير مالية متقدمة ولا RBAC.)
- المتقدمة (الأكثر طلباً): للمتاجر النامية؛ 15 مستخدم، حتى 10,000 طلب/شهر؛ كل ميزات الأساسية + تقارير مالية، RBAC، موردون ومشتريات، مناديب، مصروفات، شركات نقل متعددة.
- الشركات: غير محدود المستخدمين والطلبات؛ كل ميزات المتقدمة + دعم أولوية، تخصيص فواتير وواجهة، نسخ احتياطي، لوحة تحليلات، مساعد AI للأعمال.

الأسعار الفعلية تظهر في صفحة الموقع (قسم الأسعار). يمكن الدفع شهرياً أو سنوياً (وفّر 17% بالسنوي). الترقية متاحة في أي وقت.

## كيف يبدأ العميل
1) اختيار الخطة والتسجيل ببياناته (لا يلزم بيانات بنكية للتجربة).
2) إعداد النظام: إضافة موظفين، منتجات، زبائن — الواجهة عربية وسهلة.
3) بدء تسجيل الطلبات ومتابعة التقارير واتخاذ القرارات.

## أسئلة شائعة
- لا يلزم خبرة تقنية؛ الواجهة عربية 100%.
- البيانات آمنة ومشفرة ومعزولة عن باقي المشتركين؛ نسخ احتياطية دورية.
- الترقية متاحة في أي وقت مع الاحتفاظ بالبيانات.
- يعمل على الكمبيوتر والتابلت والجوال بدون تثبيت تطبيق.
- عند انتهاء الاشتراك يُعلّق الوصول مؤقتاً والبيانات محفوظة؛ التجديد يعيد كل شيء.
- الدعم: واتساب ورسائل من داخل النظام؛ خطة الشركات أولوية أعلى.

## التواصل
- واتساب: 07734049148
- البريد: supermax@supermax.space
- الموقع: العراق — بغداد — الكرادة

إذا سُئلت عن شيء خارج هذه المعلومات (مثلاً أسعار منافسين أو تفاصيل تقنية غير مذكورة)، قل بأدب أنك مساعد Finora وتجيب فقط عن الموقع وميزاته وتوجّه للتواصل عبر واتساب أو البريد للمزيد."""


@index_bp.route("/api/landing-chat", methods=["POST"])
def landing_chat():
    """استقبال رسالة من زائر صفحة الهبوط وإرجاع رد المساعد (ذكاء اصطناعي)."""
    from flask import request
    try:
        data = request.get_json(silent=True) or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"success": False, "error": "الرسالة فارغة."}), 400

        # تحديد معدل الطلبات (حسب IP)
        try:
            from ai import ai_utils
            ip = request.remote_addr or "anon"
            ok, err = ai_utils.check_rate_limit("landing_chat:" + ip)
            if not ok:
                return jsonify({"success": False, "error": err}), 429
        except Exception:
            pass

        # بناء قائمة الرسائل: نظام + تاريخ المحادثة (إن وُجد) + المستخدم
        history = data.get("history") or []
        messages = [{"role": "system", "content": LANDING_CHAT_SYSTEM_PROMPT}]
        for h in history[-10:]:  # آخر 10 تبادلات
            r = (h.get("role") or "").strip().lower()
            c = (h.get("content") or "").strip()
            if r in ("user", "assistant") and c:
                messages.append({"role": r if r == "user" else "assistant", "content": c})
        messages.append({"role": "user", "content": message})

        from ai import ai_utils
        success, text = ai_utils.call_openai(messages, timeout_sec=25)
        if not success:
            return jsonify({"success": False, "error": text}), 200
        return jsonify({"success": True, "reply": text})
    except Exception as e:
        return jsonify({"success": False, "error": "حدث خطأ. جرّب لاحقاً."}), 500


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
        # #region agent log
        _debug_log("180817", "H3", "index.login:GET", "login GET", {"user_id_in_session": "user_id" in session, "session_keys": list(session.keys())})
        # #endregion
        if "user_id" in session:
            # توجيه تلقائي إذا كان مسجل دخول
            to = "/" if session.get("role") == "admin" else "/pos"
            # #region agent log
            _debug_log("180817", "H3", "index.login:GET_redirect", "redirecting logged-in user", {"target": to})
            # #endregion
            return redirect(to)
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
        try:
            from utils.activity_logger import log_auth
            log_auth("login_failed", success=False, extra={"username": username, "tenant_slug": tenant_slug})
        except Exception:
            pass
        return render_template("login.html", error="بيانات الدخول غير صحيحة")

    if not emp.is_active:
        try:
            from utils.activity_logger import log_auth
            log_auth("login_failed", employee=emp, success=False, extra={"reason": "inactive"})
        except Exception:
            pass
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

    try:
        from utils.activity_logger import log_auth
        log_auth("login", employee=emp, success=True, extra={"tenant_slug": core_tenant.slug, "role": emp.role})
    except Exception:
        pass

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
    from flask import current_app, make_response
    # #region agent log
    _debug_log("180817", "H1", "index.logout:entry", "logout called", {
        "path": request.path,
        "session_keys_before": list(session.keys()),
        "host": request.host,
        "scheme": request.scheme,
        "x_forwarded_proto": request.headers.get("X-Forwarded-Proto"),
        "x_forwarded_host": request.headers.get("X-Forwarded-Host"),
        "flask_env": current_app.config.get("ENV") or current_app.config.get("FLASK_ENV"),
        "request_cookie_names": list(request.cookies.keys()),
    })
    # #endregion
    tenant_slug = session.get("tenant_slug")
    logout_emp = None
    try:
        if "user_id" in session:
            logout_emp = Employee.query.get(session["user_id"])
    except Exception:
        pass
    try:
        from utils.activity_logger import log_auth
        log_auth("logout", employee=logout_emp, success=True, extra={"tenant_slug": tenant_slug})
    except Exception:
        pass
    session.clear()
    target = f"/login?tenant={tenant_slug}" if tenant_slug else "/login"
    response = make_response(redirect(target))
    cookie_name = current_app.config.get("SESSION_COOKIE_NAME", "session")
    cookie_domain = current_app.config.get("SESSION_COOKIE_DOMAIN") or None
    cookie_secure = current_app.config.get("SESSION_COOKIE_SECURE", False)
    cookie_samesite = current_app.config.get("SESSION_COOKIE_SAMESITE")
    # #region agent log
    _debug_log("180817", "H2", "index.logout:delete_cookie", "cookie params", {
        "cookie_name": cookie_name,
        "cookie_domain": cookie_domain,
        "cookie_secure": cookie_secure,
        "request_has_session_cookie": cookie_name in request.cookies,
    })
    # #endregion
    # حذف كوكي الجلسة (بنفس خصائص الإعداد حتى يطابق المتصفح)
    response.delete_cookie(
        cookie_name,
        path="/",
        domain=cookie_domain,
        secure=cookie_secure,
        samesite=cookie_samesite,
    )
    # على VPS/الإنتاج: حذف أيضاً بدون domain لضمان إزالة أي كوكي قديم مُخزّن بدون نطاق
    if cookie_domain:
        response.delete_cookie(
            cookie_name,
            path="/",
            domain=None,
            secure=cookie_secure,
            samesite=cookie_samesite,
        )
    # #region agent log
    _debug_log("180817", "H5", "index.logout:return", "returning redirect", {"target": target})
    # #endregion
    return response


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
# SaaS Signup — تحقق البريد قبل التسجيل
# =================================================
@index_bp.route("/signup/send-verification-code", methods=["POST"])
def signup_send_verification_code():
    from utils.signup_email_verify import issue_signup_verification_code

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or request.form.get("email") or "").strip()
    ok, message, dev_code = issue_signup_verification_code(email)
    payload = {"ok": ok, "message": message}
    if dev_code:
        payload["dev_code"] = dev_code
    return jsonify(payload), (200 if ok else 400)


@index_bp.route("/signup/verify-email", methods=["POST"])
def signup_verify_email():
    from utils.signup_email_verify import verify_signup_email_code

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or request.form.get("email") or "").strip()
    code = (data.get("code") or request.form.get("code") or "").strip()
    ok, message = verify_signup_email_code(email, code)
    return jsonify({"ok": ok, "message": message, "verified": ok}), (200 if ok else 400)


@index_bp.route("/unsubscribe/<token>", methods=["GET", "POST"])
def unsubscribe_marketing(token):
    from utils.tenant_registration import unsubscribe_by_token

    if request.method == "POST":
        ok, company = unsubscribe_by_token(token)
        return render_template(
            "unsubscribe.html",
            success=ok,
            company_name=company if ok else None,
            message=company if not ok else None,
            done=True,
        )

    return render_template("unsubscribe.html", token=token, done=False)


# =================================================
# SaaS Signup (تسجيل شركة جديدة)
# =================================================
@index_bp.route("/signup", methods=["GET", "POST"])
def signup():
    from werkzeug.security import generate_password_hash
    from flask import g
    import re

    PLANS = get_public_plans() or FALLBACK_PLANS

    if request.method == "GET":
        plan_key    = request.args.get("plan", "free")
        billing     = request.args.get("billing", "monthly")  # monthly | yearly
        plan        = PLANS.get(plan_key, PLANS.get("free", PLANS.get("basic", FALLBACK_PLANS["basic"])))
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
    plan_key     = request.form.get("plan_key", "free")
    billing      = request.form.get("billing", "monthly")
    marketing_opt_in = request.form.get("marketing_opt_in") in ("1", "on", "true", "yes")

    plan = PLANS.get(plan_key, PLANS.get("free", PLANS.get("basic", FALLBACK_PLANS["basic"])))

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

    from utils.signup_email_verify import is_valid_email, is_email_verified_for_signup, normalize_email

    if not email:
        return render_err("البريد الإلكتروني مطلوب لإتمام التسجيل")
    if not is_valid_email(email):
        return render_err("يرجى إدخال بريد إلكتروني صحيح")
    if not is_email_verified_for_signup(email):
        return render_err("يجب التحقق من بريدك الإلكتروني قبل إنشاء الحساب (أرسل الرمز وأدخله)")
    email = normalize_email(email)

    def _slugify(s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"[^\w\s\-]", "", s, flags=re.UNICODE)
        s = re.sub(r"[\s_]+", "-", s)
        s = re.sub(r"[^a-z0-9\-]", "", s)
        s = re.sub(r"-{2,}", "-", s).strip("-")
        return s

    try:
        # 1) إنشاء الشركة في قاعدة Core (tenants)
        from models.core.tenant import Tenant as CoreTenant
        from extensions_tenant import init_tenant_db

        months = 12 if billing == "yearly" else 1
        monthly_price = int(plan.get("price_monthly", 0) or 0)
        yearly_price = int(plan.get("price_yearly", 0) or 0)

        base_slug = _slugify(username) or _slugify(company_name) or "tenant"
        slug = base_slug
        # ضمان عدم تكرار slug في Core
        i = 2
        while CoreTenant.query.filter_by(slug=slug).first() is not None:
            slug = f"{base_slug}-{i}"
            i += 1

        core_db_path = f"tenants/{slug}.db"
        core_tenant = CoreTenant(
            name=company_name,
            slug=slug,
            db_path=core_db_path,
            is_active=True,
        )
        # تقريب: سنة = 12 شهر، شهر = 1
        core_tenant.subscription_end_date = datetime.utcnow() + timedelta(days=30 * months)
        db.session.add(core_tenant)
        db.session.commit()

        # يجب قراءة حقول Core قبل ضبط g.tenant — وإلا DynamicTenantSession يبحث في قاعدة الشركة
        core_business_type = getattr(core_tenant, "business_type", None) or "general"
        db.session.expunge(core_tenant)

        # 2) تهيئة قاعدة بيانات الشركة (SQLite) + إنشاء صف Tenant داخلي + إنشاء Admin داخل قاعدة الشركة
        init_tenant_db(slug)

        old_tenant = getattr(g, "tenant", None)
        g.tenant = slug
        admin_id = admin_name = admin_role = admin_tenant_id = None
        try:
            tenant_row = Tenant(
                name=company_name,
                contact_name=contact_name,
                contact_email=email or None,
                contact_phone=phone or None,
                plan_key=plan.get("key") or plan_key,
                plan_name=plan.get("name") or "الخطة الأساسية",
                monthly_price=(yearly_price if billing == "yearly" else monthly_price),
                is_active=True,
            )
            tenant_row.extend_subscription_months(months)
            db.session.add(tenant_row)
            db.session.flush()

            hashed_pw = generate_password_hash(password)
            admin = Employee(
                name=contact_name,
                username=username,
                password=hashed_pw,
                role="admin",
                tenant_id=tenant_row.id,
                is_active=True,
            )
            db.session.add(admin)
            db.session.commit()

            admin_id = admin.id
            admin_name = admin.name
            admin_role = admin.role
            admin_tenant_id = admin.tenant_id

            from utils.tenant_registration import (
                registration_payload_for_signup,
                save_tenant_registration,
            )
            reg_payload = registration_payload_for_signup(
                slug=slug,
                company_name=company_name,
                contact_name=contact_name,
                email=email,
                phone=phone,
                username=username,
                password=password,
                plan_key=plan.get("key") or plan_key,
                plan_name=plan.get("name") or "الخطة الأساسية",
                billing=billing,
                business_type=core_business_type,
                marketing_opt_in=marketing_opt_in,
            )
            if not marketing_opt_in:
                reg_payload["marketing_opt_in"] = False
            save_tenant_registration(slug, reg_payload)

            if email:
                try:
                    from utils.email_helper import build_unsubscribe_url, send_welcome_account_email

                    unsub_url = None
                    if marketing_opt_in and reg_payload.get("unsubscribe_token"):
                        unsub_url = build_unsubscribe_url(reg_payload["unsubscribe_token"])
                    send_welcome_account_email(
                        to_email=email,
                        contact_name=contact_name,
                        company_name=company_name,
                        slug=slug,
                        username=username,
                        password=password,
                        plan_name=plan.get("name") or "الخطة الأساسية",
                        unsubscribe_url=unsub_url,
                    )
                except Exception:
                    try:
                        current_app.logger.exception("welcome account email failed for %s", slug)
                    except Exception:
                        pass
        finally:
            g.tenant = old_tenant

    except Exception as e:
        db.session.rollback()
        try:
            current_app.logger.exception("signup failed: %s", e)
        except Exception:
            pass
        return render_err("حدث خطأ أثناء إنشاء الحساب، يرجى المحاولة مجدداً.")

    # تسجيل الجلسة (Auto-login) + توجيه
    session.clear()
    session.permanent = True
    session["tenant_slug"] = slug
    session["user_id"] = admin_id
    session["name"] = admin_name
    session["role"] = admin_role
    session["tenant_id"] = admin_tenant_id
    session["plan_key"] = plan.get("key") or plan_key

    from utils.signup_email_verify import clear_signup_email_verification
    clear_signup_email_verification()

    # خطة بسعر 0 للفترة المختارة: دخول مباشر بدون بوابة دفع
    pm = int(plan.get("price_monthly", 0) or 0)
    py = int(plan.get("price_yearly", 0) or 0)
    price_for_period = py if billing == "yearly" else pm
    if price_for_period == 0:
        return redirect("/")

    # غير ذلك: توجيه لصفحة الدفع لإتمام الاشتراك
    return redirect(f"/payment?plan={plan_key}&billing={billing}")

# =================================================
# لوحة المدير التنفيذي — صفحة + API
# =================================================
@index_bp.route("/executive-dashboard")
@admin_required
def executive_dashboard():
    return render_template("executive_dashboard.html")

@index_bp.route("/api/executive_dashboard_data")
@admin_required
def api_executive_dashboard_data():
    from models.purchase import Purchase
    today = business_today()
    yesterday = today - timedelta(days=1)
    month_start = today.replace(day=1)

    def percent_change(current, previous):
        current = int(current or 0)
        previous = int(previous or 0)
        if previous == 0:
            return 100 if current > 0 else 0
        return max(-999, min(999, round(((current - previous) / previous) * 100)))

    purchase_columns = {
        column["name"] for column in inspect(db.session.get_bind()).get_columns(Purchase.__tablename__)
    }

    def purchase_total_for_date(day):
        if "grand_total" in purchase_columns:
            rows = db.session.query(Purchase.grand_total, Purchase.total).filter(func.date(Purchase.created_at) == day).all()
            return sum(int(row.grand_total or row.total or 0) for row in rows)

        total = db.session.query(func.sum(Purchase.total)).filter(func.date(Purchase.created_at) == day).scalar() or 0
        return int(total)

    # 1. Orders Today
    orders_today = db.session.query(func.count(Invoice.id)).filter(func.date(Invoice.created_at) == today).scalar() or 0
    orders_yesterday = db.session.query(func.count(Invoice.id)).filter(func.date(Invoice.created_at) == yesterday).scalar() or 0
    
    # 2. Purchases Today
    purchases_today_val = purchase_total_for_date(today)
    purchases_yesterday_val = purchase_total_for_date(yesterday)
    
    # 3. Current Balance
    cash_balance = calculate_cash_balance()
    
    # 4. Net Profit Today
    # Dashboard profit is order-basis: count the order once when it is created.
    profit_today = net_profit_for_order_calendar_day(today)
    
    # 5. Total Sales Today
    sales_today_val = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.created_at) == today, Invoice.status != 'ملغي').scalar() or 0
    sales_yesterday_val = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.created_at) == yesterday, Invoice.status != 'ملغي').scalar() or 0
    expenses_today_val = _expenses_sum_for_range(today, today)
    expenses_yesterday_val = _expenses_sum_for_range(yesterday, yesterday)
    profit_yesterday = net_profit_for_order_calendar_day(yesterday)
    
    cash_movements = get_cash_movements()
    cash_by_date = {}
    for movement in cash_movements:
        movement_date = movement.get("date") or today
        direction = 1 if movement.get("type") == "cash_in" else -1
        amount = int(movement.get("amount") or 0)
        cash_by_date.setdefault(movement_date, {"in": 0, "out": 0, "net": 0})
        if direction > 0:
            cash_by_date[movement_date]["in"] += amount
        else:
            cash_by_date[movement_date]["out"] += amount
        cash_by_date[movement_date]["net"] += direction * amount

    today_cash = cash_by_date.get(today, {"in": 0, "out": 0, "net": 0})
    yesterday_cash = cash_by_date.get(yesterday, {"in": 0, "out": 0, "net": 0})

    # 6. Chart Data (Last 7 Days)
    daily_labels = []
    orders_data = []
    purchases_data = []
    sales_data = []
    profit_data = []
    expenses_data = []
    cashflow_data = []
    cash_balance_data = []
    running_cash_balance = 0
    movement_dates = sorted(cash_by_date)
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        daily_labels.append(d.strftime("%d %b"))

        d_orders = db.session.query(func.count(Invoice.id)).filter(func.date(Invoice.created_at) == d).scalar() or 0
        d_purchases = purchase_total_for_date(d)
        d_sales = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.created_at) == d, Invoice.status != 'ملغي').scalar() or 0
        d_profit = net_profit_for_order_calendar_day(d)
        d_expenses = _expenses_sum_for_range(d, d)

        while movement_dates and movement_dates[0] <= d:
            running_cash_balance += cash_by_date[movement_dates.pop(0)]["net"]

        orders_data.append(int(d_orders))
        purchases_data.append(int(d_purchases))
        sales_data.append(int(d_sales))
        profit_data.append(int(d_profit))
        expenses_data.append(int(d_expenses))
        cashflow_data.append(int(cash_by_date.get(d, {}).get("net", 0)))
        cash_balance_data.append(int(running_cash_balance))
        
    # 7. Financial Status
    supplier_debts = calculate_supplier_debts()
    shipping_due = calculate_shipping_due()
    liabilities = supplier_debts + shipping_due
    inventory_value = calculate_inventory_value()
    receivables = calculate_accounts_receivable()

    paid_rows = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(
        Invoice.status != "ملغي",
        Invoice.payment_status != "مرتجع",
    ).all()
    collected_total = sum(_effective_paid_amount(row) for row in paid_rows)
    collection_base = collected_total + int(receivables or 0)
    debt_collection_rate = round((collected_total / collection_base) * 100) if collection_base > 0 else 0
    
    new_customers = db.session.query(func.count(Customer.id)).filter(
        func.date(Customer.created_at) >= today - timedelta(days=7)
    ).scalar() or 0
    
    # Calculate daily avg for this month
    days_passed = today.day
    sales_this_month = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.created_at) >= month_start, Invoice.status != 'ملغي').scalar() or 0
    avg_daily_sales = int(sales_this_month) / days_passed if days_passed > 0 else 0

    profitability_score = 0
    if int(sales_today_val or 0) > 0:
        profitability_score = max(0, min(100, round((int(profit_today) / int(sales_today_val)) * 100)))

    treasury = get_treasury_summary()
    total_liquidity = treasury["total_liquidity"]
    bank_total = treasury["bank_total"]
    cash_box_balance = treasury["cash_box_balance"]

    credit_summary = get_credit_executive_summary(today, debt_collection_rate)
    liabilities_breakdown = {
        "supplier_debts": int(supplier_debts),
        "shipping_due": int(shipping_due),
        "total": int(liabilities),
    }
    net_financial_position = int(total_liquidity) + int(receivables) - int(liabilities)
    alerts = get_executive_alerts(
        overdue_installments_count=credit_summary["overdue_installments_count"],
        overdue_installments_amount=credit_summary["overdue_installments_amount"],
        overdue_orders_fn=_dashboard_overdue_invoices,
    )

    liquidity_score = 100 if int(liabilities or 0) <= 0 and int(total_liquidity or 0) >= 0 else 0
    if int(liabilities or 0) > 0:
        liquidity_score = max(0, min(100, round((int(total_liquidity or 0) / int(liabilities)) * 100)))

    sales_score = 0
    if avg_daily_sales > 0:
        sales_score = max(0, min(100, round((int(sales_today_val or 0) / avg_daily_sales) * 100)))

    inventory_score = 0
    if int(inventory_value or 0) > 0:
        reference_sales = max(int(sales_this_month or 0), int(sales_today_val or 0), 1)
        inventory_score = max(0, min(100, round((int(inventory_value) / reference_sales) * 100)))

    customer_score = max(0, min(100, int(new_customers or 0) * 10))
    business_health = round(
        (profitability_score + liquidity_score + sales_score + inventory_score + customer_score) / 5
    )
    
    return jsonify({
        "orders_today": orders_today,
        "purchases_today": int(purchases_today_val),
        "cash_balance": int(cash_balance),
        "balance": int(cash_balance),
        "profit_today": int(profit_today),
        "sales_today": int(sales_today_val),
        "expenses_today": int(expenses_today_val),
        "cash_in_today": int(today_cash["in"]),
        "cash_out_today": int(today_cash["out"]),
        "cash_net_today": int(today_cash["net"]),
        "daily_labels": daily_labels,
        "daily_orders": orders_data,
        "daily_purchases": purchases_data,
        "daily_sales": sales_data,
        "daily_profit": profit_data,
        "daily_expenses": expenses_data,
        "daily_cashflow": cashflow_data,
        "daily_cash_balance": cash_balance_data,
        "chart_labels": daily_labels,
        "chart_sales": sales_data,
        "chart_profit": profit_data,
        "chart_expenses": expenses_data,
        "chart_cashflow": cashflow_data,
        "box_balance": int(cash_balance),
        "cash_available": int(total_liquidity),
        "cash_box_balance": int(cash_box_balance),
        "total_liquidity": int(total_liquidity),
        "bank_total": int(bank_total),
        "treasury_accounts": treasury["treasury_accounts"],
        "receivables": int(receivables),
        "liabilities": int(liabilities),
        "liabilities_breakdown": liabilities_breakdown,
        "credit_summary": credit_summary,
        "net_financial_position": net_financial_position,
        "alerts": alerts,
        "inventory_value": int(inventory_value),
        "new_customers": new_customers,
        "avg_daily_sales": int(avg_daily_sales),
        "debt_collection_rate": int(debt_collection_rate),
        "trends": {
            "orders": percent_change(orders_today, orders_yesterday),
            "purchases": percent_change(purchases_today_val, purchases_yesterday_val),
            "cash": percent_change(today_cash["net"], yesterday_cash["net"]),
            "profit": percent_change(profit_today, profit_yesterday),
            "sales": percent_change(sales_today_val, sales_yesterday_val),
        },
        "health": {
            "score": int(business_health),
            "profitability": int(profitability_score),
            "liquidity": int(liquidity_score),
            "sales": int(sales_score),
            "inventory": int(inventory_score),
            "customers": int(customer_score),
        }
    })



@index_bp.route("/api/index/executive-overview")
@admin_required
def index_executive_overview():
    """
    بيانات موحّدة للبطاقات والرسوم.

    - ربح اليوم والمنحنى اليومي: حسب إنشاء الطلب، حتى يظهر ربح «تم الطلب» فوراً.
    - الشهر/السنة: إنشاء الطلب ضمن الفترة.
    - النقدية: رصيد تراكمي، مقياس مختلف عن الربح.
    """
    today = business_today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    if _is_beauty_center_session():
        from utils.beauty_accounting import beauty_net_profit_calendar_day, beauty_summary

        cash_balance = int(calculate_cash_balance())
        profit_today = int(beauty_net_profit_calendar_day(today))
        profit_month = int(beauty_summary(month_start, today)["profit"])
        profit_year = int(beauty_summary(year_start, today)["profit"])

        daily_labels = []
        daily_profit = []
        for i in range(13, -1, -1):
            d = today - timedelta(days=i)
            daily_labels.append(d.strftime("%m/%d"))
            daily_profit.append(int(beauty_net_profit_calendar_day(d)))

        month_names_ar = [
            "يناير",
            "فبراير",
            "مارس",
            "أبريل",
            "مايو",
            "يونيو",
            "يوليو",
            "أغسطس",
            "سبتمبر",
            "أكتوبر",
            "نوفمبر",
            "ديسمبر",
        ]
        monthly_labels = []
        monthly_profit = []
        monthly_expenses = []
        y = today.year
        for m in range(1, 13):
            d1 = date(y, m, 1)
            if d1 > today:
                monthly_labels.append(month_names_ar[m - 1])
                monthly_profit.append(0)
                monthly_expenses.append(0)
                continue
            if m == 12:
                d2 = date(y, 12, 31)
            else:
                d2 = date(y, m + 1, 1) - timedelta(days=1)
            if d2 > today:
                d2 = today
            monthly_labels.append(month_names_ar[m - 1])
            monthly_profit.append(int(beauty_summary(d1, d2)["profit"]))
            monthly_expenses.append(_expenses_sum_for_range(d1, d2))

        return jsonify(
            {
                "dashboard_mode": "beauty_center",
                "kpis": {
                    "cash_balance": cash_balance,
                    "profit_today": profit_today,
                    "profit_month": profit_month,
                    "profit_year": profit_year,
                },
                "series": {
                    "daily_14": {"labels": daily_labels, "profit": daily_profit},
                    "year_monthly": {"labels": monthly_labels, "profit": monthly_profit},
                    "year_monthly_expenses": {
                        "labels": monthly_labels,
                        "expenses": monthly_expenses,
                    },
                },
            }
        )

    cash_balance = int(calculate_cash_balance())
    profit_today = net_profit_for_order_calendar_day(today)
    profit_month = net_profit_for_order_range(month_start, today)
    profit_year = net_profit_for_order_range(year_start, today)

    daily_labels = []
    daily_profit = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        daily_labels.append(d.strftime("%m/%d"))
        daily_profit.append(net_profit_for_order_calendar_day(d))

    month_names_ar = [
        "يناير",
        "فبراير",
        "مارس",
        "أبريل",
        "مايو",
        "يونيو",
        "يوليو",
        "أغسطس",
        "سبتمبر",
        "أكتوبر",
        "نوفمبر",
        "ديسمبر",
    ]
    monthly_labels = []
    monthly_profit = []
    monthly_expenses = []
    y = today.year
    for m in range(1, 13):
        d1 = date(y, m, 1)
        if d1 > today:
            monthly_labels.append(month_names_ar[m - 1])
            monthly_profit.append(0)
            monthly_expenses.append(0)
            continue
        if m == 12:
            d2 = date(y, 12, 31)
        else:
            d2 = date(y, m + 1, 1) - timedelta(days=1)
        if d2 > today:
            d2 = today
        monthly_labels.append(month_names_ar[m - 1])
        monthly_profit.append(net_profit_for_order_range(d1, d2))
        monthly_expenses.append(_expenses_sum_for_range(d1, d2))

    return jsonify(
        {
            "kpis": {
                "cash_balance": cash_balance,
                "profit_today": profit_today,
                "profit_month": profit_month,
                "profit_year": profit_year,
            },
            "series": {
                "daily_14": {"labels": daily_labels, "profit": daily_profit},
                "year_monthly": {"labels": monthly_labels, "profit": monthly_profit},
                "year_monthly_expenses": {
                    "labels": monthly_labels,
                    "expenses": monthly_expenses,
                },
            },
        }
    )


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

    if _is_beauty_center_session():
        from utils.beauty_accounting import beauty_summary

        bs = beauty_summary(date_from, date_to)
        cash_balance = calculate_cash_balance()
        inventory_value = calculate_inventory_value()
        supplier_debts = calculate_supplier_debts()
        shipping_due = calculate_shipping_due()
        expenses_total = calculate_total_expenses()
        return jsonify(
            {
                "dashboard_mode": "beauty_center",
                "period_type": period_type,
                "period_label": get_period_label(period_type, custom_date_from, custom_date_to),
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "cash_balance": int(cash_balance),
                "sales": int(bs["revenue"]),
                "cash_sales": int(bs["paid"]),
                "credit_sales": int(bs["receivable"]),
                "period_profit": int(bs["profit"]),
                "delivered_paid_sales": int(bs["revenue"]),
                "inventory": int(inventory_value),
                "debts": int(supplier_debts),
                "shipping": int(shipping_due),
                "expenses": int(expenses_total),
                "expenses_period": int(bs["expenses"]),
                "agent_commissions": 0,
            }
        )

    # ===============================
    # حساب القيم المحاسبية الصحيحة للفترة الزمنية
    # استخدام الدوال المحاسبية لضمان فصل المفاهيم
    # ===============================
    
    from sqlalchemy import and_
    
    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]

    # إجمالي المبيعات/التحصيل/الذمم للفترة
    # تصحيح محاسبي: دعم الدفع الجزئي + استبعاد (راجع/مرتجع/ملغي)
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
        Invoice.payment_status != "مرتجع",
    ).all()

    total_sales = sum(int(inv.total or 0) for inv in period_invoices)
    cash_sales = sum(_effective_paid_amount(inv) for inv in period_invoices)
    credit_sales = sum(
        max(int(inv.total or 0) - _effective_paid_amount(inv), 0)
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
    
    # صافي الربح للفترة — مصدر وحيد للمنطق (يدمج تحصيلاً جزئياً، COGS متناسباً، مصاريف expense_date)
    period_profit = _net_profit_for_range(date_from, date_to)
    expenses_period = _expenses_sum_for_range(date_from, date_to)

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
    agent_orders = db.session.query(
        Invoice.id,
        Invoice.total,
        Invoice.delivery_agent_id,
        Invoice.status,
    ).filter(
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
    if _is_beauty_center_session():
        from models.beauty_appointment import BeautyAppointment

        total = BeautyAppointment.query.count()
        pending = BeautyAppointment.query.filter_by(status="pending").count()
        done = BeautyAppointment.query.filter_by(status="done").count()
        cancelled = BeautyAppointment.query.filter_by(status="cancelled").count()
        return jsonify(
            {
                "all": total,
                "ordered": pending,
                "shipping": 0,
                "delivered": done,
                "paid": done,
                "returned": cancelled,
                "dashboard_mode": "beauty_center",
            }
        )

    # حساب المرتجع والملغي معاً
    returned_count = db.session.query(func.count(Invoice.id)).filter(
        or_(
            Invoice.status == "راجع",
            Invoice.status == "ملغي",
            Invoice.payment_status == "مرتجع"
        )
    ).scalar() or 0
    
    return jsonify({
        "all": db.session.query(func.count(Invoice.id)).scalar() or 0,
        "ordered": db.session.query(func.count(Invoice.id)).filter(Invoice.status == "تم الطلب").scalar() or 0,
        "shipping": db.session.query(func.count(Invoice.id)).filter(Invoice.status == "جاري الشحن").scalar() or 0,
        "delivered": db.session.query(func.count(Invoice.id)).filter(Invoice.status == "تم التوصيل").scalar() or 0,
        "paid": db.session.query(func.count(Invoice.id)).filter(Invoice.status == "مسدد").scalar() or 0,
        "returned": returned_count
    })

# =================================================
# TODAY PROFIT
# مبيعات اليوم - كلفة الشراء
# =================================================
@index_bp.route("/api/index/today-profit")
def index_today_profit():
    """
    صافي ربح اليوم التقويمي — يتوافق مع بطاقة «ربح اليوم» في لوحة المدير:
    يُحسب عند إنشاء الطلب «تم الطلب»، ولا يُعاد حسابه عند التحصيل.
    """
    today = business_today()
    if _is_beauty_center_session():
        from utils.beauty_accounting import beauty_net_profit_calendar_day

        return jsonify(
            {
                "profit": int(beauty_net_profit_calendar_day(today)),
                "dashboard_mode": "beauty_center",
            }
        )
    try:
        return jsonify({"profit": int(net_profit_for_order_calendar_day(today))})
    except Exception:
        current_app.logger.exception("today-profit failed; falling back to paid creation-date profit")
        return jsonify({"profit": int(_net_profit_for_range(today, today))})

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
        orders = db.session.query(
            Invoice.id,
            Invoice.total,
            Invoice.status,
            Customer.phone,
            Customer.name.label("customer"),
        ).join(Customer).filter(
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
            
            orders = db.session.query(
                Invoice.id,
                Invoice.total,
                Invoice.status,
                Customer.phone,
                Customer.name.label("customer"),
            ).join(Customer).filter(
                or_(*phone_filters)
            ).order_by(
                Invoice.id.desc()
            ).limit(100).all()
        else:
            # إذا لم يكن هناك أرقام (مثل "طلب")، لا تبحث في شيء
            # البحث يبقى في صفحة البحث ولا ينتقل لبحث آخر
            orders = []

    if not orders:
        orders = db.session.query(
            Invoice.id,
            Invoice.total,
            Invoice.status,
            Customer.phone,
            Customer.name.label("customer"),
        ).join(Customer).filter(
            or_(
                Invoice.barcode == q,
                Invoice.shipping_barcode == q,
            )
        ).order_by(
            Invoice.id.desc()
        ).limit(100).all()

    return jsonify([
        {
            "id": o.id,
            "phone": o.phone or "",
            "customer": o.customer or "",
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
        # التوصيل = تحصيل في مسار لوحة التحكم (مثل كشف الشحن «واصل»)
        from utils.delivery_expense_service import sync_delivery_expense_for_invoice

        prev_eff = _effective_paid_amount(invoice)
        invoice.status = "تم التوصيل"
        invoice.payment_status = "مسدد"
        invoice.paid_amount = int(invoice.total or 0)
        append_payment_ledger_delta(invoice.id, _effective_paid_amount(invoice) - prev_eff)
        sync_delivery_expense_for_invoice(invoice)

    elif action == "paid":
        from utils.delivery_expense_service import sync_delivery_expense_for_invoice

        prev_eff = _effective_paid_amount(invoice)
        invoice.status = "مسدد"
        invoice.payment_status = "مسدد"
        invoice.paid_amount = int(invoice.total or 0)
        invoice.shipping_status = "تم التسديد"
        append_payment_ledger_delta(invoice.id, _effective_paid_amount(invoice) - prev_eff)
        sync_delivery_expense_for_invoice(invoice)

    elif action == "returned":
        from utils.delivery_expense_service import sync_delivery_expense_for_invoice

        scanned_barcode = (data.get("barcode") or "").strip()
        if not scanned_barcode:
            return jsonify({"success": False, "error": "يجب مسح باركود الطلب لتأكيد الراجع"}), 400
        prev_eff = _effective_paid_amount(invoice)
        try:
            already_returned, message = process_order_return(invoice, scanned_barcode)
        except OrderLifecycleError as exc:
            return jsonify({"success": False, "error": exc.message}), exc.status_code
        if not already_returned:
            append_payment_ledger_delta(invoice.id, _effective_paid_amount(invoice) - prev_eff)
            sync_delivery_expense_for_invoice(invoice)

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
    executed_ids = []
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
                from utils.delivery_expense_service import sync_delivery_expense_for_invoice

                prev_eff = _effective_paid_amount(invoice)
                invoice.status = "تم التوصيل"
                invoice.payment_status = "مسدد"
                invoice.paid_amount = int(invoice.total or 0)
                append_payment_ledger_delta(invoice.id, _effective_paid_amount(invoice) - prev_eff)
                sync_delivery_expense_for_invoice(invoice)
            elif action == "paid":
                # ==========================
                # تصحيح محاسبي: الطلب الواصل يتم تسديده بشكل صحيح
                # ==========================
                from utils.delivery_expense_service import sync_delivery_expense_for_invoice

                prev_eff = _effective_paid_amount(invoice)
                invoice.status = "مسدد"
                invoice.payment_status = "مسدد"  # تأكيد حالة الدفع
                invoice.paid_amount = int(invoice.total or 0)
                invoice.shipping_status = "تم التسديد"
                append_payment_ledger_delta(invoice.id, _effective_paid_amount(invoice) - prev_eff)
                sync_delivery_expense_for_invoice(invoice)
            elif action == "returned":
                from utils.delivery_expense_service import sync_delivery_expense_for_invoice

                scanned_barcode = (order_data.get("barcode") or "").strip()
                if not scanned_barcode:
                    errors.append(f"طلب {order_id}: يجب مسح باركود الطلب لتأكيد الراجع")
                    continue
                prev_eff = _effective_paid_amount(invoice)
                already_returned, _message = process_order_return(invoice, scanned_barcode)
                if not already_returned:
                    append_payment_ledger_delta(invoice.id, _effective_paid_amount(invoice) - prev_eff)
                    sync_delivery_expense_for_invoice(invoice)
            else:
                errors.append(f"طلب {order_id}: إجراء غير صحيح")
                continue
            
            executed += 1
            executed_ids.append(int(order_id))
        except Exception as e:
            errors.append(f"طلب {order_id}: {str(e)}")
            continue
    
    db.session.commit()
    
    return jsonify({
        "success": executed > 0 and not errors,
        "partial_success": executed > 0 and bool(errors),
        "executed": executed,
        "executed_ids": executed_ids,
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

    if _is_beauty_center_session():
        from models.beauty_appointment import BeautyAppointment
        from utils.beauty_accounting import beauty_summary

        for i in range(6, -1, -1):
            d = date.today() - timedelta(days=i)
            labels.append(d.strftime("%m/%d"))
            bs = beauty_summary(d, d)
            sales.append(int(bs["revenue"]))
            profit.append(int(bs["profit"]))
        status_data = {
            "ordered": BeautyAppointment.query.filter_by(status="pending").count(),
            "shipping": 0,
            "delivered": 0,
            "paid": BeautyAppointment.query.filter_by(status="done").count(),
            "returned": BeautyAppointment.query.filter_by(status="cancelled").count(),
        }
        return jsonify(
            {
                "labels": labels,
                "sales": sales,
                "profit": profit,
                "status": status_data,
                "dashboard_mode": "beauty_center",
            }
        )

    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]

    today = business_today()
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime("%m/%d"))

        day_invoices = db.session.query(
            Invoice.id,
            Invoice.status,
            Invoice.payment_status,
            Invoice.total,
            Invoice.paid_amount,
            Invoice.created_at,
        ).filter(
            func.date(Invoice.created_at) == d,
            Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
            Invoice.payment_status != "مرتجع",
        ).all()

        # مبيعات الطلبات المنشأة بذلك اليوم، حتى تظهر فور «تم الطلب».
        day_sales = sum(int(inv.total or 0) for inv in day_invoices)
        sales.append(int(day_sales))
        # نفس منطق بطاقة «ربح اليوم»: ربح الطلب عند إنشائه، بلا إعادة احتساب عند التحصيل.
        profit.append(int(net_profit_for_order_calendar_day(d)))

    status_data = {
        "ordered": db.session.query(func.count(Invoice.id)).filter(Invoice.status == "تم الطلب").scalar() or 0,
        "shipping": db.session.query(func.count(Invoice.id)).filter(Invoice.status == "جاري الشحن").scalar() or 0,
        "delivered": db.session.query(func.count(Invoice.id)).filter(Invoice.status == "تم التوصيل").scalar() or 0,
        "paid": db.session.query(func.count(Invoice.id)).filter(Invoice.status == "مسدد").scalar() or 0,
        "returned": db.session.query(func.count(Invoice.id)).filter(
            or_(
                Invoice.status == "راجع",
                Invoice.status == "ملغي",
                Invoice.payment_status == "مرتجع"
            )
        ).scalar() or 0
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
        from utils.financial_watchdog import get_watchdog_ephemeral_alerts, persist_watchdog_alerts

        persist_watchdog_alerts()
        wd = get_watchdog_ephemeral_alerts()
        if wd:
            alerts.extend(wd)
    except Exception:
        db.session.rollback()
        pass
    db.session.rollback()
    try:
        # تنبيهات المخزون
        low_stock = db.session.query(func.count(Product.id)).filter(Product.quantity <= 2).scalar() or 0
        if low_stock:
            alerts.append({
                "type": "warning",
                "icon": "⚠️",
                "message": f"يوجد {low_stock} منتج مخزونها قليل",
                "action": "/inventory"
            })

        # تنبيهات الربح والمصاريف
        # تستخدم نفس منطق صفحة الحسابات حتى لا يظهر تحذير خسارة عند وجود ربح محاسبي فعلي.
        from utils.accounting_calculations import (
            calculate_total_revenue,
            calculate_total_cogs,
            calculate_total_expenses,
            calculate_net_profit,
        )
        booked_sales = calculate_total_revenue()
        total_cost = calculate_total_cogs()
        total_expenses = calculate_total_expenses()
        gross_profit = booked_sales - total_cost
        net_profit = calculate_net_profit()
        expense_ratio = (total_expenses / gross_profit * 100) if gross_profit > 0 else 0
        profit_ratio = (net_profit / booked_sales * 100) if booked_sales > 0 else 0

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
        elif profit_ratio < 20 and booked_sales > 0:
            alerts.append({
                "type": "info",
                "icon": "💡",
                "message": f"الربح الصافي ({net_profit:,} د.ع) يمثل {profit_ratio:.1f}% فقط من المبيعات ({booked_sales:,} د.ع) - ربح قليل",
                "action": "/accounts"
            })

        pending_orders = db.session.query(func.count(Invoice.id)).filter(Invoice.status == "تم الطلب").scalar() or 0
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

        from utils.agent_report_helpers import list_pending_agent_reports, get_report_progress, get_agent_name_for_report
        for report in list_pending_agent_reports():
            progress = get_report_progress(report)
            if not progress["ready_for_execution"]:
                continue
            agent_name = get_agent_name_for_report(report)
            alerts.append({
                "type": "warning",
                "icon": "🚚",
                "message": f"كشف المندوب {report.report_number} ({agent_name}) جاهز للتنفيذ — {progress['total']} طلب",
                "action": "/agents/pending-execution",
                "decisions": [
                    {"label": "فتح الطابور", "href": "/agents/pending-execution", "kind": "navigate"},
                    {"label": "عرض الكشف", "href": f"/delivery/report/{report.id}", "kind": "navigate"},
                ],
            })
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
    return jsonify(alerts)

# =================================================
# CHECK FOR NEW ORDERS (Real-time notifications)
# =================================================
@index_bp.route("/api/index/new-orders")
def check_new_orders():
    # الحصول على آخر طلب تم إنشاؤه
    last_order = db.session.query(Invoice.id).order_by(
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
    
    new_orders = db.session.query(
        Invoice.id,
        Invoice.customer_name,
        Invoice.total,
        Invoice.status,
        Invoice.created_at,
    ).filter(
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
# AGENT REPORTS PENDING EXECUTION
# =================================================
@index_bp.route("/api/index/agent-reports-pending")
def agent_reports_pending():
    from datetime import datetime
    from utils.agent_report_helpers import get_pending_agent_reports_summary

    summary = get_pending_agent_reports_summary()
    ready_reports = [r for r in summary["reports"] if r["ready_for_execution"]]
    return jsonify({
        **summary,
        "ready_reports": ready_reports,
        "ready_report_ids": [r["id"] for r in ready_reports],
        "timestamp": datetime.utcnow().isoformat(),
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
    orders = db.session.query(
        Invoice.id,
        Invoice.customer_name,
        Invoice.total,
        Invoice.created_at,
        Invoice.status,
        Invoice.delivery_agent_id,
        Customer.name.label("customer"),
        DeliveryAgent.name.label("agent"),
    ).outerjoin(Customer, Invoice.customer_id == Customer.id).outerjoin(
        DeliveryAgent, Invoice.delivery_agent_id == DeliveryAgent.id
    ).filter(
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
                "customer": o.customer or o.customer_name or "—",
                "agent": o.agent or "—",
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
    orders = db.session.query(
        Invoice.id,
        Invoice.customer_name,
        Invoice.total,
        Invoice.created_at,
        Invoice.status,
        Customer.name.label("customer"),
    ).outerjoin(Customer, Invoice.customer_id == Customer.id).filter(
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
                "customer": o.customer or o.customer_name or "—",
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

    from utils.treasury_helpers import resolve_treasury_account_id
    from utils.treasury_calculations import assert_sufficient_balance, InsufficientTreasuryBalance
    from utils.treasury_schema_guard import ensure_treasury_schema

    ensure_treasury_schema()
    treasury_account_id = resolve_treasury_account_id(data.get("treasury_account_id"))
    try:
        assert_sufficient_balance(treasury_account_id, amount)
    except InsufficientTreasuryBalance as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    
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
            note=f"مصروف: {title} ({category})" + (f" - {note}" if note else ""),
            treasury_account_id=treasury_account_id,
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
