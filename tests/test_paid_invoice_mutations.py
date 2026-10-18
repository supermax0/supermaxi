"""Paid invoice edit/delete safety switch and reconciliation."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_paid_invoice_edit_{os.getpid()}"


def _fresh_tenant_db():
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_paid_edit_requires_switch_then_reconciles_stock_and_collection():
    _fresh_tenant_db()
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.order_item import OrderItem
    from models.product import Product
    from routes.pos import create_order
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import get_branch_stock, set_branch_stock
    from utils.invoice_mutation_policy import set_paid_invoice_mutations_enabled
    from utils.payment_ledger import append_payment_ledger_delta

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        branch = get_default_branch()
        customer = Customer(
            name="Paid Edit Customer",
            phone="07754000000",
            branch_id=branch.id,
        )
        employee = Employee(
            name="Paid Edit Cashier",
            username="paid-edit-cashier",
            password="x",
            role="cashier",
            is_active=True,
            branch_id=branch.id,
        )
        product = Product(
            name="Paid Edit Item",
            buy_price=100,
            sale_price=500,
            quantity=0,
            active=True,
            branch_id=branch.id,
        )
        db.session.add_all([customer, employee, product])
        db.session.flush()
        set_branch_stock(branch.id, product.id, 8)
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            branch_id=branch.id,
            total=1000,
            status="تم التوصيل",
            payment_status="مسدد",
            paid_amount=1000,
            stock_is_deducted=True,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=2,
            price=500,
            cost=100,
            total=1000,
            fulfillment_branch_id=branch.id,
        ))
        append_payment_ledger_delta(invoice.id, 1000)
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
        g.tenant = TENANT
        session["user_id"] = employee_id
        response, status = create_order()
        assert status == 403
        assert response.get_json()["feature_disabled"] is True

    with app.app_context():
        g.tenant = TENANT
        assert get_branch_stock(branch_id, product_id) == 8
        assert OrderItem.query.filter_by(invoice_id=invoice_id).count() == 1
        set_paid_invoice_mutations_enabled(True)

    with app.test_request_context("/pos/create-order", method="POST", json=payload):
        g.tenant = TENANT
        session["user_id"] = employee_id
        response = create_order()
        assert response.get_json()["success"] is True

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(invoice_id)
        assert invoice.total == 500
        assert invoice.paid_amount == 500
        assert invoice.payment_status == "مسدد"
        assert OrderItem.query.filter_by(invoice_id=invoice_id).one().quantity == 1
        assert get_branch_stock(branch_id, product_id) == 9
        assert sum(
            int(row.amount_delta or 0)
            for row in InvoicePaymentLedger.query.filter_by(invoice_id=invoice_id).all()
        ) == 500


if __name__ == "__main__":
    test_paid_edit_requires_switch_then_reconciles_stock_and_collection()
    print("paid invoice mutation tests passed")
