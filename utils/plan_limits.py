"""
plan_limits.py — نظام حدود الخطط (SaaS Feature Gating)
كل خطة تحدد: عدد المستخدمين، الطلبات الشهرية، والميزات المسموح بها.
"""

# ===================================================
# تعريف خطط الاشتراك وحدودها وميزاتها
# ===================================================
PLAN_DEFINITIONS = {
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
            "messages":     False,  # نظام الرسائل
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
            "messages":     False,
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
            "messages":     True,
        },
    },
}

# Default fallback
_DEFAULT_PLAN = PLAN_DEFINITIONS["basic"]


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
                return plan.to_dict()
        finally:
            session.close()
    except Exception as e:
        # في حالة الفشل (مثلاً قبل تهيئة قاعدة البيانات)، نعود للقيم الثابتة
        pass
        
    return PLAN_DEFINITIONS.get(plan_key, _DEFAULT_PLAN)


def has_feature(plan_key: str, feature: str) -> bool:
    """
    التحقق إذا كانت الخطة تدعم ميزة معينة.
    """
    plan = get_plan(plan_key)
    features = plan.get("features", {})
    return features.get(feature, False)


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
