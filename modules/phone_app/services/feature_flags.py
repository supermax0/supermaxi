"""Tenant-aware Phone feature flags with safe defaults."""

from __future__ import annotations

import os
from typing import Any

# Phase 2A scope defaults — out-of-scope stay False.
DEFAULT_FLAGS: dict[str, bool] = {
    "overlay": True,
    "offline_sync": True,
    "recording": False,
    "ai": False,
    "queue": False,
    "reports_advanced": False,
    "order_draft_required": False,
    "phone_timeline_enabled": True,
    "phone_call_outcomes_enabled": True,
    "phone_advanced_search_enabled": True,
    "phone_smart_followup_enabled": True,
    "phone_voice_notes_enabled": False,
    "phone_product_suggestions_enabled": False,
    "phone_supervisor_dashboard_enabled": False,
}

_SETTING_PREFIX = "phone_ff_"


def _bool_setting(key: str, default: bool) -> bool:
    # Environment override wins (e.g. PHONE_FF_RECORDING=true in .env).
    env_raw = os.environ.get(f"PHONE_FF_{key.upper()}", "").strip().lower()
    if env_raw in ("1", "true", "yes", "on"):
        return True
    if env_raw in ("0", "false", "no", "off"):
        return False
    try:
        from models.system_settings import SystemSettings

        row = SystemSettings.query.filter_by(key=f"{_SETTING_PREFIX}{key}").first()
        if row is None or row.value is None:
            return default
        raw = str(row.value).strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
    except Exception:
        pass
    return default


def get_feature_flags() -> dict[str, bool]:
    flags = dict(DEFAULT_FLAGS)
    for key, default in DEFAULT_FLAGS.items():
        flags[key] = _bool_setting(key, default)
    return flags


def is_feature_enabled(flag: str) -> bool:
    return bool(get_feature_flags().get(flag, False))


def require_feature(flag: str) -> Any | None:
    """Return an api_error response if the flag is off, else None."""
    if is_feature_enabled(flag):
        return None
    from modules.phone_app.schemas import api_error

    return api_error(
        f"Feature disabled: {flag}",
        403,
        code="feature_disabled",
    )
