"""Profile, addresses, and unified search API tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_profile_{os.getpid()}"


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


def _login(client, tenant: str) -> str:
    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(tenant),
        json={"phone": "07709998877"},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(tenant),
        json={
            "phone": "07709998877",
            "code": code,
            "device_id": "profile-device",
            "name": "سارة",
            "platform": "android",
        },
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["access_token"]


def test_profile_addresses_unified_search():
    _wipe(TENANT)
    from app import app
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from extensions import db
    from modules.mobile_app.models import MobileVideo
    from datetime import datetime

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        p = Product(
            name="عطر اختبار بحث",
            buy_price=15000,
            sale_price=25000,
            quantity=10,
            active=True,
            meta_json='{"category":"عطور"}',
        )
        db.session.add(p)
        video = MobileVideo(
            title="فيديو عطر تجريبي",
            description="وصف بحث",
            status="published",
            processing_status="ready",
            processing_progress=100,
            visibility="public",
            published_at=datetime.utcnow(),
        )
        db.session.add(video)
        db.session.commit()

    client = app.test_client()
    token = _login(client, TENANT)
    h = _headers(TENANT, token)

    r = client.get("/api/mobile/v1/profile", headers=h)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["user"]["name"] == "سارة"
    assert "rewards" in body

    r = client.patch(
        "/api/mobile/v1/profile",
        headers=h,
        json={"name": "سارة علي", "city": "بغداد", "email": "sara@example.com"},
    )
    assert r.status_code == 200
    assert r.get_json()["user"]["name"] == "سارة علي"

    r = client.post(
        "/api/mobile/v1/profile/addresses",
        headers=h,
        json={
            "label": "المنزل",
            "city": "بغداد",
            "address": "الكرادة شارع 14",
            "is_default": True,
        },
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    addr_id = r.get_json()["address"]["id"]

    r = client.get("/api/mobile/v1/profile/addresses", headers=h)
    assert r.status_code == 200
    assert len(r.get_json()["items"]) == 1

    r = client.patch(
        f"/api/mobile/v1/profile/addresses/{addr_id}",
        headers=h,
        json={"notes": "قرب المول"},
    )
    assert r.status_code == 200
    assert r.get_json()["address"]["notes"] == "قرب المول"

    r = client.get("/api/mobile/v1/search/unified?q=عطر", headers=h)
    assert r.status_code == 200
    search = r.get_json()
    assert search["ok"] is True
    assert any("عطر" in (p.get("name") or "") for p in search["products"])
    assert any("عطر" in (v.get("title") or "") for v in search["videos"])

    r = client.delete(f"/api/mobile/v1/profile/addresses/{addr_id}", headers=h)
    assert r.status_code == 200

    r = client.post(
        "/api/mobile/v1/profile/delete-account",
        headers=h,
        json={"reason": "اختبار"},
    )
    assert r.status_code == 200

    r = client.get("/api/mobile/v1/profile", headers=h)
    assert r.status_code in {401, 403}

    _wipe(TENANT)
