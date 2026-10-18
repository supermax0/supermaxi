"""Quick sale lists all authorized branches and deducts every line locally."""
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_quick_sale_branch_{os.getpid()}"


def _fresh_tenant_db():
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_admin_sees_all_branches_and_mixed_cart_deducts_each_product_locally():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.branch import Branch
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.product import Product
    from models.tenant import Tenant
    from routes.quick_sale import execute, products
    from utils.branch_stock_service import get_branch_stock, set_branch_stock

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        tenant = Tenant(
            name="Quick Sale Branch Scope",
            subdomain=TENANT,
            feature_overrides_json=json.dumps({"quick_sale_advanced_checkout": True}),
        )
        admin = Employee(
            name="Quick Admin",
            username=f"quick-branch-admin-{os.getpid()}",
            password="x",
            role="admin",
            is_active=True,
        )
        first = Branch(name="Baghdad", code="BGD", is_default=True, is_active=True)
        second = Branch(name="Basra", code="BSR", is_default=False, is_active=True)
        db.session.add_all([tenant, admin, first, second])
        db.session.flush()
        first_product = Product(
            branch_id=first.id,
            catalog_group_id="shared-quick-sale-product",
            name="Shared Product",
            buy_price=100,
            sale_price=250,
            quantity=4,
            active=True,
        )
        second_product = Product(
            branch_id=second.id,
            catalog_group_id="shared-quick-sale-product",
            name="Shared Product",
            buy_price=100,
            sale_price=300,
            quantity=3,
            active=True,
        )
        first_customer = Customer(
            branch_id=first.id,
            name="Cross Branch Customer",
            phone="07701112222",
            city="بغداد",
        )
        db.session.add_all([first_product, second_product, first_customer])
        db.session.flush()
        set_branch_stock(first.id, first_product.id, 4)
        set_branch_stock(second.id, second_product.id, 3)
        db.session.commit()
        ids = {
            "admin": admin.id,
            "first": first.id,
            "second": second.id,
            "first_product": first_product.id,
            "second_product": second_product.id,
            "customer": first_customer.id,
        }

    with app.test_request_context("/quick-sale/products"):
        g.tenant = TENANT
        session["user_id"] = ids["admin"]
        data = products().get_json()
        assert data["success"] is True
        assert len(data["products"]) == 1
        shared = data["products"][0]
        assert shared["stock"] == 7
        assert {(row["id"], row["branch_id"], row["stock"]) for row in shared["stock_sources"]} == {
            (ids["first_product"], ids["first"], 4),
            (ids["second_product"], ids["second"], 3),
        }

    payload = {
        "branch_id": ids["second"],
        "advanced_checkout": True,
        "customer": {"enabled": False, "customer_id": ids["customer"]},
        "items": [
            {"product_id": ids["first_product"], "branch_id": ids["first"], "qty": 1, "price": 250},
            {"product_id": ids["second_product"], "branch_id": ids["second"], "qty": 1, "price": 300},
        ],
        "payment_type": "credit",
    }
    with app.test_request_context("/quick-sale/execute", method="POST", json=payload):
        g.tenant = TENANT
        session["user_id"] = ids["admin"]
        response = execute()
        data = response.get_json()
        assert data["success"] is True, data
        invoice_id = data["invoice_id"]

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(invoice_id)
        assert invoice.branch_id == ids["second"]
        assert invoice.customer_id == ids["customer"]
        assert get_branch_stock(ids["second"], ids["second_product"]) == 2
        assert get_branch_stock(ids["first"], ids["first_product"]) == 3
