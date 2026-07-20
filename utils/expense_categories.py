"""Expense categories stored in SystemSettings.ui_flags."""

from __future__ import annotations

import re
import unicodedata

DEFAULT_EXPENSE_CATEGORIES = [
    {"key": "rent", "label": "إيجار", "icon": "🏠", "builtin": True},
    {"key": "salary", "label": "رواتب", "icon": "💰", "builtin": True},
    {"key": "electricity", "label": "كهرباء", "icon": "⚡", "builtin": True},
    {"key": "internet", "label": "إنترنت", "icon": "🌐", "builtin": True},
    {"key": "advertising", "label": "إعلان", "icon": "📢", "builtin": True},
    {"key": "maintenance", "label": "صيانة", "icon": "🔧", "builtin": True},
    {"key": "other", "label": "أخرى", "icon": "📦", "builtin": True},
]

CATEGORY_COLORS = [
    "rent", "salary", "electricity", "internet", "advertising", "maintenance", "other",
    "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8",
]


def _normalize_label(label: str) -> str:
    return (label or "").strip()


def _slug_key(label: str) -> str:
    clean = _normalize_label(label)
    if not clean:
        return ""
    ascii_slug = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", clean).encode("ascii", "ignore").decode("ascii").lower()).strip("_")
    if ascii_slug:
        return f"custom_{ascii_slug}"[:60]
    return f"custom_{abs(hash(clean)) % 10_000_000}"


def _load_raw_categories() -> list[dict] | None:
    try:
        from models.system_settings import SystemSettings

        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags() if settings else {}
        raw = flags.get("expense_categories")
        if not raw or not isinstance(raw, list):
            return None
        out = []
        seen = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = _normalize_label(item.get("key") or "")
            label = _normalize_label(item.get("label") or "")
            if not key or not label or key in seen:
                continue
            seen.add(key)
            out.append({
                "key": key,
                "label": label,
                "icon": (item.get("icon") or "📦")[:8],
                "builtin": bool(item.get("builtin")),
            })
        return out or None
    except Exception:
        return None


def get_expense_categories() -> list[dict]:
    loaded = _load_raw_categories()
    if loaded:
        return loaded
    return [dict(c) for c in DEFAULT_EXPENSE_CATEGORIES]


def _persist_categories(categories: list[dict]) -> list[dict]:
    from extensions import db
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags["expense_categories"] = categories
    settings.set_ui_flags(flags)
    db.session.commit()
    return categories


def get_category_map() -> dict[str, dict]:
    return {c["key"]: c for c in get_expense_categories()}


def resolve_category_label(key: str | None, category_map: dict[str, dict] | None = None) -> str:
    k = (key or "").strip() or "other"
    cmap = category_map or get_category_map()
    if k in cmap:
        return cmap[k]["label"]
    return k


def resolve_category_meta(key: str | None, category_map: dict[str, dict] | None = None) -> dict:
    k = (key or "").strip() or "other"
    cmap = category_map or get_category_map()
    if k in cmap:
        return dict(cmap[k])
    return {"key": k, "label": k, "icon": "📦", "builtin": False}


def add_expense_category(label: str, icon: str | None = None) -> dict:
    clean = _normalize_label(label)
    if not clean:
        raise ValueError("اسم الفئة مطلوب")
    if len(clean) > 80:
        raise ValueError("اسم الفئة طويل جداً")

    categories = get_expense_categories()
    for c in categories:
        if c["label"].casefold() == clean.casefold() or c["key"] == clean:
            raise ValueError("الفئة موجودة مسبقاً")

    key = _slug_key(clean)
    base_key = key
    n = 2
    existing = {c["key"] for c in categories}
    while key in existing:
        key = f"{base_key}_{n}"
        n += 1

    new_cat = {
        "key": key,
        "label": clean,
        "icon": (icon or "📦")[:8],
        "builtin": False,
    }
    categories.append(new_cat)
    _persist_categories(categories)
    return new_cat


def remove_expense_category(key: str) -> list[dict]:
    clean = _normalize_label(key)
    if not clean:
        raise ValueError("الفئة غير موجودة")

    categories = get_expense_categories()
    target = next((c for c in categories if c["key"] == clean), None)
    if not target:
        raise ValueError("الفئة غير موجودة")
    if target.get("builtin"):
        raise ValueError("لا يمكن حذف الفئات الافتراضية")

    categories = [c for c in categories if c["key"] != clean]
    _persist_categories(categories)
    return categories


def build_category_groups(expenses, include_empty: bool = True) -> list[dict]:
    """Group expenses by category for the expenses page."""
    cmap = get_category_map()
    configured = get_expense_categories()
    groups: dict[str, dict] = {}

    for idx, cat in enumerate(configured):
        groups[cat["key"]] = {
            **cat,
            "color": CATEGORY_COLORS[idx % len(CATEGORY_COLORS)],
            "expenses": [],
            "total": 0,
            "count": 0,
        }

    for expense in expenses or []:
        key = (expense.category or "other").strip() or "other"
        if key not in groups:
            meta = resolve_category_meta(key, cmap)
            groups[key] = {
                **meta,
                "color": CATEGORY_COLORS[len(groups) % len(CATEGORY_COLORS)],
                "expenses": [],
                "total": 0,
                "count": 0,
            }
        groups[key]["expenses"].append(expense)
        groups[key]["count"] += 1
        if getattr(expense, "cash_posted", True):
            groups[key]["total"] += int(expense.amount or 0)

    ordered_keys = [c["key"] for c in configured]
    result = [groups[k] for k in ordered_keys if k in groups]
    for key, group in groups.items():
        if key not in ordered_keys:
            result.append(group)

    if not include_empty:
        result = [g for g in result if g["count"] > 0]
    result.sort(key=lambda g: (-g["count"], g.get("label") or ""))
    return result
