"""Central tenant feature management.

All reads and writes go to the Core database through a dedicated session, so
the result never depends on ``g.tenant`` and tenant-side code cannot alter it.
Effective state = global switch AND tenant row enabled AND not expired.
A missing row is DISABLED.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, time as dtime
from functools import wraps
from typing import Any, Iterable, Iterator

from flask import jsonify, session
from sqlalchemy.orm import Session

from extensions import db
from models.core.feature import FeatureAuditLog, TenantFeature
from models.core.global_setting import GlobalSetting
from models.core.tenant import Tenant

PLATFORM_FEATURES_PERMISSION = "platform.features.manage"

AI_TUTOR = "clinic_ai_tutor"

FEATURE_REGISTRY: dict[str, dict[str, Any]] = {
    AI_TUTOR: {
        "label_ar": "Finora AI Tutor",
        "description_ar": "نظام التعليم الذكي والتوجيه داخل النظام",
        "default_config": {
            "show_on_first_login": True,
            "allow_ai_chat": True,
            "allow_guided_tours": True,
            "allow_auto_navigation": True,
            "curriculum_enabled": True,
        },
    },
}

STATE_ENABLED = "enabled"
STATE_DISABLED = "disabled"
STATE_EXPIRED = "expired"

_UNSET: Any = object()
_CACHE_TTL_SECONDS = 15.0
_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


class FeatureError(ValueError):
    """Invalid feature operation (unknown key/tenant, bad expiry, bad config)."""


def _now() -> datetime:
    return datetime.utcnow()


@contextmanager
def core_session() -> Iterator[Session]:
    """Session bound to the Core engine regardless of the active tenant."""
    sess = Session(bind=db.engine)
    try:
        yield sess
    finally:
        sess.close()


def _cache_get(key: tuple) -> Any:
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        _cache.pop(key, None)
    return _UNSET


def _cache_put(key: tuple, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, value)


def invalidate_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _require_key(feature_key: str) -> dict[str, Any]:
    spec = FEATURE_REGISTRY.get(feature_key)
    if spec is None:
        raise FeatureError(f"unknown feature: {feature_key}")
    return spec


def _global_setting_key(feature_key: str) -> str:
    return f"{feature_key}_global_enabled"


def _read_global(sess: Session, feature_key: str) -> bool:
    row = sess.query(GlobalSetting).filter_by(key=_global_setting_key(feature_key)).first()
    if row is None or row.value is None:
        return True
    return str(row.value).strip().lower() not in {"0", "false", "off", "no"}


def is_globally_enabled(feature_key: str) -> bool:
    if feature_key not in FEATURE_REGISTRY:
        return False
    cached = _cache_get(("global", feature_key))
    if cached is not _UNSET:
        return cached
    with core_session() as sess:
        value = _read_global(sess, feature_key)
    _cache_put(("global", feature_key), value)
    return value


def _state_of(row: TenantFeature | None, now: datetime) -> str:
    if row is None or not row.enabled:
        return STATE_DISABLED
    if row.expires_at is not None and row.expires_at <= now:
        return STATE_EXPIRED
    return STATE_ENABLED


def _config_of(row: TenantFeature | None, feature_key: str) -> dict[str, Any]:
    config = dict(FEATURE_REGISTRY[feature_key]["default_config"])
    if row is not None and row.configuration_json:
        try:
            stored = json.loads(row.configuration_json)
        except (TypeError, ValueError):
            stored = {}
        if isinstance(stored, dict):
            config.update({k: bool(v) for k, v in stored.items() if k in config})
    return config


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _status_dict(row: TenantFeature | None, feature_key: str, global_enabled: bool, now: datetime) -> dict[str, Any]:
    state = _state_of(row, now)
    return {
        "feature_key": feature_key,
        "label_ar": FEATURE_REGISTRY[feature_key]["label_ar"],
        "state": state,
        "enabled": row is not None and bool(row.enabled),
        "effective": global_enabled and state == STATE_ENABLED,
        "global_enabled": global_enabled,
        "expires_at": _iso(row.expires_at) if row else None,
        "enabled_at": _iso(row.enabled_at) if row else None,
        "enabled_by": row.enabled_by if row else None,
        "disabled_at": _iso(row.disabled_at) if row else None,
        "disabled_by": row.disabled_by if row else None,
        "configuration": _config_of(row, feature_key),
    }


def _tenant_by_slug(sess: Session, slug: str) -> Tenant:
    slug = str(slug or "").strip().lower()
    tenant = sess.query(Tenant).filter(db.func.lower(Tenant.slug) == slug).first() if slug else None
    if tenant is None:
        raise FeatureError("tenant not found")
    return tenant


def _tenant_row(sess: Session, tenant_id: int, feature_key: str) -> TenantFeature | None:
    return sess.query(TenantFeature).filter_by(tenant_id=tenant_id, feature_key=feature_key).first()


# ---------------------------------------------------------------- reads

def is_enabled(tenant_id: int | None, feature_key: str) -> bool:
    """Effective state for a Core tenant id."""
    if tenant_id is None or feature_key not in FEATURE_REGISTRY:
        return False
    cache_key = ("tenant", int(tenant_id), feature_key)
    cached = _cache_get(cache_key)
    if cached is not _UNSET:
        return cached
    with core_session() as sess:
        value = _read_global(sess, feature_key) and _state_of(
            _tenant_row(sess, int(tenant_id), feature_key), _now()
        ) == STATE_ENABLED
    # Cache until the TTL or an explicit invalidation; expiry is bounded by TTL.
    _cache_put(cache_key, value)
    return value


def is_enabled_for_slug(slug: str | None, feature_key: str) -> bool:
    slug = str(slug or "").strip().lower()
    if not slug or feature_key not in FEATURE_REGISTRY:
        return False
    cached = _cache_get(("slug", slug, feature_key))
    if cached is not _UNSET:
        return cached
    with core_session() as sess:
        tenant = sess.query(Tenant).filter(db.func.lower(Tenant.slug) == slug).first()
        value = bool(
            tenant
            and _read_global(sess, feature_key)
            and _state_of(_tenant_row(sess, tenant.id, feature_key), _now()) == STATE_ENABLED
        )
    _cache_put(("slug", slug, feature_key), value)
    return value


def get_status(slug: str, feature_key: str) -> dict[str, Any]:
    _require_key(feature_key)
    with core_session() as sess:
        tenant = _tenant_by_slug(sess, slug)
        return _status_dict(
            _tenant_row(sess, tenant.id, feature_key), feature_key, _read_global(sess, feature_key), _now()
        )


def get_all_statuses(slug: str) -> list[dict[str, Any]]:
    with core_session() as sess:
        tenant = _tenant_by_slug(sess, slug)
        now = _now()
        return [
            _status_dict(_tenant_row(sess, tenant.id, key), key, _read_global(sess, key), now)
            for key in FEATURE_REGISTRY
        ]


def effective_features_for_slug(slug: str | None) -> dict[str, bool]:
    return {key: is_enabled_for_slug(slug, key) for key in FEATURE_REGISTRY}


def list_overview(feature_key: str, *, state: str = "all", query: str = "") -> list[dict[str, Any]]:
    """One row per tenant with the feature state (for the Super Admin list)."""
    _require_key(feature_key)
    state = (state or "all").strip().lower()
    if state not in {"all", STATE_ENABLED, STATE_DISABLED, STATE_EXPIRED}:
        raise FeatureError("invalid state filter")
    needle = (query or "").strip().lower()
    with core_session() as sess:
        now = _now()
        global_enabled = _read_global(sess, feature_key)
        rows = {r.tenant_id: r for r in sess.query(TenantFeature).filter_by(feature_key=feature_key)}
        result = []
        for tenant in sess.query(Tenant).order_by(Tenant.name.asc()):
            if needle and needle not in (tenant.name or "").lower() and needle not in (tenant.slug or "").lower() \
                    and needle != str(tenant.id):
                continue
            item = _status_dict(rows.get(tenant.id), feature_key, global_enabled, now)
            if state != "all" and item["state"] != state:
                continue
            item.update({"tenant_id": tenant.id, "slug": tenant.slug, "name": tenant.name})
            result.append(item)
        return result


def list_audit(feature_key: str | None = None, slug: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), 200)
    with core_session() as sess:
        q = sess.query(FeatureAuditLog)
        if feature_key:
            _require_key(feature_key)
            q = q.filter_by(feature_key=feature_key)
        if slug:
            q = q.filter_by(tenant_id=_tenant_by_slug(sess, slug).id)
        return [
            {
                "id": r.id,
                "tenant_id": r.tenant_id,
                "feature_key": r.feature_key,
                "action": r.action,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "performed_by": r.performed_by,
                "ip_address": r.ip_address,
                "created_at": _iso(r.created_at),
            }
            for r in q.order_by(FeatureAuditLog.id.desc()).limit(limit)
        ]


# --------------------------------------------------------------- writes

def parse_expiry(value: Any) -> datetime | None:
    """``None``/empty = permanent; ``YYYY-MM-DD`` = end of that day (UTC)."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, dtime(23, 59, 59))
    text = str(value).strip()
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), dtime(23, 59, 59))
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise FeatureError("invalid expiry date") from exc


def _validate_config(feature_key: str, configuration: Any) -> dict[str, bool]:
    allowed = FEATURE_REGISTRY[feature_key]["default_config"]
    if not isinstance(configuration, dict):
        raise FeatureError("configuration must be an object")
    unknown = set(configuration) - set(allowed)
    if unknown:
        raise FeatureError(f"unknown configuration keys: {', '.join(sorted(unknown))}")
    if not all(isinstance(v, bool) for v in configuration.values()):
        raise FeatureError("configuration values must be boolean")
    return dict(configuration)


def _audit(sess: Session, tenant_id: int | None, feature_key: str, action: str,
           old: Any, new: Any, actor: str, ip: str | None) -> None:
    sess.add(FeatureAuditLog(
        tenant_id=tenant_id,
        feature_key=feature_key,
        action=action,
        old_value=json.dumps(old, ensure_ascii=False, default=str),
        new_value=json.dumps(new, ensure_ascii=False, default=str),
        performed_by=actor,
        ip_address=(ip or None) and str(ip)[:64],
        created_at=_now(),
    ))


def _apply(sess: Session, tenant: Tenant, feature_key: str, *, enabled: bool | None,
           expires_at: Any, configuration: Any, actor: str, ip: str | None) -> None:
    now = _now()
    row = _tenant_row(sess, tenant.id, feature_key)
    existing_state = _state_of(row, now)
    if row is None:
        row = TenantFeature(tenant_id=tenant.id, feature_key=feature_key, enabled=False, created_at=now)
        sess.add(row)

    new_expiry = row.expires_at if expires_at is _UNSET else parse_expiry(expires_at)
    target_enabled = bool(row.enabled) if enabled is None else bool(enabled)
    if target_enabled and new_expiry is not None and new_expiry <= now:
        raise FeatureError("expiry must be in the future; choose a new date or make it permanent")

    if target_enabled != bool(row.enabled):
        _audit(sess, tenant.id, feature_key, "ENABLED" if target_enabled else "DISABLED",
               {"state": existing_state}, {"state": STATE_ENABLED if target_enabled else STATE_DISABLED},
               actor, ip)
        row.enabled = target_enabled
        if target_enabled:
            row.enabled_at, row.enabled_by = now, actor
            row.disabled_at = row.disabled_by = None
        else:
            row.disabled_at, row.disabled_by = now, actor

    if new_expiry != row.expires_at:
        _audit(sess, tenant.id, feature_key, "EXPIRY_CHANGED",
               {"expires_at": _iso(row.expires_at)}, {"expires_at": _iso(new_expiry)}, actor, ip)
        row.expires_at = new_expiry

    if configuration is not None:
        old_config = _config_of(row, feature_key)
        new_config = {**old_config, **_validate_config(feature_key, configuration)}
        if new_config != old_config:
            _audit(sess, tenant.id, feature_key, "CONFIG_CHANGED", old_config, new_config, actor, ip)
            row.configuration_json = json.dumps(new_config, ensure_ascii=False)


def set_feature(slug: str, feature_key: str, *, enabled: bool | None = None, expires_at: Any = _UNSET,
                configuration: Any = None, actor: str, ip: str | None = None) -> dict[str, Any]:
    _require_key(feature_key)
    with core_session() as sess:
        tenant = _tenant_by_slug(sess, slug)
        try:
            _apply(sess, tenant, feature_key, enabled=enabled, expires_at=expires_at,
                   configuration=configuration, actor=actor, ip=ip)
            sess.commit()
        except Exception:
            sess.rollback()
            raise
    invalidate_cache()
    return get_status(slug, feature_key)


def bulk_set_feature(slugs: Iterable[str], feature_key: str, *, enabled: bool, expires_at: Any = _UNSET,
                     actor: str, ip: str | None = None) -> list[dict[str, Any]]:
    """All-or-nothing: any unknown tenant or invalid expiry aborts everything."""
    _require_key(feature_key)
    unique = list(dict.fromkeys(str(s or "").strip().lower() for s in slugs))
    if not unique or "" in unique:
        raise FeatureError("no tenants selected")
    with core_session() as sess:
        tenants = [_tenant_by_slug(sess, slug) for slug in unique]
        try:
            for tenant in tenants:
                _apply(sess, tenant, feature_key, enabled=enabled, expires_at=expires_at,
                       configuration=None, actor=actor, ip=ip)
            sess.commit()
        except Exception:
            sess.rollback()
            raise
    invalidate_cache()
    return [get_status(slug, feature_key) for slug in unique]


def set_global_enabled(feature_key: str, enabled: bool, *, actor: str, ip: str | None = None) -> bool:
    _require_key(feature_key)
    with core_session() as sess:
        old = _read_global(sess, feature_key)
        row = sess.query(GlobalSetting).filter_by(key=_global_setting_key(feature_key)).first()
        if row is None:
            row = GlobalSetting(key=_global_setting_key(feature_key), description=f"Global kill switch: {feature_key}")
            sess.add(row)
        row.value = "true" if enabled else "false"
        row.updated_at = _now()
        if old != bool(enabled):
            _audit(sess, None, feature_key, "GLOBAL_ENABLED" if enabled else "GLOBAL_DISABLED",
                   {"global_enabled": old}, {"global_enabled": bool(enabled)}, actor, ip)
        sess.commit()
    invalidate_cache()
    return bool(enabled)


# ----------------------------------------------------------- request gate

def current_tenant_slug() -> str | None:
    slug = session.get("tenant_slug")
    return str(slug).strip().lower() if slug else None


def require_feature(feature_key: str):
    """Route decorator: backend enforcement for tenant-facing feature APIs."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("user_id") or not current_tenant_slug():
                return jsonify({"error": "AUTH_REQUIRED"}), 401
            if not is_enabled_for_slug(current_tenant_slug(), feature_key):
                return jsonify({"error": "FEATURE_NOT_ENABLED", "feature": feature_key}), 403
            return view(*args, **kwargs)
        return wrapper
    return decorator
