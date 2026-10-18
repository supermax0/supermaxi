"""Desktop exchange price and channel visibility use the existing product flags."""
import pytest
from tests.test_desktop_product_colors import inventory


def test_details_preserve_exchange_price_and_independent_channel_flags(inventory, monkeypatch):
    from flask import current_app
    from extensions import db
    product, _, _, routes = inventory
    product.exchange_sale_price = 125
    product.pos_visible, product.store_visible = False, True
    db.session.commit()
    monkeypatch.setattr(routes, "tenant_feature_enabled", lambda *a, **k: True)
    with current_app.test_request_context("/"):
        row = routes.product_api_details(product.id).get_json()["product"]
    assert row["exchange_sale_price"] == 125
    assert row["editor_settings_supported"] and row["trade_in_sales_enabled"]
    assert row["pos_visible"] is False and row["store_visible"] is True


def test_price_permission_failure_cannot_change_visibility_or_name(inventory, monkeypatch):
    from extensions import db
    product, _, update, routes = inventory
    monkeypatch.setattr(routes, "tenant_feature_enabled", lambda *a, **k: True)
    body, status = update({"name": "Must not change", "exchange_sale_price": "120", "pos_visible": "0"})
    assert status == 403, body
    db.session.expire_all()
    assert product.exchange_sale_price is None and product.pos_visible is True
    assert product.name == "Washer"


def test_shared_channel_visibility_propagates_only_explicit_family(inventory, monkeypatch):
    from extensions import db
    from flask import g
    from models.branch import Branch
    from models.product import Product
    product, stock, update, routes = inventory
    g.independent_branches_enabled = False
    branch = Branch(code="SECOND", name="Second", is_active=True)
    db.session.add(branch)
    db.session.flush()
    sibling = Product(name="Sibling", branch_id=branch.id, catalog_group_id=product.catalog_group_id,
                      buy_price=10, sale_price=20, quantity=9, active=True)
    other = Product(name="Separate", branch_id=branch.id, buy_price=10, sale_price=20, quantity=4, active=True)
    db.session.add_all([sibling, other])
    db.session.commit()
    monkeypatch.setattr(routes, "check_permission", lambda key: True)
    monkeypatch.setattr(routes, "tenant_feature_enabled", lambda *a, **k: True)
    body, status = update({"exchange_sale_price": "125", "pos_visible": "0"})
    assert status == 200, body
    assert product.exchange_sale_price == 125
    assert product.pos_visible is False and sibling.pos_visible is False and other.pos_visible is True
    assert product.store_visible is True and sibling.store_visible is True
    assert (stock.quantity, product.quantity, sibling.quantity, other.quantity) == (6, 6, 9, 4)
    body, status = update({"store_visible": "0", "exchange_sale_price": ""})
    assert status == 200, body
    assert product.exchange_sale_price is None
    assert product.store_visible is False and sibling.store_visible is False
    assert other.store_visible is True
    assert product.buy_price == 100 and product.sale_price == 150


def test_independent_branch_visibility_leaves_other_branch_unchanged(inventory):
    from extensions import db
    from flask import g
    from models.branch import Branch
    from models.product import Product
    product, _, update, _ = inventory
    g.independent_branches_enabled = True
    branch = Branch(code="SECOND", name="Second", is_active=True)
    db.session.add(branch)
    db.session.flush()
    sibling = Product(name="Sibling", branch_id=branch.id, catalog_group_id=product.catalog_group_id,
                      buy_price=10, sale_price=20, active=True)
    db.session.add(sibling)
    db.session.commit()
    body, status = update({"pos_visible": "0", "store_visible": "0"})
    assert status == 200, body
    assert product.pos_visible is False and product.store_visible is False
    assert sibling.pos_visible is True and sibling.store_visible is True


@pytest.mark.parametrize("fields", [
    {"exchange_sale_price": "-1"}, {"exchange_sale_price": "12.5"},
    {"exchange_sale_price": "abc"}, {"pos_visible": "false"}, {"store_visible": ""},
])
def test_bad_settings_cannot_partially_change_other_fields(inventory, fields):
    product, _, update, _ = inventory
    body, status = update({"name": "Must not change", **fields})
    assert status == 400, body
    assert product.name == "Washer" and product.exchange_sale_price is None
    assert product.pos_visible is True and product.store_visible is True


def test_disabled_trade_in_rejects_price_but_visibility_edits_preserve_old_price(inventory, monkeypatch):
    from extensions import db
    product, _, update, routes = inventory
    monkeypatch.setattr(routes, "check_permission", lambda key: True)
    monkeypatch.setattr(routes, "tenant_feature_enabled", lambda *a, **k: False)
    body, status = update({"exchange_sale_price": "125"})
    assert status == 400, body
    product.exchange_sale_price = 130
    db.session.commit()
    body, status = update({"store_visible": "0"})
    assert status == 200, body
    assert product.exchange_sale_price == 130 and product.store_visible is False


def test_native_creation_accepts_exchange_price_and_hidden_channels(inventory, monkeypatch):
    from flask import current_app, g
    from models.product import Product
    product, _, _, routes = inventory
    monkeypatch.setattr(routes, "tenant_feature_enabled", lambda *a, **k: True)
    g.independent_branches_enabled = False
    with current_app.test_request_context("/inventory/add", method="POST", data={
        "_response": "json", "name": "New hidden TV", "buy_price": "100", "sale_price": "150",
        "exchange_sale_price": "125", "pos_visible": "0", "store_visible": "0", "opening_stock": "0",
    }):
        response = current_app.make_response(routes.add_product_page())
        assert response.status_code == 200, response.get_json()
        created = Product.query.get(response.get_json()["product_id"])
        assert created.exchange_sale_price == 125
        assert created.pos_visible is False and created.store_visible is False
        assert created.active is True and created.quantity == 0
    assert product.quantity == 6
