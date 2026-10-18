import os
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_cancel_removes_customer_credit_{os.getpid()}"


def test_cancel_removes_linked_plan_and_installments():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.customer import Customer
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment
    from models.invoice import Invoice
    from utils.customer_credit_service import create_credit_plan
    from utils.invoice_schema_guard import ensure_invoice_schema
    from utils.order_lifecycle import process_order_cancel

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()

        customer = Customer(name="Installment Cancel Customer", phone="07700000993")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=567000,
            paid_amount=0,
            status="تم الطلب",
            payment_status="غير مسدد",
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        create_credit_plan(
            customer_id=customer.id,
            entry_type="products",
            total_amount=567000,
            installments_count=1,
            first_due_date=date.today(),
            interval="monthly",
            invoice_id=invoice.id,
            description=f"بيع آجل — طلب #{invoice.id}",
        )
        db.session.commit()

        assert CustomerCreditPlan.query.filter_by(invoice_id=invoice.id).count() == 1

        process_order_cancel(invoice)
        db.session.commit()

        assert invoice.status == "ملغي"
        assert CustomerCreditPlan.query.filter_by(invoice_id=invoice.id).count() == 0
        assert CustomerInstallment.query.count() == 0


def test_cleanup_voided_invoice_credit_plans_heals_orphan_after_cancel():
    db_file = ROOT / "tenants" / f"{TENANT}_orphan.db"
    if db_file.exists():
        db_file.unlink()

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.customer import Customer
    from models.customer_credit import CustomerCreditPlan
    from models.invoice import Invoice
    from utils.customer_credit_service import (
        cleanup_voided_invoice_credit_plans,
        create_credit_plan,
    )
    from utils.invoice_schema_guard import ensure_invoice_schema

    with app.app_context():
        g.tenant = f"{TENANT}_orphan"
        init_tenant_db(f"{TENANT}_orphan")
        ensure_invoice_schema()

        customer = Customer(name="Orphan Credit Customer", phone="07700000994")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            paid_amount=0,
            status="ملغي",
            payment_status="ملغي",
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        create_credit_plan(
            customer_id=customer.id,
            entry_type="products",
            total_amount=1000,
            installments_count=1,
            first_due_date=date.today(),
            interval="monthly",
            invoice_id=invoice.id,
        )
        db.session.commit()

        removed = cleanup_voided_invoice_credit_plans(customer.id)
        db.session.commit()

        assert removed == 1
        assert CustomerCreditPlan.query.filter_by(invoice_id=invoice.id).count() == 0
