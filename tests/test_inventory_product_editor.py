"""New product editor: JSON creation fails safely and retains zero thresholds."""
import json
import pytest
from tests.test_desktop_product_colors import inventory


def create(inventory, fields):
    from flask import current_app, g
    _, _, _, routes = inventory
    with current_app.test_request_context("/inventory/add", method="POST", data={
        "_response": "json", "name": "Editor product", "buy_price": "100", "sale_price": "150", **fields,
    }):
        g.independent_branches_enabled = False
        response = current_app.make_response(routes.add_product_page())
        return response.get_json(), response.status_code


@pytest.mark.parametrize("fields", [
    {"opening_stock": "-1"}, {"buy_price": "12.5"}, {"sale_price": "abc"},
    {"low_stock_threshold": "-1"},
    {"has_colors": "1", "color_name[]": ["Blue", "blue"], "color_qty[]": ["1", "2"]},
    {"has_colors": "1", "color_name[]": [""], "color_qty[]": ["1"]},
    {"has_colors": "1", "color_name[]": ["Blue"], "color_qty[]": ["2.5"]},
])
def test_invalid_creation_never_creates_product_or_changes_stock(inventory, fields):
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    product, stock, _, _ = inventory
    before = Product.query.count(), ProductColorVariant.query.count(), product.quantity, stock.quantity
    body, status = create(inventory, fields)
    assert status == 400 and body["success"] is False, body
    assert (Product.query.count(), ProductColorVariant.query.count(), product.quantity, stock.quantity) == before


def test_create_zero_threshold_and_independent_channel_visibility(inventory):
    from models.product import Product
    body, status = create(inventory, {"low_stock_threshold": "0", "opening_stock": "3",
                                    "not_for_sale": "1", "pos_visible": "0", "store_visible": "1"})
    assert status == 200, body
    product = Product.query.get(body["product_id"])
    assert product.low_stock_threshold == 0 and product.quantity == 3
    assert product.active is False and product.pos_visible is False and product.store_visible is True


def test_create_colors_uses_per_color_opening_stock(inventory):
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    body, status = create(inventory, {"has_colors": "1", "color_name[]": ["أسود", "أبيض"],
                                    "color_qty[]": ["2", "3"], "opening_stock": "999"})
    assert status == 200, body
    product = Product.query.get(body["product_id"])
    assert product.quantity == product.opening_stock == 5
    assert {row.color_name: row.quantity for row in ProductColorVariant.query.filter_by(product_id=product.id)} == {"أسود": 2, "أبيض": 3}


def test_edit_settings_preserves_rich_metadata_and_live_balances(inventory):
    product, stock, update, _ = inventory
    original_meta = json.loads(product.meta_json)
    body, status = update({"category": "New category", "low_stock_threshold": "0", "active": "0", "store_visible": "0"})
    assert status == 200, body
    assert json.loads(product.meta_json) == {**original_meta, "category": "New category"}
    assert (product.quantity, stock.quantity, product.opening_stock, stock.opening_stock) == (6, 6, 10, 10)
    assert product.low_stock_threshold == 0 and product.active is False and product.store_visible is False
