"""Regression: rejected POS edits must rollback restored stock and deleted items."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_pos_edit_rollback_{os.getpid()}"
TENANT_DEFERRED = f"test_pos_edit_deferred_{os.getpid()}"
TENANT_QUICK_EDIT = f"test_order_quick_edit_{os.getpid()}"


def _fresh_tenant_db(tenant=TENANT):
    try:
        from extensions import db
        db.session.remove()
    except Exception:
        pass
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(tenant)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{tenant}.db"
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
    from utils.branch_migration import get_default_branch

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        branch = get_default_branch()

        customer_a = Customer(branch_id=branch.id, name="Original POS Customer", phone="07761000000")
        customer_b = Customer(branch_id=branch.id, name="Other POS Customer", phone="07762000000")
        employee = Employee(
            name="POS Cashier",
            username="pos-edit-cashier",
            password="x",
            role="cashier",
            is_active=True,
            branch_id=branch.id,
        )
        product = Product(branch_id=branch.id, name="POS Edit Item", buy_price=100, sale_price=500, quantity=3, active=True)
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
            branch_id=branch.id,
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
                fulfillment_branch_id=branch.id,
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


def test_edit_keeps_existing_deferred_order_undeducted_when_policy_is_disabled():
    """Disabling the policy must affect new orders only, not a deferred edit."""
    _fresh_tenant_db(TENANT_DEFERRED)
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.system_settings import SystemSettings
    from routes.pos import create_order
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import get_branch_stock, set_branch_stock
    from utils.order_stock_policy import POLICY_FLAG, POLICY_INITIALIZED_FLAG

    with app.app_context():
        g.tenant = TENANT_DEFERRED
        init_tenant_db(TENANT_DEFERRED)
        branch = get_default_branch()
        customer = Customer(
            name="Deferred Edit Customer",
            phone="07763000000",
            branch_id=branch.id,
        )
        employee = Employee(
            name="Deferred Edit Cashier",
            username="deferred-edit-cashier",
            password="x",
            role="cashier",
            is_active=True,
            branch_id=branch.id,
        )
        product = Product(
            name="Last Deferred Piece",
            buy_price=100,
            sale_price=500,
            quantity=0,
            active=True,
            branch_id=branch.id,
        )
        db.session.add_all([customer, employee, product])
        db.session.flush()
        set_branch_stock(branch.id, product.id, 1)

        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags()
        flags[POLICY_FLAG] = False
        flags[POLICY_INITIALIZED_FLAG] = True
        settings.set_ui_flags(flags)

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            branch_id=branch.id,
            total=500,
            status="تم الطلب",
            payment_status="غير مسدد",
            paid_amount=0,
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            price=500,
            cost=100,
            total=500,
            fulfillment_branch_id=branch.id,
        ))
        db.session.commit()
        invoice_id = invoice.id
        customer_id = customer.id
        employee_id = employee.id
        product_id = product.id
        branch_id = branch.id

    payload = {
        "order_id": invoice_id,
        "customer_id": customer_id,
        "items": [{
            "product_id": product_id,
            "qty": 1,
            "price": 500,
            "fulfillment_branch_id": branch_id,
        }],
    }
    with app.test_request_context("/pos/create-order", method="POST", json=payload):
        g.tenant = TENANT_DEFERRED
        session["user_id"] = employee_id
        response = create_order()
        assert response.get_json()["success"] is True

    with app.app_context():
        g.tenant = TENANT_DEFERRED
        invoice = Invoice.query.get(invoice_id)
        assert invoice.status == "تم الطلب"
        assert invoice.payment_status == "غير مسدد"
        assert invoice.stock_is_deducted is False
        assert get_branch_stock(branch_id, product_id) == 1
        assert int(Product.query.get(product_id).quantity or 0) == 1


def test_quick_edit_updates_customer_note_products_quantity_price_and_discount():
    _fresh_tenant_db(TENANT_QUICK_EDIT)
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from routes.orders import quick_edit_order
    from utils.branch_migration import get_default_branch

    with app.app_context():
        g.tenant = TENANT_QUICK_EDIT
        init_tenant_db(TENANT_QUICK_EDIT)
        branch = get_default_branch()
        customer = Customer(branch_id=branch.id, name="Quick Customer", phone="07770000000")
        employee = Employee(
            name="Quick Admin",
            username="quick-edit-admin",
            password="x",
            role="admin",
            is_active=True,
            branch_id=branch.id,
        )
        old_product = Product(branch_id=branch.id, name="Old Item", buy_price=100, sale_price=500, quantity=5, active=True)
        new_product = Product(branch_id=branch.id, name="New Item", buy_price=200, sale_price=700, quantity=5, active=True)
        db.session.add_all([customer, employee, old_product, new_product])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            branch_id=branch.id,
            total=500,
            status="تم الطلب",
            payment_status="غير مسدد",
            paid_amount=0,
            note="old note",
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(OrderItem(
            invoice_id=invoice.id,
            product_id=old_product.id,
            product_name=old_product.name,
            quantity=1,
            price=500,
            cost=100,
            total=500,
            fulfillment_branch_id=branch.id,
        ))
        db.session.commit()
        invoice_id = invoice.id
        customer_id = customer.id
        employee_id = employee.id
        new_product_id = new_product.id

    payload = {
        "customer": {
            "name": "Quick Customer Updated",
            "phone": "07771111111",
            "phone2": "07882222222",
            "city": "كربلاء",
            "address": "حي الحسين",
        },
        "note": "quick edit note",
        "discount_amount": 100,
        "items": [{"product_id": new_product_id, "qty": 2, "price": 750, "sale_mode": "normal"}],
    }
    with app.test_request_context(f"/orders/quick-edit/{invoice_id}", method="POST", json=payload):
        g.tenant = TENANT_QUICK_EDIT
        session["user_id"] = employee_id
        response = quick_edit_order(invoice_id)
        assert response.get_json()["success"] is True

    with app.app_context():
        g.tenant = TENANT_QUICK_EDIT
        customer = Customer.query.get(customer_id)
        invoice = Invoice.query.get(invoice_id)
        item = OrderItem.query.filter_by(invoice_id=invoice_id).one()
        assert customer.name == "Quick Customer Updated"
        assert customer.phone == "07771111111"
        assert customer.phone2 == "07882222222"
        assert customer.city == "كربلاء"
        assert customer.address == "حي الحسين"
        assert invoice.customer_name == customer.name
        assert invoice.note == "quick edit note"
        assert invoice.discount_amount == 100
        assert invoice.total == 1400
        assert item.product_id == new_product_id
        assert item.quantity == 2
        assert item.price == 750


if __name__ == "__main__":
    test_pos_edit_customer_change_rolls_back_stock_restore()
    test_edit_keeps_existing_deferred_order_undeducted_when_policy_is_disabled()
    test_quick_edit_updates_customer_note_products_quantity_price_and_discount()
    print("pos edit rollback tests passed")
