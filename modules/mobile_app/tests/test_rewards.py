"""Phase 6 rewards / coupons / campaigns tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_rewards_{os.getpid()}"


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


def test_mobile_rewards_coupons_and_pending_points():
    _wipe(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.employee import Employee
    from models.invoice import Invoice
    from models.product import Product
    from werkzeug.security import generate_password_hash

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        admin = Employee(
            name="Admin",
            username=f"rewadmin_{os.getpid()}",
            password=generate_password_hash("x"),
            role="admin",
            is_active=True,
        )
        product = Product(
            name="مكنسة",
            buy_price=20000,
            sale_price=100000,
            quantity=10,
            active=True,
        )
        db.session.add_all([admin, product])
        db.session.commit()
        staff_id = admin.id
        product_id = product.id

    client = app.test_client()
    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT),
        json={"phone": "07709998877"},
    )
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={
            "phone": "07709998877",
            "code": code,
            "device_id": "rew-dev",
            "name": "Rewarder",
        },
    )
    assert r.status_code == 200, r.get_json()
    token = r.get_json()["access_token"]
    user_id = r.get_json()["user"]["id"]
    h = _headers(TENANT, token)

    r = client.get("/api/mobile/v1/rewards", headers=h)
    assert r.status_code == 200, r.get_json()
    rewards = r.get_json()["rewards"]
    assert rewards["balance"] >= 50  # welcome bonus

    r = client.post(
        "/api/mobile/v1/admin/coupons",
        headers=_headers(TENANT, staff_id=staff_id),
        json={
            "code": "SAVE10",
            "name": "خصم 10%",
            "discount_type": "percent",
            "value": 10,
            "min_subtotal": 0,
        },
    )
    assert r.status_code == 201, r.get_json()

    r = client.post(
        "/api/mobile/v1/cart/items",
        headers=h,
        json={"product_id": product_id, "quantity": 1},
    )
    assert r.status_code == 200
    assert r.get_json()["subtotal"] == 100000

    r = client.post(
        "/api/mobile/v1/cart/apply-coupon",
        headers=h,
        json={"code": "SAVE10"},
    )
    assert r.status_code == 200, r.get_json()
    cart = r.get_json()
    assert cart["coupon_code"] == "SAVE10"
    assert cart["coupon_discount"] == 10000
    assert cart["grand_total"] == 90000

    # Extra points via admin adjust for redemption test later
    r = client.post(
        "/api/mobile/v1/admin/rewards/adjust",
        headers=_headers(TENANT, staff_id=staff_id),
        json={
            "user_id": user_id,
            "points": 200,
            "direction": "credit",
            "description": "test topup",
        },
    )
    assert r.status_code == 200, r.get_json()

    r = client.post(
        "/api/mobile/v1/cart/apply-points",
        headers=h,
        json={"points": 100},
    )
    assert r.status_code == 200, r.get_json()
    cart = r.get_json()
    assert cart["points_to_redeem"] == 100
    assert cart["points_discount"] == 1000
    assert cart["grand_total"] == 89000

    r = client.post(
        "/api/mobile/v1/orders",
        headers=h,
        json={
            "customer_name": "Rewarder",
            "phone": "07709998877",
            "city": "بغداد",
            "address": "المنصور شارع 14",
        },
    )
    assert r.status_code == 201, r.get_json()
    invoice_id = r.get_json()["order"]["invoice_id"]
    assert r.get_json()["order"]["discount_amount"] == 11000

    r = client.get("/api/mobile/v1/rewards/history", headers=h)
    assert r.status_code == 200
    types = {i["type"] for i in r.get_json()["items"]}
    assert "purchase_reward" in types
    assert "redemption" in types
    pending = [i for i in r.get_json()["items"] if i["status"] == "pending"]
    assert pending

    # Confirm points when order completed
    with app.app_context():
        g.tenant = TENANT
        inv = db.session.get(Invoice, invoice_id)
        inv.status = "مكتمل"
        db.session.commit()

    r = client.get("/api/mobile/v1/rewards", headers=h)
    assert r.status_code == 200
    hist = client.get("/api/mobile/v1/rewards/history", headers=h).get_json()["items"]
    purchase = next(i for i in hist if i["type"] == "purchase_reward")
    assert purchase["status"] == "confirmed"

    r = client.get("/api/mobile/v1/coupons", headers=h)
    assert r.status_code == 200
    assert any(c["code"] == "SAVE10" for c in r.get_json()["items"])

    _wipe(TENANT)
