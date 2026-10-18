"""Public store catalog API."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_store_api_{os.getpid()}"


def _wipe(tenant: str = TENANT) -> None:
    try:
        from extensions import db

        db.session.remove()
    except Exception:
        pass
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(tenant)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def _seed():
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.employee import Employee
    from models.product import Product
    from utils.branch_migration import get_default_branch

    g.tenant = TENANT
    init_tenant_db(TENANT)
    branch = get_default_branch()
    admin = Employee(name="Admin", username="storeapi_admin", password="secret", role="admin", is_active=True, branch_id=branch.id)
    visible = Product(
        branch_id=branch.id,
        name="شاشة للعرض",
        sku="TV-1",
        buy_price=100000,
        sale_price=250000,
        quantity=4,
        active=True,
        store_visible=True,
        description="وصف المتجر",
    )
    hidden = Product(
        branch_id=branch.id,
        name="مخفي عن المتجر",
        buy_price=50000,
        sale_price=90000,
        quantity=2,
        active=True,
        store_visible=False,
    )
    db.session.add_all([admin, visible, hidden])
    db.session.commit()
    return {"admin_id": admin.id, "visible_id": visible.id, "hidden_id": hidden.id}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_store_api_hides_cost_and_unpublished_products():
    _wipe()
    from app import app
    from flask import g
    from modules.store_api.services.api_keys import issue_api_key, revoke_api_key

    app.config["TESTING"] = True
    with app.app_context():
        ids = _seed()
        g.tenant = TENANT
        token, row = issue_api_key(tenant_slug=TENANT, created_by=ids["admin_id"])
        key_id = row.id

    client = app.test_client()
    denied = client.get("/api/v1/store/products")
    assert denied.status_code == 401

    listed = client.get("/api/v1/store/products", headers=_auth(token))
    assert listed.status_code == 200
    body = listed.get_json()
    assert body["ok"] is True
    assert body["total"] == 1
    assert body["products"][0]["name"] == "شاشة للعرض"
    assert body["products"][0]["price"] == 250000
    assert body["products"][0]["price_currency"] == "IQD"
    assert body["products"][0]["currency"] != "USD"
    assert "USD" in body["store"]["currencies"]
    assert body["products"][0]["sku"] == "TV-1"
    assert "buy_price" not in listed.get_data(as_text=True)
    assert body["store"]["api_base_url"].endswith("/api/v1/store")

    one = client.get(f"/api/v1/store/products/{ids['visible_id']}", headers=_auth(token))
    assert one.status_code == 200
    assert one.get_json()["product"]["stock"] == 4

    missing = client.get(f"/api/v1/store/products/{ids['hidden_id']}", headers=_auth(token))
    assert missing.status_code == 404

    profile = client.get("/api/v1/store", headers=_auth(token))
    assert profile.status_code == 200
    assert profile.get_json()["connected"] is True

    with app.app_context():
        g.tenant = TENANT
        assert revoke_api_key(key_id) is True
    revoked = client.get("/api/v1/store", headers=_auth(token))
    assert revoked.status_code == 401
    _wipe()


def _core_tenant():
    from datetime import datetime, timedelta
    from flask import g
    from extensions import db
    from models.core.tenant import Tenant as CoreTenant

    g.tenant = None
    CoreTenant.query.filter_by(slug=TENANT).delete()
    db.session.add(
        CoreTenant(
            name="Store API",
            slug=TENANT,
            db_path=f"tenants/{TENANT}.db",
            business_type="general",
            is_active=True,
            subscription_end_date=datetime.utcnow() + timedelta(days=30),
        )
    )
    db.session.commit()
    g.tenant = TENANT


def _drop_core_tenant():
    from flask import g
    from extensions import db
    from models.core.tenant import Tenant as CoreTenant

    g.tenant = None
    CoreTenant.query.filter_by(slug=TENANT).delete()
    db.session.commit()


def test_store_settings_issues_token_once():
    _wipe()
    from app import app

    app.config["TESTING"] = True
    with app.app_context():
        ids = _seed()
        _core_tenant()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = ids["admin_id"]
        sess["tenant_slug"] = TENANT
        sess["role"] = "admin"

    page = client.get("/settings/storefront")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "API Base URL" in html
    assert "إصدار رمز API" in html

    created = client.post("/settings/storefront/api/keys")
    assert created.status_code == 200
    payload = created.get_json()
    assert payload["api_token"].startswith(f"sk_{TENANT}.")
    assert payload["api_base_url"].endswith("/api/v1/store")

    listed = client.get("/api/v1/store/products", headers=_auth(payload["api_token"]))
    assert listed.status_code == 200
    assert listed.get_json()["total"] == 1
    with app.app_context():
        _drop_core_tenant()
    _wipe()


def test_store_api_controls_products_orders_and_settings():
    _wipe()
    from app import app
    from flask import g
    from extensions import db
    from models.customer import Customer
    from models.invoice import Invoice
    from modules.store_api.services.api_keys import issue_api_key

    app.config["TESTING"] = True
    with app.app_context():
        _seed()
        g.tenant = TENANT
        token, _row = issue_api_key(tenant_slug=TENANT)
        customer = Customer(name="زينب", phone="07801112233", city="بغداد", address="الكرادة")
        db.session.add(customer)
        db.session.flush()
        store_order = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=250000,
            status="تم الطلب",
            payment_status="غير مسدد",
            note="طلب من متجر المنتجات | COD",
        )
        other = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            status="تم الطلب",
            payment_status="غير مسدد",
            note="طلب من نقطة البيع",
        )
        db.session.add_all([store_order, other])
        db.session.commit()
        order_id = store_order.id

    client = app.test_client()
    headers = {**_auth(token), "Content-Type": "application/json"}
    created = client.post(
        "/api/v1/store/products",
        headers=headers,
        json={"name": "مكيف جديد", "price": 180000, "category": "سبالت", "quantity": 2},
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    product = created.get_json()["product"]
    assert product["name"] == "مكيف جديد"
    assert product["price"] == 180000
    assert product["store_visible"] is True
    assert "buy_price" not in created.get_data(as_text=True)

    public = client.get("/api/v1/store/products", headers=headers)
    names = [row["name"] for row in public.get_json()["products"]]
    assert "مكيف جديد" in names
    assert "مخفي عن المتجر" not in names

    patched = client.patch(
        f"/api/v1/store/products/{product['id']}",
        headers=headers,
        json={"price": 170000, "store_visible": False},
    )
    assert patched.status_code == 200
    assert patched.get_json()["product"]["price"] == 170000
    assert patched.get_json()["product"]["store_visible"] is False

    hidden = client.get(f"/api/v1/store/products/{product['id']}", headers=headers)
    assert hidden.status_code == 404
    managed = client.get(f"/api/v1/store/products/{product['id']}?include_hidden=1", headers=headers)
    assert managed.status_code == 200

    orders = client.get("/api/v1/store/orders", headers=headers)
    assert orders.status_code == 200
    assert orders.get_json()["total"] == 1
    assert orders.get_json()["orders"][0]["id"] == order_id

    changed = client.patch(
        f"/api/v1/store/orders/{order_id}",
        headers=headers,
        json={"status": "قيد التجهيز", "payment_status": "مسدد"},
    )
    assert changed.status_code == 200
    assert changed.get_json()["order"]["status"] == "قيد التجهيز"
    assert changed.get_json()["order"]["payment_status"] == "مسدد"

    settings = client.patch(
        "/api/v1/store/settings",
        headers=headers,
        json={"store_name": "متجر السيطرة", "shipping_default_fee": 9000, "coupon_code": "SAVE10", "coupon_type": "percent", "coupon_value": 10},
    )
    assert settings.status_code == 200
    saved = settings.get_json()["settings"]
    assert saved["store_name"] == "متجر السيطرة"
    assert saved["shipping_default_fee"] == 9000
    assert saved["coupon"]["code"] == "SAVE10"
    _wipe()


def test_store_api_bulk_category_customers_and_sections():
    _wipe()
    from app import app
    from flask import g
    from extensions import db
    from models.customer import Customer
    from models.invoice import Invoice
    from modules.store_api.services.api_keys import issue_api_key

    app.config["TESTING"] = True
    with app.app_context():
        ids = _seed()
        g.tenant = TENANT
        token, _row = issue_api_key(tenant_slug=TENANT)
        customer = Customer(name="هدى", phone="07804445566", city="البصرة", address="الجبيلة")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=50000,
            status="تم الطلب",
            payment_status="غير مسدد",
            note="طلب من متجر المنتجات",
        )
        db.session.add(invoice)
        db.session.commit()
        customer_id = customer.id
        visible_id = ids["visible_id"]

    client = app.test_client()
    headers = {**_auth(token), "Content-Type": "application/json"}
    created = client.post(
        "/api/v1/store/products",
        headers=headers,
        json={"name": "منتج تجريبي", "price": 300000, "category": "موسمية"},
    )
    assert created.status_code == 201
    product_id = created.get_json()["product"]["id"]

    renamed = client.post(
        "/api/v1/store/categories/rename",
        headers=headers,
        json={"from": "موسمية", "to": "تكييف"},
    )
    assert renamed.status_code == 200
    assert renamed.get_json()["renamed"] == 1
    detail = client.get(f"/api/v1/store/products/{product_id}", headers=headers)
    assert detail.get_json()["product"]["category"] == "تكييف"

    normalized = client.post(
        "/api/v1/store/products",
        headers=headers,
        json={
            "name": "غسالة فول اوتماتيك المتين 20 كيلو الوان موديل 2060",
            "price": 400000,
            "category": "غسالة فول اوتماتيك المتين 20 كيلو الوان موديل 2060",
        },
    )
    assert normalized.status_code == 201
    assert normalized.get_json()["product"]["category"] == "غسالات"

    gallery = client.patch(
        f"/api/v1/store/products/{product_id}",
        headers=headers,
        json={"gallery": ["/static/a.jpg", "/static/b.jpg"], "specs": [{"label": "الحجم", "value": "1 طن"}]},
    )
    assert gallery.status_code == 200
    body = gallery.get_json()["product"]
    assert len(body["gallery"]) == 2
    assert body["specs"][0]["value"] == "1 طن"

    bulk = client.post(
        "/api/v1/store/products/bulk",
        headers=headers,
        json={"ids": [visible_id, product_id], "store_visible": False},
    )
    assert bulk.status_code == 200
    assert set(bulk.get_json()["updated"]) == {visible_id, product_id}

    customers = client.get("/api/v1/store/customers", headers=headers)
    assert customers.status_code == 200
    assert customers.get_json()["total"] == 1
    edited = client.patch(
        f"/api/v1/store/customers/{customer_id}",
        headers=headers,
        json={"city": "النجف", "address": "حي السعد"},
    )
    assert edited.status_code == 200
    assert edited.get_json()["customer"]["city"] == "النجف"

    sections = client.patch(
        "/api/v1/store/settings",
        headers=headers,
        json={"product_sections": [{"id": "offers", "title": "العروض", "enabled": True, "product_mode": "discount", "limit": 8}]},
    )
    assert sections.status_code == 200
    saved = sections.get_json()["settings"]["product_sections"]
    assert saved[0]["title"] == "العروض"
    assert saved[0]["product_mode"] == "discount"
    _wipe()
