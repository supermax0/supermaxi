"""Phase 8 notifications / analytics / feature flags / design tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_p8_{os.getpid()}"


def _wipe(tenant: str) -> None:
    db_file = ROOT / "tenants" / f"{tenant}.db"
    try:
        if db_file.exists():
            db_file.unlink()
    except OSError:
        pass


def _headers(tenant: str, token: str | None = None, staff_id: int | None = None) -> dict:
    h = {"X-Tenant-Slug": tenant, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if staff_id is not None:
        h["X-Test-Staff-Id"] = str(staff_id)
    return h


def test_mobile_phase8_notifications_analytics_flags_design():
    _wipe(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.employee import Employee
    from werkzeug.security import generate_password_hash

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        admin = Employee(
            name="Admin",
            username=f"p8admin_{os.getpid()}",
            password=generate_password_hash("x"),
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
        db.session.commit()
        staff_id = admin.id

    client = app.test_client()
    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT),
        json={"phone": "07706667788"},
    )
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={
            "phone": "07706667788",
            "code": code,
            "device_id": "p8-dev",
            "name": "P8 User",
        },
    )
    assert r.status_code == 200
    token = r.get_json()["access_token"]
    user_id = r.get_json()["user"]["id"]
    h = _headers(TENANT, token)

    r = client.get("/api/mobile/v1/bootstrap", headers=_headers(TENANT))
    assert r.status_code == 200
    boot = r.get_json()
    assert "feature_flags" in boot
    assert "branding" in boot
    assert "maintenance" in boot

    r = client.post(
        "/api/mobile/v1/devices/register",
        headers=h,
        json={
            "device_id": "p8-dev",
            "platform": "android",
            "push_token": "token-abc",
            "app_version": "1.0.0",
        },
    )
    assert r.status_code == 200
    assert r.get_json()["device"]["has_push_token"] is True

    r = client.post(
        "/api/mobile/v1/admin/notifications/send",
        headers=_headers(TENANT, staff_id=staff_id),
        json={
            "user_id": user_id,
            "title": "عرض خاص",
            "body": "خصم اليوم",
            "type": "marketing_offer",
        },
    )
    assert r.status_code == 201, r.get_json()

    r = client.get("/api/mobile/v1/notifications", headers=h)
    assert r.status_code == 200
    items = r.get_json()["items"]
    assert len(items) >= 1
    notif_id = items[0]["id"]
    assert r.get_json()["unread_count"] >= 1

    r = client.patch(f"/api/mobile/v1/notifications/{notif_id}/read", headers=h)
    assert r.status_code == 200
    assert r.get_json()["read"] is True

    r = client.post(
        "/api/mobile/v1/analytics/events",
        headers=h,
        json={
            "device_id": "p8-dev",
            "events": [
                {"event_name": "product_view", "product_id": 1},
                {"event_name": "add_to_cart", "product_id": 1},
                {"event_name": "order_placed", "order_id": 9},
                {"event_name": "hack_event"},  # rejected
            ],
        },
    )
    assert r.status_code == 200
    assert r.get_json()["accepted"] == 3
    assert r.get_json()["rejected"] == 1

    r = client.get(
        "/api/mobile/v1/admin/analytics/summary?days=7",
        headers=_headers(TENANT, staff_id=staff_id),
    )
    assert r.status_code == 200
    summary = r.get_json()["summary"]
    assert summary["counts"].get("add_to_cart") == 1
    assert summary["funnel"]["order_placed"] == 1

    r = client.patch(
        "/api/mobile/v1/admin/feature-flags",
        headers=_headers(TENANT, staff_id=staff_id),
        json={"key": "ai_assistant_enabled", "enabled": False},
    )
    assert r.status_code == 200
    assert r.get_json()["feature_flags"]["ai_assistant_enabled"] is False

    r = client.patch(
        "/api/mobile/v1/admin/design",
        headers=_headers(TENANT, staff_id=staff_id),
        json={"app_name": "Finora Shop", "gold_accent": "#C9A227"},
    )
    assert r.status_code == 200
    assert r.get_json()["design"]["app_name"] == "Finora Shop"

    r = client.get("/api/mobile/v1/bootstrap", headers=_headers(TENANT))
    assert r.get_json()["branding"]["app_name"] == "Finora Shop"
    assert r.get_json()["feature_flags"]["ai_assistant_enabled"] is False

    _wipe(TENANT)
