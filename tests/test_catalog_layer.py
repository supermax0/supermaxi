"""Smart Commerce Sprint 3: the master catalogue is separate from FINORA Inventory and from the POS.

Acceptance: a model can be published in the catalogue without appearing in the POS and without any stock balance;
activation into inventory is explicit and creates quantity 0 only; old shops are untouched."""
from __future__ import annotations

import pytest

from tests.storefront_harness import seed_products
from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

API = "/api/v1/desktop/catalog"
TV = {"canonical_name": "شاشة TCL 55 بوصة 4K", "brand": "TCL", "model_number": "55C7K", "category": "شاشات",
      "barcodes": ["6921732812345"], "attributes": {"الحجم": "55 بوصة", "الدقة": "4K"},
      "verification_status": "verified", "media": [{"url": "/static/img/tv.png", "role": "front"}],
      "source": {"type": "manufacturer", "url": "https://www.tcl.com/55c7k"}}


@pytest.fixture()
def shop(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from routes.storefront import reset_schema_ready

    reset_schema_ready()
    invalidate_catalog_cache()
    ids = _make_ctx(app)
    seed_products(app, ids["tenant"], 10, prefix="CL")
    invalidate_catalog_cache()
    return {**ids, "admin": _client(ids), "app": app, "anon": app.test_client()}


def _ctx(shop):
    from flask import g

    ctx = shop["app"].test_request_context()
    ctx.push()
    g.tenant = shop["tenant"]
    return ctx


def _enable(shop, **flags):
    out = _json(shop["admin"].post(f"{API}/settings", json={"catalog_layer": True, **flags}))
    assert out["catalog_layer"] is True
    return out


def _counts(shop):
    from extensions import db
    from models.branch import BranchStock
    from models.product import Product
    from models.stock_movement import StockMovement

    ctx = _ctx(shop)
    try:
        return (Product.query.execution_options(skip_branch_scope=True).count(), BranchStock.query.count(),
                StockMovement.query.execution_options(skip_branch_scope=True).count(),
                int(db.session.query(db.func.coalesce(db.func.sum(Product.quantity), 0))
                    .execution_options(skip_branch_scope=True).scalar() or 0))
    finally:
        ctx.pop()


def test_layer_is_off_by_default_and_changes_nothing_for_old_shops(shop):
    assert shop["admin"].get(f"{API}/entries").status_code == 409  # disabled
    from modules.catalog import service

    ctx = _ctx(shop)
    try:
        # the tenant schema may contain the (empty) tables, but no catalogue data exists and the flag is off
        assert service.enabled() is False and service.published_catalog_only() == []
    finally:
        ctx.pop()
    assert shop["anon"].get(f"/shop/{shop['tenant']}/catalog/1").status_code == 404


def test_publishing_a_model_creates_no_product_no_stock_and_no_pos_entry(shop):
    _enable(shop)
    before = _counts(shop)
    entry = _json(shop["admin"].post(f"{API}/entries", json=TV))["entry"]
    assert _json(shop["admin"].post(f"{API}/entries/{entry['id']}/listing", json={"publish": True}))["entry"]["listing"]["is_published"]
    assert _counts(shop) == before  # products, branch stock rows, movements, total quantity: all unchanged
    # the POS search (inventory) does not know it — neither by name nor by barcode
    pos = shop["admin"].get("/pos/search-product?q=55C7K").get_json()
    assert pos == []
    assert shop["admin"].get("/pos/search-product?q=6921732812345").get_json() == []


def test_duplicates_are_refused_by_barcode_and_by_brand_model(shop):
    _enable(shop)
    first = _json(shop["admin"].post(f"{API}/entries", json=TV))["entry"]
    by_code = shop["admin"].post(f"{API}/entries", json={**TV, "model_number": "OTHER", "barcodes": ["6921732812345"]})
    assert by_code.status_code == 409 and by_code.get_json()["existing_id"] == first["id"]
    by_model = shop["admin"].post(f"{API}/entries", json={**TV, "brand": "tcl", "model_number": "55-c7k", "barcodes": []})
    assert by_model.status_code == 409  # 'TCL 55C7K' == 'tcl 55-c7k'
    regional = shop["admin"].post(f"{API}/entries", json={**TV, "barcodes": [], "regional_version": "EU"})
    assert regional.status_code == 200  # a different regional version is a separate entry
    assert shop["admin"].post(f"{API}/entries", json={**TV, "barcodes": ["123"], "model_number": "X1"}).status_code == 400


def test_unverified_data_is_not_published(shop):
    _enable(shop)
    entry = _json(shop["admin"].post(f"{API}/entries", json={**TV, "verification_status": "needs_review"}))["entry"]
    res = shop["admin"].post(f"{API}/entries/{entry['id']}/listing", json={"publish": True})
    assert res.status_code == 409 and res.get_json()["code"] == "unverified"


def test_storefront_offers_the_model_on_request_only_in_v2_and_takes_requests(shop):
    _enable(shop)
    entry = _json(shop["admin"].post(f"{API}/entries", json=TV))["entry"]
    shop["admin"].post(f"{API}/entries/{entry['id']}/listing", json={"publish": True})
    old = shop["anon"].get(f"/shop/{shop['tenant']}/?q=55C7K").get_data(as_text=True)
    assert "اطلب توفيره" not in old  # the current design is unchanged
    v2 = shop["anon"].get(f"/shop/{shop['tenant']}/?v2=1&q=55C7K").get_data(as_text=True)
    assert "اطلب توفيره" in v2 and "data-catalog-id" in v2
    api = shop["anon"].get(f"/shop/{shop['tenant']}/api/products?q=55C7K").get_json()
    assert api["total"] == 1 and api["products"][0]["kind"] == "catalog" and api["products"][0]["price"] == 0
    # an in-stock or price filter never returns a model with neither stock nor a price
    assert shop["anon"].get(f"/shop/{shop['tenant']}/api/products?q=55C7K&availability=in_stock").get_json()["total"] == 0
    page = shop["anon"].get(f"/shop/{shop['tenant']}/catalog/{entry['id']}")
    assert page.status_code == 200 and "اطلب توفيره" in page.get_data(as_text=True)
    bad = shop["anon"].post(f"/shop/{shop['tenant']}/catalog/{entry['id']}", data={"customer_name": "علي", "phone": "123"})
    assert "رقم هاتف عراقي" in bad.get_data(as_text=True)
    ok = shop["anon"].post(f"/shop/{shop['tenant']}/catalog/{entry['id']}",
                           data={"customer_name": "علي", "phone": "+964 770 123 4567", "city": "بغداد"})
    assert "وصلنا طلبك" in ok.get_data(as_text=True)
    rows = _json(shop["admin"].get(f"{API}/requests"))["rows"]
    assert rows[0]["phone"] == "07701234567" and rows[0]["catalog_product_id"] == entry["id"]
    from models.invoice import Invoice

    ctx = _ctx(shop)
    try:
        assert Invoice.query.execution_options(skip_branch_scope=True).filter_by(customer_name="علي").count() == 0
    finally:
        ctx.pop()


def test_activation_is_explicit_creates_quantity_zero_and_stays_off_the_pos_unless_asked(shop):
    _enable(shop)
    entry = _json(shop["admin"].post(f"{API}/entries", json=TV))["entry"]
    before = _counts(shop)
    assert shop["admin"].post(f"{API}/entries/{entry['id']}/activate", json={"sale_price": 0}).status_code == 400
    pid = _json(shop["admin"].post(f"{API}/entries/{entry['id']}/activate", json={"sale_price": 450000}))["product_id"]
    again = _json(shop["admin"].post(f"{API}/entries/{entry['id']}/activate", json={"sale_price": 450000}))["product_id"]
    assert again == pid  # replay-safe: one product only
    products, stock_rows, movements, qty = _counts(shop)
    assert products == before[0] + 1 and stock_rows == before[1] and movements == before[2] and qty == before[3]
    from models.product import Product

    ctx = _ctx(shop)
    try:
        product = Product.query.execution_options(skip_branch_scope=True).get(pid)
        assert product.quantity == 0 and product.pos_visible is False and product.barcode == "6921732812345"
    finally:
        ctx.pop()
    assert shop["admin"].get("/pos/search-product?q=55C7K").get_json() == []  # hidden from the cashier by default
    # once activated it is a normal product — no longer an "on request" catalogue card
    api = shop["anon"].get(f"/shop/{shop['tenant']}/api/products?q=55C7K").get_json()
    assert all(p.get("kind") != "catalog" for p in api["products"])


def test_pos_level_three_catalogue_search_is_opt_in_and_read_only(shop):
    _enable(shop)
    _json(shop["admin"].post(f"{API}/entries", json=TV))
    assert shop["admin"].get(f"{API}/pos-search?q=TCL").status_code == 409  # off until the admin allows it
    _enable(shop, pos_catalog_search=True)
    rows = _json(shop["admin"].get(f"{API}/pos-search?q=TCL"))["rows"]
    assert rows and rows[0]["sellable"] is False and rows[0]["kind"] == "catalog"
    clerk = _client(shop, "clerk")
    assert clerk.get(f"{API}/pos-search?q=TCL").status_code in (200, 403)  # depends only on the clerk's view_pos right
    assert shop["anon"].get(f"{API}/entries").status_code in (302, 401, 403)


def test_only_inventory_managers_edit_and_only_the_admin_switches_the_layer(shop):
    _enable(shop)
    clerk = _client(shop, "clerk")
    assert clerk.post(f"{API}/settings", json={"catalog_layer": False}).status_code == 403
    assert clerk.post(f"{API}/entries", json=TV).status_code == 403
