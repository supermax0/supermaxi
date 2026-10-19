"""Inventory store visibility must publish, rather than merely set an unused flag."""
import pytest
from tests.test_desktop_product_colors import inventory


@pytest.fixture
def shared(inventory):
    from extensions import db
    from models.product import Product
    from models.tenant import Tenant
    from modules.installments.models import InstallmentProduct
    product, stock, update, routes = inventory
    company = Tenant(name="Publication regression")
    db.session.add(company)
    db.session.flush()
    anchor = Product(name="Existing published model", branch_id=product.branch_id,
                     buy_price=1, sale_price=250, active=True, store_visible=True)
    db.session.add(anchor)
    db.session.flush()
    db.session.add(InstallmentProduct(tenant_id=company.id, product_id=anchor.id,
                                     title="Published model", slug="published-model", cash_price=250, status="published"))
    db.session.commit()
    return inventory, company.id


def test_effective_status_explains_visible_flag_without_publication(shared):
    from flask import current_app
    (product, _, _, routes), _ = shared
    with current_app.test_request_context():
        row = routes.product_api_details(product.id).get_json()["product"]
    assert row["store_visible"] is True
    assert row["storefront_publication"]["status"] == "unpublished"
    assert row["storefront_publication"]["can_publish"] is True


def test_explicit_show_publishes_unlinked_product_without_changing_stock(shared):
    from modules.installments.models import InstallmentProduct
    from modules.storefront.services.catalog_service import cash_store_product_is_visible
    (product, stock, update, _), _ = shared
    body, status = update({"store_visible": "1"})
    assert status == 200, body
    item = InstallmentProduct.query.filter_by(product_id=product.id).one()
    assert item.status == "published" and item.cash_price == 150
    assert cash_store_product_is_visible(product) is True
    assert (product.quantity, stock.quantity, product.opening_stock) == (6, 6, 10)
    assert product.pos_visible is True


def test_publish_existing_catalogue_preserves_rich_copy_and_price(shared):
    from extensions import db
    from modules.installments.models import InstallmentProduct
    (product, _, update, _), company_id = shared
    item = InstallmentProduct(tenant_id=company_id, product_id=product.id, title="Custom store title",
                             slug="custom-store", short_description="Custom short", full_description="Rich text",
                             cash_price=177, category="Custom category", status="draft", featured=True)
    db.session.add(item)
    db.session.commit()
    # Editing another inventory field must never publish an existing draft.
    body, status = update({"category": "Inventory category"})
    assert status == 200 and item.status == "draft", body
    body, status = update({"store_visible": "1"})
    assert status == 200 and item.status == "published", body
    assert (item.title, item.cash_price, item.short_description, item.full_description, item.category, item.featured) == (
        "Custom store title", 177, "Custom short", "Rich text", "Custom category", True)
    body, status = update({"store_visible": "0"})
    assert status == 200 and item.status == "published" and product.store_visible is False, body


def test_failed_edit_does_not_publish_or_change_inventory(shared):
    from modules.installments.models import InstallmentProduct
    (product, stock, update, _), _ = shared
    body, status = update({"store_visible": "1", "add_colors": "[]"})
    assert status == 409, body
    assert InstallmentProduct.query.filter_by(product_id=product.id).first() is None
    assert product.quantity == stock.quantity == 6


def test_explicit_visible_creation_joins_existing_store_catalogue(shared):
    from flask import current_app, g
    from models.product import Product
    from modules.installments.models import InstallmentProduct
    (_, _, _, routes), _ = shared
    with current_app.test_request_context("/inventory/add", method="POST", data={
        "_response": "json", "name": "Created online model", "buy_price": "100", "sale_price": "150",
        "opening_stock": "0", "store_visible": "1",
    }):
        g.independent_branches_enabled = False
        response = current_app.make_response(routes.add_product_page())
        assert response.status_code == 200, response.get_json()
        product = Product.query.get(response.get_json()["product_id"])
        item = InstallmentProduct.query.filter_by(product_id=product.id).one()
        assert item.status == "published" and item.cash_price == product.sale_price == 150


def test_unrelated_edit_keeps_unlinked_product_unpublished(shared):
    from modules.installments.models import InstallmentProduct
    (product, _, update, _), _ = shared
    body, status = update({"description": "Inventory-only detail"})
    assert status == 200, body
    assert InstallmentProduct.query.filter_by(product_id=product.id).first() is None


# Inventory update followed by real public listing, detail and cart requests.
from tests.test_recommendations import shop
from tests.test_branch_management_api import app


def test_published_inventory_product_is_reachable_in_public_shop(shop, monkeypatch):
    from flask import g
    from extensions import db
    from models.product import Product
    from models.tenant import Tenant
    from modules.installments.models import InstallmentProduct
    from modules.search import engine
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from routes import storefront as sf

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        company = Tenant.query.first() or Tenant(name="Publication shop")
        db.session.add(company)
        db.session.flush()
        db.session.add(InstallmentProduct(tenant_id=company.id, product_id=shop["tv55"],
                                         title="Published television", slug="published-tv", cash_price=500000,
                                         status="published"))
        target = db.session.get(Product, shop["tv50"])
        target.store_visible, target.active = True, True
        target.quantity = 0  # zero-stock published products remain visible for reservation
        db.session.commit()
        product_id = target.id
    invalidate_catalog_cache()
    engine.invalidate()
    sf._PAGE_CACHE.clear()
    public = shop["app"].test_client()
    base = f"/shop/{shop['tenant']}"
    assert public.get(f"{base}/product/{product_id}").status_code == 404
    from routes import inventory as inventory_routes
    monkeypatch.setattr(inventory_routes, "check_permission", lambda key: True)
    with shop["app"].test_request_context(f"/inventory/api/products/{product_id}/update", method="POST", data={"store_visible": "1"}):
        g.tenant = shop["tenant"]
        response = shop["app"].make_response(inventory_routes.product_api_update(product_id))
        assert response.status_code == 200 and response.json["success"], response.get_data(as_text=True)
    # Search and listing must use the same publication, including category filtering.
    found = public.get(f"{base}/api/products?sort=latest&per_page=48").get_json()
    assert product_id in [row["id"] for row in found["products"]]
    assert public.get(f"{base}/product/{product_id}").status_code == 200
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        settings = inventory_routes.product_api_details(product_id).get_json()["product"]
        assert settings["storefront_publication"]["status"] == "published"
    added = public.post(f"{base}/api/cart/add", json={"product_id": product_id, "qty": 1},
                        headers={"X-Requested-With": "XMLHttpRequest"})
    assert added.status_code == 200, added.get_json()
