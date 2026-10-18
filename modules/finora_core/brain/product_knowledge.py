"""Read-only product catalog and reviewed customer guides. Never reads tenant records or credentials."""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from utils.tenant_feature_flags import DEFAULT_DISABLED_FEATURES, TENANT_FEATURE_GROUPS

GUIDE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "product_guides.json"


def feature_business_type(key: str) -> str | None:
    for prefix, business in (("clinics", "clinics"), ("dental", "clinics"), ("beauty", "beauty_center"),
                             ("wholesale", "wholesale"), ("food", "food_wholesale_retail"),
                             ("hr", "hr_management")):
        if key == prefix or key.startswith((prefix + "_", prefix + ".")):
            return business
    return None


def applies(business_type: str | None, *, item_type: str | None, feature_keys: list[str] | None = None) -> bool:
    if business_type and item_type and business_type != item_type:
        return False
    if business_type == "starter_business" and feature_keys:
        from utils.starter_business import DEFAULT_FEATURES
        return bool(set(feature_keys) & DEFAULT_FEATURES)
    return True


@lru_cache(maxsize=1)
def guide_definitions() -> tuple[dict, ...]:
    return tuple(json.loads(GUIDE_PATH.read_text(encoding="utf-8"))["guides"])


def catalog_items(*, business_type: str | None = None):
    from .knowledge import KnowledgeItem

    items = []
    for group in TENANT_FEATURE_GROUPS:
        for key, label in group["features"]:
            scope = feature_business_type(key)
            if not applies(business_type, item_type=scope, feature_keys=[key]):
                continue
            text = f"«{label}» ميزة مدرجة في FINORA ضمن «{group['label']}». "
            text += "ظهورها يحتاج تفعيل الميزة وموافقة الباقة وصلاحيات المستخدم؛ وجودها في الفهرس لا يعني أنها مفعلة لهذا العميل. "
            if key in DEFAULT_DISABLED_FEATURES:
                text += "هذه الميزة معطلة افتراضياً وتحتاج تفعيل الإدارة. "
            text += "هذا سجل تعريف بالميزة فقط؛ خطوات الاستخدام تؤخذ من دليل موثق منفصل."
            items.append(KnowledgeItem(f"feature:{key}", "capabilities", label, text,
                                       "utils/tenant_feature_flags.py", scope, search_text=f"{label} {key.replace('_', ' ')}"))
    return items


def guide_items(*, business_type: str | None = None):
    from .knowledge import KnowledgeItem

    items = []
    for guide in guide_definitions():
        scope = guide.get("business_type")
        # The clinic workspace has its own verified lessons; retail screens must not substitute for them.
        if business_type == "clinics" and scope is None and guide["id"] != "access.missing":
            continue
        if not applies(business_type, item_type=scope, feature_keys=guide["features"]):
            continue
        steps = "\n".join(f"{index}. {step}" for index, step in enumerate(guide["steps"], 1))
        text = f"{guide['summary']}\n{steps}\n{guide['note']}"
        items.append(KnowledgeItem(f"guide:{guide['id']}", "tutorials", guide["title"], text,
                                   ", ".join(guide["sources"]), scope,
                                   search_text=" ".join([guide["title"], *guide["aliases"]])))
    return items


def activity_items(*, business_type: str | None = None):
    """Describe reviewed activity templates from the same registry used by tenant setup."""
    from .knowledge import KnowledgeItem
    from .tenant_setup import PROFILES, PROFILE_TYPES

    return [KnowledgeItem(f"activity:{key}", "capabilities", f"قالب {profile['label']}",
                          f"قالب فينورا «{profile['label']}» مخصص لاحتياجات: {profile['needs']}. "
                          "هذه توصية قالب موجود؛ الأقسام الفعلية تتحدد بعد مراجعة احتياج العميل وباقته وصلاحياته. "
                          "لا يعني وصف القالب أن حساب العميل جرى تجهيزه. النشاط الذي لا يطابق قالباً يحتاج مراجعة الفريق.",
                          "modules/finora_core/brain/tenant_setup.py:PROFILES", PROFILE_TYPES[key],
                          search_text=f"{profile['label']} {profile['needs']}")
            for key, profile in PROFILES.items() if applies(business_type, item_type=PROFILE_TYPES[key])]


def coverage(items):
    """Operator-facing counts distinguish feature awareness from verified instruction coverage."""
    return {"featureCount": len([i for i in items if i.id.startswith("feature:")]),
            "activityCount": len([i for i in items if i.id.startswith("activity:")]),
            "guideCount": len([i for i in items if i.category == "tutorials"]),
            "publishedCount": len([i for i in items if i.id.startswith("doc:")]),
            "categories": [{"name": key, "count": count} for key, count in sorted(Counter(i.category for i in items).items())],
            "note": "الفهرس يتحدّث من ميزات النظام. الشرح يعتمد على الأدلة الموثقة؛ أي خطوة غير مغطاة تُحال للفريق، وتوفّر الميزة يخضع للباقة والصلاحيات."}
