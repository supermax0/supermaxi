"""Feature flag helpers."""
from __future__ import annotations

from extensions import db
from modules.mobile_app.models import MobileFeatureFlag
from modules.mobile_app.permissions import DEFAULT_FEATURE_FLAGS
from modules.mobile_app.schema_guard import ensure_mobile_app_schema


def list_feature_flags() -> dict[str, bool]:
    ensure_mobile_app_schema()
    flags = {key: bool(enabled) for key, enabled in DEFAULT_FEATURE_FLAGS.items()}
    for row in MobileFeatureFlag.query.all():
        flags[row.key] = bool(row.enabled)
    return flags


def is_flag_enabled(key: str, default: bool = False) -> bool:
    flags = list_feature_flags()
    return bool(flags.get(key, default))


def set_feature_flag(key: str, enabled: bool) -> dict[str, bool]:
    ensure_mobile_app_schema()
    key = (key or "").strip()
    if not key:
        raise ValueError("feature flag key required")
    row = MobileFeatureFlag.query.filter_by(key=key).first()
    if row is None:
        row = MobileFeatureFlag(key=key, enabled=bool(enabled))
        db.session.add(row)
    else:
        row.enabled = bool(enabled)
    db.session.commit()
    return list_feature_flags()
