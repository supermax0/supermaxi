"""Phase 7 Finora AI tool-grounded assistant tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_ai_{os.getpid()}"


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


def test_mobile_ai_budget_search_and_cart_confirm():
    _wipe(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True
    # Force deterministic tool path (no live OpenAI).
    os.environ.pop("OPENAI_API_KEY", None)

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        p1 = Product(
            name="شاشة 70 إنش",
            buy_price=400000,
            sale_price=650000,
            quantity=3,
            active=True,
        )
        p2 = Product(
            name="شاشة 65 إنش ضد الكسر",
            buy_price=350000,
            sale_price=590000,
            quantity=2,
            active=True,
        )
        p3 = Product(
            name="شاشة 85 إنش",
            buy_price=700000,
            sale_price=950000,
            quantity=1,
            active=True,
        )
        db.session.add_all([p1, p2, p3])
        db.session.commit()
        cheap_id = p2.id

    client = app.test_client()
    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT),
        json={"phone": "07701234567"},
    )
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={
            "phone": "07701234567",
            "code": code,
            "device_id": "ai-dev",
            "name": "AI User",
        },
    )
    assert r.status_code == 200
    token = r.get_json()["access_token"]
    h = _headers(TENANT, token)

    r = client.post("/api/mobile/v1/ai/conversations", headers=h, json={})
    assert r.status_code == 201, r.get_json()
    conv_id = r.get_json()["conversation"]["id"]

    r = client.post(
        f"/api/mobile/v1/ai/conversations/{conv_id}/messages",
        headers=h,
        json={"content": "أريد شاشة حجم كبير وميزانيتي 700 ألف"},
    )
    assert r.status_code == 200, r.get_json()
    assistant = r.get_json()["assistant_message"]
    assert "شاشة" in assistant["content"]
    products = (assistant.get("meta") or {}).get("products") or []
    assert products
    assert all(int(p["price"]) <= 700000 for p in products)
    assert {p["name"] for p in products} <= {"شاشة 70 إنش", "شاشة 65 إنش ضد الكسر"}

    # Rewards tool path
    r = client.post(
        f"/api/mobile/v1/ai/conversations/{conv_id}/messages",
        headers=h,
        json={"content": "كم رصيد نقاطي؟"},
    )
    assert r.status_code == 200
    assert "نقطة" in r.get_json()["assistant_message"]["content"]

    # Confirm add to cart flow
    r = client.post(
        f"/api/mobile/v1/ai/conversations/{conv_id}/messages",
        headers=h,
        json={"content": f"أضف للعربة منتج #{cheap_id}"},
    )
    assert r.status_code == 200
    pending = (r.get_json()["assistant_message"].get("meta") or {}).get("pending_actions") or []
    assert pending
    assert pending[0]["product_id"] == cheap_id

    r = client.post(
        f"/api/mobile/v1/ai/conversations/{conv_id}/confirm-action",
        headers=h,
        json={"action": pending[0]},
    )
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["ok"] is True

    r = client.get("/api/mobile/v1/cart", headers=h)
    assert r.status_code == 200
    assert any(i["product_id"] == cheap_id for i in r.get_json()["items"])

    r = client.get("/api/mobile/v1/ai/conversations", headers=h)
    assert r.status_code == 200
    assert len(r.get_json()["items"]) >= 1

    _wipe(TENANT)
