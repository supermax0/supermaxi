"""Regression: quick sale must respect product color stock."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT_COLOR = f"test_quick_sale_color_stock_{os.getpid()}"
TENANT_REJECT = f"test_quick_sale_color_reject_{os.getpid()}"
TENANT_COMMISSION = f"test_quick_sale_commission_{os.getpid()}"


def _fresh_tenant_db(tenant: str):
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(tenant)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_quick_sale_deducts_variant_color_stock():
    _fresh_tenant_db(TENANT_COLOR)
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from utils.branch_stock_service import get_branch_stock, set_branch_stock
    from routes.quick_sale import execute

    with app.app_context():
        g.tenant = TENANT_COLOR
        init_tenant_db(TENANT_COLOR)

        employee = Employee(name="Quick Admin", username="quick-admin", password="x", role="admin", is_active=True)
        branch = Branch(name="Main", code="MAIN", is_default=True, is_active=True)
        product = Product(
            name="Color Quick Item",
            buy_price=100,
            sale_price=250,
            quantity=2,
            active=True,
            meta_json=json.dumps({"has_colors": True}),
        )
        db.session.add_all([employee, branch, product])
        db.session.flush()
        db.session.add(ProductColorVariant(product_id=product.id, color_name="red", quantity=2))
        set_branch_stock(branch.id, product.id, 2)
        db.session.commit()
        employee_id = employee.id
        product_id = product.id
        branch_id = branch.id

    payload = {
        "customer": {"phone": "07770000000", "name": "Quick Color Customer", "city": "Baghdad"},
        "items": [{"product_id": product_id, "qty": 1, "price": 250, "color": "red"}],
        "delivery_fee": 0,
    }
    with app.test_request_context("/quick-sale/execute", method="POST", json=payload):
        g.tenant = TENANT_COLOR
        session["user_id"] = employee_id
        resp = execute()
        data = resp.get_json()
        assert data["success"], data
        invoice_id = data["invoice_id"]

    with app.app_context():
        g.tenant = TENANT_COLOR
        invoice = Invoice.query.get(invoice_id)
        item = OrderItem.query.filter_by(invoice_id=invoice_id).first()
        color = ProductColorVariant.query.filter_by(product_id=product_id, color_name="red").first()
        customer = Customer.query.filter_by(phone="07770000000").first()

        assert invoice.payment_status == "\u0645\u0633\u062f\u062f"
        assert int(invoice.paid_amount or 0) == 250
        assert item.variant_color == "red"
        assert int(color.quantity or 0) == 1
        assert get_branch_stock(branch_id, product_id) == 1
        assert customer is not None


def test_quick_sale_rejects_colored_product_without_color():
    _fresh_tenant_db(TENANT_REJECT)
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch
    from models.employee import Employee
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from utils.branch_stock_service import set_branch_stock
    from routes.quick_sale import execute

    with app.app_context():
        g.tenant = TENANT_REJECT
        init_tenant_db(TENANT_REJECT)

        employee = Employee(name="Quick Admin 2", username="quick-admin-2", password="x", role="admin", is_active=True)
        branch = Branch(name="Main", code="MAIN", is_default=True, is_active=True)
        product = Product(
            name="Color Quick Item",
            buy_price=100,
            sale_price=250,
            quantity=2,
            active=True,
            meta_json=json.dumps({"has_colors": True}),
        )
        db.session.add_all([employee, branch, product])
        db.session.flush()
        db.session.add(ProductColorVariant(product_id=product.id, color_name="red", quantity=2))
        set_branch_stock(branch.id, product.id, 2)
        db.session.commit()
        employee_id = employee.id
        product_id = product.id

    payload = {
        "customer": {"phone": "07780000000", "name": "Quick Color Customer", "city": "Baghdad"},
        "items": [{"product_id": product_id, "qty": 1, "price": 250}],
    }
    with app.test_request_context("/quick-sale/execute", method="POST", json=payload):
        g.tenant = TENANT_REJECT
        session["user_id"] = employee_id
        resp, status = execute()
        data = resp.get_json()
        assert status == 400
        assert data["success"] is False


def test_quick_sale_creates_commission_line_for_paid_sale():
    _fresh_tenant_db(TENANT_COMMISSION)
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch
    from models.employee import Employee
    from models.employee_commission_line import EmployeeCommissionLine
    from models.product import Product
    from models.role import Permission, Role
    from utils.branch_stock_service import set_branch_stock
    from routes.quick_sale import execute

    with app.app_context():
        g.tenant = TENANT_COMMISSION
        init_tenant_db(TENANT_COMMISSION)

        permission = Permission.query.filter_by(name="view_quick_sale").first()
        if not permission:
            permission = Permission(name="view_quick_sale", description="quick sale")
        role = Role(name="quick_sale_cashier", description="quick sale cashier")
        role.permissions.append(permission)
        employee = Employee(
            name="Quick Cashier",
            username="quick-cashier",
            password="x",
            role="cashier",
            is_active=True,
            commission_percent=125,
        )
        employee.roles.append(role)
        branch = Branch(name="Main", code="MAIN", is_default=True, is_active=True)
        product = Product(name="Quick Commission Item", buy_price=100, sale_price=500, quantity=2, active=True)
        db.session.add_all([permission, role, employee, branch, product])
        db.session.flush()
        set_branch_stock(branch.id, product.id, 2)
        db.session.commit()
        employee_id = employee.id
        product_id = product.id

    payload = {
        "customer": {"phone": "07790000000", "name": "Quick Commission Customer", "city": "Baghdad"},
        "items": [{"product_id": product_id, "qty": 1, "price": 500}],
        "delivery_fee": 0,
    }
    with app.test_request_context("/quick-sale/execute", method="POST", json=payload):
        g.tenant = TENANT_COMMISSION
        session["user_id"] = employee_id
        resp = execute()
        data = resp.get_json()
        assert data["success"], data
        invoice_id = data["invoice_id"]

    with app.app_context():
        g.tenant = TENANT_COMMISSION
        line = EmployeeCommissionLine.query.filter_by(invoice_id=invoice_id, employee_id=employee_id).one()
        assert line.status == "pending"
        assert int(line.amount or 0) == 125


if __name__ == "__main__":
    test_quick_sale_deducts_variant_color_stock()
    test_quick_sale_rejects_colored_product_without_color()
    test_quick_sale_creates_commission_line_for_paid_sale()
    print("quick sale color stock tests passed")
