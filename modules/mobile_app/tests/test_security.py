"""Security closeout: rate limits + cross-tenant token rejection."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT_A = f"test_mobile_sec_a_{os.getpid()}"
TENANT_B = f"test_mobile_sec_b_{os.getpid()}"


def _wipe(tenant: str) -> None:
    db_file = ROOT / "tenants" / f"{tenant}.db"
    try:
        if db_file.exists():
            db_file.unlink()
    except OSError:
        pass


def _headers(tenant: str, token: str | None = None) -> dict:
    h = {"X-Tenant-Slug": tenant, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def test_rate_limit_and_tenant_token_isolation():
    _wipe(TENANT_A)
    _wipe(TENANT_B)
    from app import app
    from extensions_tenant import init_tenant_db
    from flask import g
    from modules.mobile_app.services.rate_limit import (
        allow_request,
        reset_rate_limits_for_tests,
    )

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True
    reset_rate_limits_for_tests()

    with app.app_context():
        g.tenant = TENANT_A
        init_tenant_db(TENANT_A)
        from extensions import db
        from sqlalchemy import text

        assert db.session.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        g.tenant = TENANT_B
        init_tenant_db(TENANT_B)

    # Unit-level bucket
    with app.test_request_context(headers={"X-Tenant-Slug": TENANT_A}):
        g.tenant = TENANT_A
        assert allow_request("unit_test_bucket", limit=2, window_seconds=60)
        assert allow_request("unit_test_bucket", limit=2, window_seconds=60)
        assert not allow_request("unit_test_bucket", limit=2, window_seconds=60)

    client = app.test_client()

    r = client.get(
        "/api/mobile/v1/health",
        headers=_headers("../../outside-tenant"),
    )
    assert r.status_code == 400
    assert r.get_json()["code"] == "tenant_invalid"

    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT_A),
        json={"phone": "07701110000"},
    )
    assert r.status_code == 200
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT_A),
        json={
            "phone": "07701110000",
            "code": code,
            "device_id": "sec-device",
            "name": "أمن",
        },
    )
    assert r.status_code == 200
    token_a = r.get_json()["access_token"]

    # Token from A must not work on B
    r = client.get("/api/mobile/v1/profile", headers=_headers(TENANT_B, token_a))
    assert r.status_code == 403
    assert r.get_json()["code"] == "tenant_mismatch"

    # API-level rate limit on verify (burn remaining budget)
    reset_rate_limits_for_tests()
    limited_hit = False
    for i in range(35):
        r = client.post(
            "/api/mobile/v1/auth/verify-otp",
            headers=_headers(TENANT_A),
            json={
                "phone": "07701110000",
                "code": "000000",
                "device_id": "sec-device",
            },
        )
        if r.status_code == 429 and r.get_json().get("code") == "rate_limited":
            limited_hit = True
            break
    assert limited_hit

    _wipe(TENANT_A)
    _wipe(TENANT_B)
