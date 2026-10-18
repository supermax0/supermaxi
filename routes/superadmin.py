import os
import shutil
from datetime import datetime, timedelta, date
import json
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, g, current_app, get_flashed_messages
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db
from extensions_tenant import init_tenant_db, get_tenant_engine, clear_tenant_engine
from models.core.super_admin import SuperAdmin
from models.core.payment_request import PaymentRequest
from models.core.tenant import Tenant
from models.core.subscription_plan import SubscriptionPlan
from models.invoice_template import InvoiceTemplate, TenantTemplateSettings
from models.user import User
from utils.tenant_registration import (
    delete_tenant_registration,
    discovery_source_label,
    get_tenant_registration,
    registration_file_path,
    save_tenant_registration,
)
from utils.tenant_feature_flags import (
    TENANT_FEATURE_GROUPS,
    TENANT_FEATURE_LABELS,
    ensure_tenant_feature_overrides_column,
    feature_overrides_json,
    normalize_feature_overrides,
)

superadmin_bp = Blueprint("superadmin", __name__, url_prefix="/superadmin")

BUSINESS_TYPES = {
    "general": "شركة عامة",
    "starter_business": "إدارة أعمال مبسّطة",
    "beauty_center": "مركز تجميل",
    "wholesale": "تجارة الجملة",
    "food_wholesale_retail": "مواد غذائية – جملة ومفرد",
    "hr_management": "إدارة الموارد البشرية",
    "clinics": "عيادات Finora",
}


def _registration_json(tenant, registration: dict, admin_name: str = "—", admin_username: str = "—") -> dict:
    """تنسيق بيانات التسجيل للواجهة."""
    plan_key = registration.get("plan_key") or "basic"
    plan_name = registration.get("plan_name") or "—"
    billing = registration.get("billing")
    billing_label = {"monthly": "شهري", "yearly": "سنوي"}.get(billing, billing) if billing else "—"
    source_labels = {
        "signup": "تسجيل ذاتي",
        "superadmin_create": "إنشاء من المدير",
        "payment_approval": "موافقة دفع",
        "database_sync": "مزامنة من القاعدة",
        "core_only": "بيانات أساسية",
    }
    return {
        "company_name": registration.get("company_name") or tenant.name,
        "contact_name": registration.get("contact_name") or admin_name,
        "email": registration.get("email") or "—",
        "phone": registration.get("phone") or "—",
        "activation_status": registration.get("activation_status") or ("active" if tenant.is_active else "disabled"),
        "activation_code": registration.get("activation_code") or "—",
        "discovery_source": registration.get("discovery_source") or "",
        "discovery_source_other": registration.get("discovery_source_other") or "",
        "discovery_source_label": discovery_source_label(
            registration.get("discovery_source"), registration.get("discovery_source_other")
        ),
        "username": registration.get("username") or admin_username,
        # Passwords are never stored or revealed (hash only). Lost credentials → reset, not reveal.
        "plan_key": plan_key,
        "plan_name": plan_name,
        "billing": billing_label,
        "business_type": registration.get("business_type") or getattr(tenant, "business_type", "general"),
        "registered_at": registration.get("registered_at")
        or (tenant.created_at.strftime("%Y-%m-%d %H:%M") if tenant.created_at else "—"),
        "updated_at": registration.get("updated_at") or "—",
        "source": source_labels.get(registration.get("source"), registration.get("source") or "—"),
        "profile_file": registration_file_path(tenant.slug),
    }


def _clean_business_type(value):
    value = (value or "general").strip()
    return value if value in BUSINESS_TYPES else "general"


def _try_send_welcome_email(
    *,
    email: str,
    contact_name: str,
    company_name: str,
    slug: str,
    username: str,
    plan_name: str | None = None,
) -> None:
    """إرسال بيانات الحساب للعميل بدون كلمة المرور (لا يوقف العملية عند الفشل)."""
    to_email = (email or "").strip()
    if not to_email:
        return
    try:
        from utils.email_helper import send_welcome_account_email

        if not send_welcome_account_email(
            to_email=to_email,
            contact_name=contact_name,
            company_name=company_name,
            slug=slug,
            username=username,
            plan_name=plan_name,
        ):
            current_app.logger.warning("welcome email not sent for tenant %s", slug)
    except Exception:
        current_app.logger.exception("welcome email failed for tenant %s", slug)


def _ensure_tenant_business_type_column(engine):
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "tenant" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("tenant")}
    missing_business_type = "business_type" not in columns
    missing_feature_overrides = "feature_overrides_json" not in columns
    if missing_business_type or missing_feature_overrides:
        with engine.begin() as conn:
            if missing_business_type:
                conn.execute(text("ALTER TABLE tenant ADD COLUMN business_type VARCHAR(50) DEFAULT 'general'"))
            if missing_feature_overrides:
                conn.execute(text("ALTER TABLE tenant ADD COLUMN feature_overrides_json TEXT"))


def _read_tenant_admin_snapshot(slug):
    """قراءة الحقول المطلوبة فقط للتوافق مع قواعد الشركات القديمة."""
    from sqlalchemy import inspect, text

    engine = get_tenant_engine(slug)
    _ensure_tenant_business_type_column(engine)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    tenant_data = {}
    admin_data = {}

    with engine.connect() as connection:
        if "tenant" in table_names:
            tenant_columns = {column["name"] for column in inspector.get_columns("tenant")}
            wanted_tenant_columns = [
                column for column in (
                    "name", "contact_name", "contact_email", "contact_phone", "business_type",
                    "feature_overrides_json", "plan_key", "plan_name", "created_at", "subscription_end",
                ) if column in tenant_columns
            ]
            if wanted_tenant_columns:
                selected = ", ".join(f'"{column}"' for column in wanted_tenant_columns)
                row = connection.execute(text(f"SELECT {selected} FROM tenant LIMIT 1")).mappings().first()
                tenant_data = dict(row) if row else {}

        if "employee" in table_names:
            employee_columns = {column["name"] for column in inspector.get_columns("employee")}
            wanted_employee_columns = [column for column in ("name", "username") if column in employee_columns]
            if wanted_employee_columns:
                selected = ", ".join(f'"{column}"' for column in wanted_employee_columns)
                if "role" in employee_columns:
                    where_clause = "WHERE role = :admin_role"
                    params = {"admin_role": "admin"}
                elif "username" in employee_columns:
                    where_clause = "WHERE username = :admin_username"
                    params = {"admin_username": "admin"}
                else:
                    where_clause = ""
                    params = {}
                row = connection.execute(
                    text(f"SELECT {selected} FROM employee {where_clause} LIMIT 1"), params
                ).mappings().first()
                if not row and "role" in employee_columns and "username" in employee_columns:
                    row = connection.execute(
                        text(f"SELECT {selected} FROM employee WHERE username = :admin_username LIMIT 1"),
                        {"admin_username": "admin"},
                    ).mappings().first()
                admin_data = dict(row) if row else {}

    return tenant_data, admin_data


def _read_branch_mode_snapshot(engine) -> dict:
    """Read branch mode without requiring the tenant ORM schema to be current."""
    from sqlalchemy import inspect, text
    from utils.branch_mode import (
        BRANCH_SCOPE_MIGRATION_FLAG,
        INDEPENDENT_BRANCHES_FLAG,
        mode_enabled_from_flags,
    )

    flags = {}
    inspector = inspect(engine)
    if "system_settings" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("system_settings")}
        if "ui_flags" in columns:
            with engine.connect() as connection:
                raw = connection.execute(
                    text("SELECT ui_flags FROM system_settings ORDER BY id LIMIT 1")
                ).scalar()
            try:
                flags = json.loads(raw or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                flags = {}
    migration_completed = bool(flags.get(BRANCH_SCOPE_MIGRATION_FLAG, False))
    return {
        "enabled": mode_enabled_from_flags(flags),
        "migration_completed": migration_completed,
        "backup_path": flags.get("branch_pre_migration_backup"),
        "backup_at": flags.get("branch_pre_migration_backup_at"),
    }

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
    if not is_superadmin():
        return dict(pending_count=0, leads_dup_count=0)
    try:
        # Always read from Core DB; clear any aborted tenant txn first.
        g.tenant = None
        pending_count = PaymentRequest.query.filter_by(status="pending").count()
        leads_dup_count = 0
        try:
            from models.core.leads.models import LeadDuplicateCandidate
            leads_dup_count = LeadDuplicateCandidate.query.filter_by(status="pending").count()
        except Exception:
            db.session.rollback()
        return dict(pending_count=pending_count, leads_dup_count=leads_dup_count)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return dict(pending_count=0, leads_dup_count=0)


def _ensure_invoice_owner_user(owner_id):
    """
    جداول قوالب الفواتير مرتبطة بـ users.id.
    ننشئ مستخدم توافقياً للشركة عند الحاجة حتى لا يفشل FK.
    """
    if not owner_id:
        return None
    existing = db.session.get(User, owner_id)
    if existing:
        return owner_id

    placeholder = User(
        id=owner_id,
        username=f"invoice_owner_{owner_id}",
        email=f"invoice_owner_{owner_id}@local.invalid",
        password_hash=generate_password_hash(f"invoice-owner-{owner_id}"),
        full_name=f"Tenant Owner {owner_id}",
        is_active=True,
        is_admin=False,
    )
    db.session.add(placeholder)
    db.session.flush()
    return owner_id

@superadmin_bp.route("/login", methods=["GET", "POST"])
def login():
    if is_superadmin():
        return redirect(url_for("superadmin.dashboard"))
        
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        admin = SuperAdmin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            session.permanent = True  # استخدام PERMANENT_SESSION_LIFETIME (مثلاً 7 أيام) بدل انتهاء الجلسة سريعاً
            session["is_superadmin"] = True
            session["superadmin_id"] = admin.id
            # تجاهل رسائل flash القادمة من جلسات الشركات المشتركة على نفس الدومين
            get_flashed_messages()
            return redirect(url_for("superadmin.dashboard"))
            
        flash("بيانات الدخول غير صحيحة", "sa_login")

    # الجلسة مشتركة مع شركات .finora.company — أبقِ فقط رسائل دخول السوبر أدمن
    login_msgs = [
        msg
        for cat, msg in get_flashed_messages(with_categories=True)
        if cat == "sa_login"
    ]
    for msg in login_msgs:
        flash(msg, "sa_login")

    return render_template("superadmin_login.html")

@superadmin_bp.route("/logout")
def logout():
    session.pop("is_superadmin", None)
    session.pop("superadmin_id", None)
    return redirect(url_for("superadmin.login"))

@superadmin_bp.route("/")
def dashboard():
    # Core DB only — reset tenant bind and clear any aborted SQL txn.
    g.tenant = None
    try:
        db.session.rollback()
    except Exception:
        pass

    pending_count = PaymentRequest.query.filter_by(status="pending").count()
    active_tenants = Tenant.query.filter_by(is_active=True).count()
    total_tenants = Tenant.query.count()
    approved_count = PaymentRequest.query.filter_by(status="approved").count()
    total_revenue_query = db.session.query(db.func.sum(PaymentRequest.amount)).filter_by(status="approved").scalar()
    total_revenue = total_revenue_query if total_revenue_query else 0
    rejected_count = PaymentRequest.query.filter_by(status="rejected").count()

    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    requests_this_month = PaymentRequest.query.filter(PaymentRequest.created_at >= month_start).count()
    new_tenants_this_month = Tenant.query.filter(Tenant.created_at >= month_start).count()
    revenue_this_month_query = (
        db.session.query(db.func.sum(PaymentRequest.amount))
        .filter(
            PaymentRequest.status == "approved",
            PaymentRequest.created_at >= month_start,
        )
        .scalar()
    )
    revenue_this_month = revenue_this_month_query or 0
    total_requests = approved_count + pending_count + rejected_count
    approval_rate = round((approved_count / total_requests) * 100) if total_requests else 0
    activation_rate = round((active_tenants / total_tenants) * 100) if total_tenants else 0
    expiring_soon = Tenant.query.filter(
        Tenant.is_active.is_(True),
        Tenant.subscription_end_date.isnot(None),
        Tenant.subscription_end_date >= now,
        Tenant.subscription_end_date <= now + timedelta(days=7),
    ).count()

    # زيارات صفحة الهبوط (إجمالي + زيارات اليوم من Core DB)
    landing_visits_total = 0
    landing_visits_today = 0
    landing_tracking_ok = False
    landing_visit_analytics = {
        "periods": {
            "today": {"value": 0, "previous": 0, "change": 0},
            "7d": {"value": 0, "previous": 0, "change": 0},
            "30d": {"value": 0, "previous": 0, "change": 0},
        },
        "daily": [],
        "average_7d": 0,
        "best_day": None,
    }
    try:
        from models.core.landing_visit import LandingVisit
        old_tenant = getattr(g, "tenant", None)
        g.tenant = None
        try:
            row = LandingVisit.query.get(LandingVisit.RECORD_ID)
            landing_visits_total = (row.total_count or 0) if row else 0
            landing_visits_today = LandingVisit.get_today_count()
            try:
                landing_data = json.loads((row.daily_json if row else None) or "{}")
            except (TypeError, ValueError):
                landing_data = {}
            raw_daily = landing_data.get("daily", {})
            daily_counts = {}
            if isinstance(raw_daily, dict):
                for day_key, count in raw_daily.items():
                    try:
                        daily_counts[str(day_key)] = max(0, int(count))
                    except (TypeError, ValueError):
                        continue

            today_date = date.today()

            def _visit_series(days, offset=0):
                start = today_date - timedelta(days=days - 1 + offset)
                end = today_date - timedelta(days=offset)
                series = []
                current = start
                while current <= end:
                    day_iso = current.isoformat()
                    series.append({"date": day_iso, "value": daily_counts.get(day_iso, 0)})
                    current += timedelta(days=1)
                return series

            def _period_summary(current_series, previous_series):
                current_total = sum(item["value"] for item in current_series)
                previous_total = sum(item["value"] for item in previous_series)
                if previous_total:
                    change = round(((current_total - previous_total) / previous_total) * 100)
                else:
                    change = None if current_total else 0
                return {"value": current_total, "previous": previous_total, "change": change}

            daily_30 = _visit_series(30)
            daily_7 = daily_30[-7:]
            previous_7 = _visit_series(7, offset=7)
            previous_30 = _visit_series(30, offset=30)
            today_series = daily_30[-1:]
            yesterday_series = _visit_series(1, offset=1)
            best_day = max(daily_30, key=lambda item: item["value"], default=None)
            landing_visit_analytics = {
                "periods": {
                    "today": _period_summary(today_series, yesterday_series),
                    "7d": _period_summary(daily_7, previous_7),
                    "30d": _period_summary(daily_30, previous_30),
                },
                "daily": daily_30,
                "average_7d": round(sum(item["value"] for item in daily_7) / 7),
                "best_day": best_day,
            }
            landing_tracking_ok = True
        finally:
            g.tenant = old_tenant
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    recent_requests = PaymentRequest.query.order_by(PaymentRequest.created_at.desc()).limit(5).all()
    
    return render_template("admin_dashboard.html", 
        pending_count=pending_count, 
        active_tenants=active_tenants, 
        total_tenants=total_tenants,
        approved_count=approved_count,
        total_revenue=total_revenue,
        revenue_this_month=revenue_this_month,
        rejected_count=rejected_count,
        requests_this_month=requests_this_month,
        new_tenants_this_month=new_tenants_this_month,
        approval_rate=approval_rate,
        activation_rate=activation_rate,
        expiring_soon=expiring_soon,
        recent_requests=recent_requests,
        landing_visits=landing_visits_total,
        landing_visits_today=landing_visits_today,
        landing_tracking_ok=landing_tracking_ok,
        landing_visit_analytics=landing_visit_analytics,
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
        
    from services.tenant_provisioning import ProvisioningError, provision_tenant

    try:
        result = provision_tenant(
            name=payment_req.tenant_name.upper(),
            slug=payment_req.tenant_name,
            business_type="general",
            source="payment_approval",
            contact_name=payment_req.owner_name,
            contact_email=payment_req.email,
            contact_phone=payment_req.phone,
            subscription_days=30,
        )
    except ProvisioningError:
        db.session.rollback()
        flash("حدث خطأ أثناء تهيئة قاعدة بيانات الشركة، وتم التراجع عن الإنشاء بالكامل.")
        return redirect(url_for("superadmin.requests_list"))
    payment_req = PaymentRequest.query.get(req_id)
    payment_req.status = "approved"
    db.session.commit()
    _try_send_welcome_email(
        email=payment_req.email,
        contact_name=payment_req.owner_name,
        company_name=payment_req.tenant_name.upper(),
        slug=result.slug,
        username=result.username,
        plan_name=_plan_name("basic"),
    )
    return _one_time_credentials_response(result, company_name=payment_req.tenant_name.upper(),
                                          back_url=url_for("superadmin.requests_list"))

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
    pending_activation_slugs = {
        tenant.slug
        for tenant in tenants
        if not tenant.is_active
        and get_tenant_registration(tenant.slug, core_tenant=tenant, sync_if_missing=False).get("activation_status")
        == "pending_whatsapp"
    }
    from services import feature_service

    try:
        ai_tutor_states = {
            row["slug"]: row for row in feature_service.list_overview(feature_service.AI_TUTOR)
        }
    except Exception:
        current_app.logger.exception("Failed to load AI Tutor feature states")
        ai_tutor_states = {}
    return render_template(
        "tenant_list.html",
        tenants=tenants,
        pending_activation_slugs=pending_activation_slugs,
        ai_tutor_states=ai_tutor_states,
        ai_tutor_global_enabled=feature_service.is_globally_enabled(feature_service.AI_TUTOR),
    )


@superadmin_bp.route("/tenants/search")
def tenants_search():
    """بحث خفيف في الشركات من مركز الأوامر دون فتح قواعد بيانات الشركات."""
    from flask import jsonify

    search_term = (request.args.get("q") or "").strip()
    try:
        limit = min(max(int(request.args.get("limit", 8)), 1), 20)
    except (TypeError, ValueError):
        limit = 8

    query = Tenant.query
    if search_term:
        pattern = f"%{search_term}%"
        query = query.filter(db.or_(Tenant.name.ilike(pattern), Tenant.slug.ilike(pattern)))

    now = datetime.utcnow()
    tenants = query.order_by(Tenant.is_active.desc(), Tenant.name.asc()).limit(limit).all()
    companies = []
    for tenant in tenants:
        registration = get_tenant_registration(tenant.slug, core_tenant=tenant, sync_if_missing=False)
        if not tenant.is_active:
            status_key, status_label = "disabled", "معطلة"
        elif not tenant.subscription_end_date or tenant.subscription_end_date < now:
            status_key, status_label = "expired", "منتهية"
        else:
            status_key, status_label = "active", "نشطة"

        companies.append({
            "name": tenant.name,
            "slug": tenant.slug,
            "business_type": tenant.business_type or "general",
            "business_type_label": BUSINESS_TYPES.get(tenant.business_type or "general", "شركة عامة"),
            "plan_name": registration.get("plan_name") or "—",
            "subscription_end_date": tenant.subscription_end_date.strftime("%Y-%m-%d") if tenant.subscription_end_date else "—",
            "status_key": status_key,
            "status_label": status_label,
        })

    return jsonify({"ok": True, "companies": companies, "count": len(companies)})


@superadmin_bp.route("/tenants/details/<slug>")
def tenant_details(slug):
    from flask import jsonify
    try:
        slug_clean = (slug or "").strip().lower()
        tenant = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
        if not tenant:
            return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404
        tenant_row, admin_row = _read_tenant_admin_snapshot(tenant.slug)
        admin_username = admin_row.get("username") or "—"
        admin_name = admin_row.get("name") or "—"
        plan_key = tenant_row.get("plan_key") or "basic"
        plan_name = tenant_row.get("plan_name") or "الخطة الأساسية"
        business_type = getattr(tenant, "business_type", None) or tenant_row.get("business_type") or "general"
        feature_overrides = normalize_feature_overrides(
            tenant_row.get("feature_overrides_json")
        )
        branch_mode = _read_branch_mode_snapshot(get_tenant_engine(tenant.slug))

        # رابط تسجيل الدخول الخاص بالشركة
        try:
            base_url = request.host_url.rstrip("/")
        except Exception:
            base_url = ""
        login_url = f"{base_url}/login/{tenant.slug}"

        registration = get_tenant_registration(tenant.slug, core_tenant=tenant, sync_if_missing=False)
        registration.setdefault("contact_name", tenant_row.get("contact_name") or admin_name)
        registration.setdefault("email", tenant_row.get("contact_email"))
        registration.setdefault("phone", tenant_row.get("contact_phone"))
        registration.setdefault("username", admin_username)
        registration.setdefault("plan_key", plan_key)
        registration.setdefault("plan_name", plan_name)
        registration.setdefault("business_type", business_type)

        return jsonify({
            "ok": True,
            "name": tenant.name,
            "slug": tenant.slug,
            "db_path": tenant.db_path,
            "is_active": tenant.is_active,
            "business_type": business_type,
            "business_type_label": BUSINESS_TYPES.get(business_type, "شركة عامة"),
            "created_at": tenant.created_at.strftime("%Y-%m-%d %H:%M") if tenant.created_at else "—",
            "subscription_end_date": tenant.subscription_end_date.strftime("%Y-%m-%d") if tenant.subscription_end_date else "—",
            "admin_username": admin_username,
            "admin_name": admin_name,
            "admin_password": None,
            "plan_key": plan_key,
            "plan_name": plan_name,
            "feature_overrides": feature_overrides,
            "branch_mode": branch_mode,
            "feature_groups": [
                {
                    "key": group["key"],
                    "label": group["label"],
                    "features": [{"key": key, "label": label} for key, label in group["features"]],
                }
                for group in TENANT_FEATURE_GROUPS
            ],
            "feature_labels": [{"key": key, "label": label} for key, label in TENANT_FEATURE_LABELS.items()],
            "login_url": login_url,
            "registration": _registration_json(
                tenant, registration, admin_name=admin_name, admin_username=admin_username
            ),
        })
    except Exception as e:
        g.tenant = None
        current_app.logger.exception("tenant_details")
        return jsonify({"ok": False, "error": str(e)}), 500


@superadmin_bp.route("/tenants/registration/<slug>")
def tenant_registration_view(slug):
    """جلب بيانات التسجيل فقط (للنافذة المنبثقة)."""
    from flask import jsonify

    try:
        slug_clean = (slug or "").strip().lower()
        tenant = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
        if not tenant:
            return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404

        tenant_row, admin_row = _read_tenant_admin_snapshot(tenant.slug)
        admin_username = admin_row.get("username") or "—"
        admin_name = admin_row.get("name") or "—"
        registration = get_tenant_registration(tenant.slug, core_tenant=tenant, sync_if_missing=False)
        registration.setdefault("contact_name", tenant_row.get("contact_name") or admin_name)
        registration.setdefault("email", tenant_row.get("contact_email"))
        registration.setdefault("phone", tenant_row.get("contact_phone"))
        registration.setdefault("username", admin_username)
        registration.setdefault("plan_key", tenant_row.get("plan_key") or "basic")
        registration.setdefault("plan_name", tenant_row.get("plan_name") or "الخطة الأساسية")
        registration.setdefault("business_type", tenant_row.get("business_type") or tenant.business_type or "general")

        return jsonify({
            "ok": True,
            "slug": tenant.slug,
            "name": tenant.name,
            "registration": _registration_json(
                tenant, registration, admin_name=admin_name, admin_username=admin_username
            ),
        })
    except Exception as e:
        g.tenant = None
        current_app.logger.exception("tenant_registration_view")
        return jsonify({"ok": False, "error": str(e)}), 500


@superadmin_bp.route("/tenants/reset-password/<slug>", methods=["POST"])
def tenant_reset_password(slug):
    """Password RESET (never reveal). The server generates the password and returns it exactly once."""
    from flask import jsonify

    from services.tenant_provisioning import ProvisioningError, reset_admin_password

    try:
        result = reset_admin_password(slug or "")
    except ProvisioningError as exc:
        status = 404 if "not found" in str(exc) else 400
        error = "الشركة أو حساب المدير غير موجود" if status == 404 else "تعذر إعادة التعيين"
        return jsonify({"ok": False, "error": error}), status
    except Exception:
        current_app.logger.exception("tenant_reset_password failed for %s", slug)
        return jsonify({"ok": False, "error": "تعذر إعادة تعيين كلمة المرور"}), 500
    return _no_store(jsonify({
        "ok": True,
        "message": "تم توليد كلمة مرور جديدة. تُعرض مرة واحدة فقط وسيُطلب تغييرها عند أول دخول.",
        "credentials": result.credentials(),
    }))


@superadmin_bp.route("/tenants/reset-db/<slug>", methods=["POST"])
def tenant_reset_db(slug):
    from flask import jsonify
    from sqlalchemy.orm import sessionmaker

    from services.tenant_provisioning import ADMIN_USERNAME, generate_initial_password

    slug_clean = (slug or "").strip().lower()
    tenant = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
    if not tenant:
        return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404

    try:
        # 1. Clear engine cache to free file locks
        clear_tenant_engine(tenant.slug)

        # 2. Delete the physical .db file (+ WAL/SHM), resolved from the app root — not the process CWD
        from extensions_tenant import get_tenant_db_path

        db_file = get_tenant_db_path(tenant.slug)
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_file + suffix):
                os.remove(db_file + suffix)

        # 3. Re-initialize database schema and defaults
        init_tenant_db(tenant.slug)

        # 4. Admin account with a one-time random password (hash only, must change at first login)
        engine = get_tenant_engine(tenant.slug)
        tenant_session = sessionmaker(bind=engine)()

        from models.employee import Employee
        from models.tenant import Tenant as TenantModel
        from utils.plan_limits import get_plan

        plan_key = "basic"
        plan = get_plan(plan_key)
        password = generate_initial_password()
        try:
            tenant_row = TenantModel(
                name=tenant.name,
                business_type=getattr(tenant, "business_type", None) or "general",
                plan_key=plan_key,
                plan_name=plan["name"],
                monthly_price=plan.get("price_monthly", 0),
                is_active=True,
                subscription_end=tenant.subscription_end_date,
            )
            tenant_session.add(tenant_row)
            tenant_session.flush()
            tenant_session.add(Employee(
                name=tenant.name,
                username=ADMIN_USERNAME,
                password=generate_password_hash(password),
                role="admin",
                salary=0,
                is_active=True,
                tenant_id=tenant_row.id,
                must_change_password=True,
            ))
            tenant_session.commit()
        finally:
            tenant_session.close()

        return _no_store(jsonify({
            "ok": True,
            "message": "تمت إعادة تعيين قاعدة البيانات. كلمة مرور المدير الجديدة تُعرض مرة واحدة فقط.",
            "credentials": {"slug": tenant.slug, "username": ADMIN_USERNAME, "password": password},
        }))
    except Exception:
        current_app.logger.exception("Error resetting database for %s", slug)
        return jsonify({"ok": False, "error": "تعذر إعادة تعيين قاعدة البيانات"}), 500


def _no_store(response):
    """One-time credential responses must never be cached by the browser or a proxy."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _plan_name(plan_key: str) -> str | None:
    try:
        from utils.plan_limits import get_plan

        return get_plan(plan_key)["name"]
    except Exception:
        return None


def _one_time_credentials_response(result, *, company_name: str, back_url: str):
    """Render the provisioning result once (POST response, no-store). Nothing here is persisted or flashed."""
    from flask import make_response

    return _no_store(make_response(render_template(
        "superadmin_credentials_once.html",
        company_name=company_name,
        credentials=result.credentials(),
        back_url=back_url,
    )))


def _schema_report_summary(report: dict) -> dict:
    tables = report.get("tables_created") or []
    columns = report.get("columns_added") or []
    warnings = report.get("warnings") or []
    errors = report.get("errors") or []
    return {
        "tables": len(tables),
        "columns": len(columns),
        "warnings": len(warnings),
        "errors": len(errors),
    }


@superadmin_bp.route("/database-repair")
def superadmin_database_repair():
    tenants = Tenant.query.order_by(Tenant.name.asc()).all()
    return render_template("superadmin_database_repair.html", tenants=tenants)


@superadmin_bp.route("/database-repair/api", methods=["POST"])
def superadmin_database_repair_api():
    from flask import jsonify
    from services.schema_repair import repair_tenant_schema

    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get("dry_run", True))
    scope = (data.get("scope") or "all").strip()
    slug = (data.get("tenant_slug") or "").strip().lower()

    q = Tenant.query.order_by(Tenant.name.asc())
    if scope == "active":
        q = q.filter_by(is_active=True)
    elif scope == "one":
        if not slug:
            return jsonify({"success": False, "error": "اختر شركة أولاً."}), 400
        q = q.filter(db.func.lower(Tenant.slug) == slug)

    tenants = q.all()
    if scope == "one" and not tenants:
        return jsonify({"success": False, "error": "الشركة غير موجودة."}), 404

    results = []
    totals = {"tables": 0, "columns": 0, "warnings": 0, "errors": 0}

    old_tenant = getattr(g, "tenant", None)
    try:
        for tenant in tenants:
            item = {
                "slug": tenant.slug,
                "name": tenant.name,
                "db_path": tenant.db_path,
                "ok": True,
                "report": None,
                "summary": {"tables": 0, "columns": 0, "warnings": 0, "errors": 0},
            }
            try:
                clear_tenant_engine(tenant.slug)
                engine = get_tenant_engine(tenant.slug)
                g.tenant = tenant.slug
                report = repair_tenant_schema(engine, dry_run=dry_run)
                item["report"] = report
                item["summary"] = _schema_report_summary(report)
                item["ok"] = not bool(report.get("errors"))
                if not dry_run:
                    clear_tenant_engine(tenant.slug)
            except Exception as exc:
                current_app.logger.exception("superadmin database repair failed for %s", tenant.slug)
                item["ok"] = False
                item["error"] = str(exc)
                item["summary"]["errors"] = 1
            finally:
                for key in totals:
                    totals[key] += item["summary"].get(key, 0)
                results.append(item)
                g.tenant = None
    finally:
        g.tenant = old_tenant

    return jsonify(
        {
            "success": True,
            "dry_run": dry_run,
            "scope": scope,
            "count": len(results),
            "totals": totals,
            "results": results,
        }
    )



@superadmin_bp.route("/tenants/create", methods=["GET", "POST"])
def tenants_create():
    from models.core.global_setting import GlobalSetting
    
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        slug = (request.form.get("slug") or "").strip().lower()
        owner_name = (request.form.get("owner_name") or "").strip()
        business_type = _clean_business_type(request.form.get("business_type"))
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
        owner_email = (request.form.get("owner_email") or "").strip()
        owner_phone = (request.form.get("owner_phone") or "").strip()
        admin_display_name = owner_name or name

        from services.tenant_provisioning import ProvisioningError, provision_tenant

        try:
            result = provision_tenant(
                name=name.upper(),
                slug=slug,
                business_type=business_type,
                source="superadmin_create",
                contact_name=admin_display_name,
                contact_email=owner_email or None,
                contact_phone=owner_phone or None,
                subscription_days=trial_days,
            )
        except ProvisioningError:
            db.session.rollback()
            flash("حدث خطأ أثناء تهيئة قاعدة بيانات الشركة، وتم التراجع عن الإنشاء بالكامل.", "error")
            return redirect(url_for("superadmin.tenants_create"))

        _try_send_welcome_email(
            email=owner_email,
            contact_name=admin_display_name,
            company_name=name.upper(),
            slug=slug,
            username=result.username,
            plan_name=_plan_name("basic"),
        )
        return _one_time_credentials_response(result, company_name=name.upper(),
                                              back_url=url_for("superadmin.tenants_list"))
    
    trial_days_default = "14"
    try:
        from models.core.global_setting import GlobalSetting
        trial_days_default = GlobalSetting.get_setting("TRIAL_DAYS", "14")
    except Exception:
        pass
    
    return render_template(
        "superadmin_create_tenant.html",
        trial_days_default=trial_days_default,
        business_types=BUSINESS_TYPES,
    )


@superadmin_bp.route("/announcements")
def announcements_list():
    from models.core.platform_announcement import PlatformAnnouncement
    from models.core.announcement_send_log import AnnouncementSendLog
    from utils.tenant_emails import count_marketing_recipients

    announcements = PlatformAnnouncement.query.order_by(PlatformAnnouncement.created_at.desc()).all()
    recent_logs = AnnouncementSendLog.query.order_by(AnnouncementSendLog.sent_at.desc()).limit(50).all()
    tenants = Tenant.query.order_by(Tenant.name).all()

    return render_template(
        "superadmin_announcements.html",
        announcements=announcements,
        recent_logs=recent_logs,
        tenants=tenants,
        recipient_count=count_marketing_recipients(),
    )


@superadmin_bp.route("/announcements/create", methods=["GET", "POST"])
def announcements_create():
    from models.core.platform_announcement import PlatformAnnouncement

    if request.method == "POST":
        subject = (request.form.get("subject") or "").strip()
        body_plain = (request.form.get("body_plain") or "").strip()
        body_html = (request.form.get("body_html") or "").strip() or f"<p>{body_plain.replace(chr(10), '</p><p>')}</p>"

        if not subject or not body_plain:
            flash("العنوان والمحتوى مطلوبان", "error")
            return redirect(url_for("superadmin.announcements_create"))

        ann = PlatformAnnouncement(
            subject=subject,
            body_plain=body_plain,
            body_html=body_html,
            status="draft",
            created_by=session.get("superadmin_username") or "superadmin",
        )
        db.session.add(ann)
        db.session.commit()
        flash("تم حفظ الإعلان", "success")
        return redirect(url_for("superadmin.announcements_list"))

    return render_template("superadmin_announcements_create.html")


@superadmin_bp.route("/announcements/<int:ann_id>/send-all", methods=["POST"])
def announcements_send_all(ann_id):
    from utils.announcement_service import send_announcement_to_all

    success, failed, message = send_announcement_to_all(ann_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("superadmin.announcements_list"))


@superadmin_bp.route("/announcements/<int:ann_id>/send-one", methods=["POST"])
def announcements_send_one(ann_id):
    from utils.announcement_service import send_announcement_to_tenant

    slug = (request.form.get("tenant_slug") or "").strip().lower()
    if not slug:
        flash("اختر شركة", "error")
        return redirect(url_for("superadmin.announcements_list"))

    ok, message = send_announcement_to_tenant(ann_id, slug)
    flash(message, "success" if ok else "error")
    return redirect(url_for("superadmin.announcements_list"))


@superadmin_bp.route("/announcements/<int:ann_id>/set-weekly", methods=["POST"])
def announcements_set_weekly(ann_id):
    from utils.announcement_service import set_weekly_announcement

    ok, message = set_weekly_announcement(ann_id)
    flash(message, "success" if ok else "error")
    return redirect(url_for("superadmin.announcements_list"))


@superadmin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    from models.core.global_setting import GlobalSetting
    
    if request.method == "POST":
        # Save settings
        app_name = request.form.get("APP_NAME", "Finora System")
        trial_days = request.form.get("TRIAL_DAYS", "14")
        openai_api_key_in = (request.form.get("OPENAI_API_KEY", "") or "").strip()
        zaincash_secret = request.form.get("ZAINCASH_SECRET", "")
        zaincash_merchant = request.form.get("ZAINCASH_MERCHANT", "")
        zaincash_transfer_phone = request.form.get("ZAINCASH_TRANSFER_PHONE", "07734049148").strip()
        
        GlobalSetting.set_setting("APP_NAME", app_name, "اسم النظام العام للمنصة")
        GlobalSetting.set_setting("TRIAL_DAYS", trial_days, "عدد أيام التجربة المجانية للشركات")
        
        # Global OpenAI key (used by all AI features)
        # If user leaves the masked value (starts with ●) do not overwrite.
        if openai_api_key_in and not openai_api_key_in.startswith("●"):
            GlobalSetting.set_setting("OPENAI_API_KEY", openai_api_key_in, "مفتاح OpenAI (ذكاء اصطناعي) لكل النظام")
        GlobalSetting.set_setting("ZAINCASH_SECRET", zaincash_secret, "كلمة سر حساب مركز زين كاش")
        GlobalSetting.set_setting("ZAINCASH_MERCHANT", zaincash_merchant, "رقم تعريف تاجر زين كاش")
        GlobalSetting.set_setting("ZAINCASH_TRANSFER_PHONE", zaincash_transfer_phone, "رقم تحويل زين كاش (محفظة استلام الدفع)")
        
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

        GlobalSetting.set_setting(
            "WEEKLY_ANNOUNCEMENT_ENABLED",
            "1" if request.form.get("WEEKLY_ANNOUNCEMENT_ENABLED") else "0",
            "تفعيل الإرسال الأسبوعي التلقائي",
        )
        GlobalSetting.set_setting(
            "WEEKLY_ANNOUNCEMENT_DAY",
            request.form.get("WEEKLY_ANNOUNCEMENT_DAY", "mon"),
            "يوم الإرسال الأسبوعي (mon/tue/...)",
        )
        GlobalSetting.set_setting(
            "WEEKLY_ANNOUNCEMENT_HOUR",
            request.form.get("WEEKLY_ANNOUNCEMENT_HOUR", "9"),
            "ساعة الإرسال الأسبوعي (0-23)",
        )
        
        flash("تم حفظ الإعدادات بنجاح!", "success")
        return redirect(url_for("superadmin.settings"))

    # GET Request - Load Settings
    from utils.platform_branding import DEFAULT_LOGO_PATH, get_platform_logo_path, get_platform_logo_url

    openai_key = (GlobalSetting.get_setting("OPENAI_API_KEY", "") or "").strip()
    logo_path = get_platform_logo_path()
    settings_data = {
        "app_name": GlobalSetting.get_setting("APP_NAME", "Finora System"),
        "app_logo_path": get_platform_logo_url(),
        "has_custom_logo": logo_path != DEFAULT_LOGO_PATH,
        "trial_days": GlobalSetting.get_setting("TRIAL_DAYS", "14"),
        "openai_api_key_present": bool(openai_key),
        "openai_api_key_masked": "●●●●●●●●●●" if openai_key else "",
        "zaincash_secret": GlobalSetting.get_setting("ZAINCASH_SECRET", ""),
        "zaincash_merchant": GlobalSetting.get_setting("ZAINCASH_MERCHANT", ""),
        "zaincash_transfer_phone": GlobalSetting.get_setting("ZAINCASH_TRANSFER_PHONE", "07734049148"),
        "notify_email_enabled": GlobalSetting.get_setting("NOTIFY_EMAIL_ENABLED", "0") == "1",
        "smtp_host": GlobalSetting.get_setting("SMTP_HOST", ""),
        "smtp_port": GlobalSetting.get_setting("SMTP_PORT", "587"),
        "smtp_user": GlobalSetting.get_setting("SMTP_USER", ""),
        "smtp_password": GlobalSetting.get_setting("SMTP_PASSWORD", ""),
        "smtp_from": GlobalSetting.get_setting("SMTP_FROM", ""),
        "notify_sms_enabled": GlobalSetting.get_setting("NOTIFY_SMS_ENABLED", "0") == "1",
        "sms_api_url": GlobalSetting.get_setting("SMS_API_URL", ""),
        "sms_sender": GlobalSetting.get_setting("SMS_SENDER", ""),
        "weekly_announcement_enabled": GlobalSetting.get_setting("WEEKLY_ANNOUNCEMENT_ENABLED", "1") == "1",
        "weekly_announcement_day": GlobalSetting.get_setting("WEEKLY_ANNOUNCEMENT_DAY", "mon"),
        "weekly_announcement_hour": GlobalSetting.get_setting("WEEKLY_ANNOUNCEMENT_HOUR", "9"),
    }
    
    return render_template("superadmin_settings.html", settings=settings_data)


@superadmin_bp.route("/settings/upload-logo", methods=["POST"])
def upload_platform_logo():
    from flask import jsonify
    from utils.platform_branding import save_platform_logo

    try:
        if "logo" not in request.files:
            return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400

        file = request.files["logo"]
        logo_path = save_platform_logo(file, current_app.root_path)
        return jsonify({
            "success": True,
            "message": "تم رفع الشعار بنجاح",
            "logo_path": logo_path,
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("platform logo upload failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@superadmin_bp.route("/settings/remove-logo", methods=["POST"])
def remove_platform_logo_route():
    from flask import jsonify
    from utils.platform_branding import remove_platform_logo

    try:
        remove_platform_logo(current_app.root_path)
        return jsonify({"success": True, "message": "تم حذف الشعار"})
    except Exception as exc:
        current_app.logger.exception("platform logo remove failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@superadmin_bp.route("/invoice-templates")
def invoice_templates_manager():
    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    templates = InvoiceTemplate.query.order_by(InvoiceTemplate.price.asc(), InvoiceTemplate.id.asc()).all()

    tenant_ids = [t.id for t in tenants]
    settings_rows = TenantTemplateSettings.query.filter(
        TenantTemplateSettings.tenant_id.in_(tenant_ids)
    ).all() if tenant_ids else []

    active_template_by_tenant = {row.tenant_id: row.active_template_id for row in settings_rows}
    template_by_id = {tmpl.id: tmpl for tmpl in templates}
    return render_template(
        "superadmin_invoice_templates.html",
        tenants=tenants,
        templates=templates,
        active_template_by_tenant=active_template_by_tenant,
        template_by_id=template_by_id,
    )


@superadmin_bp.route("/invoice-templates/activate", methods=["POST"])
def activate_invoice_template_for_tenant():
    tenant_slug = (request.form.get("tenant_slug") or "").strip().lower()
    template_id_raw = (request.form.get("template_id") or "").strip()

    if not tenant_slug:
        flash("يرجى تحديد الشركة", "error")
        return redirect(url_for("superadmin.invoice_templates_manager"))

    if not template_id_raw.isdigit():
        flash("يرجى اختيار قالب صالح", "error")
        return redirect(url_for("superadmin.invoice_templates_manager"))

    template_id = int(template_id_raw)
    tenant = Tenant.query.filter(db.func.lower(Tenant.slug) == tenant_slug).first()
    if not tenant:
        flash("الشركة غير موجودة", "error")
        return redirect(url_for("superadmin.invoice_templates_manager"))

    template = InvoiceTemplate.query.get(template_id)
    if not template:
        flash("القالب غير موجود", "error")
        return redirect(url_for("superadmin.invoice_templates_manager"))

    try:
        owner_uid = tenant.id
        _ensure_invoice_owner_user(owner_uid)

        tset = TenantTemplateSettings.query.filter_by(tenant_id=owner_uid).first()
        if not tset:
            tset = TenantTemplateSettings(tenant_id=owner_uid)
            db.session.add(tset)

        tset.active_template_id = template.id
        db.session.commit()
        # تحقق سريع بعد الحفظ لتوضيح أي مشكلة صامتة
        verify = TenantTemplateSettings.query.filter_by(tenant_id=owner_uid).first()
        if not verify or verify.active_template_id != template.id:
            flash(
                f"تمت العملية لكن لم يتم تثبيت القالب. (tenant_id={owner_uid}, expected={template.id}, got={getattr(verify,'active_template_id',None)})",
                "error",
            )
        else:
            flash(
                f"تم تفعيل قالب «{template.name}» لشركة «{tenant.name}» بنجاح (slug={tenant.slug}, tenant_id={owner_uid})",
                "success",
            )
    except Exception as e:
        db.session.rollback()
        flash(f"فشل تفعيل القالب: {str(e)}", "error")

    return redirect(url_for("superadmin.invoice_templates_manager"))


# دليل الصفحات — روابط لكل القوالب والصفحات في النظام
PAGES_GUIDE = [
    {
        "title": "لوحة الإدارة العليا (Super Admin)",
        "icon": "fa-user-shield",
        "links": [
            ("/superadmin/", "لوحة القيادة (Dashboard)", "admin_dashboard.html"),
            ("/superadmin/brain", "عقل المنصة — مجرة الزبائن", "superadmin_brain.html"),
            ("/superadmin/requests", "طلبات ZainCash", "payment_requests.html"),
            ("/superadmin/tenants", "الشركات المسجلة", "tenant_list.html"),
            ("/superadmin/tenants/create", "إنشاء شركة جديدة", "superadmin_create_tenant.html"),
            ("/superadmin/invoice-templates", "تفعيل قوالب الفواتير للشركات", "superadmin_invoice_templates.html"),
            ("/superadmin/settings", "إعدادات النظام", "superadmin_settings.html"),
            ("/superadmin/database-repair", "إصلاح قواعد بيانات الشركات", "superadmin_database_repair.html"),
            ("/superadmin/links", "دليل الصفحات — كل الروابط", "superadmin_links.html"),
            ("/superadmin/login", "تسجيل دخول المدير", "superadmin_login.html"),
        ],
    },
    {
        "title": "Leads CRM — مبيعات المنصة",
        "icon": "fa-bullseye",
        "links": [
            ("/superadmin/leads/", "Leads CRM — Overview", "superadmin/leads/overview.html"),
            ("/superadmin/leads/all", "All Leads", "superadmin/leads/all_leads.html"),
            ("/superadmin/leads/activities", "Activities", "superadmin/leads/activities.html"),
            ("/superadmin/leads/pipeline", "Pipeline Kanban", "superadmin/leads/pipeline.html"),
            ("/superadmin/leads/follow-ups", "Follow-ups", "superadmin/leads/followups.html"),
            ("/superadmin/leads/trials", "Trials", "superadmin/leads/trials.html"),
            ("/superadmin/leads/imports", "Excel Import", "superadmin/leads/imports.html"),
            ("/superadmin/leads/duplicates", "Duplicate Center", "superadmin/leads/duplicates.html"),
            ("/superadmin/leads/sources", "Sources", "superadmin/leads/sources.html"),
            ("/superadmin/leads/performance", "Performance", "superadmin/leads/performance.html"),
            ("/superadmin/leads/reports", "Reports", "superadmin/leads/reports.html"),
            ("/superadmin/leads/settings", "Leads Settings", "superadmin/leads/settings.html"),
            ("/superadmin/leads/map", "Map View", "superadmin/leads/map.html"),
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
            ("/inventory/add", "إضافة منتج (نموذج كامل)", "inventory_add_product.html"),
            ("/inventory/audit", "جرد المخزون", "inventory_audit.html"),
            ("/inventory/ledger", "دفتر المخزون", "inventory_ledger.html"),
            ("/inventory/report/<id>", "تقرير صنف", "inventory_report.html"),
            ("/purchases", "المشتريات", "purchases_history.html"),
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
            ("/delivery/report/<id>/print", "طباعة كشف مع المنتجات", "shipping_report_print.html"),
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
    from utils.plan_limits import resolve_plan_features

    plans = SubscriptionPlan.query.all()
    effective_plan_features = {
        plan.id: resolve_plan_features(plan.plan_key, plan.get_features())
        for plan in plans
    }
    # If no plans in DB, we should probably seed them from utils/plan_limits.py or show empty
    return render_template(
        "superadmin_plans.html",
        plans=plans,
        effective_plan_features=effective_plan_features,
    )

@superadmin_bp.route("/plans/edit/<int:plan_id>", methods=["GET", "POST"])
def edit_plan(plan_id):
    from utils.plan_limits import (
        PLAN_FEATURE_GROUPS,
        PLAN_FEATURE_LABELS,
        resolve_plan_features,
    )

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
        
        # حفظ جميع صفحات النظام، مع الإبقاء على أي مفتاح مستقبلي غير معروض
        # بدلاً من مسحه عند تعديل خطة قديمة.
        old_features = plan.get_features()
        features = {
            key: bool(value)
            for key, value in old_features.items()
            if key not in PLAN_FEATURE_LABELS
        }
        for feat in PLAN_FEATURE_LABELS:
            features[feat] = bool(request.form.get(f"feat_{feat}"))
            
        plan.set_features(features)
        db.session.commit()
        flash(f"تم تحديث الخطة «{plan.name}» بنجاح")
        return redirect(url_for("superadmin.plans_list"))
        
    effective_features = resolve_plan_features(plan.plan_key, plan.get_features())
    return render_template(
        "superadmin_edit_plan.html",
        plan=plan,
        feature_groups=PLAN_FEATURE_GROUPS,
        effective_features=effective_features,
    )

@superadmin_bp.route("/plans/seed", methods=["POST"])
def seed_plans():
    """Seed plans from PLAN_DEFINITIONS if empty"""
    from utils.plan_limits import PLAN_DEFINITIONS, resolve_plan_features
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
            new_p.set_features(resolve_plan_features(key, data["features"]))
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
        
        new_status = not tenant.is_active
        registration = get_tenant_registration(tenant.slug, core_tenant=tenant, sync_if_missing=False)
        is_first_whatsapp_activation = (
            new_status and registration.get("activation_status") == "pending_whatsapp"
        )
        activation_end = None
        if is_first_whatsapp_activation:
            if registration.get("plan_key") == "free":
                try:
                    duration_days = max(1, min(365, int(registration.get("trial_days") or 14)))
                except (TypeError, ValueError):
                    duration_days = 14
            else:
                duration_days = 360 if registration.get("billing") == "yearly" else 30
            activation_end = datetime.utcnow() + timedelta(days=duration_days)

        # مزامنة حالة الشركة داخل قاعدة بياناتها أيضاً، حتى يصبح الدخول ممكناً
        # فور موافقة الإدارة على طلب واتساب.
        from sqlalchemy.orm import sessionmaker
        from models.tenant import Tenant as TenantModel

        TenantSession = sessionmaker(bind=get_tenant_engine(tenant.slug))
        tenant_session = TenantSession()
        try:
            tenant_row = tenant_session.query(TenantModel).first()
            if tenant_row:
                tenant_row.is_active = new_status
                if activation_end:
                    tenant_row.subscription_start = datetime.utcnow()
                    tenant_row.subscription_end = activation_end
                tenant_session.commit()
        except Exception:
            tenant_session.rollback()
            raise
        finally:
            tenant_session.close()

        tenant.is_active = new_status
        if activation_end:
            tenant.subscription_end_date = activation_end
        db.session.commit()

        registration_update = {
            "activation_status": "active" if new_status else "disabled",
        }
        if new_status:
            registration_update["activated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        try:
            save_tenant_registration(tenant.slug, registration_update)
        except Exception:
            current_app.logger.exception("failed to update activation profile for %s", tenant.slug)
        
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

        delete_tenant_registration(tenant.slug)
        
        # 3. Delete from Core DB
        db.session.delete(tenant)
        db.session.commit()
        
        return jsonify({"ok": True, "message": "تم حذف الشركة وقاعدة البيانات الخاصة بها نهائياً"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@superadmin_bp.route("/tenants/update-business-type/<slug>", methods=["POST"])
def tenant_update_business_type(slug):
    from flask import request, jsonify
    from sqlalchemy.orm import sessionmaker
    from extensions_tenant import get_tenant_engine, clear_tenant_engine
    from models.tenant import Tenant as TenantSpecific

    try:
        data = request.get_json() or {}
        business_type = _clean_business_type(data.get("business_type"))
        slug_clean = (slug or "").strip().lower()
        tenant_core = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
        if not tenant_core:
            return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404

        tenant_core.business_type = business_type
        db.session.commit()

        engine = get_tenant_engine(tenant_core.slug)
        _ensure_tenant_business_type_column(engine)
        SessionLocal = sessionmaker(bind=engine)
        tenant_session = SessionLocal()
        try:
            tenant_spec = tenant_session.query(TenantSpecific).first()
            if tenant_spec:
                tenant_spec.business_type = business_type
                tenant_session.commit()
        except Exception as te:
            tenant_session.rollback()
            return jsonify({"ok": False, "error": f"فشل تحديث قاعدة بيانات الشركة: {str(te)}"}), 500
        finally:
            tenant_session.close()

        clear_tenant_engine(tenant_core.slug)
        return jsonify({
            "ok": True,
            "message": f"تم تغيير نوع النشاط إلى {BUSINESS_TYPES[business_type]}",
            "business_type": business_type,
            "business_type_label": BUSINESS_TYPES[business_type],
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500


@superadmin_bp.route("/tenants/update-branch-mode/<slug>", methods=["POST"])
def tenant_update_branch_mode(slug):
    """Select legacy shared mode or verified independent branches per company."""
    from flask import jsonify
    from sqlalchemy.orm import load_only, sessionmaker
    from models.system_settings import SystemSettings
    from utils.branch_mode import (
        BRANCH_SCOPE_MIGRATION_FLAG,
        INDEPENDENT_BRANCHES_FLAG,
        LEGACY_SHARED_MODE_FLAG,
    )

    data = request.get_json(silent=True) or {}
    if "enabled" not in data:
        return jsonify({"ok": False, "error": "قيمة وضع الفروع مطلوبة"}), 400
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        return jsonify({"ok": False, "error": "قيمة وضع الفروع يجب أن تكون تفعيل أو إيقاف"}), 400
    slug_clean = (slug or "").strip().lower()
    tenant_core = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
    if not tenant_core:
        return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404

    tenant_slug = tenant_core.slug
    engine = get_tenant_engine(tenant_slug)
    SessionLocal = sessionmaker(bind=engine)
    tenant_session = SessionLocal()
    try:
        settings = tenant_session.query(SystemSettings).options(
            load_only(SystemSettings.id, SystemSettings.ui_flags)
        ).first()
        if not settings:
            settings = SystemSettings()
            settings.set_ui_flags({})
            tenant_session.add(settings)
            tenant_session.flush()
        flags = settings.get_ui_flags()
        migrated = bool(flags.get(BRANCH_SCOPE_MIGRATION_FLAG, False))
        if not enabled and migrated:
            return jsonify({
                "ok": False,
                "error": (
                    "لا يمكن الرجوع للنظام المشترك بعد اكتمال ترحيل الفروع. "
                    "الرجوع يحتاج استعادة النسخة السابقة للترحيل."
                ),
                "migration_completed": True,
                "backup_path": flags.get("branch_pre_migration_backup"),
            }), 409
        if enabled:
            # Re-enabling an explicitly approved compatibility tenant returns
            # it to the already-migrated independent branch view.
            flags.pop(LEGACY_SHARED_MODE_FLAG, None)
        flags[INDEPENDENT_BRANCHES_FLAG] = enabled
        settings.set_ui_flags(flags)
        tenant_session.commit()
    except Exception as exc:
        tenant_session.rollback()
        return jsonify({"ok": False, "error": f"تعذر حفظ وضع الفروع: {exc}"}), 500
    finally:
        tenant_session.close()

    if enabled and not migrated:
        previous_tenant = getattr(g, "tenant", None)
        try:
            db.session.remove()
            g.tenant = tenant_slug
            from utils.branch_mode import clear_branch_mode_cache
            from utils.branch_migration import ensure_branch_schema

            clear_branch_mode_cache()
            ensure_branch_schema(force_independent=True)
            mode_result = _read_branch_mode_snapshot(engine)
            if not mode_result["migration_completed"]:
                rollback_session = SessionLocal()
                try:
                    rollback_settings = rollback_session.query(SystemSettings).options(
                        load_only(SystemSettings.id, SystemSettings.ui_flags)
                    ).first()
                    rollback_flags = rollback_settings.get_ui_flags()
                    rollback_flags[INDEPENDENT_BRANCHES_FLAG] = False
                    rollback_settings.set_ui_flags(rollback_flags)
                    rollback_session.commit()
                finally:
                    rollback_session.close()
                return jsonify({
                    "ok": False,
                    "error": "فشل التحقق من ترحيل الفروع؛ بقيت الشركة على النظام المشترك.",
                    **mode_result,
                }), 500
        finally:
            db.session.remove()
            g.tenant = previous_tenant

    result = _read_branch_mode_snapshot(engine)
    clear_tenant_engine(tenant_slug)
    return jsonify({
        "ok": True,
        "message": (
            "تم تفعيل الفروع المستقلة"
            if enabled
            else "تم إبقاء الشركة على النظام المشترك"
        ),
        **result,
    })


@superadmin_bp.route("/tenants/update-features/<slug>", methods=["POST"])
def tenant_update_features(slug):
    from flask import request, jsonify
    from sqlalchemy.orm import sessionmaker
    from extensions_tenant import get_tenant_engine, clear_tenant_engine
    from models.tenant import Tenant as TenantSpecific

    try:
        data = request.get_json() or {}
        overrides = normalize_feature_overrides(data.get("features") or {})
        slug_clean = (slug or "").strip().lower()
        tenant_core = Tenant.query.filter(db.func.lower(Tenant.slug) == slug_clean).first()
        if not tenant_core:
            return jsonify({"ok": False, "error": "الشركة غير موجودة"}), 404

        engine = get_tenant_engine(tenant_core.slug)
        ensure_tenant_feature_overrides_column(engine)
        if overrides.get("trade_in_sales"):
            from utils.product_schema_guard import ensure_product_schema

            previous_tenant = getattr(g, "tenant", None)
            g.tenant = tenant_core.slug
            try:
                ensure_product_schema()
            finally:
                g.tenant = previous_tenant
        SessionLocal = sessionmaker(bind=engine)
        tenant_session = SessionLocal()
        try:
            tenant_spec = tenant_session.query(TenantSpecific).first()
            if not tenant_spec:
                return jsonify({"ok": False, "error": "لم يتم العثور على سجل الشركة داخل قاعدتها"}), 404
            tenant_spec.feature_overrides_json = feature_overrides_json(overrides)
            if overrides.get("trade_in_sales"):
                from utils.trade_in_service import ensure_replacement_product_with_session

                ensure_replacement_product_with_session(
                    tenant_session,
                    tenant_id=None,
                )
            tenant_session.commit()
        except Exception as te:
            tenant_session.rollback()
            return jsonify({"ok": False, "error": f"فشل تحديث قاعدة بيانات الشركة: {str(te)}"}), 500
        finally:
            tenant_session.close()

        clear_tenant_engine(tenant_core.slug)
        return jsonify({
            "ok": True,
            "message": "تم حفظ إعدادات ظهور الميزات بنجاح",
            "feature_overrides": overrides,
        })
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


# ── عقل المنصة — مجرة الزبائن عبر كل الشركات ──────────────────────────────

BRAIN_ORBITS = [
    {"key": "blacklist", "label": "قائمة سوداء", "radius": 1},
    {"key": "vip", "label": "VIP", "radius": 2},
    {"key": "unpaid", "label": "متأخر الدفع", "radius": 3},
    {"key": "active", "label": "نشط", "radius": 4},
    {"key": "dormant", "label": "جديد / خامل", "radius": 5},
]
BRAIN_VIP_THRESHOLD = 500_000
BRAIN_ACTIVE_DAYS = 90
BRAIN_MAX_PLANETS = 5000


def _brain_classify_orbit(is_blacklisted, sales_total, unpaid_total, last_invoice_at, now_utc):
    if is_blacklisted:
        return "blacklist"
    if (sales_total or 0) >= BRAIN_VIP_THRESHOLD:
        return "vip"
    if (unpaid_total or 0) > 0:
        return "unpaid"
    if last_invoice_at:
        cutoff = now_utc - timedelta(days=BRAIN_ACTIVE_DAYS)
        last = last_invoice_at
        if getattr(last, "tzinfo", None) is not None:
            last = last.replace(tzinfo=None)
        if last >= cutoff:
            return "active"
    return "dormant"


def _brain_collect_tenant_planets(tenant, now_utc):
    """Aggregate customers + invoice stats for one tenant DB. Raises on hard failure."""
    from sqlalchemy import case, func, or_
    from models.customer import Customer
    from models.invoice import Invoice

    try:
        from utils.product_schema_guard import ensure_customer_blacklist_columns
        ensure_customer_blacklist_columns()
    except Exception:
        pass

    unpaid_expr = case(
        (
            or_(
                Invoice.payment_status.is_(None),
                Invoice.payment_status == "غير مسدد",
            ),
            func.coalesce(Invoice.total, 0) - func.coalesce(Invoice.paid_amount, 0),
        ),
        else_=0,
    )

    stats_rows = (
        db.session.query(
            Invoice.customer_id,
            func.count(Invoice.id).label("invoice_count"),
            func.coalesce(func.sum(Invoice.total), 0).label("sales_total"),
            func.coalesce(func.sum(unpaid_expr), 0).label("unpaid_total"),
            func.max(Invoice.created_at).label("last_invoice_at"),
        )
        .group_by(Invoice.customer_id)
        .all()
    )
    stats_by_id = {
        int(row.customer_id): {
            "invoice_count": int(row.invoice_count or 0),
            "sales_total": int(row.sales_total or 0),
            "unpaid_total": max(0, int(row.unpaid_total or 0)),
            "last_invoice_at": row.last_invoice_at,
        }
        for row in stats_rows
        if row.customer_id is not None
    }

    customers = Customer.query.order_by(Customer.id.asc()).all()
    planets = []
    for c in customers:
        st = stats_by_id.get(int(c.id), {
            "invoice_count": 0,
            "sales_total": 0,
            "unpaid_total": 0,
            "last_invoice_at": None,
        })
        is_bl = bool(getattr(c, "is_blacklisted", False))
        orbit = _brain_classify_orbit(
            is_bl,
            st["sales_total"],
            st["unpaid_total"],
            st["last_invoice_at"],
            now_utc,
        )
        planets.append({
            "id": f"{tenant.slug}:{c.id}",
            "name": c.name or "—",
            "phone": c.phone or "",
            "city": c.city or "",
            "tenant_slug": tenant.slug,
            "tenant_name": tenant.name,
            "orbit": orbit,
            "invoice_count": st["invoice_count"],
            "sales_total": st["sales_total"],
            "unpaid_total": st["unpaid_total"],
            "is_blacklisted": is_bl,
        })
    return planets


@superadmin_bp.route("/brain")
def brain_page():
    return render_template("superadmin_brain.html")


@superadmin_bp.route("/brain/api")
def brain_galaxy_api():
    from flask import jsonify

    g.tenant = None
    try:
        db.session.rollback()
    except Exception:
        pass

    now_utc = datetime.utcnow()
    tenants = Tenant.query.order_by(Tenant.name.asc()).all()
    all_planets = []
    errors = []
    companies_ok = 0

    old_tenant = getattr(g, "tenant", None)
    try:
        for tenant in tenants:
            slug = (tenant.slug or "").strip()
            if not slug:
                continue
            g.tenant = slug
            try:
                planets = _brain_collect_tenant_planets(tenant, now_utc)
                all_planets.extend(planets)
                companies_ok += 1
            except Exception as exc:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                current_app.logger.exception("brain galaxy failed for %s", slug)
                errors.append({"slug": slug, "error": str(exc)})
            finally:
                g.tenant = None
                try:
                    db.session.remove()
                except Exception:
                    pass
    finally:
        g.tenant = old_tenant

    by_orbit = {o["key"]: 0 for o in BRAIN_ORBITS}
    for p in all_planets:
        key = p.get("orbit") or "dormant"
        by_orbit[key] = by_orbit.get(key, 0) + 1

    total_customers = len(all_planets)
    all_planets.sort(key=lambda p: (p.get("sales_total") or 0), reverse=True)
    truncated = False
    if len(all_planets) > BRAIN_MAX_PLANETS:
        all_planets = all_planets[:BRAIN_MAX_PLANETS]
        truncated = True

    return jsonify({
        "ok": True,
        "totals": {
            "customers": total_customers,
            "companies": companies_ok,
            "companies_total": len(tenants),
            "by_orbit": by_orbit,
            "truncated": truncated,
            "vip_threshold": BRAIN_VIP_THRESHOLD,
            "active_days": BRAIN_ACTIVE_DAYS,
        },
        "orbits": BRAIN_ORBITS,
        "planets": all_planets,
        "errors": errors,
    })

