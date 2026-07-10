"""Regression tests for report return/payment status filters."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = "test_reports_return_filters"

RETURNED = "\u0631\u0627\u062c\u0639"
ORDERED = "\u062a\u0645 \u0627\u0644\u0637\u0644\u0628"
UNPAID = "\u063a\u064a\u0631 \u0645\u0633\u062f\u062f"


def _fresh_tenant_db():
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_returned_report_includes_returned_payment_status():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from routes.reports import returned_report

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        customer = Customer(name="Returned Customer", phone="07740000000")
        db.session.add(customer)
        db.session.flush()
        db.session.add(
            Invoice(
                customer_id=customer.id,
                customer_name=customer.name,
                total=1000,
                status=ORDERED,
                payment_status=RETURNED,
                paid_amount=0,
            )
        )
        db.session.commit()

    with app.test_request_context("/reports/returned"):
        g.tenant = TENANT
        response = returned_report()
        rows = response.get_json()
        assert len(rows) == 1


def test_shipping_report_excludes_returned_payment_status():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.shipping import ShippingCompany
    from routes.reports import shipping_report

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        customer = Customer(name="Shipping Return Customer", phone="07740000001")
        company = ShippingCompany(name="Return Filter Shipping")
        db.session.add_all([customer, company])
        db.session.flush()
        db.session.add(
            Invoice(
                customer_id=customer.id,
                customer_name=customer.name,
                shipping_company_id=company.id,
                total=1000,
                status=ORDERED,
                payment_status=RETURNED,
                paid_amount=0,
            )
        )
        db.session.commit()

    with app.test_request_context("/reports/shipping"):
        g.tenant = TENANT
        response = shipping_report()
        rows = response.get_json()
        assert len(rows) == 1
        assert rows[0]["\u0627\u0644\u0645\u0633\u062a\u062d\u0642"] == 0


if __name__ == "__main__":
    test_returned_report_includes_returned_payment_status()
    test_shipping_report_excludes_returned_payment_status()
    print("report return filter tests passed")
