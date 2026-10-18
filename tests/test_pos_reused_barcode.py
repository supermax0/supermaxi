"""Reused legacy TV barcodes cannot hide products or select the wrong sale."""
import os
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def catalog(monkeypatch):
    from app import app
    from extensions import db
    from extensions_tenant import clear_tenant_engine, init_tenant_db
    from flask import g
    from models.branch import Branch, BranchStock
    from models.employee import Employee
    from models.product import Product
    import routes.inventory as inventory

    tenant = f"test_pos_reused_barcode_{os.getpid()}_{uuid4().hex[:8]}"
    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        branches = [Branch(code=str(i), name=str(i), is_active=True, is_default=i == 1) for i in (1, 2)]
        db.session.add_all(branches)
        db.session.flush()
        employee = Employee(name="Test", username="test", password="unused", role="admin", branch_id=branches[0].id)
        db.session.add(employee)
        products = []
        for name, sku, family, quantities in [
            ("شاشه جنرال حجم 50", "003", "general", [7, 4]),
            ("شاشه الجي حجم 50", "010", "lg", [3, 12]),
        ]:
            for branch, quantity in zip(branches, quantities):
                product = Product(name=name, sku=sku, catalog_group_id=family, barcode="260101050",
                    branch_id=branch.id, buy_price=100, sale_price=150, quantity=quantity,
                    active=True, pos_visible=True)
                db.session.add(product)
                db.session.flush()
                db.session.add(BranchStock(branch_id=branch.id, product_id=product.id, quantity=quantity))
                products.append(product)
        db.session.commit()
        g.independent_branches_enabled = False
        g.branch, g.branches, g.view_all_branches, g.branch_scope_ready = branches[0], branches, True, True
        monkeypatch.setattr(inventory, "check_permission", lambda key: key == "can_manage_inventory")
        yield app, employee, products
        db.session.remove()
    clear_tenant_engine(tenant)
    (Path(__file__).resolve().parents[1] / "tenants" / f"{tenant}.db").unlink(missing_ok=True)


def test_native_products_and_pos_can_find_lg_without_general_stock(catalog):
    from flask import session
    from routes.inventory import products_api
    from routes.pos import pos_api_products
    app, employee, products = catalog
    for route in (products_api, pos_api_products):
        with app.test_request_context("/?search=الجي"):
            session["user_id"] = employee.id
            body = route().get_json()
            assert body["total"] == 1
            assert body["rows"][0]["name"] == "شاشه الجي حجم 50"
            assert body["rows"][0]["quantity"] == 15
            assert body["rows"][0]["id"] == products[2].id
    assert [p.quantity for p in products] == [7, 4, 3, 12]


def test_reused_barcode_returns_both_choices_without_auto_add(catalog):
    from services.pos_catalog import search_pos_products
    app, employee, _ = catalog
    with app.test_request_context("/"):
        rows = search_pos_products(employee, "260101050")
        assert {row["name"]: row["quantity"] for row in rows} == {
            "شاشه جنرال حجم 50": 11, "شاشه الجي حجم 50": 15,
        }
        assert all(row["is_barcode"] is False for row in rows)


def test_unique_family_barcode_keeps_auto_add_and_hidden_products_stay_hidden(catalog):
    from extensions import db
    from services.pos_catalog import search_pos_products
    app, employee, products = catalog
    for product in products[:2]:
        product.pos_visible = False
    db.session.commit()
    with app.test_request_context("/"):
        rows = search_pos_products(employee, "260101050")
        assert len(rows) == 1
        assert rows[0]["name"] == "شاشه الجي حجم 50"
        assert rows[0]["is_barcode"] is True
