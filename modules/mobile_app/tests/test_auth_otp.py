"""Phase 1 mobile auth API tests (OTP + session + tenant isolation)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_auth_{os.getpid()}"
OTHER_TENANT = f"test_mobile_other_{os.getpid()}"


def _fresh_tenant_db(tenant: str) -> None:
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


def test_mobile_auth_otp_flow_and_tenant_isolation():
    _fresh_tenant_db(TENANT)
    _fresh_tenant_db(OTHER_TENANT)

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from modules.mobile_app.models import MobileOtpRequest, MobileUser
    from models.customer import Customer

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        g.tenant = OTHER_TENANT
        init_tenant_db(OTHER_TENANT)

    client = app.test_client()

    # Missing tenant header
    r = client.get("/api/mobile/v1/health")
    assert r.status_code == 400
    assert r.get_json()["code"] == "tenant_required"

    # Unknown tenant
    r = client.get("/api/mobile/v1/health", headers=_headers("no_such_tenant_xyz"))
    assert r.status_code == 404

    # Health + bootstrap
    r = client.get("/api/mobile/v1/health", headers=_headers(TENANT))
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["tenant"] == TENANT

    r = client.get("/api/mobile/v1/bootstrap", headers=_headers(TENANT))
    assert r.status_code == 200
    flags = r.get_json()["feature_flags"]
    assert flags["mobile_app_enabled"] is True
    assert flags["video_feed_enabled"] is True

    # Frictionless shopper login does not require an OTP challenge.
    r = client.post(
        "/api/mobile/v1/auth/phone-login",
        headers=_headers(TENANT),
        json={"phone": "07700000001", "device_id": "direct-device"},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    direct = r.get_json()
    assert direct["access_token"]
    assert direct["user"]["phone"] == "07700000001"
    r = client.get(
        "/api/mobile/v1/auth/me",
        headers=_headers(TENANT, direct["access_token"]),
    )
    assert r.status_code == 200

    # Request OTP
    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT),
        json={"phone": "07701234567"},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert data["ok"] is True
    code = data.get("debug_code")
    assert code and len(code) == 6

    # Wrong code
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={
            "phone": "07701234567",
            "code": "000000",
            "device_id": "test-device-1",
            "name": "أحمد",
            "platform": "android",
        },
    )
    assert r.status_code == 401

    # Correct code
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={
            "phone": "07701234567",
            "code": code,
            "device_id": "test-device-1",
            "name": "أحمد",
            "platform": "android",
        },
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    tokens = r.get_json()
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]
    assert tokens["user"]["phone"] == "07701234567"
    assert tokens["user"]["customer_id"]

    # Me
    r = client.get("/api/mobile/v1/auth/me", headers=_headers(TENANT, access))
    assert r.status_code == 200
    assert r.get_json()["user"]["name"] == "أحمد"

    # Token on wrong tenant rejected
    r = client.get("/api/mobile/v1/auth/me", headers=_headers(OTHER_TENANT, access))
    assert r.status_code == 403
    assert r.get_json()["code"] == "tenant_mismatch"

    # Refresh rotates
    r = client.post(
        "/api/mobile/v1/auth/refresh",
        headers=_headers(TENANT),
        json={"refresh_token": refresh},
    )
    assert r.status_code == 200
    new_access = r.get_json()["access_token"]
    new_refresh = r.get_json()["refresh_token"]
    assert new_refresh != refresh

    # Old refresh invalid
    r = client.post(
        "/api/mobile/v1/auth/refresh",
        headers=_headers(TENANT),
        json={"refresh_token": refresh},
    )
    assert r.status_code == 401

    # Logout
    r = client.post(
        "/api/mobile/v1/auth/logout",
        headers=_headers(TENANT, new_access),
        json={"refresh_token": new_refresh},
    )
    assert r.status_code == 200

    # Me after logout fails (session revoked)
    r = client.get("/api/mobile/v1/auth/me", headers=_headers(TENANT, new_access))
    assert r.status_code == 401

    # Customer linked once
    with app.app_context():
        g.tenant = TENANT
        assert Customer.query.filter_by(phone="07701234567").count() == 1
        assert MobileUser.query.filter_by(phone="07701234567").count() == 1
        assert MobileUser.query.filter_by(phone="07700000001").count() == 1
        assert MobileOtpRequest.query.filter_by(phone="07701234567").count() >= 1

    _fresh_tenant_db(TENANT)
    _fresh_tenant_db(OTHER_TENANT)
