"""Regression: rejected POS edits must rollback restored stock and deleted items."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_pos_edit_rollback_{os.getpid()}"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_pos_edit_customer_change_rolls_back_stock_restore():
    _fresh_tenant_db()
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from routes.pos import create_order

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)

        customer_a = Customer(name="Original POS Customer", phone="07761000000")
        customer_b = Customer(name="Other POS Customer", phone="07762000000")
        employee = Employee(
            name="POS Cashier",
            username="pos-edit-cashier",
            password="x",
            role="cashier",
            is_active=True,
        )
        product = Product(name="POS Edit Item", buy_price=100, sale_price=500, quantity=3, active=True)
        db.session.add_all([customer_a, customer_b, employee, product])
        db.session.flush()

        invoice = Invoice(
            customer_id=customer_a.id,
            customer_name=customer_a.name,
            employee_id=employee.id,
            employee_name=employee.name,
            total=1000,
            status="\u062a\u0645 \u0627\u0644\u0637\u0644\u0628",
            payment_status="\u063a\u064a\u0631 \u0645\u0633\u062f\u062f",
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=2,
                price=500,
                cost=100,
                total=1000,
            )
        )
        db.session.commit()
        invoice_id = invoice.id
        customer_b_id = customer_b.id
        employee_id = employee.id
        product_id = product.id

    payload = {
        "order_id": invoice_id,
        "customer_id": customer_b_id,
        "items": [{"product_id": product_id, "qty": 1, "price": 500}],
    }
    with app.test_request_context("/pos/create-order", method="POST", json=payload):
        g.tenant = TENANT
        session["user_id"] = employee_id
        resp, status = create_order()
        assert status == 400
        assert "error" in resp.get_json()

        # A later commit in the same request/session must not persist the rejected edit.
        db.session.commit()

    with app.app_context():
        g.tenant = TENANT
        assert int(Product.query.get(product_id).quantity or 0) == 3
        assert OrderItem.query.filter_by(invoice_id=invoice_id).count() == 1
        assert int(Invoice.query.get(invoice_id).total or 0) == 1000


if __name__ == "__main__":
    test_pos_edit_customer_change_rolls_back_stock_restore()
    print("pos edit rollback tests passed")
