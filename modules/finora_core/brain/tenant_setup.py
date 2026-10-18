"""Reviewed tenant configuration. The target always comes from the conversation's customer binding."""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from utils.tenant_feature_flags import TENANT_FEATURE_LABELS, normalize_feature_overrides, feature_overrides_json, default_feature_enabled
from .extract import normalize

PROFILE_TYPES = {"flowers": "starter_business", "wholesale": "wholesale", "grocery": "food_wholesale_retail", "clinic": "clinics", "dental_clinic": "clinics"}
PROFILE_TYPES.update({key: key for key in ("general", "starter_business", "beauty_center", "hr_management")})
PROFILE_PATTERNS = (("hr_management", r"موارد (?:ال)?بشريه|شوون الموظفين|اداره الموظفين"), ("beauty_center", r"مركز تجميل|صالون|بيوتي|سبا"), ("starter_business", r"اعمال مبسطه|اعمال بسيطه|نشاط مبسط"), ("general", r"شركه عامه|نشاط عام"), ("flowers", r"ورد|زهور|هدايا"), ("grocery", r"غذا|بقال|ماركت"), ("wholesale", r"جمله"), ("dental_clinic", r"اسنان"), ("clinic", r"عياده|عيادات"))

PROFILES = {
    "general": {"label": "شركة عامة", "needs": "البيع والطلبات، المخزون، المشتريات، الزبائن، الحسابات والتقارير", "defaults": True},
    "starter_business": {"label": "إدارة أعمال مبسّطة", "needs": "البيع السريع، الطلبات، مخزون المنتجات، الموردون والحركات المالية", "defaults": True},
    "beauty_center": {"label": "مركز تجميل", "needs": "المواعيد، الخدمات والجلسات، العملاء، المنتجات والحسابات والتقارير", "prefixes": ("beauty", "inventory", "reports", "installments"), "keys": {"maintenance", "customers", "customer_blacklist", "customer_provinces", "customer_credit", "expenses", "cash", "accounts", "payroll", "employee_page_warnings", "storefront"}},
    "hr_management": {"label": "إدارة الموارد البشرية", "needs": "ملفات الموظفين، الحضور والانصراف، الإجازات، الرواتب، الصندوق والتقارير", "prefixes": ("hr",), "keys": set()},
    "flowers": {"label": "محل ورد وهدايا", "needs": "طلبات المناسبات، البيع، الزبائن، مخزون الورد والهدايا والمشتريات", "prefixes": ("inventory", "orders", "reports"), "keys": {"pos", "quick_sale", "purchases", "suppliers", "supplier_statement", "customers", "customer_credit", "cash", "expenses", "receipts"}},
    "wholesale": {"label": "تاجر جملة", "needs": "بيع وشراء الجملة، المخازن والتحويلات، الموردون، الديون وكشوف الحساب", "prefixes": ("wholesale", "inventory", "reports"), "keys": {"customers", "customer_credit", "purchases", "suppliers", "cash", "accounts", "expenses", "receipts", "stock_transfers"}},
    "grocery": {"label": "مواد غذائية", "needs": "الكاشير، المنتجات، المشتريات، المخزون، الموردون والحركات المالية", "prefixes": ("food",), "keys": {"customers", "suppliers", "cash", "expenses", "receipts"}},
    "clinic": {"label": "عيادة", "needs": "المرضى، المواعيد، زيارات الطبيب، الفواتير والتقارير", "prefixes": ("clinics",), "keys": set()},
    "dental_clinic": {"label": "عيادة أسنان", "needs": "صفحات العيادة مع مخطط الأسنان وخطط العلاج والجلسات والصور", "prefixes": ("clinics", "dental"), "keys": set()},
}
PROTECTED = {"dashboard", "notes", "employees", "employee_roles", "permissions", "settings", "settings_system", "settings_invoice", "settings_appearance", "settings_branches", "settings_database_repair", "messages", "activity", "trade_in_sales", "shipping_company_returns"}
PERMISSIONS = ("can_see_orders", "can_see_orders_placed", "can_see_orders_delivered", "can_see_orders_returned", "can_see_orders_shipped", "can_edit_price", "can_see_reports", "can_manage_inventory", "can_see_expenses", "can_manage_suppliers", "can_manage_customers", "can_see_accounts", "can_see_financial")
PRESETS = {
    "sales": {"label": "مبيعات وكاشير", "allow": {"can_see_orders", "can_see_orders_placed", "can_see_orders_delivered", "can_see_orders_returned", "can_see_orders_shipped", "can_manage_customers"}},
    "inventory": {"label": "مخزون ومشتريات", "allow": {"can_manage_inventory", "can_manage_suppliers"}},
    "accounting": {"label": "محاسبة وتقارير", "allow": {"can_see_reports", "can_see_expenses", "can_see_accounts", "can_see_financial"}},
    "reception": {"label": "استقبال وخدمة عملاء", "allow": {"can_manage_customers", "can_see_orders", "can_see_orders_placed"}},
}
ALIASES = {"inventory": ("المخزون", "المخزن"), "customers": ("الزبائن", "العملاء"), "suppliers": ("الموردين", "الموردون"), "purchases": ("المشتريات",), "pos": ("نقطة البيع", "نقطه البيع"), "reports": ("التقارير",), "expenses": ("المصاريف", "المصروفات"), "cash": ("الصندوق",), "orders": ("الطلبات",), "food_cashier": ("كاشير المواد الغذائية",), "clinics_appointments": ("المواعيد",), "dental.view": ("الاسنان",)}


def error(code, text):
    from .tools import ToolError
    return ToolError(code, text)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def profile_features(profile):
    preset = PROFILES[profile]
    business_type = PROFILE_TYPES[profile]
    return {key: activity_allows(key, business_type) and (
        default_feature_enabled(key, business_type=business_type) if preset.get("defaults") else
        key in preset["keys"] or any(key == prefix or key.startswith(prefix + "_") or key.startswith(prefix + ".") for prefix in preset["prefixes"]))
        for key in TENANT_FEATURE_LABELS if key not in PROTECTED}


def protected_role(name, permissions):
    return bool(re.search(r"admin|مدير|مالك|manage_(?:users|employees|roles|permissions)|delete_tenant", name + " " + " ".join(permissions), re.I))


def activity_allows(key, business_type):
    required = "clinics" if key.startswith(("clinics", "dental.")) else "wholesale" if key.startswith("wholesale") else "food_wholesale_retail" if key.startswith("food") else "hr_management" if key == "hr" or key.startswith("hr_") else "beauty_center" if key == "beauty" or key.startswith("beauty_") else None
    if required:
        return business_type == required
    return business_type not in {"clinics", "hr_management"} or key in PROTECTED


def bound_tenant(s, customer):
    from models.core.tenant import Tenant
    from ..store import house_slug
    from extensions_tenant import get_tenant_db_path, is_valid_tenant_slug
    slug = customer.tenant_slug
    if not slug or not is_valid_tenant_slug(slug) or slug == house_slug():
        raise error("ACCOUNT_NOT_LINKED", "اربط حساب العميل وتحقق من ملكيته أولاً؛ حساب فينورا الداخلي محمي")
    tenant = s.query(Tenant).filter_by(slug=slug).one_or_none()
    if tenant is None or not tenant.is_active or not Path(get_tenant_db_path(slug)).is_file():
        raise error("ACCOUNT_UNAVAILABLE", "حساب العميل غير موجود أو متوقف؛ لم تُنشأ قاعدة بيانات بديلة")
    return tenant


@contextmanager
def local_session(s, customer):
    from extensions_tenant import get_tenant_engine
    tenant = bound_tenant(s, customer)
    with Session(get_tenant_engine(tenant.slug), expire_on_commit=False) as local:
        try:
            yield tenant, local
        except SQLAlchemyError as exc:
            local.rollback()
            raise error("ACCOUNT_SCHEMA", "تعذر قراءة أو حفظ إعدادات حساب العميل؛ يحتاج مراجعة الفريق") from exc


def _read(tenant, local):
    from models.tenant import Tenant as LocalTenant
    from models.employee import Employee
    from models.role import Role
    rows = local.query(LocalTenant).limit(2).all()
    if len(rows) != 1:
        raise error("ACCOUNT_SCHEMA", "تعذر تحديد سجل الشركة بشكل فريد داخل حساب العميل")
    row = rows[0]
    if local.query(Employee).count() > 100 or local.query(Role).count() > 100:
        raise error("ACCOUNT_REVIEW", "الحساب يتجاوز حجم المراجعة المدعوم؛ يحتاج ترتيباً من المشرف")
    overrides = normalize_feature_overrides(row.feature_overrides_json)
    # Subscription ceilings are immutable here; company switches cannot grant paid entitlements.
    from utils.plan_limits import get_plan
    plan_features = get_plan(row.plan_key or "basic").get("features", {})
    features = [{"key": key, "label": label, "enabled": activity_allows(key, row.business_type) and bool(plan_features.get(key, True)) and overrides.get(key, default_feature_enabled(key, business_type=row.business_type)),
                 "available": bool(plan_features.get(key, True)), "protected": key in PROTECTED} for key, label in TENANT_FEATURE_LABELS.items()]
    employees = [{"id": employee.id, "name": employee.name, "username": employee.username, "owner": employee.role == "admin" or any(protected_role(role.name, [p.name for p in role.permissions]) for role in employee.roles), "active": bool(employee.is_active),
                  "permissions": {key: bool(getattr(employee, key)) for key in PERMISSIONS}, "roleIds": sorted(role.id for role in employee.roles)}
                 for employee in local.query(Employee).order_by(Employee.id).limit(100).all()]
    roles = [{"id": role.id, "name": role.name, "permissions": sorted(p.name for p in role.permissions)} for role in local.query(Role).order_by(Role.id).limit(100).all()]
    return row, {"tenantSlug": tenant.slug, "companyName": tenant.name, "businessType": row.business_type, "coreBusinessType": tenant.business_type, "features": features, "employees": employees, "roles": roles, "overrides": overrides}


def inspect_account(s, customer):
    with local_session(s, customer) as (tenant, local):
        _, state = _read(tenant, local)
        state["version"] = digest(state)
        return state


def build_configuration(s, customer, action):
    state = inspect_account(s, customer)
    operation = action.get("operation")
    updates, permission_updates, role_ids, unavailable = {}, {}, None, []
    employee_id, employee_name, permission_changes, role_changes, business_type, business_change = None, None, [], None, None, None
    profile = action.get("profile")
    features = {row["key"]: row for row in state["features"]}
    if operation == "profile":
        if not isinstance(profile, str):
            raise error("INVALID_PROFILE", "اختر اسم قالب بصيغة صحيحة")
        if profile not in PROFILES:
            raise error("UNKNOWN_PROFILE", "نوع النشاط غير موجود؛ اختر نشاطاً موثقاً")
        business_type = PROFILE_TYPES[profile]
        from routes.superadmin import BUSINESS_TYPES
        business_change = {"before": BUSINESS_TYPES.get(state["businessType"], state["businessType"]), "after": BUSINESS_TYPES[business_type]}
        updates = profile_features(profile)
        unavailable = [{"key": key, "label": features[key]["label"]} for key, enabled in updates.items() if enabled and not features[key]["available"]]
        updates = {key: value and features[key]["available"] for key, value in updates.items()}
        from utils.plan_limits import PLAN_FEATURE_PARENTS
        for key in updates:
            parent, visited = PLAN_FEATURE_PARENTS.get(key), set()
            while parent in features and parent not in visited:
                visited.add(parent)
                if not updates.get(parent, features[parent]["enabled"]):
                    updates[key] = False
                parent = PLAN_FEATURE_PARENTS.get(parent)
        title = PROFILES[profile]["label"]
    elif operation == "feature":
        key, enabled = action.get("feature"), action.get("enabled")
        if key not in features or type(enabled) is not bool or key in PROTECTED:
            raise error("UNSUPPORTED_FEATURE", "الميزة غير موجودة أو محمية؛ لن تُضاف ميزة وهمية")
        if enabled and not features[key]["available"]:
            raise error("PLAN_LIMIT", "هذه الميزة خارج باقة العميل؛ يلزم تدخل المشرف")
        if enabled and not activity_allows(key, state["businessType"]):
            raise error("ACTIVITY_REQUIRED", "هذا القسم يحتاج نوع النشاط المناسب؛ راجع تجهيز النشاط أولاً")
        updates[key] = enabled
        from utils.plan_limits import PLAN_FEATURE_PARENTS
        if enabled:
            parent = PLAN_FEATURE_PARENTS.get(key)
            while parent in features and parent not in updates:
                if not features[parent]["available"]:
                    raise error("PLAN_LIMIT", "القسم الرئيسي خارج باقة العميل")
                updates[parent] = True
                parent = PLAN_FEATURE_PARENTS.get(parent)
        else:
            updates.update({child: False for child in features if child.startswith(key + "_") or child.startswith(key + ".")})
        title = ("إظهار " if enabled else "إخفاء ") + features[key]["label"]
    elif operation == "advisory":
        from .setup_advisor import recommendation
        advice = recommendation(s, customer, action.get("advice_ref"), state, action.get("advice_version"))
        updates, unavailable, business_type = advice["updates"], advice["unavailable"], advice["business_type"]
        from routes.superadmin import BUSINESS_TYPES
        business_change = {"before": BUSINESS_TYPES.get(state["businessType"], state["businessType"]), "after": BUSINESS_TYPES[business_type]}
        title = "تجهيز مخصص: " + advice["activity"]
    elif operation == "permissions":
        employee_id = action.get("employee_id")
        if type(employee_id) is not int:
            raise error("INVALID_USER", "اختر موظفاً من الحساب المرتبط")
        employee = next((row for row in state["employees"] if row["id"] == employee_id), None)
        preset_key = action.get("permission_preset")
        if employee is None or employee["owner"] or not employee["active"] or preset_key not in PRESETS:
            raise error("PROTECTED_USER", "اختر موظفاً فعالاً من حساب العميل؛ صلاحيات مالك الحساب محمية")
        permission_updates = {key: key in PRESETS[preset_key]["allow"] for key in PERMISSIONS}
        employee_name = employee["name"]
        permission_changes = [{"key": key, "before": employee["permissions"][key], "after": value} for key, value in permission_updates.items()]
        requested_roles = action.get("role_ids")
        if requested_roles is not None:
            if not isinstance(requested_roles, list) or any(type(key) is not int for key in requested_roles):
                raise error("INVALID_ROLE", "الأدوار غير صالحة")
            roles = {role["id"]: role for role in state["roles"]}
            if any(key not in roles or protected_role(roles[key]["name"], roles[key]["permissions"]) for key in requested_roles):
                raise error("PROTECTED_ROLE", "لا يمكن منح دور إداري محمي بهذه الأداة")
            role_ids = sorted(set(requested_roles))
        role_names = {row["id"]: row["name"] for row in state["roles"]}
        role_changes = {"before": [role_names[key] for key in employee["roleIds"]], "after": [role_names[key] for key in (employee["roleIds"] if role_ids is None else role_ids)]}
        title = f"صلاحيات {employee['name']} — {PRESETS[preset_key]['label']}"
    else:
        raise error("INVALID_OPERATION", "نوع إعداد الحساب غير صالح")
    changes = [{"key": key, "label": features[key]["label"], "before": features[key]["enabled"], "after": value} for key, value in updates.items() if features[key]["enabled"] != value]
    if operation == "advisory":
        reasons = {row["key"]: row["reason"] for row in advice["recommendations"]}
        for row in changes:
            row["label"] += " — " + reasons.get(row["key"], "قسم غير مطلوب حسب إجابات العميل؛ صفحات الإدارة تبقى محمية")
    return {"customer_id": customer.id, "tenant_slug": state["tenantSlug"], "expected_version": state["version"], "operation": operation,
            "profile": profile if operation == "profile" else None, "feature": action.get("feature") if operation == "feature" else None,
            "enabled": action.get("enabled") if operation == "feature" else None, "employee_id": employee_id,
            "permission_preset": action.get("permission_preset") if operation == "permissions" else None, "role_ids": role_ids,
            "feature_updates": updates, "permission_updates": permission_updates, "title": title, "changes": changes,
            "employee_name": employee_name, "permission_changes": permission_changes, "role_changes": role_changes, "unavailable_features": unavailable,
            "business_type": business_type, "business_change": business_change,
            **({"advice_ref": str(action["advice_ref"]), "advice_version": advice["version"]} if operation == "advisory" else {})}


def apply_configuration(s, customer, args):
    if args["customer_id"] != customer.id or args["tenant_slug"] != customer.tenant_slug:
        raise error("SCOPE_CHANGED", "ربط العميل تغيّر؛ راجع خطة جديدة")
    # Reconstruct the plan from trusted catalogue/state, never execute arbitrary supplied property names.
    current = build_configuration(s, customer, args)
    if digest(current) != digest(args):
        raise error("PLAN_CHANGED", "تغيّرت إعدادات الحساب أو الخطة؛ راجع من جديد")
    # The Core savepoint rolls metadata back if the isolated company transaction fails.
    with s.begin_nested(), local_session(s, customer) as (tenant, local):
        if local.get_bind().dialect.name == "sqlite":
            local.connection().exec_driver_sql("BEGIN IMMEDIATE")
        row, state = _read(tenant, local)
        if digest(state) != args["expected_version"]:
            raise error("PLAN_CHANGED", "إعدادات الحساب تغيّرت أثناء التنفيذ")
        row.feature_overrides_json = feature_overrides_json({**state["overrides"], **args["feature_updates"]})
        if args["business_type"] is not None:
            row.business_type = args["business_type"]
            tenant.business_type = args["business_type"]
            s.flush()
        if args["employee_id"] is not None:
            from models.employee import Employee
            from models.role import Role
            employee = local.get(Employee, args["employee_id"])
            if employee is None or employee.role == "admin":
                raise error("PROTECTED_USER", "المستخدم غير متاح للتعديل")
            for key, value in args["permission_updates"].items():
                setattr(employee, key, value)
            if args["role_ids"] is not None:
                employee.roles = local.query(Role).filter(Role.id.in_(args["role_ids"])).all()
        local.commit()
    # Keep tenant engines in use; visibility caches are request-local and refresh on the next request.
    after = inspect_account(s, customer)
    return {"tenant_slug": tenant.slug, "operation": args["operation"], "feature_updates": args["feature_updates"],
            "employee_id": args["employee_id"], "permission_updates": args["permission_updates"], "role_ids": args["role_ids"], "version": after["version"]}


def verified(s, customer, args, data, **_):
    state = inspect_account(s, customer)
    if customer.tenant_slug != data.get("tenant_slug"):
        return False
    if args["business_type"] is not None and (state["businessType"] != args["business_type"] or state["coreBusinessType"] != args["business_type"]):
        return False
    if any(state["overrides"].get(key) != value for key, value in args["feature_updates"].items()):
        return False
    if args["employee_id"] is not None:
        employee = next((row for row in state["employees"] if row["id"] == args["employee_id"]), None)
        return bool(employee and employee["permissions"] == args["permission_updates"] and (args["role_ids"] is None or employee["roleIds"] == args["role_ids"]))
    return True


def missing_profile_request(text):
    """Ground missing-template alerts in an explicit customer activity, never model/media guesses."""
    value = normalize(text)
    nouns = r"محل|متجر|تاجر|تجاره|مشروع|مركز|مكتب|مكتبه|ورشه|شركه|مصنع|مطعم|صيدليه|فندق|مزرعه|مخبز|صالون|عياده|عيادات|مقهي|مدرسه|حضانه|روضه"
    contexts = (
        r"(?:^|\s)(?:نشاطي|نشاطنا|نشاط العميل|نوع نشاطي|نوع النشاط|مجال عملي)\s*(?:هو|:)?\s+(.{2,160})",
        rf"(?:^|\s)و?(?:عندي|عدي|عدنا|لدي|لدينا)\s+((?:{nouns})\b.{{0,150}})",
        r"(?:رتب(?:لي)?|جهز(?:لي)?|اعداد)\s+(?:حساب(?:ي|نا)?|نظام(?:ي|نا)?)\s+لنشاط\s+(.{2,160})",
        rf"(?:رتب(?:لي)?|جهز(?:لي)?|اعداد)\s+(?:حساب(?:ي|نا)?|نظام(?:ي|نا)?)\s+(?:ل(?:نشاط\s+)?|لـ)?((?:{nouns})\b.{{0,150}})",
        rf"^((?:{nouns})\b.{{0,150}})$",
    )
    for pattern in contexts:
        match = re.search(pattern, value)
        if not match:
            continue
        activity = re.split(r"[،,.;\n]|\s+و?(?:اريد|احتاج|رقمي|عندي|عدي|عدنا|رتب|جهز|اخفي|اظهر|خلي|فعل|سوولي|سويلي)\b", match[1], maxsplit=1)[0].strip()
        if activity in {"محل", "متجر", "تاجر", "تجاره", "مشروع", "مركز", "مكتب", "شركه", "ورشه"}:
            continue  # Ask for the activity; an unspecified shop is not evidence of a missing template.
        if activity and not any(re.search(pattern, activity) for _, pattern in PROFILE_PATTERNS):
            return activity
    return None


def propose(text, state):
    """Only explicit customer requests authorize configuration proposals; media observations cannot call this."""
    value = normalize(text)
    if not re.search(r"رتب|جهز|فعل|اظهر|اخف|خلي|احتاج|صلاحيات|اعداد", value):
        return None
    if re.search(r"رتب|جهز|اعداد", value):
        for key, pattern in PROFILE_PATTERNS:
            if re.search(pattern, value):
                return {"type": "configure_tenant", "operation": "profile", "profile": key, "reason": text[:300]}
    if "صلاحيات" in value:
        matches = [row for row in state["employees"] if not row["owner"] and row["active"] and any(normalize(name) in value for name in (row["name"], row["username"]) if len(name) >= 3)]
        employee = matches[0] if len(matches) == 1 else None
        presets = (("inventory", r"مخزون|مخزن|مشتريات"), ("accounting", r"محاسب|حسابات"), ("reception", r"استقبال"), ("sales", r"مبيعات|كاشير"))
        for key, pattern in presets:
            if employee and re.search(pattern, value):
                return {"type": "configure_tenant", "operation": "permissions", "employee_id": employee["id"], "permission_preset": key, "reason": text[:300]}
        return None
    candidates = []
    for key, names in ALIASES.items():
        if key in TENANT_FEATURE_LABELS and any(normalize(name) in value for name in names):
            if state.get("businessType") == "clinics":
                key = {"reports": "clinics_reports", "inventory": "clinics_inventory", "customers": "clinics_patients"}.get(key, key)
            candidates.append(key)
    # Multiple features or ambiguous staff names need a human review rather than guessing the target.
    if len(candidates) == 1:
        return {"type": "configure_tenant", "operation": "feature", "feature": candidates[0], "enabled": not bool(re.search(r"اخف|ما احتاج|لا احتاج", value)), "reason": text[:300]}
    return None
