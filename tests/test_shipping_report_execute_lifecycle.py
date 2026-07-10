"""Regression: executing shipping reports must use the full cancel/delay accounting lifecycle."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT_CANCEL = f"test_shipping_report_cancel_lifecycle_{os.getpid()}"
TENANT_DELAY = f"test_shipping_report_delay_lifecycle_{os.getpid()}"


def _fresh_tenant_db(tenant: str):
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_shipping_report_cancel_reverses_payment_and_restores_color_stock():
    _fresh_tenant_db(TENANT_CANCEL)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.order_item import OrderItem
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from models.shipping_report import ShippingReport
    from utils.payment_ledger import append_payment_ledger_delta
    from utils.shipping_report_execute import execute_shipping_report

    with app.app_context():
        g.tenant = TENANT_CANCEL
        init_tenant_db(TENANT_CANCEL)

        customer = Customer(name="Report Customer", phone="07740000000")
        product = Product(name="Report Color Item", buy_price=300, sale_price=1000, quantity=0, active=True)
        db.session.add_all([customer, product])
        db.session.flush()
        db.session.add(ProductColorVariant(product_id=product.id, color_name="red", quantity=0))

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            paid_amount=1000,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=1,
                price=1000,
                cost=300,
                total=1000,
                variant_color="red",
            )
        )
        append_payment_ledger_delta(invoice.id, 1000)
        report = ShippingReport(
            report_number="SR-CANCEL-LIFECYCLE",
            shipping_company_name="Courier",
            orders_data=json.dumps([{"id": invoice.id}]),
            total_amount=1000,
            orders_count=1,
            order_status_selections=json.dumps({str(invoice.id): "\u0645\u0644\u063a\u064a"}),
        )
        db.session.add(report)
        db.session.commit()

        result = execute_shipping_report(report)
        assert result["success"], result

        db.session.refresh(invoice)
        db.session.refresh(product)
        color = ProductColorVariant.query.filter_by(product_id=product.id, color_name="red").first()
        ledger_amounts = [
            int(row.amount_delta)
            for row in InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).order_by(InvoicePaymentLedger.id).all()
        ]

        assert invoice.status == "\u0645\u0644\u063a\u064a"
        assert invoice.payment_status == "\u0645\u0644\u063a\u064a"
        assert int(invoice.paid_amount or 0) == 0
        assert int(product.quantity or 0) == 1
        assert int(color.quantity or 0) == 1
        assert ledger_amounts == [1000, -1000]


def test_shipping_report_delay_reverses_previous_payment():
    _fresh_tenant_db(TENANT_DELAY)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.shipping_report import ShippingReport
    from utils.payment_ledger import append_payment_ledger_delta
    from utils.shipping_report_execute import execute_shipping_report

    with app.app_context():
        g.tenant = TENANT_DELAY
        init_tenant_db(TENANT_DELAY)

        customer = Customer(name="Delay Customer", phone="07750000000")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=750,
            paid_amount=750,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
        )
        db.session.add(invoice)
        db.session.flush()
        append_payment_ledger_delta(invoice.id, 750)
        report = ShippingReport(
            report_number="SR-DELAY-LIFECYCLE",
            shipping_company_name="Courier",
            orders_data=json.dumps([{"id": invoice.id}]),
            total_amount=750,
            orders_count=1,
            order_status_selections=json.dumps({str(invoice.id): "\u0645\u0624\u062c\u0644"}),
        )
        db.session.add(report)
        db.session.commit()

        result = execute_shipping_report(report)
        assert result["success"], result

        db.session.refresh(invoice)
        ledger_amounts = [
            int(row.amount_delta)
            for row in InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).order_by(InvoicePaymentLedger.id).all()
        ]

        assert invoice.status == "\u062a\u0645 \u0627\u0644\u0637\u0644\u0628"
        assert invoice.payment_status == "\u063a\u064a\u0631 \u0645\u0633\u062f\u062f"
        assert int(invoice.paid_amount or 0) == 0
        assert ledger_amounts == [750, -750]


if __name__ == "__main__":
    test_shipping_report_cancel_reverses_payment_and_restores_color_stock()
    test_shipping_report_delay_reverses_previous_payment()
    print("shipping report lifecycle tests passed")
