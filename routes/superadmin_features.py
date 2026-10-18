"""Super Admin controls for tenant features (permission: platform.features.manage)."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request, session

from models.core.super_admin import SuperAdmin
from services import feature_service as fs
from services.feature_service import FeatureError

superadmin_features_bp = Blueprint("superadmin_features", __name__, url_prefix="/superadmin/features")


def _has_platform_permission(permission: str) -> bool:
    # Super Admin is the platform owner; tenant users never carry this flag.
    return permission == fs.PLATFORM_FEATURES_PERMISSION and session.get("is_superadmin") is True


@superadmin_features_bp.before_request
def _require_platform_admin():
    g.tenant = None  # always Core DB
    if not _has_platform_permission(fs.PLATFORM_FEATURES_PERMISSION):
        return jsonify({"error": "FORBIDDEN", "permission": fs.PLATFORM_FEATURES_PERMISSION}), 403
    return None


def _actor() -> str:
    admin_id = session.get("superadmin_id")
    admin = SuperAdmin.query.get(admin_id) if admin_id else None
    return f"{admin.username}#{admin.id}" if admin else "superadmin"


def _ip() -> str | None:
    return request.remote_addr


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _bool(data: dict, key: str) -> bool | None:
    if key not in data:
        return None
    if not isinstance(data[key], bool):
        raise FeatureError(f"{key} must be boolean")
    return data[key]


def _error(exc: FeatureError):
    status = 404 if str(exc) in {"tenant not found"} or str(exc).startswith("unknown feature") else 400
    return jsonify({"ok": False, "error": str(exc)}), status


@superadmin_features_bp.get("/registry")
def registry():
    return jsonify({"ok": True, "features": [
        {"key": key, "label_ar": spec["label_ar"], "description_ar": spec["description_ar"],
         "default_config": spec["default_config"], "global_enabled": fs.is_globally_enabled(key)}
        for key, spec in fs.FEATURE_REGISTRY.items()
    ]})


@superadmin_features_bp.get("/<feature_key>/overview")
def overview(feature_key):
    try:
        rows = fs.list_overview(feature_key, state=request.args.get("state", "all"), query=request.args.get("q", ""))
    except FeatureError as exc:
        return _error(exc)
    return jsonify({"ok": True, "tenants": rows, "count": len(rows)})


@superadmin_features_bp.get("/tenants/<slug>")
def tenant_features(slug):
    try:
        return jsonify({"ok": True, "features": fs.get_all_statuses(slug)})
    except FeatureError as exc:
        return _error(exc)


@superadmin_features_bp.patch("/tenants/<slug>/<feature_key>")
def update_tenant_feature(slug, feature_key):
    data = _body()
    try:
        kwargs = {"enabled": _bool(data, "enabled"), "configuration": data.get("configuration")}
        if "expires_at" in data:
            kwargs["expires_at"] = data["expires_at"]
        status = fs.set_feature(slug, feature_key, actor=_actor(), ip=_ip(), **kwargs)
    except FeatureError as exc:
        return _error(exc)
    return jsonify({"ok": True, "status": status})


@superadmin_features_bp.post("/<feature_key>/bulk")
def bulk_update(feature_key):
    data = _body()
    slugs = data.get("slugs")
    try:
        if not isinstance(slugs, list):
            raise FeatureError("slugs must be a list")
        enabled = _bool(data, "enabled")
        if enabled is None:
            raise FeatureError("enabled is required")
        kwargs = {"expires_at": data["expires_at"]} if "expires_at" in data else {}
        statuses = fs.bulk_set_feature(slugs, feature_key, enabled=enabled, actor=_actor(), ip=_ip(), **kwargs)
    except FeatureError as exc:
        return _error(exc)
    return jsonify({"ok": True, "statuses": statuses, "count": len(statuses)})


@superadmin_features_bp.put("/<feature_key>/global")
def set_global(feature_key):
    try:
        enabled = _bool(_body(), "enabled")
        if enabled is None:
            raise FeatureError("enabled is required")
        fs.set_global_enabled(feature_key, enabled, actor=_actor(), ip=_ip())
    except FeatureError as exc:
        return _error(exc)
    return jsonify({"ok": True, "global_enabled": enabled})


@superadmin_features_bp.get("/<feature_key>/audit")
def audit(feature_key):
    try:
        limit = int(request.args.get("limit", 50))
        return jsonify({"ok": True, "logs": fs.list_audit(feature_key, request.args.get("slug") or None, limit)})
    except (FeatureError, ValueError) as exc:
        return _error(FeatureError(str(exc)))
