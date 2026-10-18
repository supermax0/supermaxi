from types import SimpleNamespace
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_transfer_catalog_exposes_product_branch_for_source_filter(monkeypatch):
    import routes.stock_transfers as stock_transfers

    monkeypatch.setattr(stock_transfers, "colors_for_product_dict", lambda _product: {})
    products = [
        SimpleNamespace(
            id=51,
            branch_id=1,
            name="منتج مشترك",
            sku="SKU-1",
            barcode="BAR-1",
            buy_price=100,
            sale_price=150,
        ),
        SimpleNamespace(
            id=173,
            branch_id=2,
            name="منتج مشترك",
            sku="SKU-1",
            barcode="BAR-1",
            buy_price=100,
            sale_price=150,
        ),
    ]

    catalog = stock_transfers._products_catalog(products)

    assert [(row["id"], row["branch_id"]) for row in catalog] == [(51, 1), (173, 2)]


def test_transfer_catalog_exposes_per_branch_color_stock():
    from app import app
    from extensions import db
    from extensions_tenant import clear_tenant_engine, init_tenant_db
    from flask import g
    from models.branch import Branch
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from routes.stock_transfers import _products_catalog

    tenant = f"test_transfer_color_catalog_{os.getpid()}"
    database = ROOT / "tenants" / f"{tenant}.db"
    clear_tenant_engine(tenant)
    if database.exists():
        database.unlink()

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        main = Branch(code="TRC-M", name="Main", is_active=True, is_default=True)
        second = Branch(code="TRC-S", name="Second", is_active=True)
        first = Product(
            branch_id=1,
            name="ثلاجة مشتركة",
            barcode="TRC-1",
            buy_price=100,
            sale_price=150,
            quantity=1,
            active=True,
            meta_json='{"has_colors": true}',
        )
        second_product = Product(
            branch_id=2,
            name="ثلاجة مشتركة",
            barcode="TRC-1",
            buy_price=100,
            sale_price=150,
            quantity=3,
            active=True,
            meta_json='{"has_colors": true}',
        )
        db.session.add_all([main, second, first, second_product])
        db.session.flush()
        first.branch_id = main.id
        second_product.branch_id = second.id
        second_product.catalog_group_id = first.catalog_group_id
        db.session.add_all(
            [
                ProductColorVariant(product_id=first.id, color_name="أبيض", quantity=1),
                ProductColorVariant(product_id=second_product.id, color_name="أبيض", quantity=3),
            ]
        )
        db.session.flush()

        rows = {row["id"]: row for row in _products_catalog([first, second_product])}

        assert rows[first.id]["branch_color_stocks"][str(main.id)]["أبيض"] == 1
        assert rows[first.id]["branch_color_stocks"][str(second.id)]["أبيض"] == 3
        assert rows[second_product.id]["branch_color_stocks"][str(main.id)]["أبيض"] == 1
        assert rows[second_product.id]["branch_color_stocks"][str(second.id)]["أبيض"] == 3

    clear_tenant_engine(tenant)
