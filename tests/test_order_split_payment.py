"""Split order collections must be posted to their actual treasury accounts."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_order_split_payment_{os.getpid()}"

PAID = "\u0645\u0633\u062f\u062f"
PARTIAL = "\u062c\u0632\u0626\u064a"
UNPAID = "\u063a\u064a\u0631 \u0645\u0633\u062f\u062f"
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


def _response(result):
    if isinstance(result, tuple):
        return result[0].get_json(), result[1]
    return result.get_json(), result.status_code


def test_full_order_payment_can_be_split_between_cash_and_bank():
    _fresh_tenant_db()
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.treasury_account import TreasuryAccount
    from routes.orders import payment
    from utils.payment_ledger import append_payment_ledger_delta
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        cash = get_default_cash_account()
        bank = TreasuryAccount(
            name="Split Payment Bank",
            account_type="bank",
            is_active=True,
        )
        employee = Employee(
            name="Split Payment Tester",
            username=f"split_payment_{os.getpid()}",
            password="pw",
            role="admin",
        )
        customer = Customer(name="Split Customer", phone="07731111111")
        db.session.add_all([bank, employee, customer])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            total=530000,
            status=ORDERED,
            payment_status=UNPAID,
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.commit()
        ids = {
            "cash": cash.id,
            "bank": bank.id,
            "employee": employee.id,
            "invoice": invoice.id,
        }

    with app.test_request_context(
        "/orders/payment",
        method="POST",
        json={
            "id": ids["invoice"],
            "payment": PAID,
            "delivery_fee": 0,
            "payment_allocations": [
                {"treasury_account_id": ids["cash"], "amount": 230000},
                {"treasury_account_id": ids["bank"], "amount": 300000},
            ],
        },
    ):
        g.tenant = TENANT
        session["user_id"] = ids["employee"]
        data, status = _response(payment())
        assert status == 200, data
        assert data["success"] is True

    with app.app_context():
        g.tenant = TENANT
        rows = (
            InvoicePaymentLedger.query.filter_by(invoice_id=ids["invoice"])
            .order_by(InvoicePaymentLedger.id)
            .all()
        )
        assert [
            (row.treasury_account_id, row.amount_delta)
            for row in rows
        ] == [
            (ids["cash"], 230000),
            (ids["bank"], 300000),
        ]
        assert calculate_treasury_balance(ids["cash"]) == 230000
        assert calculate_treasury_balance(ids["bank"]) == 300000

        append_payment_ledger_delta(ids["invoice"], -530000)
        db.session.commit()
        assert calculate_treasury_balance(ids["cash"]) == 0
        assert calculate_treasury_balance(ids["bank"]) == 0


def test_split_payment_rejects_a_total_that_does_not_match_due():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.treasury_account import TreasuryAccount
    from routes.orders import payment
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        cash = get_default_cash_account()
        bank = TreasuryAccount(name="Mismatch Bank", account_type="bank", is_active=True)
        customer = Customer(name="Mismatch Customer", phone="07732222222")
        db.session.add_all([bank, customer])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            status=ORDERED,
            payment_status=UNPAID,
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.commit()
        ids = {"cash": cash.id, "bank": bank.id, "invoice": invoice.id}

    with app.test_request_context(
        "/orders/payment",
        method="POST",
        json={
            "id": ids["invoice"],
            "payment": PAID,
            "payment_allocations": [
                {"treasury_account_id": ids["cash"], "amount": 400},
                {"treasury_account_id": ids["bank"], "amount": 500},
            ],
        },
    ):
        g.tenant = TENANT
        data, status = _response(payment())
        assert status == 400
        assert data["success"] is False
        assert "1,000" in data["error"]

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(ids["invoice"])
        assert invoice.payment_status == UNPAID
        assert int(invoice.paid_amount or 0) == 0


def test_partial_order_payment_records_accounts_and_keeps_delivery_fee_until_completion():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.expense import Expense
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.treasury_account import TreasuryAccount
    from routes.orders import payment
    from utils.order_shipping import get_shipping_fee_from_invoice
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        cash = get_default_cash_account()
        bank = TreasuryAccount(name="Partial Payment Bank", account_type="bank", is_active=True)
        customer = Customer(name="Partial Customer", phone="07737777777")
        db.session.add_all([bank, customer])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            status=ORDERED,
            payment_status=UNPAID,
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.commit()
        ids = {"cash": cash.id, "bank": bank.id, "invoice": invoice.id}

    with app.test_request_context(
        "/orders/payment",
        method="POST",
        json={
            "id": ids["invoice"],
            "payment": PARTIAL,
            "paid_amount": 600,
            "delivery_fee": 100,
            "payment_allocations": [
                {"treasury_account_id": ids["cash"], "amount": 200},
                {"treasury_account_id": ids["bank"], "amount": 400},
            ],
        },
    ):
        g.tenant = TENANT
        data, status = _response(payment())
        assert status == 200, data
        assert data["order"]["payment_status"] == PARTIAL
        assert data["order"]["remaining"] == 400

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(ids["invoice"])
        assert get_shipping_fee_from_invoice(invoice) == 100
        assert Expense.query.filter_by(note=f"delivery_fee_invoice:{ids['invoice']}").count() == 0
        rows = InvoicePaymentLedger.query.filter_by(invoice_id=ids["invoice"]).all()
        assert [(row.treasury_account_id, row.amount_delta) for row in rows] == [
            (ids["cash"], 200),
            (ids["bank"], 400),
        ]
        assert calculate_treasury_balance(ids["cash"]) == 200
        assert calculate_treasury_balance(ids["bank"]) == 400

    with app.test_request_context(
        "/orders/payment",
        method="POST",
        json={
            "id": ids["invoice"],
            "payment": PARTIAL,
            "paid_amount": 400,
            "delivery_fee": 0,
            "payment_allocations": [
                {"treasury_account_id": ids["bank"], "amount": 400},
            ],
        },
    ):
        g.tenant = TENANT
        data, status = _response(payment())
        assert status == 200, data
        assert data["order"]["payment_status"] == PAID
        assert data["order"]["remaining"] == 0

    with app.app_context():
        g.tenant = TENANT
        assert Expense.query.filter_by(note=f"delivery_fee_invoice:{ids['invoice']}").count() == 1
        assert calculate_treasury_balance(ids["cash"]) == 100
        assert calculate_treasury_balance(ids["bank"]) == 800


def test_shipping_settlement_preserves_split_accounts():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.shipping import ShippingCompany
    from models.shipping_payment import ShippingPayment
    from models.treasury_account import TreasuryAccount
    from utils.shipping_settlement_service import ensure_paid_shipping_order_settled
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        cash = get_default_cash_account()
        bank = TreasuryAccount(name="Courier Split Bank", account_type="bank", is_active=True)
        customer = Customer(name="Courier Split Customer", phone="07733333333")
        company = ShippingCompany(name="Split Courier", phone="07734444444")
        db.session.add_all([bank, customer, company])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            shipping_company_id=company.id,
            total=1000,
            paid_amount=1000,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status=PAID,
        )
        db.session.add(invoice)
        db.session.flush()

        ensure_paid_shipping_order_settled(
            invoice,
            allocations=[
                {"treasury_account_id": cash.id, "amount": 400},
                {"treasury_account_id": bank.id, "amount": 600},
            ],
        )
        db.session.commit()

        rows = ShippingPayment.query.filter_by(
            invoice_id=invoice.id,
            action="\u062a\u0633\u062f\u064a\u062f",
        ).order_by(ShippingPayment.id).all()
        assert [(row.treasury_account_id, row.amount) for row in rows] == [
            (cash.id, 400),
            (bank.id, 600),
        ]
        assert calculate_treasury_balance(cash.id) == 400
        assert calculate_treasury_balance(bank.id) == 600


def test_manual_delivery_fee_is_always_deducted_from_default_cash():
    _fresh_tenant_db()
    from app import app
    from flask import g, session
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.treasury_account import TreasuryAccount
    from routes.orders import payment
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        cash = get_default_cash_account()
        bank = TreasuryAccount(name="Delivery Fee Bank", account_type="bank", is_active=True)
        employee = Employee(
            name="Delivery Fee Tester",
            username=f"delivery_fee_tester_{os.getpid()}",
            password="pw",
            role="admin",
        )
        customer = Customer(name="Delivery Fee Customer", phone="07735555555")
        db.session.add_all([bank, employee, customer])
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
        ids = {
            "cash": cash.id,
            "bank": bank.id,
            "employee": employee.id,
            "invoice": invoice.id,
        }

    with app.test_request_context(
        "/orders/payment",
        method="POST",
        json={
            "id": ids["invoice"],
            "payment": PAID,
            "delivery_fee": 100,
            "payment_allocations": [
                {"treasury_account_id": ids["bank"], "amount": 1000},
            ],
        },
    ):
        g.tenant = TENANT
        session["user_id"] = ids["employee"]
        data, status = _response(payment())
        assert status == 200, data
        assert data["success"] is True

    with app.app_context():
        g.tenant = TENANT
        fee_tx = AccountTransaction.query.filter_by(
            type="withdraw",
            amount=100,
        ).one()
        assert fee_tx.treasury_account_id == ids["cash"]
        assert calculate_treasury_balance(ids["cash"]) == -100
        assert calculate_treasury_balance(ids["bank"]) == 1000


def test_payment_ignores_modal_branch_for_stock_already_deducted():
    """Legacy invoice/line branch mismatches must not block settlement."""
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from routes.orders import payment
    from utils.branch_migration import ensure_branch_schema, get_default_branch

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_branch_schema()
        displayed_branch = get_default_branch()
        deducted_branch = Branch(
            code="LEGACY-STOCK",
            name="Legacy deducted branch",
            is_active=True,
            is_default=False,
        )
        customer = Customer(name="Legacy Stock Customer", phone="07736666666")
        product = Product(
            name="Legacy Stock Item",
            buy_price=100,
            sale_price=500,
            quantity=0,
            active=True,
        )
        db.session.add_all([deducted_branch, customer, product])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=displayed_branch.id,
            total=500,
            status=ORDERED,
            payment_status=UNPAID,
            paid_amount=0,
            stock_is_deducted=True,
        )
        db.session.add(invoice)
        db.session.flush()
        item = OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            price=500,
            cost=100,
            total=500,
            fulfillment_branch_id=deducted_branch.id,
        )
        db.session.add(item)
        db.session.commit()
        ids = {
            "invoice": invoice.id,
            "item": item.id,
            "displayed_branch": displayed_branch.id,
            "deducted_branch": deducted_branch.id,
        }

    with app.test_request_context(
        "/orders/payment",
        method="POST",
        json={
            "id": ids["invoice"],
            "payment": PAID,
            "delivery_fee": 0,
            # This is what the disabled modal used to submit for order #444.
            "branch_id": ids["displayed_branch"],
        },
    ):
        g.tenant = TENANT
        data, status = _response(payment())
        assert status == 200, data
        assert data["success"] is True

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(ids["invoice"])
        item = OrderItem.query.get(ids["item"])
        assert invoice.payment_status == PAID
        assert invoice.stock_is_deducted is True
        assert invoice.branch_id == ids["displayed_branch"]
        assert item.fulfillment_branch_id == ids["deducted_branch"]
