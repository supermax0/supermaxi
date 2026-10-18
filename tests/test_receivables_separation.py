"""Regression tests for separating customer and shipping receivables."""

from flask import Flask

from extensions import db
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan
from models.delivery_agent import DeliveryAgent  # noqa: F401 - registers referenced table
from models.invoice import Invoice
from models.page import Page  # noqa: F401 - registers referenced table
from models.shipping import ShippingCompany
from models.user import User  # noqa: F401 - registers referenced table
from utils.accounting_calculations import (
    calculate_accounts_receivable,
    calculate_shipping_due,
)
from utils.financial_report_data import get_financial_report_data


def _make_test_app():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    return app


def test_financial_report_counts_customer_and_shipping_receivables_once():
    app = _make_test_app()

    with app.app_context():
        db.create_all()

        customer = Customer(name="Receivables Customer", phone="07700000000")
        shipping_company = ShippingCompany(
            name="Receivables Shipping",
            opening_balance=3_000,
        )
        db.session.add_all([customer, shipping_company])
        db.session.flush()

        db.session.add_all(
            [
                Invoice(
                    customer_id=customer.id,
                    customer_name=customer.name,
                    total=40_000,
                    status="تم الطلب",
                    payment_status="غير مسدد",
                ),
                Invoice(
                    customer_id=customer.id,
                    customer_name=customer.name,
                    shipping_company_id=shipping_company.id,
                    total=60_000,
                    status="تم الطلب",
                    payment_status="غير مسدد",
                ),
                CustomerCreditPlan(
                    customer_id=customer.id,
                    entry_type="opening",
                    total_amount=7_000,
                    paid_amount=0,
                    installments_count=1,
                ),
            ]
        )
        db.session.commit()

        assert calculate_accounts_receivable() == 40_000
        assert calculate_shipping_due() == 63_000

        report = get_financial_report_data("this_month")
        assert report["customer_receivables"] == 47_000
        assert report["shipping_orders_receivable"] == 60_000
        assert report["shipping_opening_balance"] == 3_000
        assert report["shipping_receivables"] == 63_000
        assert report["accounts_receivable"] == 110_000
        assert report["total_assets"] == 110_000
