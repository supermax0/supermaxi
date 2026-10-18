"""Regression: POS stock labels for colored products use color balances."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_pos_color_stock_display_{os.getpid()}"


def _fresh_tenant_db(tenant: str):
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(tenant)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_pos_bootstrap_colored_product_quantity_matches_colors():
    _fresh_tenant_db(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from routes.pos import _product_bootstrap_dict

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)

        product = Product(
            name="ثلاجة إيفولي 7 قدم",
            buy_price=150000,
            sale_price=185000,
            quantity=7,
            active=True,
            meta_json=json.dumps({"has_colors": True}, ensure_ascii=False),
        )
        db.session.add(product)
        db.session.flush()
        db.session.add_all(
            [
                ProductColorVariant(product_id=product.id, color_name="أبيض", quantity=1),
                ProductColorVariant(product_id=product.id, color_name="سلفر", quantity=1),
                ProductColorVariant(product_id=product.id, color_name="أسود", quantity=0),
            ]
        )
        db.session.flush()

        row = _product_bootstrap_dict(product)

        assert row["has_colors"] is True
        assert row["quantity"] == 2
        assert row["total_quantity"] == 2


def test_shared_pos_catalog_colored_product_quantity_ignores_stale_branch_stock():
    _fresh_tenant_db(TENANT + "_branch")
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.branch import Branch, BranchStock
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from services.pos_catalog import shared_catalog_products

    with app.app_context():
        g.tenant = TENANT + "_branch"
        init_tenant_db(TENANT + "_branch")

        branch = Branch(code="MAIN", name="Main", is_active=True, is_default=True)
        product = Product(
            branch_id=1,
            name="ثلاجة إيفولي 7 قدم",
            buy_price=150000,
            sale_price=185000,
            quantity=7,
            active=True,
            meta_json=json.dumps({"has_colors": True}, ensure_ascii=False),
        )
        db.session.add_all([branch, product])
        db.session.flush()
        product.branch_id = branch.id
        db.session.add_all(
            [
                BranchStock(branch_id=branch.id, product_id=product.id, quantity=7, opening_stock=7),
                ProductColorVariant(product_id=product.id, color_name="أبيض", quantity=1),
                ProductColorVariant(product_id=product.id, color_name="سلفر", quantity=1),
            ]
        )
        db.session.flush()

        row = shared_catalog_products([product])[0]

        assert row["quantity"] == 2
        assert row["total_quantity"] == 2
