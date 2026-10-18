"""Allow correcting payment-only ملغي shipping orders into راجع."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_return_payment_canceled_shipping_{os.getpid()}"


def _fresh_tenant_db():
    from extensions_tenant import clear_tenant_engine
    clear_tenant_engine(TENANT)
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_return_allowed_when_payment_canceled_but_status_still_shipping():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.customer import Customer
    from models.invoice import Invoice
    from utils.invoice_schema_guard import ensure_invoice_schema
    from utils.order_lifecycle import OrderLifecycleError, process_order_return
    from utils.order_status import RETURN_STATUS

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()

        customer = Customer(name="Shipping Cancelled Payment", phone="07744182624")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=19000,
            paid_amount=0,
            status="جاري الشحن",
            payment_status="ملغي",
            shipping_status="جاري الشحن",
            barcode="SHIP-CANCEL-2",
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.commit()

        already_returned, message = process_order_return(invoice, "SHIP-CANCEL-2")
        assert already_returned is False
        assert "ترجيع" in message
        assert invoice.status == RETURN_STATUS
        assert invoice.payment_status == RETURN_STATUS
        assert invoice.shipping_status == RETURN_STATUS


def test_return_still_blocked_when_status_is_canceled():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.customer import Customer
    from models.invoice import Invoice
    from utils.invoice_schema_guard import ensure_invoice_schema
    from utils.order_lifecycle import OrderLifecycleError, process_order_return

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()

        customer = Customer(name="Fully Cancelled", phone="07744182625")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            paid_amount=0,
            status="ملغي",
            payment_status="ملغي",
            barcode="FULL-CANCEL-1",
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.commit()

        try:
            process_order_return(invoice, "FULL-CANCEL-1")
            assert False, "expected OrderLifecycleError"
        except OrderLifecycleError as exc:
            assert "ملغي" in exc.message


if __name__ == "__main__":
    test_return_allowed_when_payment_canceled_but_status_still_shipping()
    test_return_still_blocked_when_status_is_canceled()
    print("ok")
