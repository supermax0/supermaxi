"""Regression tests for paid amount accounting rules."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = "test_payment_effective_amount"

PAID = "\u0645\u0633\u062f\u062f"
PARTIAL = "\u062c\u0632\u0626\u064a"
UNPAID = "\u063a\u064a\u0631 \u0645\u0633\u062f\u062f"
DELIVERED = "\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644"
ORDERED = "\u062a\u0645 \u0627\u0644\u0637\u0644\u0628"


def _fresh_tenant_db():
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_effective_paid_amount_respects_explicit_payment_status():
    from utils.cash_calculations import _effective_paid_amount

    assert _effective_paid_amount(
        SimpleNamespace(total=1000, status=DELIVERED, payment_status=UNPAID, paid_amount=0)
    ) == 0
    assert _effective_paid_amount(
        SimpleNamespace(total=1000, status=DELIVERED, payment_status=PARTIAL, paid_amount=350)
    ) == 350
    assert _effective_paid_amount(
        SimpleNamespace(total=1000, status=DELIVERED, payment_status=PAID, paid_amount=1000)
    ) == 1000
    assert _effective_paid_amount(
        SimpleNamespace(total=1000, status=DELIVERED, payment_status=None, paid_amount=0)
    ) == 1000


def test_negative_partial_payment_is_rejected_without_changing_invoice():
    _fresh_tenant_db()
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from routes.orders import payment

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        employee = Employee(name="Payment Tester", username="pay_tester", password="pw", role="admin")
        customer = Customer(name="Payment Customer", phone="07730000000")
        db.session.add_all([employee, customer])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            total=1000,
            status=ORDERED,
            payment_status=UNPAID,
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.commit()
        employee_id = employee.id
        invoice_id = invoice.id

    with app.test_request_context(
        "/orders/payment",
        method="POST",
        json={"id": invoice_id, "payment": PARTIAL, "paid_amount": -100},
    ):
        g.tenant = TENANT
        session["user_id"] = employee_id
        resp, status_code = payment()
        data = resp.get_json()
        assert status_code == 400
        assert data["success"] is False

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(invoice_id)
        assert invoice.payment_status == UNPAID
        assert int(invoice.paid_amount or 0) == 0


def test_default_cash_counts_only_legacy_delivered_without_explicit_unpaid_status():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from sqlalchemy import text
    from utils.cash_calculations import calculate_cash_balance

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        customer = Customer(name="Legacy Cash Customer", phone="07730000001")
        db.session.add(customer)
        db.session.flush()
        legacy_invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            status=DELIVERED,
            paid_amount=0,
        )
        explicit_unpaid_invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=2000,
            status=DELIVERED,
            payment_status=UNPAID,
            paid_amount=0,
        )
        db.session.add_all([legacy_invoice, explicit_unpaid_invoice])
        db.session.flush()
        db.session.execute(
            text("UPDATE invoice SET payment_status = NULL WHERE id = :invoice_id"),
            {"invoice_id": legacy_invoice.id},
        )
        db.session.commit()

        assert calculate_cash_balance() == 1000


def test_paid_sales_and_cogs_ignore_delivered_explicit_unpaid_orders():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from sqlalchemy import text
    from utils.accounting_calculations import calculate_paid_cogs, calculate_paid_sales

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        customer = Customer(name="Accounting Customer", phone="07730000002")
        product = Product(name="Accounting Product", buy_price=100, sale_price=1000, quantity=10)
        db.session.add_all([customer, product])
        db.session.flush()

        legacy_paid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            status=DELIVERED,
            paid_amount=0,
        )
        explicit_unpaid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=2000,
            status=DELIVERED,
            payment_status=UNPAID,
            paid_amount=0,
        )
        partial = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=3000,
            status=DELIVERED,
            payment_status=PARTIAL,
            paid_amount=400,
        )
        paid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=500,
            status=DELIVERED,
            payment_status=PAID,
            paid_amount=500,
        )
        db.session.add_all([legacy_paid, explicit_unpaid, partial, paid])
        db.session.flush()
        db.session.execute(
            text("UPDATE invoice SET payment_status = NULL WHERE id = :invoice_id"),
            {"invoice_id": legacy_paid.id},
        )
        db.session.add_all(
            [
                OrderItem(
                    invoice_id=legacy_paid.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=1,
                    price=1000,
                    cost=100,
                    total=1000,
                ),
                OrderItem(
                    invoice_id=explicit_unpaid.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=1,
                    price=2000,
                    cost=200,
                    total=2000,
                ),
                OrderItem(
                    invoice_id=partial.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=1,
                    price=3000,
                    cost=1500,
                    total=3000,
                ),
                OrderItem(
                    invoice_id=paid.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=1,
                    price=500,
                    cost=250,
                    total=500,
                ),
            ]
        )
        db.session.commit()

        assert calculate_paid_sales() == 1900
        assert calculate_paid_cogs() == 550


def test_financial_report_cash_sales_respects_explicit_payment_status():
    _fresh_tenant_db()
    from datetime import datetime

    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from sqlalchemy import text
    from utils.financial_report_data import get_financial_report_data

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        created_at = datetime(2026, 7, 5, 10, 0, 0)
        customer = Customer(name="Financial Customer", phone="07730000003")
        product = Product(name="Financial Product", buy_price=100, sale_price=1000, quantity=10)
        db.session.add_all([customer, product])
        db.session.flush()

        legacy_paid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            status=DELIVERED,
            paid_amount=0,
            created_at=created_at,
        )
        explicit_unpaid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=2000,
            status=DELIVERED,
            payment_status=UNPAID,
            paid_amount=0,
            created_at=created_at,
        )
        partial = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=3000,
            status=DELIVERED,
            payment_status=PARTIAL,
            paid_amount=400,
            created_at=created_at,
        )
        paid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=500,
            status=DELIVERED,
            payment_status=PAID,
            paid_amount=500,
            created_at=created_at,
        )
        db.session.add_all([legacy_paid, explicit_unpaid, partial, paid])
        db.session.flush()
        db.session.execute(
            text("UPDATE invoice SET payment_status = NULL WHERE id = :invoice_id"),
            {"invoice_id": legacy_paid.id},
        )
        for invoice, cost in (
            (legacy_paid, 100),
            (explicit_unpaid, 200),
            (partial, 1500),
            (paid, 250),
        ):
            db.session.add(
                OrderItem(
                    invoice_id=invoice.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=1,
                    price=invoice.total,
                    cost=cost,
                    total=invoice.total,
                )
            )
        db.session.commit()

        report = get_financial_report_data(
            "custom",
            custom_date_from="2026-07-01",
            custom_date_to="2026-07-31",
        )

        assert report["total_revenue"] == 6500
        assert report["cash_sales"] == 1900
        assert report["credit_sales"] == 4600
        assert report["accounts_receivable"] == 4600


def test_period_profit_collection_profit_and_dashboard_keep_legacy_null_paid_orders():
    _fresh_tenant_db()
    from datetime import date, datetime

    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from sqlalchemy import text
    from utils.executive_dashboard_data import get_credit_executive_summary
    from utils.payment_ledger import net_profit_for_collection_calendar_day
    from utils.period_net_profit import net_profit_for_range

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        day = date(2026, 7, 10)
        created_at = datetime(2026, 7, 10, 10, 0, 0)
        customer = Customer(name="Dashboard Customer", phone="07730000004")
        product = Product(name="Dashboard Product", buy_price=100, sale_price=1000, quantity=10)
        db.session.add_all([customer, product])
        db.session.flush()

        legacy_paid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            status=DELIVERED,
            paid_amount=0,
            created_at=created_at,
        )
        explicit_unpaid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=2000,
            status=DELIVERED,
            payment_status=UNPAID,
            paid_amount=0,
            created_at=created_at,
        )
        partial = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=3000,
            status=DELIVERED,
            payment_status=PARTIAL,
            paid_amount=400,
            created_at=created_at,
        )
        paid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=500,
            status=DELIVERED,
            payment_status=PAID,
            paid_amount=500,
            created_at=created_at,
        )
        canceled_payment = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=800,
            status=DELIVERED,
            payment_status="\u0645\u0644\u063a\u064a",
            paid_amount=800,
            created_at=created_at,
        )
        returned_payment = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=700,
            status=DELIVERED,
            payment_status="\u0631\u0627\u062c\u0639",
            paid_amount=700,
            created_at=created_at,
        )
        db.session.add_all(
            [legacy_paid, explicit_unpaid, partial, paid, canceled_payment, returned_payment]
        )
        db.session.flush()
        db.session.execute(
            text("UPDATE invoice SET payment_status = NULL WHERE id = :invoice_id"),
            {"invoice_id": legacy_paid.id},
        )
        for invoice, cost in (
            (legacy_paid, 100),
            (explicit_unpaid, 200),
            (partial, 1500),
            (paid, 250),
            (canceled_payment, 80),
            (returned_payment, 70),
        ):
            db.session.add(
                OrderItem(
                    invoice_id=invoice.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=1,
                    price=invoice.total,
                    cost=cost,
                    total=invoice.total,
                )
            )
        db.session.commit()

        assert net_profit_for_range(day, day) == 1350
        assert net_profit_for_collection_calendar_day(day) == 1350

        summary = get_credit_executive_summary(today=day)
        assert summary["cash_sales_today"] == 1900
        assert summary["credit_sales_today"] == 4600


if __name__ == "__main__":
    test_effective_paid_amount_respects_explicit_payment_status()
    test_negative_partial_payment_is_rejected_without_changing_invoice()
    test_default_cash_counts_only_legacy_delivered_without_explicit_unpaid_status()
    test_paid_sales_and_cogs_ignore_delivered_explicit_unpaid_orders()
    test_financial_report_cash_sales_respects_explicit_payment_status()
    test_period_profit_collection_profit_and_dashboard_keep_legacy_null_paid_orders()
    print("payment effective amount tests passed")
