"""Tenant province configuration stored in SystemSettings.ui_flags."""

from __future__ import annotations

DEFAULT_PROVINCES = [
    "بغداد", "البصرة", "نينوى", "أربيل", "النجف", "كربلاء", "ذي قار",
    "السليمانية", "دهوك", "كركوك", "ديالى", "الأنبار", "صلاح الدين",
    "واسط", "بابل", "القادسية", "ميسان", "المثنى",
]

DEFAULT_PRIMARY = "بغداد"
DEFAULT_GROUP_LABEL = "محافظات"

FILTER_PRIMARY = "__primary__"
FILTER_GROUP = "__group__"


def _normalize_name(name: str) -> str:
    return (name or "").strip()


def _default_config() -> dict:
    return {
        "primary": DEFAULT_PRIMARY,
        "group_label": DEFAULT_GROUP_LABEL,
        "list": list(DEFAULT_PROVINCES),
    }


def _load_raw_config() -> dict | None:
    try:
        from models.system_settings import SystemSettings

        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags() if settings else {}
        raw = flags.get("tenant_provinces")
        if not raw or not isinstance(raw, dict):
            return None
        names = [_normalize_name(n) for n in (raw.get("list") or []) if _normalize_name(n)]
        if not names:
            return None
        primary = _normalize_name(raw.get("primary") or "") or names[0]
        if primary not in names:
            primary = names[0]
        return {
            "primary": primary,
            "group_label": _normalize_name(raw.get("group_label") or "") or DEFAULT_GROUP_LABEL,
            "list": names,
        }
    except Exception:
        return None


def get_tenant_provinces_config() -> dict:
    return _load_raw_config() or _default_config()


def get_group_provinces(config: dict | None = None) -> list[str]:
    cfg = config or get_tenant_provinces_config()
    primary = cfg.get("primary") or DEFAULT_PRIMARY
    return [n for n in (cfg.get("list") or []) if n != primary]


def _persist_config(config: dict) -> None:
    from extensions import db
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags["tenant_provinces"] = {
        "primary": config["primary"],
        "group_label": config.get("group_label") or DEFAULT_GROUP_LABEL,
        "list": list(config["list"]),
    }
    settings.set_ui_flags(flags)
    db.session.commit()


def save_tenant_provinces(primary: str, names: list[str], group_label: str | None = None) -> dict:
    clean = []
    seen = set()
    for raw in names:
        name = _normalize_name(raw)
        if not name or name in seen:
            continue
        seen.add(name)
        clean.append(name)
    if not clean:
        clean = list(DEFAULT_PROVINCES)
    primary_name = _normalize_name(primary) or clean[0]
    if primary_name not in clean:
        clean.insert(0, primary_name)
    config = {
        "primary": primary_name,
        "group_label": _normalize_name(group_label or "") or DEFAULT_GROUP_LABEL,
        "list": clean,
    }
    _persist_config(config)
    return config


def add_province(name: str) -> dict:
    cfg = get_tenant_provinces_config()
    clean = _normalize_name(name)
    if not clean:
        raise ValueError("اسم المحافظة مطلوب")
    if clean in cfg["list"]:
        raise ValueError("المحافظة موجودة مسبقاً")
    cfg["list"].append(clean)
    _persist_config(cfg)
    return cfg


def remove_province(name: str) -> dict:
    cfg = get_tenant_provinces_config()
    clean = _normalize_name(name)
    if not clean:
        raise ValueError("اسم المحافظة مطلوب")
    if clean not in cfg["list"]:
        raise ValueError("المحافظة غير موجودة")
    if clean == cfg["primary"] and len(cfg["list"]) <= 1:
        raise ValueError("لا يمكن حذف المحافظة الأساسية الوحيدة")
    if clean == cfg["primary"]:
        raise ValueError("عيّن محافظة أساسية أخرى قبل الحذف")
    cfg["list"] = [n for n in cfg["list"] if n != clean]
    _persist_config(cfg)
    return cfg


def set_primary(name: str) -> dict:
    cfg = get_tenant_provinces_config()
    clean = _normalize_name(name)
    if not clean:
        raise ValueError("اسم المحافظة مطلوب")
    if clean not in cfg["list"]:
        raise ValueError("المحافظة غير موجودة في القائمة")
    cfg["primary"] = clean
    _persist_config(cfg)
    return cfg


def match_city_filter(city_value: str | None, filter_mode: str, config: dict | None = None) -> bool:
    if not filter_mode:
        return True
    cfg = config or get_tenant_provinces_config()
    city = _normalize_name(city_value or "")
    if filter_mode == FILTER_PRIMARY:
        return city == cfg.get("primary")
    if filter_mode == FILTER_GROUP:
        group = get_group_provinces(cfg)
        label = cfg.get("group_label") or DEFAULT_GROUP_LABEL
        if city == label:
            return True
        return city in group
    return city == filter_mode


def get_provinces_context() -> dict:
    cfg = get_tenant_provinces_config()
    group = get_group_provinces(cfg)
    return {
        "primary_province": cfg["primary"],
        "provinces_group_label": cfg.get("group_label") or DEFAULT_GROUP_LABEL,
        "tenant_provinces_list": list(cfg["list"]),
        "tenant_group_provinces": group,
        "province_filter_primary": FILTER_PRIMARY,
        "province_filter_group": FILTER_GROUP,
    }
