"""Regression: generic order status updates must use accounting lifecycle logic."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = "test_orders_update_lifecycle"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_update_order_cancel_restores_stock_and_payment_ledger():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.order_item import OrderItem
    from models.product import Product
    from routes.orders import update_order

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        customer = Customer(name="Cancel Customer", phone="07730000000")
        product = Product(name="Cancelable Item", buy_price=50, sale_price=100, quantity=3, active=True)
        db.session.add_all([customer, product])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=200,
            status="تم الطلب",
            payment_status="جزئي",
            paid_amount=100,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=2,
                price=100,
                cost=50,
                total=200,
            )
        )
        db.session.commit()
        invoice_id = invoice.id
        product_id = product.id

    with app.test_request_context("/orders/update", method="POST", json={"id": invoice_id, "status": "ملغي"}):
        g.tenant = TENANT
        resp = update_order()
        data = resp.get_json()
        assert data["success"], data

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(invoice_id)
        product = Product.query.get(product_id)
        ledger = InvoicePaymentLedger.query.filter_by(invoice_id=invoice_id).one()
        assert invoice.status == "ملغي"
        assert invoice.payment_status == "ملغي"
        assert int(invoice.paid_amount or 0) == 0
        assert int(product.quantity or 0) == 5
        assert int(ledger.amount_delta or 0) == -100


if __name__ == "__main__":
    test_update_order_cancel_restores_stock_and_payment_ledger()
    print("orders update lifecycle tests passed")
