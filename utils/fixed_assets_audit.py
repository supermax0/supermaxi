"""سجل تدقيق الأصول الثابتة."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from extensions import db
from models.fixed_asset_audit_log import FixedAssetAuditLog

ASSET_SNAPSHOT_FIELDS = (
    "asset_code",
    "name",
    "status",
    "total_cost",
    "book_value",
    "accumulated_depreciation",
    "monthly_depreciation",
    "location_text",
    "responsible_user_id",
    "category_id",
    "payment_method",
)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return str(value)
    except Exception:
        return "[unserializable]"


def asset_snapshot(asset) -> dict:
    if asset is None:
        return {}
    out = {}
    for field in ASSET_SNAPSHOT_FIELDS:
        out[field] = _serialize_value(getattr(asset, field, None))
    return out


def log_fixed_asset_audit(
    action: str,
    entity_type: str,
    *,
    entity_id: int | None = None,
    asset_id: int | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
    summary: str = "",
    user_id: int | None = None,
    commit: bool = False,
) -> FixedAssetAuditLog | None:
    try:
        entry = FixedAssetAuditLog(
            user_id=user_id,
            action=(action or "unknown")[:50],
            entity_type=(entity_type or "fixed_asset")[:50],
            entity_id=entity_id,
            asset_id=asset_id,
            summary=(summary or "")[:2000],
        )
        entry.set_old_values(old_values)
        entry.set_new_values(new_values)
        db.session.add(entry)
        if commit:
            db.session.commit()
        return entry
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def list_audit_logs(asset_id: int | None = None, limit: int = 100):
    q = FixedAssetAuditLog.query.order_by(FixedAssetAuditLog.created_at.desc())
    if asset_id:
        q = q.filter_by(asset_id=asset_id)
    return q.limit(limit).all()
