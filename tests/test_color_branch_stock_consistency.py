"""Regressions for the color/branch inventory source-of-truth invariant."""
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_color_branch_stock_consistency_{os.getpid()}"


def _fresh_tenant_db(tenant: str):
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(tenant)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_color_adjustment_repairs_branch_total_and_preserves_opening_stock():
    _fresh_tenant_db(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.branch import Branch, BranchStock
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from utils.branch_stock_service import get_branch_stock
    from utils.product_color_service import adjust_color_stock, get_branch_product_colors

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)

        branch = Branch(code="MAIN", name="الكرادة", is_active=True, is_default=True)
        db.session.add(branch)
        db.session.flush()
        product = Product(
            branch_id=branch.id,
            name="ثلاجة",
            buy_price=100,
            sale_price=150,
            opening_stock=9,
            quantity=5,
            active=True,
            meta_json=json.dumps({"has_colors": True}, ensure_ascii=False),
        )
        db.session.add(product)
        db.session.flush()
        db.session.add_all(
            [
                BranchStock(
                    branch_id=branch.id,
                    product_id=product.id,
                    quantity=5,
                    opening_stock=9,
                ),
                ProductColorVariant(
                    product_id=product.id,
                    color_name="أبيض",
                    quantity=4,
                ),
            ]
        )
        db.session.flush()

        before, after, total = adjust_color_stock(
            product.id,
            "أبيض",
            -2,
            branch_id=branch.id,
        )
        db.session.flush()

        assert (before, after, total) == (4, 2, 2)
        assert get_branch_stock(branch.id, product.id) == 2
        assert get_branch_product_colors(product.id, branch.id)[0]["qty"] == 2
        assert product.quantity == 2
        assert product.opening_stock == 9


def test_inventory_quick_editor_requires_and_serializes_color():
    template = (ROOT / "templates" / "inventory.html").read_text(encoding="utf-8")

    assert 'name="color_name"' in template
    assert '"branch_colors"' in template
    assert "setAdjustColors(product" in template

