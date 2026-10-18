import json
from collections import OrderedDict


TENANT_FEATURE_GROUPS = [
    {
        "key": "main",
        "label": "الرئيسية والبيع",
        "features": [
            ("dashboard", "لوحة القيادة"),
            ("executive_dashboard", "لوحة المدير التنفيذي"),
            ("notes", "دفتر الملاحظات"),
            ("pos", "نقطة البيع"),
            ("quick_sale", "بيع سريع"),
            ("quick_sale_advanced_checkout", "تسديد متقدم وبيانات زبون في البيع السريع"),
            ("trade_in_sales", "الاستبدال"),
            ("orders", "الطلبات"),
            ("orders_all", "كل الطلبات"),
            ("orders_placed", "طلبات تم الطلب"),
            ("orders_packed", "طلبات تم التجهيز"),
            ("orders_shipping", "طلبات قيد الشحن"),
            ("orders_delivered", "طلبات تم التسليم"),
            ("orders_returned", "الطلبات الراجعة/الملغاة"),
            ("orders_reports", "تقارير الطلبات"),
            ("orders_printing", "طباعة الطلبات والتقارير"),
        ],
    },
    {
        "key": "stock",
        "label": "المخزون والمشتريات",
        "features": [
            ("inventory", "المخزون"),
            ("inventory_products", "قائمة المنتجات"),
            ("inventory_ledger", "سجل حركة المخزون"),
            ("inventory_audit", "جرد المخزون"),
            ("inventory_add_product", "إضافة منتج"),
            ("inventory_reports", "تقارير الأصناف"),
            ("maintenance", "الصيانة"),
            ("purchases", "المشتريات"),
            ("suppliers", "الموردون"),
            ("supplier_statement", "كشف حساب المورد"),
            ("stock_transfers", "تحويلات المخزون"),
        ],
    },
    {
        "key": "contacts",
        "label": "العلاقات والموظفين",
        "features": [
            ("customers", "الزبائن"),
            ("customer_blacklist", "القائمة السوداء للزبائن"),
            ("customer_provinces", "مناطق الزبائن"),
            ("customer_credit", "ديون وتقسيط الزبائن"),
            ("agents", "مناديب التوصيل"),
            ("agents_pending_execution", "تنفيذ كشوف المندوب"),
            ("employees", "الموظفون"),
            ("employee_page_warnings", "تحذير البيجات"),
            ("payroll", "الرواتب"),
            ("employee_roles", "أدوار وصلاحيات الموظفين"),
            ("pages", "البيجات"),
        ],
    },
    {
        "key": "money",
        "label": "المال والتقارير",
        "features": [
            ("shipping", "شركات النقل"),
            ("shipping_company_returns", "مرتجع شركة النقل"),
            ("shipping_reports", "تقارير التوصيل"),
            ("delivery_archive", "أرشيف التوصيل"),
            ("delivery_agent_portal", "بوابة مندوب التوصيل"),
            ("expenses", "المصروفات"),
            ("receipts", "القبض والتسديدات"),
            ("cash", "الصندوق"),
            ("accounts", "دفتر الحسابات"),
            ("fixed_assets", "الأصول"),
            ("rotating_savings", "الجمعيات والسلف"),
            ("installments", "نظام الأقساط"),
            ("installments_dashboard", "لوحة الأقساط"),
            ("installments_products", "منتجات الأقساط"),
            ("installments_applications", "طلبات الأقساط"),
            ("installments_contracts", "عقود ودفعات الأقساط"),
            ("installments_overdue", "متأخرات الأقساط"),
            ("installments_reports", "تقارير الأقساط"),
            ("installments_settings", "إعدادات الأقساط"),
            ("reports", "التقارير"),
            ("reports_daily", "تقرير اليوم"),
            ("reports_monitors", "مركز المراقبة"),
            ("reports_financial", "التقرير المالي"),
            ("reports_sales", "تقارير المبيعات"),
            ("reports_profit", "تقارير الأرباح"),
        ],
    },
    {
        "key": "ai",
        "label": "الذكاء والأنظمة",
        "features": [
            ("ai_assistant", "ميزات الذكاء الاصطناعي"),
            ("investments", "مستشار الاستثمار"),
            ("assistant_chat", "المساعد الذكي"),
            ("ai_sales", "موظف المبيعات AI"),
            ("ai_workspace", "مساحة LEON"),
            ("messages", "الرسائل"),
            ("mobile_app", "تطبيق الهاتف"),
            ("mobile_app_videos", "فيديوهات تطبيق الهاتف"),
            ("mobile_app_users", "مستخدمي تطبيق الهاتف"),
            ("mobile_app_comments", "تعليقات تطبيق الهاتف"),
            ("mobile_app_rewards", "مكافآت تطبيق الهاتف"),
            ("mobile_app_coupons", "كوبونات تطبيق الهاتف"),
            ("mobile_app_flags", "أعلام ميزات تطبيق الهاتف"),
            ("mobile_app_design", "تصميم تطبيق الهاتف"),
            ("mobile_app_notifications", "إشعارات تطبيق الهاتف"),
            ("mobile_app_analytics", "تحليلات تطبيق الهاتف"),
            ("storefront", "رابط المتجر"),
        ],
    },
    {
        "key": "admin",
        "label": "الإدارة والتخصيص",
        "features": [
            ("permissions", "الصلاحيات"),
            ("activity", "سجل النشاط"),
            ("settings", "الإعدادات"),
            ("settings_system", "إعدادات النظام والموظفين"),
            ("settings_invoice", "إعدادات الفاتورة"),
            ("settings_appearance", "مظهر الفاتورة"),
            ("settings_branches", "إعدادات الفروع"),
            ("settings_storefront", "إعدادات المتجر"),
            ("settings_database_repair", "إصلاح قاعدة البيانات"),
            ("invoice_templates", "قوالب الفواتير"),
            ("beauty", "صفحات مركز التجميل"),
            ("beauty_appointments", "مواعيد مركز التجميل"),
            ("beauty_services", "خدمات مركز التجميل"),
            ("beauty_sessions", "جلسات مركز التجميل"),
            ("beauty_alerts", "تنبيهات مركز التجميل"),
            ("beauty_accounts", "حسابات مركز التجميل"),
            ("beauty_clients", "سجل عملاء التجميل"),
            ("wholesale", "تجارة الجملة"),
            ("wholesale_ops", "مركز عمليات الجملة"),
            ("wholesale_sales", "مبيعات الجملة"),
            ("wholesale_purchases", "مشتريات الجملة"),
            ("wholesale_receipts", "قبض الجملة"),
            ("wholesale_payments", "تسديد الجملة"),
            ("wholesale_customers", "عملاء الجملة"),
            ("wholesale_suppliers", "موردو الجملة"),
            ("wholesale_products", "منتجات الجملة"),
            ("wholesale_warehouses", "مخازن الجملة"),
            ("wholesale_transfers", "تحويل مخازن الجملة"),
            ("wholesale_accounts", "حسابات وصناديق الجملة"),
            ("wholesale_statement", "كشف حساب الجملة"),
            ("wholesale_expenses", "مصروفات الجملة"),
            ("wholesale_reports", "تقارير الجملة"),
            ("wholesale_settings", "إعدادات الجملة"),
            ("food", "نشاط المواد الغذائية"),
            ("food_dashboard", "لوحة المواد الغذائية"),
            ("food_cashier", "كاشير المواد الغذائية"),
            ("food_orders", "طلبات المواد الغذائية"),
            ("food_products", "منتجات المواد الغذائية"),
            ("food_purchases", "مشتريات المواد الغذائية"),
            ("food_inventory", "مخزن المواد الغذائية"),
            ("food_parties", "عملاء وموردو المواد الغذائية"),
            ("food_finance", "حركات المواد الغذائية المالية"),
            ("food_reports", "تقارير المواد الغذائية"),
            ("food_settings", "إعدادات المواد الغذائية"),
            ("hr", "نظام إدارة الموارد البشرية"),
            ("hr_dashboard", "لوحة الموارد البشرية"),
            ("hr_employees", "ملفات الموظفين HR"),
            ("hr_attendance", "الحضور والانصراف"),
            ("hr_leaves", "الإجازات والطلبات"),
            ("hr_payroll", "رواتب الموارد البشرية"),
            ("hr_cash", "صندوق الموارد البشرية"),
            ("hr_reports", "تقارير الموارد البشرية"),
            ("hr_settings", "إعدادات وأقسام HR"),
            ("clinics", "نشاط العيادات والمراكز الطبية"),
            ("clinics_dashboard", "لوحة العيادة"),
            ("clinics_reception", "استقبال العيادة"),
            ("clinics_appointments", "مواعيد العيادة"),
            ("clinics_patients", "مرضى العيادة"),
            ("clinics_visits", "زيارات العيادة"),
            ("clinics_clinical", "السجل الطبي"),
            ("clinics_clinical_shared_read", "قراءة السجل السريري للأطباء الآخرين"),
            ("clinics_billing", "فواتير ومدفوعات العيادة"),
            ("clinics_inventory", "مخزون العيادة"),
            ("clinics_admin", "إدارة الأطباء والخدمات"),
            ("clinics_reports", "تقارير العيادة"),
            ("clinics_settings", "إعدادات العيادة"),
            ("dental.view", "وحدة الأسنان"),
            ("dental.chart.view", "عرض مخطط الأسنان"),
            ("dental.chart.edit", "تعديل مخطط الأسنان"),
            ("dental.treatment_plan.view", "عرض خطط علاج الأسنان"),
            ("dental.treatment_plan.create", "إنشاء خطط علاج الأسنان"),
            ("dental.treatment_plan.edit", "تعديل خطط علاج الأسنان"),
            ("dental.treatment_plan.delete", "إلغاء أو أرشفة خطط علاج الأسنان"),
            ("dental.treatment_plan.approve", "اعتماد خطط علاج الأسنان"),
            ("dental.sessions.view", "عرض جلسات الأسنان"),
            ("dental.sessions.create", "إنشاء جلسات الأسنان"),
            ("dental.sessions.edit", "تعديل جلسات الأسنان"),
            ("dental.sessions.complete", "إكمال جلسات الأسنان"),
            ("dental.images.view", "عرض صور الأسنان"),
            ("dental.images.upload", "رفع صور الأسنان"),
            ("dental.images.delete", "حذف بيانات صور الأسنان"),
            ("dental.reports.view", "تقارير الأسنان"),
        ],
    },
]


TENANT_FEATURE_LABELS = OrderedDict(
    (key, label)
    for group in TENANT_FEATURE_GROUPS
    for key, label in group["features"]
)

DEFAULT_DISABLED_FEATURES = {"trade_in_sales", "quick_sale_advanced_checkout", "shipping_company_returns"}


def default_feature_enabled(key: str, *, business_type: str = "general") -> bool:
    """Default state before a company has an explicit feature override."""
    if business_type == "starter_business":
        from utils.starter_business import DEFAULT_FEATURES

        return str(key or "") in DEFAULT_FEATURES
    if str(key or "") in DEFAULT_DISABLED_FEATURES:
        return False
    return True


def normalize_feature_overrides(value) -> dict:
    if not value:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return {}
    if not isinstance(value, dict):
        return {}
    allowed = set(TENANT_FEATURE_LABELS.keys())
    return {str(key): bool(val) for key, val in value.items() if str(key) in allowed}


def feature_overrides_json(overrides: dict) -> str:
    return json.dumps(normalize_feature_overrides(overrides), ensure_ascii=False)


def tenant_feature_enabled(key: str, *, default: bool | None = None) -> bool:
    """Read one feature flag from the active tenant DB.

    Sensitive opt-in features such as trade-in sales remain disabled when the
    tenant row/override is missing or cannot be read.
    """
    feature_key = str(key or "").strip()
    if default is None:
        default = default_feature_enabled(feature_key)
    cache = None
    try:
        from flask import g, has_app_context

        if has_app_context():
            cache = getattr(g, "_tenant_feature_enabled_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                g._tenant_feature_enabled_cache = cache
            if feature_key in cache:
                return bool(cache[feature_key])
    except Exception:
        cache = None
    try:
        from models.tenant import Tenant

        tenant = Tenant.query.first()
        if not tenant:
            enabled = bool(default)
            if cache is not None:
                cache[feature_key] = enabled
            return enabled
        overrides = normalize_feature_overrides(
            getattr(tenant, "feature_overrides_json", None)
        )
        if feature_key in overrides:
            enabled = bool(overrides[feature_key])
        else:
            enabled = default_feature_enabled(
                feature_key,
                business_type=getattr(tenant, "business_type", None) or "general",
            )
        if cache is not None:
            cache[feature_key] = enabled
        return enabled
    except Exception:
        return bool(default)


def ensure_tenant_feature_overrides_column(engine) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "tenant" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("tenant")}
    if "feature_overrides_json" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE tenant ADD COLUMN feature_overrides_json TEXT"))
