"""Phase 5 cart / checkout / orders tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_cart_{os.getpid()}"


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


def test_mobile_cart_checkout_and_orders():
    _wipe(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        p1 = Product(
            name="سماعات",
            buy_price=10000,
            sale_price=25000,
            quantity=5,
            active=True,
        )
        p2 = Product(
            name="كابل",
            buy_price=1000,
            sale_price=3000,
            quantity=1,
            active=True,
        )
        db.session.add_all([p1, p2])
        db.session.commit()
        product_id = p1.id
        limited_id = p2.id

    client = app.test_client()
    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT),
        json={"phone": "07701112233"},
    )
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={
            "phone": "07701112233",
            "code": code,
            "device_id": "cart-dev",
            "name": "Buyer",
        },
    )
    assert r.status_code == 200, r.get_json()
    token = r.get_json()["access_token"]
    h = _headers(TENANT, token)

    r = client.get("/api/mobile/v1/cart", headers=h)
    assert r.status_code == 200
    assert r.get_json()["items"] == []

    r = client.post(
        "/api/mobile/v1/cart/items",
        headers=h,
        json={"product_id": product_id, "quantity": 2},
    )
    assert r.status_code == 200
    cart = r.get_json()
    assert cart["items_count"] == 2
    assert cart["subtotal"] == 50000
    item_id = cart["items"][0]["id"]

    # stock limit on limited product
    r = client.post(
        "/api/mobile/v1/cart/items",
        headers=h,
        json={"product_id": limited_id, "quantity": 2},
    )
    assert r.status_code == 400
    assert r.get_json()["code"] == "stock_limit"

    r = client.patch(
        f"/api/mobile/v1/cart/items/{item_id}",
        headers=h,
        json={"quantity": 1},
    )
    assert r.status_code == 200
    assert r.get_json()["items_count"] == 1

    r = client.post("/api/mobile/v1/cart/validate", headers=h)
    assert r.status_code == 200
    assert r.get_json()["valid"] is True

    r = client.post(
        "/api/mobile/v1/checkout/preview",
        headers=h,
        json={"shipping_fee": 5000},
    )
    assert r.status_code == 200
    assert r.get_json()["grand_total"] == 30000

    r = client.post(
        "/api/mobile/v1/orders",
        headers=h,
        json={
            "customer_name": "Buyer",
            "phone": "07701112233",
            "city": "بغداد",
            "address": "الكرادة شارع 62",
            "notes": "اتصال قبل التوصيل",
            "shipping_fee": 5000,
        },
    )
    assert r.status_code == 201, r.get_json()
    order_payload = r.get_json()["order"]
    invoice_id = order_payload["invoice_id"]
    assert order_payload.get("attribution_video_id") is None

    r = client.get("/api/mobile/v1/cart", headers=h)
    assert r.get_json()["items"] == []

    r = client.get("/api/mobile/v1/orders", headers=h)
    assert r.status_code == 200
    items = r.get_json()["items"]
    assert len(items) >= 1
    assert items[0]["id"] == invoice_id
    assert items[0]["steps"]

    r = client.get(f"/api/mobile/v1/orders/{invoice_id}", headers=h)
    assert r.status_code == 200
    detail = r.get_json()["order"]
    assert detail["total"] == 25000
    assert any(i["product_id"] == product_id for i in detail["items"])
    assert "source=mobile_app" in (detail.get("note") or "")

    r = client.post(f"/api/mobile/v1/orders/{invoice_id}/cancel", headers=h)
    assert r.status_code == 200
    assert r.get_json()["order"]["status"] == "ملغي"

    _wipe(TENANT)
