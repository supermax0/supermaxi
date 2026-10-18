from datetime import date, datetime
from pathlib import Path

from flask import Flask

from extensions import db
from models.account_transaction import AccountTransaction
from models.customer import Customer
from models.expense import Expense
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.treasury_account import TreasuryAccount
from utils.financial_report_data import _comparison_period, get_financial_report_data
from utils.treasury_calculations import get_treasury_movements


ROOT = Path(__file__).resolve().parents[1]


def _make_test_app():
    app = Flask(__name__, template_folder=str(ROOT / "templates"))
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    return app


def test_this_month_comparison_uses_same_number_of_days():
    start, end, label = _comparison_period(
        "this_month", date(2026, 8, 1), date(2026, 8, 19)
    )

    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 19)
    assert label == "الفترة المماثلة من الشهر الماضي"


def test_net_profit_and_visible_arithmetic_checks_include_all_expenses(monkeypatch):
    app = _make_test_app()

    fixed_summary = {
        "fixed_assets_book_value": 0,
        "fixed_assets_cost": 0,
        "fixed_assets_accumulated_depreciation": 0,
        "fixed_assets_depreciation_period": 50,
        "fixed_assets_active_count": 0,
    }
    savings_summary = {
        "rotating_savings_paid": 0,
        "rotating_savings_received": 0,
        "rotating_savings_liability": 0,
        "rotating_savings_asset": 0,
        "rotating_savings_fees": 25,
        "rotating_savings_active_count": 0,
    }
    monkeypatch.setattr(
        "utils.financial_report_data._fixed_assets_financial_summary",
        lambda *_args: fixed_summary,
    )
    monkeypatch.setattr(
        "utils.financial_report_data._rotating_savings_financial_summary",
        lambda *_args: savings_summary,
    )

    with app.app_context():
        db.create_all()
        cash = TreasuryAccount(
            name="الصندوق", account_type="cash", is_default=True, is_active=True
        )
        customer = Customer(name="عميل", phone="07700000000")
        product = Product(
            name="منتج",
            buy_price=400,
            sale_price=1_000,
            quantity=9,
            active=True,
        )
        db.session.add_all([cash, customer, product])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1_000,
            status="تم التوصيل",
            payment_status="مسدد",
            paid_amount=1_000,
            created_at=datetime(2026, 8, 10, 12, 0),
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add_all(
            [
                OrderItem(
                    invoice_id=invoice.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=1,
                    price=1_000,
                    cost=400,
                    total=1_000,
                ),
                Expense(
                    title="مصروف",
                    category="تشغيل",
                    amount=100,
                    expense_date=date(2026, 8, 10),
                    cash_posted=True,
                ),
            ]
        )
        db.session.commit()

        report = get_financial_report_data("custom", "2026-08-01", "2026-08-31")

        assert report["gross_profit"] == 600
        assert report["total_operating_expenses_period"] == 175
        assert report["net_profit_period"] == 425
        assert report["expense_to_revenue_pct"] == 17.5
        assert report["number_checks_passed"] == len(report["number_checks"])


def test_treasury_movements_respect_inclusive_report_period():
    app = _make_test_app()

    with app.app_context():
        db.create_all()
        cash = TreasuryAccount(
            name="الصندوق", account_type="cash", is_default=True, is_active=True
        )
        db.session.add(cash)
        db.session.flush()
        db.session.add_all(
            [
                AccountTransaction(
                    type="deposit",
                    amount=900,
                    note="قديم",
                    treasury_account_id=cash.id,
                    created_at=datetime(2026, 7, 31, 20, 59),
                ),
                AccountTransaction(
                    type="deposit",
                    amount=500,
                    note="إيداع خلال الفترة",
                    treasury_account_id=cash.id,
                    created_at=datetime(2026, 8, 1, 10, 0),
                ),
                AccountTransaction(
                    type="withdraw",
                    amount=120,
                    note="مصروف: خلال الفترة",
                    treasury_account_id=cash.id,
                    created_at=datetime(2026, 8, 31, 18, 0),
                ),
                AccountTransaction(
                    type="deposit",
                    amount=700,
                    note="لاحق",
                    treasury_account_id=cash.id,
                    created_at=datetime(2026, 9, 1, 0, 1),
                ),
            ]
        )
        db.session.commit()

        movements = get_treasury_movements(
            cash.id, date(2026, 8, 1), date(2026, 8, 31)
        )

        assert [(row["type"], row["amount"]) for row in movements] == [
            ("cash_in", 500),
            ("cash_out", 120),
        ]


def test_financial_report_template_compiles():
    app = _make_test_app()
    with app.app_context():
        app.jinja_env.get_template("reports_financial.html")
