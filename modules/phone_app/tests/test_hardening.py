"""Hardening tests for Finora Phone API."""

from __future__ import annotations

from modules.phone_app.api.v1.calls import ALLOWED_STATUS
from modules.phone_app.api.v1.customers import _phone_variants
from modules.phone_app.services.rate_limit import allow_request


def test_phone_variants_spaces_and_plus():
    variants = _phone_variants("+964 770-123-4567")
    assert any(v.endswith("7701234567") for v in variants)


def test_allowed_call_statuses_cover_state_machine():
    for s in (
        "detected",
        "ringing",
        "dialing",
        "answered",
        "ended",
        "missed",
        "rejected",
        "failed",
        "cancelled",
    ):
        assert s in ALLOWED_STATUS
    # legacy alias still accepted by ALLOWED_STATUS union
    assert "synced" in ALLOWED_STATUS


def test_rate_limit_blocks_burst(app=None):
    # Without Flask request context, key still works via defaults.
    from flask import Flask

    app = Flask(__name__)
    with app.test_request_context("/", headers={"X-Tenant-Slug": "super"}):
        ok = 0
        blocked = 0
        for _ in range(25):
            if allow_request("test_burst", limit=10, window_seconds=60):
                ok += 1
            else:
                blocked += 1
        assert ok == 10
        assert blocked == 15
