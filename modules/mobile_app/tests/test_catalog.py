"""Phase 4 catalog / favorites / video-product link tests."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_catalog_{os.getpid()}"


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


def test_mobile_catalog_search_favorites_and_video_link():
    _wipe(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.employee import Employee
    from models.product import Product
    from modules.mobile_app.models import MobileVideo
    from werkzeug.security import generate_password_hash

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        admin = Employee(
            name="Admin",
            username=f"catadmin_{os.getpid()}",
            password=generate_password_hash("x"),
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
        db.session.flush()
        p1 = Product(
            name="شاشة 55",
            buy_price=200000,
            sale_price=300000,
            quantity=4,
            active=True,
            meta_json='{"category":"شاشات","compare_at_price":350000}',
        )
        p2 = Product(
            name="ثلاجة",
            buy_price=100000,
            sale_price=150000,
            quantity=0,
            active=True,
            meta_json='{"category":"أجهزة"}',
        )
        db.session.add_all([p1, p2])
        video = MobileVideo(
            creator_employee_id=admin.id,
            title="Promo",
            status="published",
            visibility="public",
            processing_status="ready",
            processing_progress=100,
            published_at=datetime.utcnow(),
        )
        db.session.add(video)
        db.session.commit()
        staff_id = admin.id
        product_id = p1.id
        video_id = video.id

    client = app.test_client()

    # Guests can discover the store without creating an account.
    r = client.get("/api/mobile/v1/categories", headers=_headers(TENANT))
    assert r.status_code == 200
    r = client.get("/api/mobile/v1/products", headers=_headers(TENANT))
    assert r.status_code == 200
    assert any(i["id"] == product_id for i in r.get_json()["items"])
    first_page = client.get(
        "/api/mobile/v1/products?limit=1", headers=_headers(TENANT)
    ).get_json()
    assert len(first_page["items"]) == 1
    assert first_page["has_more"] is True
    second_page = client.get(
        f"/api/mobile/v1/products?limit=1&offset={first_page['next_offset']}",
        headers=_headers(TENANT),
    ).get_json()
    assert len(second_page["items"]) == 1
    assert second_page["items"][0]["id"] != first_page["items"][0]["id"]
    category_page = client.get(
        "/api/mobile/v1/products",
        query_string={"category": "شاشات", "limit": 1},
        headers=_headers(TENANT),
    ).get_json()
    assert [item["id"] for item in category_page["items"]] == [product_id]
    assert category_page["has_more"] is False
    r = client.get(
        f"/api/mobile/v1/products/{product_id}", headers=_headers(TENANT)
    )
    assert r.status_code == 200

    # Personal actions remain account-only.
    r = client.post(
        f"/api/mobile/v1/favorites/{product_id}", headers=_headers(TENANT)
    )
    assert r.status_code == 401

    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT),
        json={"phone": "07705556677"},
    )
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={"phone": "07705556677", "code": code, "device_id": "cat-dev", "name": "Buyer"},
    )
    access = r.get_json()["access_token"]

    r = client.get("/api/mobile/v1/categories", headers=_headers(TENANT, access))
    assert r.status_code == 200
    cats = [c["name"] for c in r.get_json()["items"]]
    assert "شاشات" in cats

    r = client.get("/api/mobile/v1/products", headers=_headers(TENANT, access))
    assert r.status_code == 200
    assert len(r.get_json()["items"]) >= 2

    r = client.get("/api/mobile/v1/search?q=شاشة", headers=_headers(TENANT, access))
    assert r.status_code == 200
    assert any(i["id"] == product_id for i in r.get_json()["items"])

    r = client.get("/api/mobile/v1/offers", headers=_headers(TENANT, access))
    assert r.status_code == 200
    assert any(i["id"] == product_id for i in r.get_json()["items"])

    r = client.get(f"/api/mobile/v1/products/{product_id}", headers=_headers(TENANT, access))
    assert r.status_code == 200
    assert r.get_json()["product"]["stock_status"] == "كمية محدودة"

    r = client.post(
        f"/api/mobile/v1/favorites/{product_id}",
        headers=_headers(TENANT, access),
    )
    assert r.status_code == 200
    assert r.get_json()["favorited"] is True

    r = client.get("/api/mobile/v1/favorites", headers=_headers(TENANT, access))
    assert any(i["id"] == product_id for i in r.get_json()["items"])

    r = client.post(
        f"/api/mobile/v1/admin/videos/{video_id}/products",
        headers=_headers(TENANT, staff_id=staff_id),
        json={"product_id": product_id, "special_price": 280000, "custom_cta": "اشترِ الآن"},
    )
    assert r.status_code == 201, r.get_data(as_text=True)

    r = client.get(
        f"/api/mobile/v1/videos/{video_id}/products",
        headers=_headers(TENANT, access),
    )
    assert r.status_code == 200
    items = r.get_json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == product_id
    assert items[0]["special_price"] == 280000

    _wipe(TENANT)
