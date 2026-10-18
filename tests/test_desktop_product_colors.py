"""Native color addition preserves stock, history, metadata and offline holds."""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def inventory(monkeypatch):
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db, clear_tenant_engine
    from flask import g
    from models.branch import Branch, BranchStock
    from models.product import Product
    import routes.inventory as routes

    tenant = f"test_desktop_colors_{os.getpid()}_{uuid4().hex[:8]}"
    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        branch = Branch(code="COLORS", name="Colors", is_active=True, is_default=True)
        db.session.add(branch)
        db.session.flush()
        product = Product(branch_id=branch.id, name="Washer", sku="COLORS-1", quantity=6,
                          opening_stock=10, buy_price=100, sale_price=150, active=True,
                          meta_json=json.dumps({"specs": {"capacity": "13"}, "gallery_urls": ["old.png"]}))
        db.session.add(product)
        db.session.flush()
        stock = BranchStock(branch_id=branch.id, product_id=product.id, quantity=6, opening_stock=10)
        db.session.add(stock)
        db.session.commit()
        monkeypatch.setattr(routes, "check_permission", lambda key: key == "can_manage_inventory")

        def update(fields):
            with app.test_request_context(f"/inventory/api/products/{product.id}/update", method="POST", data=fields):
                result = routes.product_api_update(product.id)
                response, status = result if isinstance(result, tuple) else (result, 200)
                return response.get_json(), status

        yield product, stock, update, routes
        db.session.remove()
    clear_tenant_engine(tenant)
    (Path(__file__).resolve().parents[1] / "tenants" / f"{tenant}.db").unlink(missing_ok=True)


def test_first_color_preserves_live_stock_and_metadata(inventory):
    from models.product_color_variant import ProductColorVariant
    product, stock, update, _ = inventory
    body, status = update({"add_colors": json.dumps(["أبيض", "أسود"]), "color_stock": "6"})
    assert status == 200, body
    rows = ProductColorVariant.query.filter_by(product_id=product.id).all()
    assert {row.color_name: row.quantity for row in rows} == {"أبيض": 6, "أسود": 0}
    assert product.quantity == stock.quantity == 6
    assert product.opening_stock == stock.opening_stock == 10
    assert json.loads(product.meta_json) == {"specs": {"capacity": "13"}, "gallery_urls": ["old.png"], "has_colors": True}
    assert {(row.buy_price, row.sale_price) for row in rows} == {(100, 150)}


def test_stale_stock_and_duplicate_names_roll_back_other_edits(inventory):
    from models.product_color_variant import ProductColorVariant
    product, _, update, _ = inventory
    for fields in [
        {"add_colors": '["أبيض"]', "color_stock": "7"},
        {"add_colors": '[" White ","white"]', "color_stock": "6"},
        {"add_colors": '[1]', "color_stock": "6"},
    ]:
        body, status = update({**fields, "name": "Must rollback"})
        assert status == 409, body
        assert product.name == "Washer"
        assert ProductColorVariant.query.filter_by(product_id=product.id).count() == 0


def test_existing_color_quantities_prices_and_other_branches_are_untouched(inventory):
    from extensions import db
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    product, stock, update, _ = inventory
    product.meta_json = json.dumps({"has_colors": True, "specs": {"capacity": "13"}})
    old = ProductColorVariant(product_id=product.id, color_name="أبيض", quantity=6, buy_price=88, sale_price=177)
    sibling = Product(name="Sibling", sku=product.sku, catalog_group_id=product.catalog_group_id,
                      quantity=25, buy_price=900, sale_price=999, active=True)
    db.session.add_all([old, sibling])
    db.session.flush()
    other = ProductColorVariant(product_id=sibling.id, color_name="فضي", quantity=25, sale_price=999)
    db.session.add(other)
    db.session.commit()
    body, status = update({"add_colors": '["فضي"]', "color_stock": "0"})
    assert status == 200, body
    assert (old.quantity, old.buy_price, old.sale_price) == (6, 88, 177)
    assert (other.quantity, other.sale_price) == (25, 999)
    assert product.quantity == stock.quantity == 6
    assert ProductColorVariant.query.filter_by(product_id=product.id, color_name="فضي").one().quantity == 0


def test_price_permission_cannot_be_bypassed_with_colors(inventory):
    from models.product_color_variant import ProductColorVariant
    product, _, update, _ = inventory
    body, status = update({"add_colors": '["أبيض"]', "color_stock": "6", "sale_price": "500"})
    assert status == 403, body
    assert product.sale_price == 150
    assert ProductColorVariant.query.filter_by(product_id=product.id).count() == 0


def test_offline_stock_hold_blocks_conversion_and_rolls_back(inventory):
    from extensions import db
    from utils.desktop_stock_reservations import ensure_reservation_schema, DesktopStockAllocation
    from models.product_color_variant import ProductColorVariant
    product, stock, update, _ = inventory
    ensure_reservation_schema()
    db.session.add(DesktopStockAllocation(id=str(uuid4()), grant_id="hold", requested_product_id=product.id, product_id=product.id,
        stock_id=stock.id, variant_id=0, branch_id=product.branch_id, color="", quantity=2, consumed=0, returned=0))
    db.session.commit()
    body, status = update({"add_colors": '["أبيض"]', "color_stock": "6", "name": "Must rollback"})
    assert status == 409, body
    assert "أوفلاين" in body["error"]
    assert product.name == "Washer"
    assert product.quantity == stock.quantity == 6
    assert ProductColorVariant.query.filter_by(product_id=product.id).count() == 0


def test_barcode_edit_keeps_one_shared_row_and_preserves_branch_stock(inventory, monkeypatch):
    from extensions import db
    from flask import g, current_app
    from models.branch import Branch, BranchStock
    from models.product import Product
    from services.pos_catalog import shared_catalog_products

    product, stock, update, routes = inventory
    g.independent_branches_enabled = False
    g.view_all_branches = True
    second_branch = Branch(code="SECOND", name="Second", is_active=True)
    db.session.add(second_branch)
    db.session.flush()
    copy = Product(branch_id=second_branch.id, catalog_group_id=product.catalog_group_id,
                   name=product.name, quantity=4, opening_stock=4, buy_price=88, sale_price=199, active=True)
    db.session.add(copy)
    db.session.flush()
    other_stock = BranchStock(branch_id=second_branch.id, product_id=copy.id, quantity=4, opening_stock=4)
    db.session.add(other_stock)
    db.session.commit()

    def rows():
        with current_app.test_request_context("/inventory/api/products"):
            return routes.products_api().get_json()["rows"]

    assert len(rows()) == 1
    monkeypatch.setattr(routes, "check_permission", lambda key: True)
    body, status = update({"barcode": "2909536325824", "sale_price": "265000"})
    assert status == 200, body
    result = rows()
    assert len(result) == 1
    assert result[0]["id"] == product.id
    assert result[0]["quantity"] == 10
    assert result[0]["barcode"] == "2909536325824"
    assert result[0]["sale_price"] == 265000
    assert Product.query.count() == 2
    assert (stock.quantity, other_stock.quantity, copy.sale_price) == (6, 4, 199)
    pos_rows = shared_catalog_products([product, copy])
    assert len(pos_rows) == 1
    assert pos_rows[0]["quantity"] == 10
    assert pos_rows[0]["branch_products"] == {str(product.branch_id): product.id, str(copy.branch_id): copy.id}
    g.independent_branches_enabled = True
    assert len(rows()) == 2
