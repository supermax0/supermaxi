import json
from collections import OrderedDict


TENANT_FEATURE_GROUPS = [
    {
        "key": "main",
        "label": "الرئيسية والبيع",
        "features": [
            ("dashboard", "لوحة القيادة"),
            ("executive_dashboard", "لوحة المدير التنفيذي"),
            ("pos", "نقطة البيع"),
            ("quick_sale", "بيع سريع"),
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
            ("shipping_reports", "تقارير التوصيل"),
            ("delivery_archive", "أرشيف التوصيل"),
            ("delivery_agent_portal", "بوابة مندوب التوصيل"),
            ("expenses", "المصروفات"),
            ("cash", "الصندوق"),
            ("accounts", "دفتر الحسابات"),
            ("fixed_assets", "الأصول"),
            ("rotating_savings", "الجمعيات والسلف"),
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
        ],
    },
]


TENANT_FEATURE_LABELS = OrderedDict(
    (key, label)
    for group in TENANT_FEATURE_GROUPS
    for key, label in group["features"]
)


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


def ensure_tenant_feature_overrides_column(engine) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "tenant" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("tenant")}
    if "feature_overrides_json" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE tenant ADD COLUMN feature_overrides_json TEXT"))
