"""Tests for direct payment adjustment on invoices."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = "test_payment_adjust"

PAID = "\u0645\u0633\u062f\u062f"
PARTIAL = "\u062c\u0632\u0626\u064a"
UNPAID = "\u063a\u064a\u0631 \u0645\u0633\u062f\u062f"
SHIPPING = "\u062c\u0627\u0631\u064a \u0627\u0644\u0634\u062d\u0646"


def _fresh_tenant_db():
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_adjust_payment_sets_partial_and_full_amounts():
    _fresh_tenant_db()
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from routes.orders import adjust_payment
    from utils.cash_calculations import _effective_paid_amount

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        employee = Employee(name="Adjust Tester", username="adjust_tester", password="pw", role="admin")
        customer = Customer(name="Adjust Customer", phone="07730000111")
        db.session.add_all([employee, customer])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            total=379000,
            status=SHIPPING,
            payment_status=UNPAID,
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.commit()
        employee_id = employee.id
        invoice_id = invoice.id

    with app.test_request_context(
        "/orders/payment/adjust",
        method="POST",
        json={"id": invoice_id, "payment": PARTIAL, "paid_amount": 210000},
    ):
        g.tenant = TENANT
        session["user_id"] = employee_id
        resp = app.make_response(adjust_payment())
        status_code = resp.status_code
        data = resp.get_json()
        assert status_code == 200
        assert data["success"] is True
        assert data["order"]["payment_status"] == PARTIAL
        assert data["order"]["paid_amount"] == 210000
        assert data["order"]["remaining"] == 169000

    with app.test_request_context(
        "/orders/payment/adjust",
        method="POST",
        json={"id": invoice_id, "payment": PAID},
    ):
        g.tenant = TENANT
        session["user_id"] = employee_id
        resp = app.make_response(adjust_payment())
        status_code = resp.status_code
        data = resp.get_json()
        assert status_code == 200
        assert data["success"] is True
        assert data["order"]["payment_status"] == PAID
        assert data["order"]["paid_amount"] == 379000
        assert data["order"]["remaining"] == 0

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(invoice_id)
        assert _effective_paid_amount(invoice) == 379000


def test_adjust_payment_rejects_returned_invoice():
    _fresh_tenant_db()
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from routes.orders import adjust_payment

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        employee = Employee(name="Adjust Tester 2", username="adjust_tester_2", password="pw", role="admin")
        customer = Customer(name="Returned Customer", phone="07730000112")
        db.session.add_all([employee, customer])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            total=100000,
            status="\u0631\u0627\u062c\u0639",
            payment_status="\u0631\u0627\u062c\u0639",
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.commit()
        employee_id = employee.id
        invoice_id = invoice.id

    with app.test_request_context(
        "/orders/payment/adjust",
        method="POST",
        json={"id": invoice_id, "payment": PARTIAL, "paid_amount": 50000},
    ):
        g.tenant = TENANT
        session["user_id"] = employee_id
        resp, status_code = adjust_payment()
        data = resp.get_json()
        assert status_code == 400
        assert data["success"] is False
