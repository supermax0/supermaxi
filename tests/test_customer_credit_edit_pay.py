import os
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_customer_credit_edit_pay_{os.getpid()}"


def test_update_opening_plan_amount_and_backdated_payment():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        try:
            db_file.unlink()
        except PermissionError:
            pass

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.customer import Customer
    from models.customer_credit import CustomerCreditPayment, CustomerCreditPlan, CustomerInstallment
    from utils.customer_credit_service import (
        allocate_payment_fifo,
        create_credit_plan,
        customer_credit_summary,
        update_credit_plan,
    )
    from utils.invoice_schema_guard import ensure_invoice_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()

        customer = Customer(name="Credit Edit Customer", phone="07700000991")
        db.session.add(customer)
        db.session.flush()

        plan = create_credit_plan(
            customer_id=customer.id,
            entry_type="opening",
            total_amount=525000,
            installments_count=1,
            first_due_date=date.today(),
            interval="monthly",
            description="رصيد افتتاحي",
        )
        db.session.commit()

        update_credit_plan(plan.id, description="رصيد معدل", total_amount=600000)
        db.session.commit()

        plan = CustomerCreditPlan.query.get(plan.id)
        assert plan.description == "رصيد معدل"
        assert plan.total_amount == 600000
        assert plan.remaining == 600000
        inst = CustomerInstallment.query.filter_by(plan_id=plan.id).one()
        assert inst.amount == 600000

        pay_day = date.today() - timedelta(days=3)
        payments, applied = allocate_payment_fifo(
            customer.id,
            100000,
            note="دفعة قديمة",
            payment_date=pay_day,
        )
        db.session.commit()

        assert applied == 100000
        assert len(payments) == 1
        assert payments[0].created_at.date() == pay_day

        summary = customer_credit_summary(customer.id)
        assert summary["total_debt"] == 600000
        assert summary["total_paid"] == 100000
        assert summary["remaining"] == 500000

        stored = CustomerCreditPayment.query.filter_by(customer_id=customer.id).one()
        assert stored.created_at.date() == pay_day
        assert stored.note == "دفعة قديمة"

        try:
            update_credit_plan(plan.id, total_amount=50000)
            assert False, "expected ValueError for amount below paid"
        except ValueError as exc:
            assert "أقل من المسدد" in str(exc)

        db.session.remove()


def test_products_plan_amount_locked():
    tenant = f"{TENANT}_products"
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        try:
            db_file.unlink()
        except PermissionError:
            pass

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.customer import Customer
    from models.invoice import Invoice
    from utils.customer_credit_service import create_credit_plan, update_credit_plan
    from utils.invoice_schema_guard import ensure_invoice_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_invoice_schema()

        customer = Customer(name="Products Lock Customer", phone="07700000992")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=200000,
            paid_amount=0,
            status="تم الطلب",
            payment_status="غير مسدد",
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        plan = create_credit_plan(
            customer_id=customer.id,
            entry_type="products",
            total_amount=200000,
            installments_count=1,
            first_due_date=date.today(),
            interval="monthly",
            invoice_id=invoice.id,
            description=f"بيع آجل — طلب #{invoice.id}",
        )
        db.session.commit()

        update_credit_plan(plan.id, description="وصف فقط")
        db.session.commit()
        assert plan.description == "وصف فقط"

        try:
            update_credit_plan(plan.id, total_amount=250000)
            assert False, "expected ValueError for locked products amount"
        except ValueError as exc:
            assert "فاتورة" in str(exc)

        db.session.remove()
