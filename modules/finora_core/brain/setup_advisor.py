"""Grounded, conversation-scoped setup consultation; no model output is executable configuration."""
from __future__ import annotations

import json
import re

from ..store import get_setting, set_setting
from .extract import normalize
from .tenant_setup import PROFILES, PROFILE_TYPES, PROFILE_PATTERNS, PROTECTED, digest, activity_allows, profile_features, error
from .models import FcConversationCustomer
from .observability import redact
from utils.tenant_feature_flags import TENANT_FEATURE_LABELS
from utils.plan_limits import PLAN_FEATURE_PARENTS, get_plan

QUESTIONS = {
    "category": "شغلك بيع منتجات، تقديم خدمات، لو الاثنين؟",
    "sales_mode": "بيعك مفرد، جملة، لو الاثنين؟",
    "installments": "تبيع بالتقسيط لو بدون تقسيط؟",
    "maintenance": "عندك صيانة للأجهزة أو المنتجات لو لا؟",
    "delivery": "تحتاج متابعة طلبات وتوصيل للزبائن لو لا؟",
}
SPECIAL = {"clinic", "dental_clinic", "beauty_center", "hr_management"}


def _key(customer, ref):
    return f"advisor:{customer.id}:{digest(str(ref))[:24]}"


def load(s, customer, ref):
    link = s.get(FcConversationCustomer, str(ref))
    if not link or link.customer_id != customer.id:
        raise error("ADVICE_SCOPE", "استشارة التجهيز لازم تكون من محادثة العميل نفسه")
    raw = get_setting(s, _key(customer, ref))
    if not raw:
        return None
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise error("ADVICE_INVALID", "استشارة التجهيز تحتاج إعادة إعداد")
    return data


def _save(s, customer, ref, draft):
    set_setting(s, _key(customer, ref), json.dumps(draft, ensure_ascii=False), "FINORA CORE")
    s.flush()


def wants_advice(text):
    return bool(re.search(r"تنصح|انصح|اقترح|اقتراح|توصي|شنو.*(?:احتاج|ميزات|صفحات)|(?:ميزات|صفحات).*(?:احتاج|مناسب)|استشاره.*تجهيز", normalize(text)))


def _answers(value, prefs, waiting):
    value = re.sub(r"\bما(عندي|عدي|عدنا|احتاج)", r"ما \1", value)
    out = dict(prefs)
    if re.search(r"(?:مفرد.*جمله|جمله.*مفرد|الاثنين|كلاهما)", value):
        out["sales_mode"] = "both"
        if waiting == "category":
            out["category"] = "mixed"
    elif re.search(r"مفرد|تجزيه", value):
        out["sales_mode"] = "retail"
    elif re.search(r"جمله", value):
        out["sales_mode"] = "wholesale"
    if re.search(r"منتجات.*خدمات|خدمات.*منتجات", value):
        out["category"] = "mixed"
    elif re.search(r"منتجات|بضايع|بضاعه", value):
        out["category"] = "products"
    elif re.search(r"خدمات", value):
        out["category"] = "services"
    for key, term in (("installments", r"تقسيط|اقساط"), ("maintenance", r"صيانه"), ("delivery", r"توصيل|شحن")):
        if re.search(term, value):
            out[key] = not bool(re.search(rf"(?:بدون|ما عندي|ما عدي|ما عدنا|ماكو|لا يوجد|ما احتاج|لا احتاج|لا)\s+(?:(?:بيع|خدمه|خدمات)\s+)?(?:بال|ال|ب)?(?:{term})", value))
    if waiting in {"installments", "maintenance", "delivery"}:
        if re.fullmatch(r"(?:نعم|اي|اي نعم|اجل|عندي|عدي|عدنا)[.!؟]?", value):
            out[waiting] = True
        elif re.fullmatch(r"(?:لا|كلا|ماكو|ما عندي|ما عدي|بدون)[.!؟]?", value):
            out[waiting] = False
    return out


def next_question(draft):
    if draft.get("profile") in SPECIAL:
        return None
    prefs = draft["preferences"]
    required = ["category"]
    if prefs.get("category") in {"products", "mixed"}:
        required += ["sales_mode", "installments", "maintenance"]
    required += ["delivery"]
    return next((key for key in required if key not in prefs), None)


def recommendation(s, customer, ref, state=None, expected=None):
    draft = load(s, customer, ref)
    if not draft or next_question(draft):
        raise error("ADVICE_INCOMPLETE", "أكمل أسئلة الاحتياج قبل تجهيز الحساب")
    version = digest(draft)
    if expected and expected != version:
        raise error("ADVICE_CHANGED", "احتياجات العميل تغيّرت؛ راجع اقتراحاً جديداً")
    from .approvals import TRIAL_PLAN_KEY
    available = {row["key"]: row["available"] for row in state["features"]} if state else get_plan(TRIAL_PLAN_KEY).get("features", {})
    prefs, profile = draft["preferences"], draft.get("profile")
    target = PROFILE_TYPES[profile] if profile else "general"
    if profile not in SPECIAL and prefs.get("sales_mode") in {"wholesale", "both"}:
        target = "wholesale"
    selected = {}

    def add(keys, reason):
        for key in keys:
            if key in TENANT_FEATURE_LABELS and key not in PROTECTED and activity_allows(key, target):
                selected[key] = reason

    def group(prefix, reason):
        add([key for key in TENANT_FEATURE_LABELS if key == prefix or key.startswith(prefix + "_") or key.startswith(prefix + ".")], reason)

    if profile in SPECIAL:
        add([key for key, on in profile_features(profile).items() if on], "قسم فعلي مناسب لطبيعة نشاطك حسب قالب فينورا")
        if profile in {"clinic", "dental_clinic"}:
            add(["clinics_reception", "clinics_appointments"], "حتى موظف الاستقبال ينظم الحجز ومواعيد الأطباء")
            add(["clinics_patients", "clinics_visits", "clinics_clinical"], "لحفظ ملفات المرضى والزيارات والسجل الطبي")
            add(["clinics_admin"], "لإدارة الأطباء والخدمات داخل العيادة")
            add(["clinics_billing", "clinics_reports"], "لمتابعة الفواتير والمدفوعات وتقارير العيادة")
            add(["clinics_inventory"], "لمتابعة مستلزمات العيادة والمخزون")
            if profile == "dental_clinic":
                add(["dental.chart.view", "dental.treatment_plan.view", "dental.sessions.view", "dental.images.view"],
                    "حتى طبيب الأسنان يتابع مخطط الأسنان وخطة العلاج والجلسات والصور")
    else:
        add(["customers", "cash", "expenses", "receipts", "accounts"], "لمتابعة الزبائن والحركات المالية اليومية")
        add(["reports", "reports_daily", "reports_sales", "reports_profit"], "حتى تتابع البيع والنتيجة اليومية والأرباح")
        if prefs.get("category") in {"products", "mixed"}:
            add(["inventory", "inventory_products", "inventory_add_product", "inventory_audit", "inventory_ledger", "inventory_reports", "purchases", "suppliers", "supplier_statement"], "لتنظيم المنتجات والكميات والمشتريات وحسابات الموردين")
            if prefs.get("sales_mode") != "wholesale":
                add(["quick_sale"], "لبيع المفرد وتسجيل الفاتورة بسرعة")
            if target == "wholesale":
                group("wholesale", "لبيع الجملة وإدارة مخازنها وديون العملاء؛ يحتاج نشاط تجارة الجملة")
            if prefs.get("installments"):
                group("installments", "لأنك تبيع بالتقسيط وتحتاج متابعة العقود والدفعات والمتأخرات")
                add(["customer_credit"], "لمتابعة المبالغ المتبقية على الزبائن")
            if prefs.get("maintenance"):
                add(["maintenance"], "لأنك تقدم صيانة وتحتاج تنظيم أعمالها داخل القسم الموجود")
        if prefs.get("delivery"):
            add(["orders", "orders_all", "orders_placed", "orders_delivered", "orders_returned", "orders_printing", "shipping", "shipping_companies", "shipping_reports"], "لمتابعة الطلبات وحالات تسليمها وشركات النقل")
    # Ancestors come from the actual plan catalogue. No protected page is changed.
    for key in list(selected):
        parent, visited = PLAN_FEATURE_PARENTS.get(key), set()
        while parent in TENANT_FEATURE_LABELS and parent not in visited:
            visited.add(parent)
            add([parent], selected[key])
            parent = PLAN_FEATURE_PARENTS.get(parent)
    updates = {key: key in selected and bool(available.get(key, True)) for key in TENANT_FEATURE_LABELS if key not in PROTECTED}
    for key in updates:
        parent, visited = PLAN_FEATURE_PARENTS.get(key), set()
        while parent in TENANT_FEATURE_LABELS and parent not in visited:
            visited.add(parent)
            if not available.get(parent, True) or (parent not in PROTECTED and not updates.get(parent, False)):
                updates[key] = False
            parent = PLAN_FEATURE_PARENTS.get(parent)
    rows = [{"key": key, "label": TENANT_FEATURE_LABELS[key], "reason": reason, "available": bool(updates[key])} for key, reason in selected.items()]
    return {"activity": draft["activity"], "version": version, "business_type": target, "updates": updates, "recommendations": rows,
            "unavailable": [{"key": row["key"], "label": row["label"]} for row in rows if not row["available"]]}


def consult(s, customer, ref, text, *, activity=None, state=None, shadow=False):
    """One question per turn. Customer answers change a draft; only an explicit request proposes execution."""
    value = normalize(text)
    if re.search(r"اخف|اظهر|صلاحيات", value):
        return None
    draft = load(s, customer, ref)
    if not draft and not wants_advice(text):
        return None
    profile = next((key for key, pattern in PROFILE_PATTERNS if re.search(pattern, value)), None)
    if draft and draft.get("waiting") == "activity":
        activity = None if profile else value[:160]
        draft = None
    elif draft and not wants_advice(text) and re.search(r"شلون|كيف|وين|شنو الفرق|مشكله|خلل", value):
        return None
    if not draft or (wants_advice(text) and activity and activity != draft["activity"]):
        if not activity and not profile:
            _save(s, customer, ref, {"schema": 1, "activity": "", "profile": None, "preferences": {}, "waiting": "activity"})
            return {"reply": "حتى أنصحك بصفحات مناسبة، شنو نوع نشاطك وشلون تشتغل؟", "action": None}
        name = redact(re.split(r"\s+(?:شنو|ممكن|هل|تنصح|شنهي)", activity or PROFILES[profile]["label"], maxsplit=1)[0][:160])
        # A missing activity cannot inherit a profile mentioned incidentally in the customer's requirements.
        profile = None if activity else profile
        prefs = {}
        if profile in {"flowers", "wholesale", "grocery", "starter_business"} or re.search(r"محل|متجر|ملابس|اجهزه|بيع|مطعم|صيدليه|ورد", name):
            prefs["category"] = "products"
        if profile == "wholesale":
            prefs["sales_mode"] = "wholesale"
        draft = {"schema": 1, "activity": name, "profile": profile, "preferences": prefs, "waiting": None}
    elif not draft.get("waiting") and not re.search(r"تنصح|اقترح|اقتراح|طبق|طبقه|جهز|تجريبي|سوولي|سويلي|اخلي|فعل|تقسيط|اقساط|صيانه|توصيل|مفرد|جمله|منتجات|خدمات", value):
        return None  # A consultation must not consume unrelated training or support messages.
    draft["preferences"] = _answers(value, draft["preferences"], draft.get("waiting"))
    draft["waiting"] = next_question(draft)
    _save(s, customer, ref, draft)
    if draft["waiting"]:
        return {"reply": QUESTIONS[draft["waiting"]], "action": None, "custom_activity": draft["activity"] if not draft.get("profile") else None}
    info = recommendation(s, customer, ref, state)
    apply = bool(re.search(r"طبق|جهز|فعل|سوولي|سويلي|حساب تجريبي", value))
    if re.search(r"(?:لا|ما|مو)\s+(?:ت?طبق|ت?جهز|ت?فعل|تسوي|تسويلي|تسوولي|اريد حساب)", value):
        apply = False
    if apply:
        if state:
            action = {"type": "configure_tenant", "operation": "advisory", "advice_ref": str(ref), "advice_version": info["version"], "reason": text[:300]}
        else:
            # Account creation remains a distinct, explicit request, with the existing contact/approval checks.
            action = {"type": "start_trial", "advice_ref": str(ref), "advice_version": info["version"], "reason": text[:300]} if re.search(r"حساب|تجريبي|سوولي|سويلي", value) else None
        return {"reply": "اقتراح التجهيز جاهز لمراجعة مشرف فينورا قبل التطبيق." if action else "اقتراحك جاهز. حتى أطبقه، يلزم ربط حسابك بعد التحقق أو تطلب إنشاء حساب تجريبي.", "action": action, "custom_activity": draft["activity"] if not draft.get("profile") else None}
    # Summarize groups to keep the customer reply simple; each row still carries its reason in the owner review.
    lines, seen = [], set()
    for row in info["recommendations"]:
        reason = row["reason"]
        if reason not in seen:
            seen.add(reason)
            labels = [item["label"] for item in info["recommendations"] if item["reason"] == reason][:4]
            lines.append("• " + "، ".join(labels) + ": " + reason)
    notice = "\nخارج الباقة الحالية وتحتاج مراجعة: " + "، ".join(row["label"] for row in info["unavailable"][:5]) if info["unavailable"] else ""
    return {"reply": f"لنشاطك «{info['activity']}» أقترح من ميزات فينورا الموجودة:\n" + "\n".join(lines) + notice + "\nإذا يناسبك، قل «جهز حسابي بهذا الاقتراح»؛ التطبيق يكون بعد مراجعة المشرف وعلى حسابك وحده.", "action": None, "custom_activity": draft["activity"] if not draft.get("profile") else None}
