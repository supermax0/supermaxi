"""Read adapters used by FINORA Management Desktop (orders lookups/counts and
range filters, paginated products with stock stats, paginated purchases).

They run behind the normal staff session (app.require_login), reuse the same
queries as the web pages, and must enforce the same permissions.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_desktop_data_{os.getpid()}"


def _wipe() -> None:
    try:
        from extensions import db

        db.session.remove()
    except Exception:
        pass
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def _seed() -> dict:
    from flask import g
    from werkzeug.security import generate_password_hash

    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import BranchStock
    from models.customer import Customer
    from models.delivery_agent import DeliveryAgent
    from models.employee import Employee
    from models.invoice import Invoice
    from models.product import Product
    from models.purchase import Purchase
    from models.shipping import ShippingCompany
    from models.supplier import Supplier
    from utils.branch_migration import get_default_branch

    g.tenant = TENANT
    init_tenant_db(TENANT)
    branch = get_default_branch()
    admin = Employee(name="Admin", username="dd_admin", password=generate_password_hash("x-pass-123"),
                     role="admin", is_active=True, branch_id=branch.id)
    clerk = Employee(name="Clerk", username="dd_clerk", password=generate_password_hash("x-pass-123"),
                     role="cashier", is_active=True, branch_id=branch.id)
    baghdad = Customer(branch_id=branch.id, name="أحمد سالم", phone="07701234567", city="بغداد", address="شارع الجامعة")
    basra = Customer(branch_id=branch.id, name="فاطمة محمد", phone="07812345678", city="البصرة", address="حي الجمعية")
    ship = ShippingCompany(name="شركة النقل السريع")
    agent = DeliveryAgent(name="مندوب علي")
    supplier = Supplier(name="شركة الرافدين")
    db.session.add_all([admin, clerk, baghdad, basra, ship, agent, supplier])
    db.session.flush()

    products = [
        Product(branch_id=branch.id, name="شاشة LG 50", sku="TV-LG-50", barcode="6290000000011", buy_price=280000,
                sale_price=325000, quantity=28, low_stock_threshold=5, catalog_category="شاشات", active=True),
        Product(branch_id=branch.id, name="شاشة Samsung 60", sku="TV-SAM-60", barcode="6290000000028",
                buy_price=340000, sale_price=399000, quantity=3, low_stock_threshold=5, catalog_category="شاشات",
                active=True),
        Product(branch_id=branch.id, name="مكيف جنرال", sku="AC-GEN-1", barcode="6290000000035", buy_price=500000,
                sale_price=575000, quantity=0, low_stock_threshold=2, catalog_category="مكيفات", active=True),
    ]
    db.session.add_all(products)
    db.session.flush()
    for product in products:
        db.session.add(BranchStock(branch_id=branch.id, product_id=product.id, quantity=product.quantity,
                                   opening_stock=product.quantity))

    orders = [
        Invoice(customer_id=baghdad.id, customer_name=baghdad.name, branch_id=branch.id, total=450000, paid_amount=0, status="تم الطلب",
                payment_status="غير مسدد", created_at=datetime(2026, 10, 7, 10, 25)),
        Invoice(customer_id=basra.id, customer_name=basra.name, branch_id=branch.id, total=180000, paid_amount=0, status="معباة",
                payment_status="غير مسدد", created_at=datetime(2026, 10, 5, 9, 0)),
        Invoice(customer_id=baghdad.id, customer_name=baghdad.name, branch_id=branch.id, total=720000, paid_amount=0, status="جاري الشحن",
                payment_status="غير مسدد", created_at=datetime(2026, 9, 20, 12, 0), shipping_company_id=None),
    ]
    db.session.add_all(orders)

    purchases = [
        Purchase(supplier_id=supplier.id, product_id=products[0].id, quantity=10, price=280000, total=2800000,
                 grand_total=2800000, paid_total=2800000, remaining_total=0, status="confirmed",
                 invoice_no="P-2026-0001", purchase_date=datetime(2026, 10, 1).date()),
        Purchase(supplier_id=supplier.id, product_id=products[1].id, quantity=5, price=340000, total=1700000,
                 grand_total=1700000, paid_total=0, remaining_total=1700000, status="confirmed",
                 purchase_mode="credit", invoice_no="P-2026-0002", purchase_date=datetime(2026, 10, 3).date()),
        Purchase(supplier_id=supplier.id, product_id=products[2].id, quantity=1, price=500000, total=500000,
                 grand_total=500000, status="draft", invoice_no="P-2026-0003",
                 purchase_date=datetime(2026, 10, 4).date()),
    ]
    db.session.add_all(purchases)
    db.session.commit()
    return {"admin_id": admin.id, "clerk_id": clerk.id, "ship_id": ship.id, "agent_id": agent.id,
            "branch_id": branch.id, "order_ids": [o.id for o in orders]}


@pytest.fixture(scope="module")
def ctx():
    _wipe()
    # Loopback "local workspace" mode: skips only the Core subscription lookup for this
    # throwaway tenant; login, RBAC and branch scoping run exactly as in production.
    previous = os.environ.get("FINORA_LOCAL_WORKSPACE")
    os.environ["FINORA_LOCAL_WORKSPACE"] = "1"
    from app import app

    app.config["TESTING"] = True
    with app.app_context():
        ids = _seed()
    yield {"app": app, "ids": ids}
    if previous is None:
        os.environ.pop("FINORA_LOCAL_WORKSPACE", None)
    else:
        os.environ["FINORA_LOCAL_WORKSPACE"] = previous
    _wipe()


def _client(ctx, employee_key="admin_id", role="admin"):
    client = ctx["app"].test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = ctx["ids"][employee_key]
        sess["tenant_slug"] = TENANT
        sess["role"] = role
        sess["name"] = "Admin" if role == "admin" else "Clerk"
    return client


JSON = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}


def test_order_lookups_list_real_options(ctx):
    res = _client(ctx).get("/orders/api/lookups", headers=JSON)
    assert res.status_code == 200, res.get_data(as_text=True)[:400]
    body = res.get_json()
    assert {"بغداد", "البصرة"} <= set(body["cities"])
    assert {"id": ctx["ids"]["ship_id"], "name": "شركة النقل السريع"} in body["shipping_companies"]
    assert {"id": ctx["ids"]["agent_id"], "name": "مندوب علي"} in body["delivery_agents"]
    assert any(b["id"] == ctx["ids"]["branch_id"] for b in body["branches"])


def test_order_counts_follow_the_grid_query_and_filters(ctx):
    client = _client(ctx)
    counts = client.get("/orders/api/counts", headers=JSON).get_json()["counts"]
    assert counts["all"] == 3 and counts["ordered"] == 1 and counts["packed"] == 1 and counts["shipping"] == 1
    filtered = client.get("/orders/api/counts", query_string={"city": "بغداد"}, headers=JSON).get_json()["counts"]
    assert filtered["all"] == 2 and filtered["packed"] == 0


def test_orders_grid_date_and_amount_ranges(ctx):
    client = _client(ctx)
    by_date = client.get("/orders/data", query_string={"date_from": "2026-10-01", "date_to": "2026-10-06",
                                                       "page_size": 10}, headers=JSON).get_json()
    assert [row["total"] for row in by_date["rows"]] == [180000]
    by_amount = client.get("/orders/data", query_string={"amount_min": 200000, "amount_max": 500000,
                                                         "page_size": 10}, headers=JSON).get_json()
    assert [row["total"] for row in by_amount["rows"]] == [450000]


def test_products_page_stats_filters_and_pagination(ctx):
    client = _client(ctx)
    body = client.get("/inventory/api/products", query_string={"page_size": 2}, headers=JSON).get_json()
    assert body["stats"] == {"total": 3, "available": 1, "low": 1, "out": 1}
    assert body["categories"] == sorted(["شاشات", "مكيفات"])
    assert body["total"] == 3 and body["total_pages"] == 2 and len(body["rows"]) == 2

    low = client.get("/inventory/api/products", query_string={"stock": "low"}, headers=JSON).get_json()
    assert [r["sku"] for r in low["rows"]] == ["TV-SAM-60"] and low["rows"][0]["quantity"] == 3

    by_barcode = client.get("/inventory/api/products", query_string={"search": "6290000000035"}, headers=JSON)
    assert [r["name"] for r in by_barcode.get_json()["rows"]] == ["مكيف جنرال"]

    by_category = client.get("/inventory/api/products", query_string={"category": "شاشات", "sort_field": "quantity",
                                                                       "sort_dir": "desc"}, headers=JSON).get_json()
    assert [r["quantity"] for r in by_category["rows"]] == [28, 3]


def test_purchases_page_tabs_summary_and_pagination(ctx):
    client = _client(ctx)
    body = client.get("/purchases/api/page", query_string={"page_size": 2}, headers=JSON).get_json()
    assert body["counts"]["all"] == 3 and body["counts"]["draft"] == 1
    assert body["total"] == 3 and len(body["rows"]) == 2
    assert body["summary"]["draft"] == 1 and body["summary"]["count"] == 3
    assert any(s["name"] == "شركة الرافدين" for s in body["suppliers"])

    drafts = client.get("/purchases/api/page", query_string={"tab": "draft"}, headers=JSON).get_json()
    assert [r["invoice_no"] for r in drafts["rows"]] == ["P-2026-0003"]

    searched = client.get("/purchases/api/page", query_string={"search": "p-2026-0002"}, headers=JSON).get_json()
    assert [r["invoice_no"] for r in searched["rows"]] == ["P-2026-0002"]

    legacy = client.get("/purchases/api/list", headers=JSON).get_json()
    assert sorted(r["invoice_no"] for r in legacy) == ["P-2026-0001", "P-2026-0002", "P-2026-0003"]


@pytest.mark.parametrize("adapter,reference", [
    ("/orders/api/lookups", "/orders/data"),
    ("/orders/api/counts", "/orders/data"),
    ("/inventory/api/products", "/inventory/api/movements/1"),
    ("/purchases/api/page", "/purchases/api/list"),
])
def test_adapters_grant_exactly_what_finora_grants(ctx, adapter, reference):
    """A non-admin gets the same allow/deny answer from an adapter as from FINORA's own endpoint."""
    client = _client(ctx, "clerk_id", role="cashier")
    allowed = lambda res: res.status_code == 200  # noqa: E731
    assert allowed(client.get(adapter, headers=JSON)) == allowed(client.get(reference, headers=JSON))


def test_inventory_and_purchase_adapters_deny_without_inventory_permission(ctx):
    client = _client(ctx, "clerk_id", role="cashier")
    assert client.get("/inventory/api/products", headers=JSON).status_code in (302, 403)
    assert client.get("/purchases/api/page", headers=JSON).status_code in (302, 403)


def test_pos_bootstrap_reports_provinces_and_permissions(ctx):
    body = _client(ctx).get("/pos/api/bootstrap", headers=JSON).get_json()
    assert body["success"] is True and body["provinces"]
    assert body["can_edit_price"] is True and body["can_print"] is True and body["can_pay"] is True


def test_pos_products_page_search_and_categories(ctx):
    client = _client(ctx)
    body = client.get("/pos/api/products", query_string={"page_size": 2}, headers=JSON).get_json()
    assert body["total"] == 3 and body["total_pages"] == 2 and len(body["rows"]) == 2
    scanned = client.get("/pos/api/products", query_string={"search": "6290000000035"}, headers=JSON).get_json()
    assert [r["sku"] for r in scanned["rows"]] == ["AC-GEN-1"]
    assert {"id", "name", "price", "quantity", "image_url", "has_colors"} <= set(scanned["rows"][0])


def test_pos_checkout_through_existing_create_order(ctx):
    client = _client(ctx)
    added = client.post("/pos/add-customer", json={"name": "زبون سطح المكتب", "phone": "07700000099",
                                                     "city": "بغداد", "address": "الكرادة"}, headers=JSON)
    assert added.status_code == 200, added.get_data(as_text=True)[:300]
    customer_id = added.get_json()["id"]
    found = client.get("/pos/search-customer", query_string={"q": "07700000099"}, headers=JSON).get_json()
    assert any(row["id"] == customer_id for row in found)
    product = client.get("/pos/api/products", query_string={"search": "TV-LG-50"}, headers=JSON).get_json()["rows"][0]
    created = client.post("/pos/create-order", json={
        "customer_id": customer_id,
        "items": [{"product_id": product["id"], "qty": 2, "price": product["price"]}],
        "discount_amount": 50000,
        "submission_token": "desktop-test-1",
    }, headers=JSON)
    assert created.status_code == 200, created.get_data(as_text=True)[:300]
    payload = created.get_json()
    assert payload["success"] is True and payload["total"] == 2 * 325000 - 50000


def test_supplier_quick_create_and_purchase_creation(ctx):
    client = _client(ctx)
    created = client.post("/suppliers/api/quick-create", json={"name": "مورد سطح المكتب", "phone": "07700000077"},
                          headers=JSON)
    assert created.status_code == 200, created.get_data(as_text=True)[:300]
    supplier_id = created.get_json()["supplier"]["id"]
    assert client.post("/suppliers/api/quick-create", json={"name": "  "}, headers=JSON).status_code == 400

    product = client.get("/inventory/api/products", query_string={"search": "TV-LG-50"}, headers=JSON).get_json()["rows"][0]
    before = product["quantity"]

    confirmed = client.post("/purchases/create", json={
        "supplier_id": supplier_id,
        "purchase_date": "2026-10-07",
        "purchase_mode": "credit",
        "status": "confirmed",
        "supplier_invoice_no": "INV-DESK-1",
        "discount_value": 10000,
        "shipping_extra": 5000,
        "items": [{"product_id": product["id"], "quantity": 4, "unit_cost_before_discount": 270000, "discount_value": 0}],
    }, headers=JSON)
    assert confirmed.status_code == 200, confirmed.get_data(as_text=True)[:300]
    body = confirmed.get_json()
    assert body["success"] is True and body["invoice_no"]

    page = client.get("/purchases/api/page", query_string={"search": "INV-DESK-1"}, headers=JSON).get_json()
    row = page["rows"][0]
    assert row["grand_total"] == 4 * 270000 - 10000 + 5000 and row["tab"] == "unpaid"
    after = client.get("/inventory/api/products", query_string={"search": "TV-LG-50"}, headers=JSON).get_json()["rows"][0]
    assert after["quantity"] == before + 4

    draft = client.post("/purchases/create", json={
        "supplier_id": supplier_id,
        "purchase_date": "2026-10-07",
        "purchase_mode": "credit",
        "status": "draft",
        "items": [{"product_id": product["id"], "quantity": 2, "unit_cost_before_discount": 270000}],
    }, headers=JSON)
    assert draft.status_code == 200, draft.get_data(as_text=True)[:300]
    still = client.get("/inventory/api/products", query_string={"search": "TV-LG-50"}, headers=JSON).get_json()["rows"][0]
    assert still["quantity"] == before + 4


def test_supplier_quick_create_requires_supplier_permission(ctx):
    res = _client(ctx, "clerk_id", role="cashier").post("/suppliers/api/quick-create", json={"name": "x"}, headers=JSON)
    assert res.status_code in (302, 403)


def test_purchase_supplier_options_collapse_branch_copies(ctx):
    from flask import g

    from extensions import db
    from models.branch import Branch
    from models.supplier import Supplier
    from utils.branch_mode import independent_branches_enabled

    with ctx["app"].app_context():
        g.tenant = TENANT
        second = Branch(code="DUP2", name="فرع ثاني", is_active=True)
        db.session.add(second)
        db.session.flush()
        db.session.add(Supplier(name="شركة الرافدين", branch_id=second.id))
        db.session.commit()
        independent = independent_branches_enabled()

    body = _client(ctx).get("/purchases/api/page", headers=JSON).get_json()
    names = [s["name"] for s in body["suppliers"]]
    if not independent:
        assert names.count("شركة الرافدين") == 1
    assert len(names) == len(set((s["id"]) for s in body["suppliers"]))


def test_product_create_via_finora_form_and_field_safe_update(ctx):
    import json as _json

    from flask import g

    from extensions import db
    from models.product import Product

    client = _client(ctx)
    created = client.post("/inventory/add", data={
        "_response": "json",
        "name": "مكيف جري 1.5 طن",
        "sku": "AC-GR-15",
        "barcode": "6290000000999",
        "buy_price": "410000",
        "sale_price": "475000",
        "opening_stock": "6",
        "low_stock_threshold": "2",
        "category": "مكيفات",
        "brand": "Gree",
    }, headers=JSON)
    assert created.status_code == 200, created.get_data(as_text=True)[:300]
    product_id = created.get_json()["product_id"]

    details = client.get(f"/inventory/api/products/{product_id}", headers=JSON).get_json()["product"]
    assert details["category"] == "مكيفات" and details["brand"] == "Gree" and details["current_stock"] == 6

    listed = client.get("/inventory/api/products", query_string={"search": "AC-GR-15"}, headers=JSON).get_json()
    assert listed["rows"][0]["brand"] == "Gree" and "Gree" in listed["brands"]

    dup = client.post("/inventory/add", data={"_response": "json", "name": "x", "barcode": "6290000000999",
                                              "buy_price": "1", "sale_price": "1"}, headers=JSON)
    assert dup.status_code == 409

    # extra data the desktop does not edit must survive an update
    with ctx["app"].app_context():
        g.tenant = TENANT
        row = db.session.get(Product, product_id)
        meta = _json.loads(row.meta_json or "{}")
        meta["specs_items"] = [{"label": "القدرة", "value": "18000 BTU"}]
        meta["gallery"] = ["/static/a.png"]
        row.meta_json = _json.dumps(meta, ensure_ascii=False)
        db.session.commit()

    updated = client.post(f"/inventory/api/products/{product_id}/update", data={
        "name": "مكيف جري 1.5 طن انفرتر",
        "sale_price": "489000",
        "category": "تكييف وتبريد",
        "brand": "",
    }, headers=JSON)
    assert updated.status_code == 200, updated.get_data(as_text=True)[:300]
    with ctx["app"].app_context():
        g.tenant = TENANT
        row = db.session.get(Product, product_id)
        meta = _json.loads(row.meta_json or "{}")
        assert row.name.endswith("انفرتر") and row.sale_price == 489000 and row.buy_price == 410000
        assert meta["category"] == "تكييف وتبريد" and "brand" not in meta
        assert meta["specs_items"] and meta["gallery"] == ["/static/a.png"]
        assert row.catalog_category == "تكييف وتبريد"

    conflict = client.post(f"/inventory/api/products/{product_id}/update", data={"barcode": "6290000000011"}, headers=JSON)
    assert conflict.status_code == 409

    adjusted = client.post(f"/inventory/adjust-stock/{product_id}", json={"adjustment": -2, "reason": "تلف"}, headers=JSON)
    assert adjusted.status_code == 200 and adjusted.get_json()["new_quantity"] == 4
    no_reason = client.post(f"/inventory/adjust-stock/{product_id}", json={"adjustment": 1}, headers=JSON)
    assert no_reason.status_code == 400


def test_product_update_requires_inventory_permission(ctx):
    res = _client(ctx, "clerk_id", role="cashier").post("/inventory/api/products/1/update", data={"name": "x"}, headers=JSON)
    assert res.status_code in (302, 403)


def test_desktop_suppliers_create_update_filters_and_balance_protection(ctx):
    client = _client(ctx)
    invalid = client.post("/suppliers/api/create", json={"name": " ", "opening_balance": 100}, headers=JSON)
    assert invalid.status_code == 400
    for amount in (-1, 1.5, "NaN", "Infinity"):
        assert client.post("/suppliers/api/create", json={"name": "invalid", "opening_balance": amount}, headers=JSON).status_code == 400
    created = client.post("/suppliers/api/create", json={"name": "Desktop Supplier API", "phone": "07700990011",
                                                        "phone2": "07800990011", "address": "بغداد", "opening_balance": 2000}, headers=JSON)
    assert created.status_code == 200
    supplier_id = created.get_json()["id"]
    page = client.get("/suppliers/api/page", query_string={"search": "07700990011", "tab": "debt"}, headers=JSON).get_json()
    assert page["total"] == 1 and page["counts"]["debt"] == 1
    assert page["rows"][0]["remaining"] == 2000
    assert client.get("/suppliers/api/page", query_string={"search": "Desktop Supplier API", "tab": "settled"}, headers=JSON).get_json()["total"] == 0
    assert client.get("/suppliers/api/page", query_string={"search": "Desktop Supplier API", "min_balance": 3000}, headers=JSON).get_json()["total"] == 0
    updated = client.post(f"/suppliers/api/{supplier_id}/update", json={"name": "Desktop Supplier Updated", "phone": "07700990011", "phone2": "07800990011", "address": "البصرة",
                                                                       "opening_balance": 999999, "total_paid": 999999}, headers=JSON)
    assert updated.status_code == 200
    details = client.get(f"/suppliers/api/{supplier_id}", headers=JSON).get_json()
    assert details["supplier"]["address"] == "البصرة"
    assert details["supplier"]["opening_balance"] == 2000
    assert details["supplier"]["remaining"] == 2000
    assert details["supplier"]["total_paid"] == 0


def test_desktop_supplier_pay_reuses_real_treasury_and_allocation_service(ctx):
    client = _client(ctx)
    supplier_id = client.post("/suppliers/api/create", json={"name": "Desktop Pay Supplier", "opening_balance": 2000}, headers=JSON).get_json()["id"]
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.treasury_account import TreasuryAccount
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        account = TreasuryAccount(name="Desktop API Payment Bank", account_type="bank", branch_id=ctx["ids"]["branch_id"])
        db.session.add(account)
        db.session.flush()
        account_id = account.id
        db.session.add(AccountTransaction(type="deposit", amount=10000, treasury_account_id=account_id, branch_id=ctx["ids"]["branch_id"]))
        db.session.commit()
    payload = {"amount": 500, "treasury_account_id": account_id, "payment_date": "2026-10-09", "document_number": "DESK-001", "note": "دفعة اختبار"}
    assert client.post(f"/suppliers/api/{supplier_id}/pay", json={**payload, "amount": 2001}, headers=JSON).status_code == 400
    assert client.post(f"/suppliers/api/{supplier_id}/pay", json={**payload, "amount": 0}, headers=JSON).status_code == 400
    assert client.post(f"/suppliers/api/{supplier_id}/pay", json={**payload, "payment_date": "bad"}, headers=JSON).status_code == 400
    paid = client.post(f"/suppliers/api/{supplier_id}/pay", json=payload, headers=JSON)
    assert paid.status_code == 200, paid.get_data(as_text=True)[:400]
    details = client.get(f"/suppliers/api/{supplier_id}", headers=JSON).get_json()
    assert details["supplier"]["remaining"] == 1500
    assert details["supplier"]["total_paid"] == 500
    assert details["payments"][0]["amount"] == 500
    assert details["payments"][0]["document_number"] == "DESK-001"
    assert details["supplier"]["payment_count"] == 1


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/suppliers/api/page", None), ("get", "/suppliers/api/1", None),
    ("post", "/suppliers/api/create", {"name": "Denied"}),
    ("post", "/suppliers/api/1/update", {"name": "Denied"}),
    ("post", "/suppliers/api/1/pay", {"amount": 1}),
    ("get", "/suppliers/api/sale-products?q=LG", None),
    ("post", "/suppliers/api/1/sale", {"items": []}),
])
def test_desktop_supplier_endpoints_require_supplier_permission(ctx, method, path, payload):
    client = _client(ctx, "clerk_id", role="cashier")
    response = getattr(client, method)(path, json=payload, headers=JSON)
    assert response.status_code in (302, 403)


def test_desktop_suppliers_shared_rows_combine_branch_accounts_without_double_counting(ctx, monkeypatch):
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch
    from models.supplier import Supplier
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        other = Branch(code="desktop-supplier", name="Desktop Supplier Branch", is_active=True)
        db.session.add(other)
        db.session.flush()
        db.session.add_all([
            Supplier(name="Desktop Shared Supplier", phone="07700990022", branch_id=ctx["ids"]["branch_id"], total_debt=1000, total_paid=100),
            Supplier(name="Desktop Shared Supplier", phone="07700990022", branch_id=other.id, total_debt=2000, total_paid=200),
        ])
        db.session.commit()
    monkeypatch.setattr("routes.suppliers.independent_branches_enabled", lambda: False)
    monkeypatch.setattr("utils.supplier_payment_ops.independent_branches_enabled", lambda: False)
    page = _client(ctx).get("/suppliers/api/page", query_string={"search": "Desktop Shared Supplier"}, headers=JSON).get_json()
    assert page["total"] == 1
    assert page["rows"][0]["member_count"] == 2
    assert page["rows"][0]["remaining"] == 2700
    supplier_id = page["rows"][0]["id"]
    response = _client(ctx).post(f"/suppliers/api/{supplier_id}/update", json={"name": "Desktop Shared Renamed", "phone": "07700990022", "phone2": "", "address": "بغداد"}, headers=JSON)
    assert response.status_code == 200
    renamed = _client(ctx).get("/suppliers/api/page", query_string={"search": "Desktop Shared Renamed"}, headers=JSON).get_json()
    assert renamed["total"] == 1 and renamed["rows"][0]["remaining"] == 2700


def test_desktop_supplier_purchase_totals_exclude_drafts_and_cancelled(ctx):
    client = _client(ctx)
    page = client.get("/suppliers/api/page", query_string={"search": "شركة الرافدين"}, headers=JSON).get_json()
    assert page["rows"][0]["total_purchases"] == 4500000
    assert page["rows"][0]["purchase_count"] == 2
    details = client.get(f"/suppliers/api/{page['rows'][0]['id']}", headers=JSON).get_json()
    assert any(p["status"] == "draft" for p in details["purchases"])
    assert details["supplier"]["last_transaction"] == "2026-10-03"


def _supplier_sale_product(ctx, *, colored=False):
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.product import Product
    from models.branch import BranchStock
    from models.product_color_variant import ProductColorVariant
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        product = Product(branch_id=ctx["ids"]["branch_id"], name="Native supplier sale colors" if colored else "Native supplier sale stock",
                          sku="DESK-SALE-COLOR" if colored else "DESK-SALE",
                          quantity=99, sale_price=300, buy_price=200, active=True)
        db.session.add(product)
        db.session.flush()
        product.barcode = f"6290099{product.id:06d}"
        db.session.add(BranchStock(branch_id=product.branch_id, product_id=product.id, quantity=5, opening_stock=5))
        if colored:
            db.session.add_all([ProductColorVariant(product_id=product.id, color_name="أسود", quantity=2, sale_price=350),
                                ProductColorVariant(product_id=product.id, color_name="أبيض", quantity=3, sale_price=400)])
        db.session.commit()
        return product.id


@pytest.mark.parametrize("mode", ["shared", "legacy", "independent"])
def test_supplier_sale_catalog_uses_one_local_copy_and_preserves_distinct_products(ctx, monkeypatch, mode):
    import json
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch, BranchStock
    from models.product import Product
    from uuid import uuid4

    independent = mode == "independent"
    monkeypatch.setattr("utils.branch_mode.independent_branches_enabled", lambda: independent)
    monkeypatch.setattr("utils.branch_context.independent_branches_enabled", lambda: independent)
    monkeypatch.setattr("routes.suppliers.independent_branches_enabled", lambda: independent)
    name = f"Supplier duplicate regression {mode}"
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        other = Branch(code=f"supplier-catalog-{mode}", name=name, is_active=True)
        db.session.add(other)
        db.session.flush()
        group = str(uuid4())
        # More than the search limit: deduplication must happen before slicing.
        # Legacy copies have unrelated group IDs, one per branch. Multiple
        # independent families in the same branch are intentionally ambiguous
        # and must not be collapsed by a matching SKU alone.
        copy_branches = [other] * 16
        if mode == "legacy":
            copy_branches = [other] + [Branch(code=f"supplier-catalog-legacy-{i}", name=f"Legacy {i}", is_active=True)
                                       for i in range(1, 16)]
            db.session.add_all(copy_branches[1:])
            db.session.flush()
        copies = [Product(branch_id=copy_branch.id, name=name, sku=f"DUP-{mode}",
                          catalog_group_id=str(uuid4()) if mode == "legacy" else group,
                          buy_price=100, sale_price=175000, quantity=9, active=True)
                  for copy_branch in copy_branches]
        db.session.add_all(copies)
        db.session.flush()
        local = Product(branch_id=ctx["ids"]["branch_id"], name=name, sku=f"DUP-{mode}",
                        catalog_group_id=group, buy_price=100, sale_price=155000, quantity=99, active=True)
        distinct = Product(branch_id=local.branch_id, name=name, sku=f"DISTINCT-{mode}",
                           buy_price=100, sale_price=166000, quantity=99, active=True)
        db.session.add_all([local, distinct])
        db.session.flush()
        db.session.add_all([BranchStock(branch_id=local.branch_id, product_id=local.id, quantity=3),
                            BranchStock(branch_id=distinct.branch_id, product_id=distinct.id, quantity=2)])
        db.session.commit()
        local_id, distinct_id = local.id, distinct.id

    client = _client(ctx)
    response = client.get("/suppliers/api/sale-products", query_string={"q": name}, headers=JSON)
    assert response.status_code == 200
    rows = response.get_json()
    assert {row["id"] for row in rows} == {local_id, distinct_id}
    assert len(rows) == 2  # Identical names alone must never merge distinct SKUs.
    local_row = next(row for row in rows if row["id"] == local_id)
    assert local_row["sale_price"] == 155000 and local_row["quantity"] == 3

    # The offline export must use the same canonical IDs, prices and quantities.
    snapshot_id = str(uuid4())
    manifest_response = client.post("/api/v1/desktop/snapshots",
                                    json={"id": snapshot_id, "device_id": str(uuid4())}, headers=JSON)
    assert manifest_response.status_code == 200, manifest_response.get_json()
    page = client.get(f"/api/v1/desktop/snapshots/{snapshot_id}/supplier-products?cursor=0", headers=JSON)
    assert page.status_code == 200, page.get_json()
    exported = [row for row in json.loads(page.get_json()["rows_json"]) if row["name"] == name]
    assert {row["id"] for row in exported} == {local_id, distinct_id}
    assert next(row for row in exported if row["id"] == local_id) == local_row


def test_supplier_sale_barcode_prefers_local_price_even_when_foreign_copy_is_older(ctx, monkeypatch):
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch, BranchStock
    from models.product import Product
    from uuid import uuid4

    monkeypatch.setattr("utils.branch_mode.independent_branches_enabled", lambda: False)
    monkeypatch.setattr("utils.branch_context.independent_branches_enabled", lambda: False)
    monkeypatch.setattr("routes.suppliers.independent_branches_enabled", lambda: False)
    barcode = "6290099887766"
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        other = Branch(code="supplier-barcode-copy", name="Barcode copy", is_active=True)
        db.session.add(other)
        db.session.flush()
        group = str(uuid4())
        foreign = Product(branch_id=other.id, name="Older barcode copy", barcode=barcode,
                          catalog_group_id=group, buy_price=100, sale_price=175000, quantity=9, active=True)
        db.session.add(foreign)
        db.session.flush()
        local = Product(branch_id=ctx["ids"]["branch_id"], name="Local barcode copy", barcode=barcode,
                        catalog_group_id=group, buy_price=100, sale_price=155000, quantity=99, active=True)
        db.session.add(local)
        db.session.flush()
        db.session.add(BranchStock(branch_id=local.branch_id, product_id=local.id, quantity=1))
        db.session.commit()
        local_id = local.id
    rows = _client(ctx).get("/suppliers/api/sale-products", query_string={"q": barcode}, headers=JSON).get_json()
    assert len(rows) == 1 and rows[0]["id"] == local_id
    assert rows[0]["sale_price"] == 155000 and rows[0]["quantity"] == 1


def test_desktop_supplier_sale_uses_branch_stock_and_offsets_balance_without_cash(ctx):
    client = _client(ctx)
    product_id = _supplier_sale_product(ctx)
    supplier_id = client.post("/suppliers/api/create", json={"name": "Native Supplier Sale", "opening_balance": 500}, headers=JSON).get_json()["id"]
    for q in ("DESK-SALE", f"6290099{product_id:06d}"):
        products = client.get("/suppliers/api/sale-products", query_string={"q": q}, headers=JSON).get_json()
        assert products[0]["id"] == product_id
        assert products[0]["quantity"] == 5  # authoritative branch stock, not legacy quantity=99
    payload = {"items": [{"product_id": product_id, "qty": 2, "price": 300}], "note": "Native sale"}
    response = client.post(f"/suppliers/api/{supplier_id}/sale", json=payload, headers=JSON)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["grand_total"] == 600 and body["remaining"] == -100 and body["supplier_receivable"] == 100
    details = client.get(f"/suppliers/api/{supplier_id}", headers=JSON).get_json()
    assert details["supplier"]["total_paid"] == 600
    assert details["sales"][0]["invoice_no"] == body["invoice_no"]
    assert details["payments"][0]["payment_method"] == "offset"
    assert details["payments"][0]["amount"] == 600
    assert client.get(f"/suppliers/api/sale-products?q=6290099{product_id:06d}", headers=JSON).get_json()[0]["quantity"] == 3
    from flask import g
    from extensions_tenant import init_tenant_db
    from models.supplier_payment import SupplierPayment
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        payment = SupplierPayment.query.filter_by(supplier_id=supplier_id).one()
        assert payment.treasury_account_id is None


def test_desktop_supplier_sale_invalid_lines_and_stock_failures_are_atomic(ctx):
    client = _client(ctx)
    product_id = _supplier_sale_product(ctx)
    supplier_id = client.post("/suppliers/api/create", json={"name": "Native Failed Sale", "opening_balance": 500}, headers=JSON).get_json()["id"]
    line = {"product_id": product_id, "qty": 1, "price": 300}
    for field, value in [("qty", 0), ("qty", -1), ("qty", 1.5), ("price", 0), ("price", -1), ("price", 1.5), ("product_id", 999999)]:
        response = client.post(f"/suppliers/api/{supplier_id}/sale", json={"items": [{**line, field: value}]}, headers=JSON)
        assert response.status_code == 400, response.get_json()
    # First deduction must roll back when the next line exceeds available stock.
    response = client.post(f"/suppliers/api/{supplier_id}/sale", json={"items": [{**line, "qty": 2}, {**line, "qty": 4}]}, headers=JSON)
    assert response.status_code == 400, response.get_json()
    details = client.get(f"/suppliers/api/{supplier_id}", headers=JSON).get_json()
    assert details["supplier"]["remaining"] == 500
    assert details["sales"] == [] and details["payments"] == []
    products = client.get(f"/suppliers/api/sale-products?q=6290099{product_id:06d}", headers=JSON).get_json()
    assert next(p for p in products if p["id"] == product_id)["quantity"] == 5


def test_desktop_supplier_sale_requires_color_and_deducts_selected_color(ctx):
    client = _client(ctx)
    product_id = _supplier_sale_product(ctx, colored=True)
    supplier_id = client.post("/suppliers/api/create", json={"name": "Native Color Sale"}, headers=JSON).get_json()["id"]
    product = client.get(f"/suppliers/api/sale-products?q=6290099{product_id:06d}", headers=JSON).get_json()[0]
    assert product["has_colors"] and product["quantity"] == 5
    assert {c["name"]: c["sale_price"] for c in product["colors"]} == {"أسود": 350, "أبيض": 400}
    line = {"product_id": product_id, "qty": 1, "price": 350}
    assert client.post(f"/suppliers/api/{supplier_id}/sale", json={"items": [line]}, headers=JSON).status_code == 400
    assert client.post(f"/suppliers/api/{supplier_id}/sale", json={"items": [{**line, "variant_color": "غير موجود"}]}, headers=JSON).status_code == 400
    response = client.post(f"/suppliers/api/{supplier_id}/sale", json={"items": [{**line, "variant_color": "أسود"}]}, headers=JSON)
    assert response.status_code == 200, response.get_json()
    product = client.get(f"/suppliers/api/sale-products?q=6290099{product_id:06d}", headers=JSON).get_json()[0]
    assert product["quantity"] == 4
    assert {c["name"]: c["qty"] for c in product["colors"]} == {"أسود": 1, "أبيض": 3}


def test_desktop_sync_supplier_sale_deduplicates_durably_and_rejects_changed_payload(ctx):
    from uuid import uuid4
    client = _client(ctx)
    product_id = _supplier_sale_product(ctx)
    supplier_id = client.post("/suppliers/api/create", json={"name": "Sync Receipt Supplier", "opening_balance": 500}, headers=JSON).get_json()["id"]
    payload = {"device_id": str(uuid4()), "operation_id": str(uuid4()), "supplier_id": supplier_id,
               "items": [{"product_id": product_id, "qty": 2, "price": 300}], "note": "durable sync"}
    first = client.post("/api/v1/desktop/sync/supplier-sale", json=payload, headers=JSON)
    assert first.status_code == 200, first.get_json()
    # A different HTTP client/session simulates a restarted device after a lost reply.
    replayed = _client(ctx).post("/api/v1/desktop/sync/supplier-sale", json=payload, headers=JSON)
    assert replayed.status_code == 200 and replayed.get_json() == first.get_json()
    changed = client.post("/api/v1/desktop/sync/supplier-sale", json={**payload, "items": [{"product_id": product_id, "qty": 2, "price": 400}]}, headers=JSON)
    assert changed.status_code == 409
    details = client.get(f"/suppliers/api/{supplier_id}", headers=JSON).get_json()
    assert len(details["sales"]) == 1 and len(details["payments"]) == 1
    assert details["supplier"]["remaining"] == -100
    assert client.get(f"/suppliers/api/sale-products?q=6290099{product_id:06d}", headers=JSON).get_json()[0]["quantity"] == 3


def test_desktop_sync_stock_failure_rolls_back_receipt_invoice_and_all_stock_lines(ctx):
    from uuid import uuid4
    from flask import g
    from extensions_tenant import init_tenant_db
    from modules.desktop_api.sync import DesktopSyncReceipt
    client = _client(ctx)
    product_id = _supplier_sale_product(ctx)
    supplier_id = client.post("/suppliers/api/create", json={"name": "Sync Failed Supplier"}, headers=JSON).get_json()["id"]
    payload = {"device_id": str(uuid4()), "operation_id": str(uuid4()), "supplier_id": supplier_id,
               "items": [{"product_id": product_id, "qty": 2, "price": 300}, {"product_id": product_id, "qty": 4, "price": 300}]}
    response = client.post("/api/v1/desktop/sync/supplier-sale", json=payload, headers=JSON)
    assert response.status_code == 409, response.get_json()
    details = client.get(f"/suppliers/api/{supplier_id}", headers=JSON).get_json()
    assert details["sales"] == [] and details["payments"] == []
    assert client.get(f"/suppliers/api/sale-products?q=6290099{product_id:06d}", headers=JSON).get_json()[0]["quantity"] == 5
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        assert DesktopSyncReceipt.query.filter_by(operation_id=payload["operation_id"]).count() == 0


def test_desktop_sync_requires_permission_and_valid_operation_identity(ctx):
    client = _client(ctx)
    invalid = client.post("/api/v1/desktop/sync/supplier-sale", json={"device_id": "bad", "operation_id": "bad", "supplier_id": 1}, headers=JSON)
    assert invalid.status_code == 400
    denied = _client(ctx, "clerk_id", role="cashier").post("/api/v1/desktop/sync/supplier-sale", json={}, headers=JSON)
    assert denied.status_code in (302, 403)


def test_desktop_sync_concurrent_last_piece_confirms_only_one_invoice(ctx):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import BranchStock

    client = _client(ctx)
    product_id = _supplier_sale_product(ctx)
    supplier_id = client.post("/suppliers/api/create", json={"name": "Concurrent Last Piece"}, headers=JSON).get_json()["id"]
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        BranchStock.query.filter_by(product_id=product_id, branch_id=ctx["ids"]["branch_id"]).one().quantity = 1
        db.session.commit()
    base = {"supplier_id": supplier_id, "branch_id": ctx["ids"]["branch_id"],
            "items": [{"product_id": product_id, "qty": 1, "price": 300}]}
    # Prepare tables before the simultaneous business transactions.
    warmup = {**base, "device_id": str(uuid4()), "operation_id": str(uuid4()), "items": []}
    assert client.post("/api/v1/desktop/sync/supplier-sale", json=warmup, headers=JSON).status_code == 409
    payloads = [{**base, "device_id": str(uuid4()), "operation_id": str(uuid4())} for _ in range(2)]
    barrier = Barrier(2)
    def submit(payload):
        concurrent_client = _client(ctx)
        barrier.wait(timeout=10)
        response = concurrent_client.post("/api/v1/desktop/sync/supplier-sale", json=payload, headers=JSON)
        return response.status_code, response.get_json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, payloads))
    # SQLite may ask the losing transaction to retry after its snapshot is locked.
    for index, (status, _) in enumerate(results):
        if status == 503:
            response = client.post("/api/v1/desktop/sync/supplier-sale", json=payloads[index], headers=JSON)
            results[index] = response.status_code, response.get_json()
    assert sorted(status for status, _ in results) == [200, 409], results
    details = client.get(f"/suppliers/api/{supplier_id}", headers=JSON).get_json()
    assert len(details["sales"]) == 1 and len(details["payments"]) == 1
    assert client.get(f"/suppliers/api/sale-products?q=6290099{product_id:06d}", headers=JSON).get_json()[0]["quantity"] == 0


def test_desktop_snapshot_exports_all_pages_and_freezes_resumable_data(ctx):
    import hashlib
    import json
    from uuid import uuid4
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.product import Product
    client = _client(ctx)
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        products = [Product(branch_id=ctx["ids"]["branch_id"], name=f"Snapshot unseen {index:03}",
                            sku=f"SNAP-{index}", buy_price=100, sale_price=200, quantity=0, active=True)
                    for index in range(105)]
        db.session.add_all(products)
        db.session.commit()
        changed_id = products[0].id
    payload = {"id": str(uuid4()), "device_id": str(uuid4())}
    response = client.post("/api/v1/desktop/snapshots", json=payload, headers=JSON)
    assert response.status_code == 200, response.get_data(as_text=True)[:1000]
    manifest = response.get_json()
    definitions = {entry["name"]: entry for entry in manifest["datasets"]}
    assert definitions["products"]["total"] >= 108
    assert definitions["customers"]["total"] >= 2
    assert {"orders", "purchases", "supplier-details", "supplier-products", "pos-products", "product-details", "purchase-products"} <= definitions.keys()
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        db.session.get(Product, changed_id).name = "Changed after snapshot"
        db.session.commit()
    captured = []
    cursor = 0
    while cursor < definitions["products"]["total"]:
        page_response = client.get(f"/api/v1/desktop/snapshots/{payload['id']}/products?cursor={cursor}", headers=JSON)
        assert page_response.status_code == 200, page_response.get_data(as_text=True)[:1000]
        page = page_response.get_json()
        assert hashlib.sha256(page["rows_json"].encode()).hexdigest() == page["digest"]
        rows = json.loads(page["rows_json"])
        assert len(rows) == page["next_cursor"] - cursor
        captured.extend(rows)
        cursor = page["next_cursor"]
    assert len(captured) == definitions["products"]["total"]
    assert next(row for row in captured if row["id"] == changed_id)["name"] == "Snapshot unseen 000"
    replayed = _client(ctx).post("/api/v1/desktop/snapshots", json=payload, headers=JSON)
    assert replayed.status_code == 200 and replayed.get_json() == manifest
    invalid = client.get(f"/api/v1/desktop/snapshots/{payload['id']}/products?cursor=1", headers=JSON)
    assert invalid.status_code == 400
    denied = _client(ctx, "clerk_id", role="cashier").get(f"/api/v1/desktop/snapshots/{payload['id']}/products?cursor=0", headers=JSON)
    assert denied.status_code == 403
    from modules.desktop_api.snapshots import DesktopSnapshot
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        db.session.get(DesktopSnapshot, payload["id"]).expires = 0
        db.session.commit()
    expired = client.get(f"/api/v1/desktop/snapshots/{payload['id']}/products?cursor=0", headers=JSON)
    assert expired.status_code == 410


def _quota_product(ctx, *, colors=False):
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.product import Product
    from models.branch import BranchStock
    from models.supplier import Supplier
    from utils.product_color_service import save_product_colors
    from uuid import uuid4
    with ctx["app"].app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        product = Product(branch_id=ctx["ids"]["branch_id"], name=f"Quota {uuid4().hex[:8]}",
                          quantity=2 if colors else 1, sale_price=1000, buy_price=500, active=True)
        db.session.add(product)
        db.session.flush()
        db.session.add(BranchStock(branch_id=product.branch_id, product_id=product.id, quantity=product.quantity))
        db.session.flush()
        if colors:
            save_product_colors(product.id, [("أسود", 1), ("أبيض", 1)])
        db.session.commit()
        return product.id, Supplier.query.first().id


def _quota_request(ctx, product_id, *, color="", device=None):
    from uuid import uuid4
    return {"id": str(uuid4()), "device_id": device or str(uuid4()), "branch_id": ctx["ids"]["branch_id"],
            "items": [{"product_id": product_id, "qty": 1, **({"variant_color": color} if color else {})}]}


def test_device_quota_last_piece_replay_and_native_sale_protection(ctx):
    product_id, supplier_id = _quota_product(ctx)
    client = _client(ctx)
    payload = _quota_request(ctx, product_id)
    response = client.post("/api/v1/desktop/stock/reserve", json=payload, headers=JSON)
    assert response.status_code == 200, response.get_data(as_text=True)
    grant = response.get_json()
    assert client.post("/api/v1/desktop/stock/reserve", json=payload, headers=JSON).get_json() == grant
    another = client.post("/api/v1/desktop/stock/reserve", json=_quota_request(ctx, product_id), headers=JSON)
    assert another.status_code == 409
    online = client.post(f"/suppliers/api/{supplier_id}/sale", json={"items": [{"product_id": product_id, "qty": 1, "price": 1000}]}, headers=JSON)
    assert online.status_code == 400 and online.get_json()["success"] is False
    changed = {**payload, "items": [{"product_id": product_id, "qty": 2}]}
    assert client.post("/api/v1/desktop/stock/reserve", json=changed, headers=JSON).status_code == 409
    from uuid import uuid4
    returned = {"id": str(uuid4()), "device_id": payload["device_id"], "branch_id": payload["branch_id"],
                "parts": [{"id": grant["allocations"][0]["id"], "qty": 1}]}
    assert client.post("/api/v1/desktop/stock/return", json=returned, headers=JSON).status_code == 200
    assert client.post("/api/v1/desktop/stock/return", json=returned, headers=JSON).status_code == 200
    assert client.post(f"/suppliers/api/{supplier_id}/sale", json={"items": [{"product_id": product_id, "qty": 1, "price": 1000}]}, headers=JSON).status_code == 200


def test_device_quota_protects_direct_stock_writes_deletion_and_product_mirrors(ctx):
    from flask import g
    from extensions import db
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    product_id, _ = _quota_product(ctx)
    payload = _quota_request(ctx, product_id)
    grant = _client(ctx).post("/api/v1/desktop/stock/reserve", json=payload, headers=JSON).get_json()
    with ctx["app"].app_context():
        g.tenant = TENANT
        for statement in ["UPDATE branch_stock SET quantity=0 WHERE product_id=:id",
                          "DELETE FROM branch_stock WHERE product_id=:id",
                          "UPDATE product SET quantity=0 WHERE id=:id",
                          "DELETE FROM product WHERE id=:id",
                          "UPDATE product SET active=0 WHERE id=:id"]:
            with pytest.raises(IntegrityError, match="finora_offline_stock_reserved"):
                db.session.execute(text(statement), {"id": product_id})
            db.session.rollback()
        assert db.session.execute(text("SELECT quantity FROM branch_stock WHERE product_id=:id"), {"id": product_id}).scalar() == 1
        assert db.session.execute(text("SELECT COUNT(*) FROM desktop_stock_mirror_ticket")).scalar() == 0
    from uuid import uuid4
    _client(ctx).post("/api/v1/desktop/stock/return", json={"id": str(uuid4()), "device_id": payload["device_id"],
        "branch_id": payload["branch_id"], "parts": [{"id": grant["allocations"][0]["id"], "qty": 1}]}, headers=JSON)


def test_reserved_supplier_sync_commits_quota_receipt_and_color_sale_once(ctx):
    from uuid import uuid4
    product_id, supplier_id = _quota_product(ctx, colors=True)
    client = _client(ctx)
    payload = _quota_request(ctx, product_id, color="أسود")
    response = client.post("/api/v1/desktop/stock/reserve", json=payload, headers=JSON)
    assert response.status_code == 200, response.get_data(as_text=True)
    allocation = response.get_json()["allocations"][0]["id"]
    # Unreserved color is still sellable while black is protected.
    white = client.post(f"/suppliers/api/{supplier_id}/sale", json={"items": [{"product_id": product_id,
                   "qty": 1, "price": 1000, "variant_color": "أبيض"}]}, headers=JSON)
    assert white.status_code == 200, white.get_data(as_text=True)
    sale = {"device_id": payload["device_id"], "operation_id": str(uuid4()), "branch_id": payload["branch_id"],
            "supplier_id": supplier_id, "items": [{"product_id": product_id, "qty": 1, "price": 1000, "variant_color": "أسود"}],
            "reservations": [{"id": allocation, "qty": 1}]}
    broken = {**sale, "items": [{**sale["items"][0], "price": 0}]}
    assert client.post("/api/v1/desktop/sync/supplier-sale", json=broken, headers=JSON).status_code == 409
    good = client.post("/api/v1/desktop/sync/supplier-sale", json=sale, headers=JSON)
    assert good.status_code == 200, good.get_data(as_text=True)
    assert client.post("/api/v1/desktop/sync/supplier-sale", json=sale, headers=JSON).get_json() == good.get_json()
    exhausted = {**sale, "operation_id": str(uuid4())}
    assert client.post("/api/v1/desktop/sync/supplier-sale", json=exhausted, headers=JSON).status_code == 409
    from flask import g
    from extensions import db
    from utils.desktop_stock_reservations import DesktopStockAllocation
    from utils.branch_stock_service import get_branch_stock
    with ctx["app"].app_context():
        g.tenant = TENANT
        assert db.session.get(DesktopStockAllocation, allocation).consumed == 1
        assert get_branch_stock(payload["branch_id"], product_id) == 0


def test_device_quota_concurrent_last_piece_and_foreign_device_refusal(ctx):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    product_id, _ = _quota_product(ctx)
    requests = [_quota_request(ctx, product_id), _quota_request(ctx, product_id)]
    def reserve(payload):
        for _ in range(3):
            result = _client(ctx).post("/api/v1/desktop/stock/reserve", json=payload, headers=JSON)
            if result.status_code != 503:
                return result.status_code, result.get_json()
        return result.status_code, result.get_json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, requests))
    assert sorted(code for code, _ in results) == [200, 409]
    index = next(i for i, (code, _) in enumerate(results) if code == 200)
    grant = results[index][1]
    returned = {"id": str(uuid4()), "device_id": str(uuid4()), "branch_id": requests[index]["branch_id"],
                "parts": [{"id": grant["allocations"][0]["id"], "qty": 1}]}
    assert _client(ctx).post("/api/v1/desktop/stock/return", json=returned, headers=JSON).status_code == 403
    # Cashiers with view_pos can reserve a quota; the last piece is already held.
    assert _client(ctx, "clerk_id", role="cashier").post("/api/v1/desktop/stock/reserve", json=_quota_request(ctx, product_id), headers=JSON).status_code == 409
    returned["device_id"] = requests[index]["device_id"]
    assert _client(ctx).post("/api/v1/desktop/stock/return", json=returned, headers=JSON).status_code == 200


@pytest.mark.parametrize("payment", ["cash", "bank", "credit"])
def test_reserved_pos_sale_invoice_stock_and_payment_commit_once(ctx, payment):
    from uuid import uuid4
    from flask import g
    from extensions import db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.treasury_account import TreasuryAccount
    from utils.desktop_stock_reservations import DesktopStockAllocation
    from utils.branch_stock_service import get_branch_stock
    product_id, _ = _quota_product(ctx)
    with ctx["app"].app_context():
        g.tenant = TENANT
        customer = Customer.query.first()
        customer_id, customer_name = customer.id, customer.name
        account = TreasuryAccount(name=f"Offline POS {uuid4().hex}", account_type="cash" if payment == "cash" else "bank", branch_id=ctx["ids"]["branch_id"])
        db.session.add(account)
        db.session.commit()
        account_id = account.id
    client = _client(ctx)
    payload = _quota_request(ctx, product_id)
    reserved = client.post("/api/v1/desktop/stock/reserve", json=payload, headers=JSON)
    assert reserved.status_code == 200, reserved.get_data(as_text=True)
    allocation = reserved.get_json()["allocations"][0]["id"]
    sale = {"device_id": payload["device_id"], "operation_id": str(uuid4()), "branch_id": payload["branch_id"],
        "sale": {"kind": "pos", "customerId": customer_id, "customerName": customer_name,
          "items": [{"product_id": product_id, "qty": 1, "price": 1000}], "discount": 100, "total": 900,
          "payment": payment, "accountId": None if payment == "credit" else account_id},
        "reservations": [{"id": allocation, "qty": 1}]}
    created_at = datetime.utcnow().replace(microsecond=0)
    sale["created_at"] = int((created_at - datetime(1970, 1, 1)).total_seconds() * 1000)
    sale["local_invoice_no"] = f"OFF-{payload['device_id'].replace('-', '')}-000001"
    first = client.post("/api/v1/desktop/sync/pos-sale", json=sale, headers=JSON)
    assert first.status_code == 200, first.get_data(as_text=True)
    assert client.post("/api/v1/desktop/sync/pos-sale", json=sale, headers=JSON).get_json() == first.get_json()
    changed = {**sale, "sale": {**sale["sale"], "customerName": "Changed"}}
    assert client.post("/api/v1/desktop/sync/pos-sale", json=changed, headers=JSON).status_code == 409
    exhausted = {**sale, "operation_id": str(uuid4())}
    assert client.post("/api/v1/desktop/sync/pos-sale", json=exhausted, headers=JSON).status_code == 409
    with ctx["app"].app_context():
        g.tenant = TENANT
        invoice = db.session.get(Invoice, first.get_json()["invoice_id"])
        assert invoice.total == 900 and invoice.stock_is_deducted and invoice.status == "تم التوصيل"
        assert invoice.created_at == created_at
        assert invoice.payment_status == ("غير مسدد" if payment == "credit" else "مسدد")
        ledger = InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).all()
        assert len(ledger) == (0 if payment == "credit" else 1)
        if ledger:
            assert ledger[0].amount_delta == 900 and ledger[0].treasury_account_id == account_id
            assert ledger[0].recorded_at == created_at
        assert get_branch_stock(payload["branch_id"], product_id) == 0
        assert db.session.get(DesktopStockAllocation, allocation).consumed == 1


def test_reserved_pos_failed_collection_rolls_back_everything(ctx, monkeypatch):
    from uuid import uuid4
    from flask import g
    from extensions import db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.treasury_account import TreasuryAccount
    from utils.desktop_stock_reservations import DesktopStockAllocation
    from utils.branch_stock_service import get_branch_stock
    from modules.desktop_api.sync import DesktopSyncReceipt
    import utils.payment_ledger as payments
    product_id, _ = _quota_product(ctx)
    with ctx["app"].app_context():
        g.tenant = TENANT
        customer = Customer.query.first()
        customer_id, name = customer.id, customer.name
        account = TreasuryAccount(name="Atomic offline POS", account_type="cash", branch_id=ctx["ids"]["branch_id"])
        db.session.add(account)
        db.session.commit()
        account_id, count = account.id, Invoice.query.count()
    client = _client(ctx)
    grant = _quota_request(ctx, product_id)
    allocation = client.post("/api/v1/desktop/stock/reserve", json=grant, headers=JSON).get_json()["allocations"][0]["id"]
    sale = {"device_id": grant["device_id"], "operation_id": str(uuid4()), "branch_id": grant["branch_id"],
        "sale": {"kind": "pos", "customerId": customer_id, "customerName": name, "items": [{"product_id": product_id, "qty": 1, "price": 1000}],
            "discount": 0, "total": 1000, "payment": "cash", "accountId": account_id}, "reservations": [{"id": allocation, "qty": 1}]}
    native = payments.append_payment_ledger_delta
    def failing(*args, **kwargs):
        native(*args, **kwargs)
        db.session.flush()
        raise ValueError("Injected collection failure")
    monkeypatch.setattr(payments, "append_payment_ledger_delta", failing)
    assert client.post("/api/v1/desktop/sync/pos-sale", json=sale, headers=JSON).status_code == 409
    with ctx["app"].app_context():
        g.tenant = TENANT
        assert Invoice.query.count() == count
        assert get_branch_stock(grant["branch_id"], product_id) == 1
        assert db.session.get(DesktopStockAllocation, allocation).consumed == 0
        assert not DesktopSyncReceipt.query.filter_by(operation_id=sale["operation_id"]).first()
    monkeypatch.setattr(payments, "append_payment_ledger_delta", native)
    assert client.post("/api/v1/desktop/sync/pos-sale", json=sale, headers=JSON).status_code == 200


def test_device_reservation_rejects_special_stock_and_guards_conversion(ctx):
    from flask import g
    from extensions import db
    from modules.food.models import FoodProductProfile
    from sqlalchemy.exc import IntegrityError
    product_id, _ = _quota_product(ctx)
    client = _client(ctx)
    grant = _quota_request(ctx, product_id)
    assert client.post("/api/v1/desktop/stock/reserve", json=grant, headers=JSON).status_code == 200
    with ctx["app"].app_context():
        g.tenant = TENANT
        db.session.add(FoodProductProfile(tenant_id=1, product_id=product_id))
        with pytest.raises(IntegrityError, match="finora_offline_stock_reserved"):
            db.session.flush()
        db.session.rollback()
    product_id, _ = _quota_product(ctx)
    with ctx["app"].app_context():
        g.tenant = TENANT
        db.session.add(FoodProductProfile(tenant_id=1, product_id=product_id))
        db.session.commit()
    rejected = client.post("/api/v1/desktop/stock/reserve", json=_quota_request(ctx, product_id), headers=JSON)
    assert rejected.status_code == 409


@pytest.mark.parametrize("colors", [False, True])
def test_online_pos_stock_preview_excludes_device_quota(ctx, colors):
    from flask import g
    from utils.order_stock_lock import check_stock_rows
    from utils.branch_sales import available_fulfillment_qty
    from utils.product_color_service import get_available_color_quantity
    product_id, _ = _quota_product(ctx, colors=colors)
    grant = _quota_request(ctx, product_id, color="أسود" if colors else "")
    reserved = _client(ctx).post("/api/v1/desktop/stock/reserve", json=grant, headers=JSON)
    assert reserved.status_code == 200, reserved.get_data(as_text=True)
    branch = ctx["ids"]["branch_id"]
    with ctx["app"].app_context():
        g.tenant = TENANT
        row = {"product_id": product_id, "qty": 1, "fulfillment_branch_id": branch,
               **({"variant_color": "أسود"} if colors else {})}
        preview = check_stock_rows([row], preferred_branch_id=branch)
        assert not preview.can_fulfill
        assert available_fulfillment_qty(branch, product_id, "أسود" if colors else None) == 0
        if colors:
            assert get_available_color_quantity(product_id, "أسود") == 0
            assert available_fulfillment_qty(branch, product_id, "أبيض") == 1
            assert check_stock_rows([{**row, "variant_color": "أبيض"}], preferred_branch_id=branch).can_fulfill


def test_withdrawn_desktop_workspaces_are_empty_for_existing_clients(ctx):
    admin = _client(ctx).get("/api/v1/desktop/workspace", headers=JSON)
    assert admin.status_code == 200
    assert admin.get_json()["pages"] == []
    clerk = _client(ctx, "clerk_id", role="cashier").get("/api/v1/desktop/workspace", headers=JSON)
    assert clerk.status_code == 200
    assert clerk.get_json()["pages"] == []


def test_recovery_quota_read_is_scoped_and_does_not_return_or_consume_stock(ctx):
    from uuid import uuid4
    product_id, _ = _quota_product(ctx)
    client = _client(ctx)
    payload = _quota_request(ctx, product_id)
    reserved = client.post("/api/v1/desktop/stock/reserve", json=payload, headers=JSON)
    assert reserved.status_code == 200
    path = "/api/v1/desktop/stock/device?device_id=" + payload["device_id"]
    response = client.get(path, headers=JSON)
    assert response.status_code == 200, response.get_data(as_text=True)
    rows = response.get_json()["allocations"]
    assert len(rows) == 1 and rows[0]["quantity"] == 1 and rows[0]["used"] == rows[0]["returned"] == 0
    assert rows[0]["id"] == reserved.get_json()["allocations"][0]["id"]
    assert client.get(path, headers=JSON).get_json() == response.get_json()
    other = _client(ctx, "clerk_id", role="cashier").get(path, headers=JSON)
    assert other.status_code in (200, 403)
    if other.status_code == 200:
        assert other.get_json()["allocations"] == []
    assert client.get("/api/v1/desktop/stock/device?device_id=" + str(uuid4()), headers=JSON).get_json()["allocations"] == []
    assert client.get("/api/v1/desktop/stock/device?device_id=invalid", headers=JSON).status_code == 400
