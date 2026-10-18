"""Store analytics API (/api/v1/desktop/store-analytics): view_financial to read (it shows revenue and margin, and
view_reports is on for every employee by default); the experiment switch is admin only."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from extensions import db
from modules.store_analytics import service

store_analytics_bp = Blueprint("store_analytics", __name__, url_prefix="/api/v1/desktop/store-analytics")


def _deny(*, admin_only: bool = False):
    from utils.permission_checks import employee_can, get_current_employee

    actor = get_current_employee()
    if actor is None:
        return jsonify({"success": False, "error": "سجّل الدخول"}), 401
    if admin_only and actor.role != "admin":
        return jsonify({"success": False, "error": "للمدير العام فقط"}), 403
    if not admin_only and not employee_can(actor, "view_financial"):
        return jsonify({"success": False, "error": "ليست لديك صلاحية رؤية البيانات المالية"}), 403
    return None


@store_analytics_bp.get("")
def dashboard():
    denied = _deny()
    if denied:
        return denied
    return jsonify({"success": True, **service.dashboard(request.args.get("days", 30, type=int))})


_SETTING_KEYS = {"design_v2": "storefront_v2", "about_text": "storefront_about_text",
                 "returns_policy": "storefront_returns_policy"}


@store_analytics_bp.get("/settings")
def store_settings():
    denied = _deny(admin_only=True)
    if denied:
        return denied
    from models.system_settings import SystemSettings

    flags = SystemSettings.get_settings().get_ui_flags()
    return jsonify({"success": True, "design_v2": bool(flags.get("storefront_v2")),
                    "about_text": str(flags.get("storefront_about_text") or ""),
                    "returns_policy": str(flags.get("storefront_returns_policy") or "")})


@store_analytics_bp.post("/settings")
def store_settings_save():
    """The online store's design switch and the owner's own texts («عن المتجر», return policy). Admin only."""
    denied = _deny(admin_only=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    from models.system_settings import SystemSettings
    from utils.activity_logger import log_activity

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    changed = {}
    if "design_v2" in data:
        flags["storefront_v2"] = changed["design_v2"] = bool(data["design_v2"])
    for key, limit in (("about_text", 1500), ("returns_policy", 2000)):
        if key in data:
            text = str(data.get(key) or "").strip()
            if len(text) > limit:
                return jsonify({"success": False, "error": f"النص أطول من {limit} حرف"}), 400
            flags[_SETTING_KEYS[key]] = changed[key] = text
    settings.set_ui_flags(flags)
    try:
        log_activity("store_settings_changed", "store_analytics", "إعدادات المتجر الإلكتروني",
                     payload={"changed": sorted(changed)}, commit=False)
    except Exception:
        pass
    db.session.commit()
    try:  # show at once, not after the page caches expire
        from routes import storefront as storefront_routes

        storefront_routes._PAGE_CACHE.clear()
    except Exception:
        pass
    return jsonify({"success": True, "design_v2": bool(flags.get("storefront_v2")),
                    "about_text": str(flags.get("storefront_about_text") or ""),
                    "returns_policy": str(flags.get("storefront_returns_policy") or "")})


@store_analytics_bp.post("/experiment")
def experiment():
    """Share of shop sessions (0–50%) that see no recommendations, to measure their real effect on orders."""
    denied = _deny(admin_only=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        pct = int(data.get("holdout_pct"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "نسبة غير صالحة"}), 400
    if not 0 <= pct <= 50:
        return jsonify({"success": False, "error": "النسبة بين 0 و50%"}), 400
    from models.system_settings import SystemSettings
    from utils.activity_logger import log_activity

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    old = int(flags.get("storefront_rec_holdout_pct") or 0)
    flags["storefront_rec_holdout_pct"] = pct
    settings.set_ui_flags(flags)
    try:
        log_activity("store_experiment_changed", "store_analytics", f"تجربة التوصيات: {old}% ← {pct}%",
                     payload={"old": old, "new": pct}, commit=False)
    except Exception:
        pass
    db.session.commit()
    return jsonify({"success": True, "holdout_pct": pct})
