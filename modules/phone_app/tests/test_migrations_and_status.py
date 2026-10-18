"""Phone schema migration + call_status separation tests."""

from __future__ import annotations

from modules.phone_app.api.v1.calls import (
    ALLOWED_CALL_STATUS,
    ALLOWED_STATUS,
    _normalize_call_status,
    _parse_dt,
)
from modules.phone_app.migrations import TARGET_VERSION, UPGRADES, DOWNGRADES


def test_migration_versions_registered():
    assert TARGET_VERSION == 4
    assert all(version in UPGRADES for version in (1, 2, 3, 4))
    assert all(version in DOWNGRADES for version in (1, 2, 3, 4))


def test_call_status_includes_dialing_cancelled():
    assert "dialing" in ALLOWED_CALL_STATUS
    assert "cancelled" in ALLOWED_CALL_STATUS
    assert "synced" not in ALLOWED_CALL_STATUS
    assert "synced" in ALLOWED_STATUS  # legacy alias only


def test_normalize_legacy_synced_splits():
    call_status, sync_status = _normalize_call_status("synced", None)
    assert call_status == "ended"
    assert sync_status == "synced"


def test_parse_dt_zulu_utc():
    dt = _parse_dt("2026-08-05T10:30:00Z")
    assert dt is not None
    assert dt.hour == 10
    assert dt.minute == 30
