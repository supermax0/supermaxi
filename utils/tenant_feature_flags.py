import json
from collections import OrderedDict


TENANT_FEATURE_LABELS = OrderedDict([
    ("dashboard", "لوحة القيادة"),
    ("executive_dashboard", "لوحة المدير التنفيذي"),
    ("pos", "نقطة البيع والبيع السريع"),
    ("inventory", "المخزون"),
    ("inventory_audit", "جرد المخزون"),
    ("maintenance", "الصيانة"),
    ("purchases", "المشتريات"),
    ("suppliers", "الموردون"),
    ("customers", "الزبائن"),
    ("customer_blacklist", "القائمة السوداء للزبائن"),
    ("agents", "مناديب التوصيل"),
    ("employees", "الموظفون والرواتب"),
    ("pages", "البيجات"),
    ("orders", "الطلبات"),
    ("shipping", "شركات النقل"),
    ("expenses", "المصروفات"),
    ("cash", "الصندوق"),
    ("accounts", "دفتر الحسابات"),
    ("fixed_assets", "الأصول"),
    ("rotating_savings", "الجمعيات والسلف"),
    ("reports", "التقارير"),
    ("ai_assistant", "المساعد الذكي ومستشار الاستثمار"),
    ("ai_sales", "موظف المبيعات AI"),
    ("permissions", "الصلاحيات"),
    ("activity", "سجل النشاط"),
    ("settings", "الإعدادات"),
    ("invoice_templates", "قوالب الفواتير"),
    ("messages", "الرسائل"),
    ("ai_workspace", "مساحة LEON"),
    ("mobile_app", "تطبيق الهاتف"),
    ("beauty", "صفحات مركز التجميل"),
    ("beauty_accounts", "حسابات مركز التجميل"),
])


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
