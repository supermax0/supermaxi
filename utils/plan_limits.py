"""
plan_limits.py — نظام حدود الخطط (SaaS Feature Gating)
كل خطة تحدد: عدد المستخدمين، الطلبات الشهرية، والميزات المسموح بها.
"""

from collections import OrderedDict

from utils.tenant_feature_flags import TENANT_FEATURE_GROUPS, default_feature_enabled


# مفاتيح قديمة ما زالت مستخدمة كحدود عامة في القوائم والمسارات، بينما
# TENANT_FEATURE_GROUPS يحتوي كل الصفحات والتفاصيل التي تظهر داخل الشركة.
_LEGACY_PLAN_FEATURE_GROUP = {
    "key": "plan_limits",
    "label": "حدود الخطة العامة",
    "features": [
        ("cashflow", "التحصيل والمدفوعات"),
        ("printing", "الطباعة والفواتير"),
        ("reports_adv", "التقارير المالية المتقدمة"),
        ("rbac", "صلاحيات RBAC"),
    ],
}

PLAN_FEATURE_GROUPS = [_LEGACY_PLAN_FEATURE_GROUP, *TENANT_FEATURE_GROUPS]
PLAN_FEATURE_LABELS = OrderedDict(
    (key, label)
    for group in PLAN_FEATURE_GROUPS
    for key, label in group["features"]
)


# الصفحة الفرعية ترث حالة الباب الرئيسي عندما لا تكون لها قيمة محفوظة بعد.
# هذا يحافظ على الخطط القديمة ويمنع ظهور الصفحة مقفولة لمجرد أن المفتاح أضيف
# بعد إنشاء سجل الخطة في قاعدة البيانات.
PLAN_FEATURE_PARENTS = {
    "executive_dashboard": "dashboard",
    "trade_in_sales": "pos",
    "orders_all": "orders",
    "orders_placed": "orders",
    "orders_packed": "orders",
    "orders_shipping": "orders",
    "orders_delivered": "orders",
    "orders_returned": "orders",
    "orders_reports": "orders",
    "orders_printing": "printing",
    "inventory_products": "inventory",
    "inventory_ledger": "inventory",
    "inventory_audit": "inventory",
    "inventory_add_product": "inventory",
    "inventory_reports": "inventory",
    "maintenance": "inventory",
    "supplier_statement": "suppliers",
    "stock_transfers": "inventory",
    "customer_blacklist": "customers",
    "customer_provinces": "customers",
    "customer_credit": "customers",
    "agents_pending_execution": "agents",
    "employee_roles": "rbac",
    "shipping_reports": "shipping",
    "shipping_company_returns": "shipping",
    "delivery_archive": "shipping",
    "delivery_agent_portal": "shipping",
    "cash": "cashflow",
    "fixed_assets": "accounts",
    "rotating_savings": "accounts",
    "installments_dashboard": "installments",
    "installments_products": "installments",
    "installments_applications": "installments",
    "installments_contracts": "installments",
    "installments_overdue": "installments",
    "installments_reports": "installments",
    "installments_settings": "installments",
    "reports": "reports_adv",
    "reports_daily": "reports_adv",
    "reports_monitors": "reports_adv",
    "reports_financial": "reports_adv",
    "reports_sales": "reports_adv",
    "reports_profit": "reports_adv",
    "investments": "ai_assistant",
    "assistant_chat": "ai_assistant",
    "mobile_app_videos": "mobile_app",
    "mobile_app_users": "mobile_app",
    "mobile_app_comments": "mobile_app",
    "mobile_app_rewards": "mobile_app",
    "mobile_app_coupons": "mobile_app",
    "mobile_app_flags": "mobile_app",
    "mobile_app_design": "mobile_app",
    "mobile_app_notifications": "mobile_app",
    "mobile_app_analytics": "mobile_app",
    "permissions": "rbac",
    "settings_system": "settings",
    "settings_invoice": "settings",
    "settings_appearance": "settings",
    "settings_branches": "settings",
    "settings_storefront": "settings",
    "settings_database_repair": "settings",
    "invoice_templates": "printing",
    "beauty_appointments": "beauty",
    "beauty_services": "beauty",
    "beauty_sessions": "beauty",
    "beauty_alerts": "beauty",
    "beauty_accounts": "beauty",
    "beauty_clients": "beauty",
    "wholesale_ops": "wholesale",
    "wholesale_sales": "wholesale",
    "wholesale_purchases": "wholesale",
    "wholesale_receipts": "wholesale",
    "wholesale_payments": "wholesale",
    "wholesale_customers": "wholesale",
    "wholesale_suppliers": "wholesale",
    "wholesale_products": "wholesale",
    "wholesale_warehouses": "wholesale",
    "wholesale_transfers": "wholesale",
    "wholesale_accounts": "wholesale",
    "wholesale_statement": "wholesale",
    "wholesale_expenses": "wholesale",
    "wholesale_reports": "wholesale",
    "wholesale_settings": "wholesale",
}

# ===================================================
# تعريف خطط الاشتراك وحدودها وميزاتها
# ===================================================
PLAN_DEFINITIONS = {
    "free": {
        "key":          "free",
        "name":         "الخطة المجانية",
        "price_monthly": 0,
        "price_yearly":  0,
        "max_users":     3,
        "max_orders_monthly": 500,
        # العرض الترحيبي يفتح كل صفحات النظام التشغيلية والمحاسبية،
        # وتبقى منتجات الذكاء الاصطناعي خارج الاشتراك المجاني.
        "features": {
            "orders":       True,
            "pos":          True,
            "inventory":    True,
            "customers":    True,
            "cashflow":     True,
            "printing":     True,
            "expenses":     True,
            "suppliers":    True,
            "purchases":    True,
            "shipping":     True,
            "reports_adv":  True,
            "rbac":         True,
            "agents":       True,
            "accounts":     True,
            "messages":     True,
            "ai_assistant": False,
            "ai_workspace": False,
            "ai_sales":     False,
        },
    },
    "basic": {
        "key":          "basic",
        "name":         "الخطة الأساسية",
        "price_monthly": 25000,
        "price_yearly":  250000,
        "max_users":     5,
        "max_orders_monthly": 1000,
        "features": {
            "orders":       True,   # إدارة الطلبات
            "pos":          True,   # نقطة البيع
            "inventory":    True,   # المخزون
            "customers":    True,   # الزبائن
            "cashflow":     True,   # التحصيل والمدفوعات
            "printing":     True,   # الطباعة والفواتير
            "expenses":     False,  # المصروفات
            "suppliers":    False,  # الموردون
            "purchases":    False,  # المشتريات
            "shipping":     False,  # شركات النقل
            "reports_adv":  False,  # تقارير مالية متقدمة
            "rbac":         False,  # صلاحيات RBAC
            "agents":       False,  # مناديب التوصيل
            "accounts":     False,  # دفتر الحسابات
            "ai_assistant": False,  # مساعد AI
            "ai_workspace": False,  # مساحة LEON التفاعلية
            "messages":     False,  # نظام الرسائل
            "ai_sales":     False,  # موظف المبيعات الذكي
        },
    },

    "pro": {
        "key":          "pro",
        "name":         "الخطة المتقدمة",
        "price_monthly": 45000,
        "price_yearly":  450000,
        "max_users":     15,
        "max_orders_monthly": 10000,
        "features": {
            "orders":       True,
            "pos":          True,
            "inventory":    True,
            "customers":    True,
            "cashflow":     True,
            "printing":     True,
            "expenses":     True,
            "suppliers":    True,
            "purchases":    True,
            "shipping":     True,
            "reports_adv":  True,
            "rbac":         True,
            "agents":       True,
            "accounts":     True,
            "ai_assistant": False,  # فقط في Enterprise
            "ai_workspace": False,
            "messages":     False,
            "ai_sales":     False,
        },
    },

    "enterprise": {
        "key":          "enterprise",
        "name":         "خطة الشركات",
        "price_monthly": 90000,
        "price_yearly":  900000,
        "max_users":     None,   # غير محدود
        "max_orders_monthly": None,
        "features": {
            "orders":       True,
            "pos":          True,
            "inventory":    True,
            "customers":    True,
            "cashflow":     True,
            "printing":     True,
            "expenses":     True,
            "suppliers":    True,
            "purchases":    True,
            "shipping":     True,
            "reports_adv":  True,
            "rbac":         True,
            "agents":       True,
            "accounts":     True,
            "ai_assistant": True,
            "ai_workspace": True,
            "messages":     True,
            "ai_sales":     True,
        },
    },
}

# Default fallback
_DEFAULT_PLAN = PLAN_DEFINITIONS["basic"]


def resolve_plan_features(plan_key: str, stored_features=None) -> dict:
    """Return a complete, backwards-compatible feature matrix for a plan.

    Old database rows can contain only a handful of keys.  Missing page keys
    inherit their parent feature; standalone pages stay enabled until the
    superadmin explicitly disables them.  Values stored in the database always
    win over defaults.
    """
    static_features = dict(
        PLAN_DEFINITIONS.get(plan_key, _DEFAULT_PLAN).get("features", {})
    )
    explicit_features = (
        {str(key): bool(value) for key, value in stored_features.items()}
        if isinstance(stored_features, dict)
        else {}
    )
    source = {**static_features, **explicit_features}
    resolved = dict(source)

    def feature_state(feature: str, visiting=None) -> bool:
        if feature in source:
            return bool(source[feature])
        visiting = set(visiting or ())
        if feature in visiting:
            return False
        visiting.add(feature)
        parent = PLAN_FEATURE_PARENTS.get(feature)
        if parent:
            return feature_state(parent, visiting)
        # هذه صفحات كانت متاحة قبل إضافة مصفوفة الصفحات الشاملة؛ نستخدم
        # افتراض الشركة نفسه (ومن ضمنه الميزات الحساسة المعطلة افتراضياً).
        return default_feature_enabled(feature)

    for feature in PLAN_FEATURE_LABELS:
        resolved[feature] = feature_state(feature)
    return resolved


def get_plan(plan_key: str) -> dict:
    """
    إرجاع بيانات الخطة بناءً على مفتاحها.
    نحاول جلبها من قاعدة البيانات الأساسية (Core DB) أولاً.
    يتم استخدام session منفصلة لضمان الوصول لقاعدة البيانات الأساسية حتى لو كان هناك Tenant نشط.
    """
    try:
        from extensions import db
        from models.core.subscription_plan import SubscriptionPlan
        from sqlalchemy.orm import sessionmaker
        
        # الوصول للمحرك الافتراضي (Core DB) مباشرة
        engine = db.engine 
        Session = sessionmaker(bind=engine)
        session = Session()
        
        try:
            plan = session.query(SubscriptionPlan).filter_by(plan_key=plan_key).first()
            if plan:
                data = plan.to_dict()
                data["features"] = resolve_plan_features(
                    plan.plan_key, data.get("features")
                )
                return data
        finally:
            session.close()
    except Exception as e:
        # في حالة الفشل (مثلاً قبل تهيئة قاعدة البيانات)، نعود للقيم الثابتة
        pass
        
    data = dict(PLAN_DEFINITIONS.get(plan_key, _DEFAULT_PLAN))
    data["features"] = resolve_plan_features(
        data.get("key", plan_key), data.get("features")
    )
    return data


def has_feature(plan_key: str, feature: str) -> bool:
    """
    التحقق إذا كانت الخطة تدعم ميزة معينة.
    إذا الميزة غير موجودة في قاعدة البيانات، نرجع للتعريف الثابت في PLAN_DEFINITIONS.
    """
    plan = get_plan(plan_key)
    features = plan.get("features", {})
    if feature in features:
        return bool(features[feature])
    fallback = PLAN_DEFINITIONS.get(plan_key, _DEFAULT_PLAN)
    return bool(fallback.get("features", {}).get(feature, False))


def check_user_limit(plan_key: str, current_user_count: int) -> bool:
    """True إذا أمكن إضافة مستخدم جديد."""
    plan = get_plan(plan_key)
    limit = plan["max_users"]
    if limit is None:
        return True
    return current_user_count < limit


def check_order_limit(plan_key: str, monthly_order_count: int) -> bool:
    """True إذا لم يتجاوز عدد الطلبات الشهرية الحد المسموح."""
    plan = get_plan(plan_key)
    limit = plan["max_orders_monthly"]
    if limit is None:
        return True
    return monthly_order_count < limit


def get_usage_stats(tenant) -> dict:
    """
    تحسب إحصائيات الاستخدام لـ Tenant معين.
    يُستدعى من لوحة التحكم لعرض نسبة الاستهلاك.
    """
    from models.employee import Employee
    from models.order_item import OrderItem
    from datetime import datetime

    plan = get_plan(tenant.plan_key)

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # عدد الموظفين الحاليين
    user_count = Employee.query.filter_by(tenant_id=tenant.id).count()

    # طلبات الشهر الحالي (نفترض أن OrderItem له created_at و tenant_id)
    try:
        from models.order_item import OrderItem
        monthly_orders = OrderItem.query.filter(
            OrderItem.created_at >= month_start
        ).count()
    except Exception:
        monthly_orders = 0

    max_users = plan["max_users"]
    max_orders = plan["max_orders_monthly"]

    return {
        "plan":          plan,
        "user_count":    user_count,
        "max_users":     max_users,
        "users_pct":     round(user_count / max_users * 100) if max_users else 0,
        "users_ok":      max_users is None or user_count < max_users,
        "monthly_orders":  monthly_orders,
        "max_orders":    max_orders,
        "orders_pct":    round(monthly_orders / max_orders * 100) if max_orders else 0,
        "orders_ok":     max_orders is None or monthly_orders < max_orders,
    }
