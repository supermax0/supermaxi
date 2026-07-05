"""سجل تدقيق الجمعيات والسلف الدوّارة."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from utils.activity_logger import log_activity

SAVING_SNAPSHOT_FIELDS = (
    "name",
    "type",
    "status",
    "receive_status",
    "monthly_amount",
    "total_months",
    "total_paid",
    "total_received",
    "remaining_to_pay",
    "asset_balance",
    "liability_balance",
    "accounting_status",
)


def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return str(value)
    except Exception:
        return "[unserializable]"


def saving_snapshot(saving) -> dict:
    if saving is None:
        return {}
    return {f: _serialize(getattr(saving, f, None)) for f in SAVING_SNAPSHOT_FIELDS}


def log_rotating_saving_audit(
    action: str,
    summary: str,
    *,
    saving_id: int | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
    extra: dict | None = None,
    user_id: int | None = None,
    commit: bool = False,
):
    payload = {"old": old_values or {}, "new": new_values or {}}
    if extra:
        payload["extra"] = extra
    if user_id:
        payload["user_id"] = user_id
    return log_activity(
        action=action,
        category="finance",
        summary=summary,
        entity_type="rotating_saving",
        entity_id=saving_id,
        payload=payload,
        commit=commit,
    )
