"""POS machine API + shared checkout service tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_pos_api_{os.getpid()}"


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


def _headers(token: str | None = None, tenant: str = TENANT) -> dict:
    h = {"X-Tenant-Slug": tenant, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _seed():
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch, BranchStock
    from models.customer import Customer
    from models.employee import Employee
    from models.product import Product
    from utils.branch_migration import get_default_branch

    g.tenant = TENANT
    init_tenant_db(TENANT)
    branch = get_default_branch()
    second = Branch(code="B2", name="Second", is_active=True)
    db.session.add(second)
    db.session.flush()
    admin = Employee(
        name="Ahmed",
        username="posapi_admin",
        password="secret",
        role="admin",
        is_active=True,
        branch_id=branch.id,
    )
    cashier = Employee(
        name="Cashier",
        username="posapi_cashier",
        password="secret",
        role="cashier",
        is_active=True,
        branch_id=branch.id,
    )
    customer = Customer(
        branch_id=branch.id,
        name="علي حسين",
        phone="07801234567",
        city="كربلاء",
        address="حي الحسين",
    )
    product = Product(
        branch_id=branch.id,
        name="شاشة جنرال 50",
        buy_price=300000,
        sale_price=425000,
        quantity=7,
        active=True,
    )
    db.session.add_all([admin, cashier, customer, product])
    db.session.flush()
    db.session.add(
        BranchStock(branch_id=branch.id, product_id=product.id, quantity=7, opening_stock=7)
    )
    db.session.commit()
    return {
        "branch_id": branch.id,
        "second_branch_id": second.id,
        "admin_id": admin.id,
        "cashier_id": cashier.id,
        "customer_id": customer.id,
        "product_id": product.id,
    }


def test_pos_api_login_search_preview_create_idempotency_and_price_rules():
    _wipe()
    from app import app
    from flask import g
    from extensions import db
    from models.invoice import Invoice
    from models.product import Product

    app.config["TESTING"] = True
    with app.app_context():
        ids = _seed()

    client = app.test_client()
    denied = client.get("/api/v1/pos/products", query_string={"q": "جنرال"})
    assert denied.status_code in (400, 401)

    login = client.post(
        "/api/v1/pos/auth/login",
        headers=_headers(),
        json={"username": "posapi_admin", "password": "secret"},
    )
    assert login.status_code == 200, login.get_data(as_text=True)
    body = login.get_json()
    assert body["ok"] is True
    token = body["access_token"]
    assert body["employee"]["name"] == "Ahmed"
    assert "view_pos" in body["permissions"]
    auth = _headers(token)

    customers = client.get("/api/v1/pos/customers", query_string={"q": "07801234567"}, headers=auth)
    assert customers.status_code == 200
    found = customers.get_json()["customers"]
    assert any(row["id"] == ids["customer_id"] for row in found)

    products = client.get("/api/v1/pos/products", query_string={"q": "جنرال 50"}, headers=auth)
    assert products.status_code == 200
    listed = products.get_json()["products"]
    assert any(row["id"] == ids["product_id"] for row in listed)

    preview = client.post(
        "/api/v1/pos/orders/preview",
        headers=auth,
        json={
            "customer_id": ids["customer_id"],
            "items": [{"product_id": ids["product_id"], "quantity": 1}],
            "branch_id": ids["branch_id"],
        },
    )
    assert preview.status_code == 200, preview.get_data(as_text=True)
    preview_body = preview.get_json()["preview"]
    assert preview_body["total"] == 425000
    assert preview_body["stock_ok"] is True
    assert preview_body["items"][0]["unit_price"] == 425000

    cashier_login = client.post(
        "/api/v1/pos/auth/login",
        headers=_headers(),
        json={"username": "posapi_cashier", "password": "secret"},
    )
    cashier_token = cashier_login.get_json()["access_token"]
    blocked = client.post(
        "/api/v1/pos/orders/preview",
        headers=_headers(cashier_token),
        json={
            "customer_id": ids["customer_id"],
            "items": [{"product_id": ids["product_id"], "quantity": 1, "override_price": 400000}],
            "branch_id": ids["branch_id"],
        },
    )
    assert blocked.status_code == 403
    assert blocked.get_json()["code"] == "PRICE_OVERRIDE_NOT_ALLOWED"

    forbidden_branch = client.post(
        "/api/v1/pos/orders/preview",
        headers=_headers(cashier_token),
        json={
            "customer_id": ids["customer_id"],
            "items": [{"product_id": ids["product_id"], "quantity": 1}],
            "branch_id": ids["second_branch_id"],
        },
    )
    assert forbidden_branch.status_code == 403
    assert forbidden_branch.get_json()["code"] == "BRANCH_NOT_ALLOWED"

    idem = "voice-action-f742-test"
    create = client.post(
        "/api/v1/pos/orders",
        headers={**auth, "Idempotency-Key": idem},
        json={
            "customer_id": ids["customer_id"],
            "items": [{"product_id": ids["product_id"], "quantity": 1}],
            "branch_id": ids["branch_id"],
            "note": "من المساعد الصوتي",
        },
    )
    assert create.status_code == 200, create.get_data(as_text=True)
    created = create.get_json()
    assert created["ok"] is True
    order_id = created["order_id"]
    assert created["total"] == 425000
    assert created.get("duplicate") is False

    replay = client.post(
        "/api/v1/pos/orders",
        headers={**auth, "Idempotency-Key": idem},
        json={
            "customer_id": ids["customer_id"],
            "items": [{"product_id": ids["product_id"], "quantity": 1}],
            "branch_id": ids["branch_id"],
        },
    )
    assert replay.status_code == 200
    replayed = replay.get_json()
    assert replayed["duplicate"] is True
    assert replayed["order_id"] == order_id

    with app.app_context():
        g.tenant = TENANT
        assert Invoice.query.count() == 1
        product = Product.query.get(ids["product_id"])
        assert int(product.quantity or 0) <= 7

    recent = client.get("/api/v1/pos/orders/recent", headers=auth)
    assert recent.status_code == 200
    assert any(row["id"] == order_id for row in recent.get_json()["orders"])

    searched = client.get(
        "/api/v1/pos/orders/search",
        query_string={"customer": "علي", "product": "جنرال", "province": "كربلاء"},
        headers=auth,
    )
    assert searched.status_code == 200
    assert any(row["id"] == order_id for row in searched.get_json()["orders"])

    detail = client.get(f"/api/v1/pos/orders/{order_id}", headers=auth)
    assert detail.status_code == 200
    assert detail.get_json()["order"]["remaining"] == 425000

    pay_preview = client.post(
        f"/api/v1/pos/orders/{order_id}/payments/preview",
        headers=auth,
        json={"mode": "partial", "amount": 50000, "method": "cash"},
    )
    assert pay_preview.status_code == 200, pay_preview.get_data(as_text=True)
    assert pay_preview.get_json()["payment"]["remaining_after"] == 375000

    paid = client.post(
        f"/api/v1/pos/orders/{order_id}/payments",
        headers=auth,
        json={"mode": "partial", "amount": 50000, "method": "cash"},
    )
    assert paid.status_code == 200, paid.get_data(as_text=True)
    assert paid.get_json()["payment"]["remaining"] == 375000

    full_preview = client.post(
        f"/api/v1/pos/orders/{order_id}/payments/preview",
        headers=auth,
        json={"mode": "full", "method": "cash"},
    )
    assert full_preview.status_code == 200
    assert full_preview.get_json()["payment"]["remaining_after"] == 0

    cancel_other = client.post(
        "/api/v1/pos/orders",
        headers={**auth, "Idempotency-Key": "voice-cancel-order"},
        json={
            "customer_id": ids["customer_id"],
            "items": [{"product_id": ids["product_id"], "quantity": 1}],
            "branch_id": ids["branch_id"],
        },
    )
    cancel_id = cancel_other.get_json()["order_id"]
    cancel_preview = client.post(f"/api/v1/pos/orders/{cancel_id}/cancel/preview", headers=auth)
    assert cancel_preview.status_code == 200
    cancelled = client.post(
        f"/api/v1/pos/orders/{cancel_id}/cancel",
        headers=auth,
        json={"reason": "الزبون ألغى الطلب"},
    )
    assert cancelled.status_code == 200, cancelled.get_data(as_text=True)
    assert cancelled.get_json()["status"] == "ملغي"


def test_web_pos_create_order_uses_shared_service():
    _wipe(f"{TENANT}_web")
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.product import Product
    from models.branch import BranchStock
    from routes.pos import create_order
    from utils.branch_migration import get_default_branch

    tenant = f"{TENANT}_web"
    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        branch = get_default_branch()
        customer = Customer(branch_id=branch.id, name="Web POS Customer", phone="07700000999")
        employee = Employee(
            name="Web Cashier",
            username="web_pos_cashier",
            password="x",
            role="admin",
            is_active=True,
            branch_id=branch.id,
        )
        product = Product(
            branch_id=branch.id,
            name="Web Item",
            buy_price=10,
            sale_price=100,
            quantity=5,
            active=True,
        )
        db.session.add_all([customer, employee, product])
        db.session.flush()
        db.session.add(BranchStock(branch_id=branch.id, product_id=product.id, quantity=5, opening_stock=5))
        db.session.commit()
        payload = {
            "customer_id": customer.id,
            "items": [{"product_id": product.id, "qty": 1, "price": 100}],
            "branch_id": branch.id,
        }
        employee_id = employee.id

    with app.test_request_context("/pos/create-order", method="POST", json=payload):
        g.tenant = tenant
        session["user_id"] = employee_id
        resp = create_order()
        status = 200
        if isinstance(resp, tuple):
            resp, status = resp
        data = resp.get_json()
        assert status == 200
        assert data["success"] is True
        assert data["invoice_id"]


def test_pos_api_long_lived_key_issue_use_and_revoke():
    _wipe()
    from app import app

    app.config["TESTING"] = True
    with app.app_context():
        _seed()

    client = app.test_client()
    cashier_denied = client.post(
        "/api/v1/pos/auth/login",
        headers=_headers(),
        json={"username": "posapi_cashier", "password": "secret", "issue_api_key": True},
    )
    assert cashier_denied.status_code == 403
    assert cashier_denied.get_json()["code"] == "forbidden"

    login = client.post(
        "/api/v1/pos/auth/login",
        headers=_headers(),
        json={"username": "posapi_admin", "password": "secret", "issue_api_key": True},
    )
    assert login.status_code == 200, login.get_data(as_text=True)
    body = login.get_json()
    api_key = body["api_key"]
    assert api_key.startswith("finora_pos_")
    assert TENANT in api_key

    products = client.get(
        "/api/v1/pos/products",
        query_string={"q": "جنرال"},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    assert products.status_code == 200, products.get_data(as_text=True)
    assert products.get_json()["ok"] is True

    jwt_auth = _headers(body["access_token"])
    listed = client.get("/api/v1/pos/auth/api-keys", headers=jwt_auth)
    assert listed.status_code == 200
    keys = listed.get_json()["keys"]
    assert len(keys) == 1
    key_id = keys[0]["id"]

    revoked = client.delete(f"/api/v1/pos/auth/api-keys/{key_id}", headers=jwt_auth)
    assert revoked.status_code == 200
    after_revoke = client.get(
        "/api/v1/pos/products",
        query_string={"q": "جنرال"},
        headers={"Authorization": f"Bearer {api_key}", "X-Tenant-Slug": TENANT},
    )
    assert after_revoke.status_code == 401
    assert after_revoke.get_json()["code"] == "token_invalid"
