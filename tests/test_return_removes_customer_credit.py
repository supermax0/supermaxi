import os
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_return_removes_customer_credit_{os.getpid()}"


def test_return_removes_linked_plan_and_installments_but_keeps_payment_history():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.customer import Customer
    from models.customer_credit import CustomerCreditPayment, CustomerCreditPlan, CustomerInstallment
    from models.invoice import Invoice
    from utils.customer_credit_service import create_credit_plan
    from utils.invoice_schema_guard import ensure_invoice_schema
    from utils.order_lifecycle import process_order_return

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()

        customer = Customer(name="Installment Return Customer", phone="07700000992")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            paid_amount=500,
            status="تم التوصيل",
            payment_status="جزئي",
            barcode="RETURN-CREDIT",
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        plan = create_credit_plan(
            customer_id=customer.id,
            entry_type="products",
            total_amount=1000,
            installments_count=2,
            first_due_date=date.today(),
            interval="monthly",
            invoice_id=invoice.id,
        )
        db.session.flush()
        installment = plan.installments[0]
        installment.paid_amount = 500
        installment.status = "paid"
        plan.paid_amount = 500
        payment = CustomerCreditPayment(
            customer_id=customer.id,
            plan_id=plan.id,
            installment_id=installment.id,
            amount=500,
        )
        db.session.add(payment)
        db.session.commit()
        payment_id = payment.id

        already_returned, _message = process_order_return(invoice, "RETURN-CREDIT")
        db.session.commit()

        assert already_returned is False
        assert CustomerCreditPlan.query.filter_by(invoice_id=invoice.id).count() == 0
        assert CustomerInstallment.query.count() == 0
        kept_payment = db.session.get(CustomerCreditPayment, payment_id)
        assert kept_payment is not None
        assert kept_payment.plan_id is None
        assert kept_payment.installment_id is None
        assert f"#{invoice.id}" in kept_payment.note
