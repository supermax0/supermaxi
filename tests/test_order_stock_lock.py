import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_order_stock_lock_{os.getpid()}"
TENANT_GUARD = f"test_order_stock_lock_guard_{os.getpid()}"


def _fresh_tenant_db(tenant=TENANT):
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_pos_short_stock_creates_deferred_pending_order_without_stock_movement():
    _fresh_tenant_db()
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.product import Product
    from routes.pos import create_order
    from utils.accounting_calculations import calculate_total_sales_for_display
    from utils.branch_migration import ensure_branch_schema
    from utils.inventory_movements import get_product_inventory_movements
    from utils.invoice_schema_guard import ensure_invoice_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()
        ensure_branch_schema()

        customer = Customer(name="Stock Lock Customer", phone="07700000001")
        employee = Employee(
            name="Stock Lock Cashier",
            username="stock-lock-cashier",
            password="x",
            role="cashier",
            is_active=True,
        )
        product = Product(name="Locked POS Item", buy_price=100, sale_price=500, quantity=0, active=True)
        db.session.add_all([customer, employee, product])
        db.session.commit()
        customer_id = customer.id
        employee_id = employee.id
        product_id = product.id

    payload = {
        "customer_id": customer_id,
        "items": [{"product_id": product_id, "qty": 1, "price": 500}],
    }
    with app.test_request_context("/pos/create-order", method="POST", json=payload):
        g.tenant = TENANT
        session["user_id"] = employee_id
        resp = create_order()
        status = 200
        if isinstance(resp, tuple):
            resp, status = resp
        data = resp.get_json()
        assert status == 200
        assert data["success"] is True
        assert data["stock_locked"] is False
        invoice_id = data["invoice_id"]

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(invoice_id)
        product = Product.query.get(product_id)
        assert invoice.is_stock_locked is False
        assert invoice.stock_is_deducted is False
        assert invoice.payment_status == "غير مسدد"
        assert int(product.quantity or 0) == 0
        movements = get_product_inventory_movements(product_id)
        assert not [m for m in movements if m["type"] == "sale" and m["reference_id"] == invoice_id]


def test_deferred_order_deducts_when_stock_arrives_and_status_advances():
    from app import app
    from flask import g
    from extensions import db
    from models.invoice import Invoice
    from models.product import Product
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import receive_stock
    from utils.order_stock_policy import ensure_stock_for_transition

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.filter_by(stock_is_deducted=False, status="تم الطلب").order_by(Invoice.id.asc()).first()
        assert invoice is not None
        product_id = invoice.items[0].product_id
        branch = get_default_branch()
        assert branch is not None

        receive_stock(branch.id, product_id, 1)
        db.session.commit()

        deducted = ensure_stock_for_transition(invoice, target_status="معباة")
        invoice.status = "معباة"
        db.session.commit()

        invoice = Invoice.query.get(invoice.id)
        product = Product.query.get(product_id)
        assert deducted is True
        assert invoice.is_stock_locked is False
        assert invoice.stock_is_deducted is True
        assert invoice.items[0].fulfillment_branch_id == branch.id
        assert int(product.quantity or 0) == 0


def test_locked_order_payment_endpoint_is_blocked():
    _fresh_tenant_db(TENANT_GUARD)
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from routes.orders import payment
    from utils.invoice_schema_guard import ensure_invoice_schema

    with app.app_context():
        g.tenant = TENANT_GUARD
        init_tenant_db(TENANT_GUARD)
        ensure_invoice_schema()
        customer = Customer(name="Guard Customer", phone="07700000002")
        employee = Employee(name="Guard Cashier", username="guard-cashier", password="x", role="admin", is_active=True)
        product = Product(name="Guard Item", buy_price=100, sale_price=500, quantity=0, active=True)
        db.session.add_all([customer, employee, product])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            total=500,
            status="تم الطلب",
            payment_status="غير مسدد",
            is_stock_locked=True,
            stock_lock_reason="Guard Item: المتوفر 0 والمطلوب 1",
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=1,
                price=500,
                cost=100,
                total=500,
            )
        )
        db.session.commit()
        invoice_id = invoice.id
        employee_id = employee.id

    with app.test_request_context("/orders/payment", method="POST", json={"id": invoice_id, "payment": "مسدد"}):
        g.tenant = TENANT_GUARD
        session["user_id"] = employee_id
        resp, status = payment()
        data = resp.get_json()
        assert status == 423
        assert data["success"] is False
        assert data["locked"] is True
