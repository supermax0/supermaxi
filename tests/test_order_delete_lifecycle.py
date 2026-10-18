"""Regression: deleting orders must not leave accounting or stock ghosts."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT_CANCELED = f"test_order_delete_canceled_{os.getpid()}"
TENANT_LEDGER = f"test_order_delete_ledger_{os.getpid()}"
TENANT_SIDE_EFFECTS = f"test_order_delete_side_effects_{os.getpid()}"
TENANT_PAID_COMMISSION = f"test_order_delete_paid_commission_{os.getpid()}"
TENANT_PAID_PAYROLL = f"test_order_delete_paid_payroll_{os.getpid()}"


def _fresh_tenant_db(tenant: str):
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def _json_payload(response):
    if isinstance(response, tuple):
        response = response[0]
    return response.get_json()


def test_delete_canceled_order_does_not_restore_stock_twice():
    _fresh_tenant_db(TENANT_CANCELED)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from routes.orders import delete_order
    from utils.order_lifecycle import process_order_cancel

    with app.app_context():
        g.tenant = TENANT_CANCELED
        init_tenant_db(TENANT_CANCELED)

        customer = Customer(name="Delete Canceled Customer", phone="07740000000")
        product = Product(
            name="Delete Canceled Color Item",
            buy_price=100,
            sale_price=150,
            quantity=3,
            opening_stock=5,
            active=True,
            meta_json=json.dumps({"has_colors": True}),
        )
        db.session.add_all([customer, product])
        db.session.flush()
        db.session.add(ProductColorVariant(product_id=product.id, color_name="red", quantity=3))
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=300,
            status="تم الطلب",
            payment_status="غير مسدد",
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=2,
                price=150,
                cost=100,
                total=300,
                variant_color="red",
            )
        )
        db.session.commit()

        invoice_id = invoice.id
        product_id = product.id
        process_order_cancel(invoice)
        db.session.commit()

        assert int(Product.query.get(product_id).quantity or 0) == 5
        assert (
            int(
                ProductColorVariant.query.filter_by(
                    product_id=product_id, color_name="red"
                ).one().quantity
                or 0
            )
            == 5
        )

    with app.test_request_context(f"/orders/delete/{invoice_id}", method="POST"):
        g.tenant = TENANT_CANCELED
        data = _json_payload(delete_order(invoice_id))
        assert data["success"], data

    with app.app_context():
        g.tenant = TENANT_CANCELED
        assert Invoice.query.get(invoice_id) is None
        assert int(Product.query.get(product_id).quantity or 0) == 5
        assert (
            int(
                ProductColorVariant.query.filter_by(
                    product_id=product_id, color_name="red"
                ).one().quantity
                or 0
            )
            == 5
        )


def test_delete_paid_order_removes_collection_ledger_from_daily_profit():
    _fresh_tenant_db(TENANT_LEDGER)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.order_item import OrderItem
    from models.product import Product
    from routes.orders import delete_order
    from utils.payment_ledger import (
        append_payment_ledger_delta,
        business_today,
        net_profit_for_collection_calendar_day,
    )
    from utils.invoice_mutation_policy import set_paid_invoice_mutations_enabled

    with app.app_context():
        g.tenant = TENANT_LEDGER
        init_tenant_db(TENANT_LEDGER)
        set_paid_invoice_mutations_enabled(True)

        customer = Customer(name="Delete Ledger Customer", phone="07750000000")
        product = Product(name="Delete Ledger Item", buy_price=100, sale_price=500, quantity=3, active=True)
        db.session.add_all([customer, product])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            status="تم التوصيل",
            payment_status="مسدد",
            paid_amount=1000,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=2,
                price=500,
                cost=100,
                total=1000,
            )
        )
        append_payment_ledger_delta(invoice.id, 1000)
        db.session.commit()

        invoice_id = invoice.id
        product_id = product.id
        today = business_today()
        assert net_profit_for_collection_calendar_day(today) == 800

    with app.test_request_context(f"/orders/delete/{invoice_id}", method="POST"):
        g.tenant = TENANT_LEDGER
        data = _json_payload(delete_order(invoice_id))
        assert data["success"], data

    with app.app_context():
        g.tenant = TENANT_LEDGER
        assert Invoice.query.get(invoice_id) is None
        assert InvoicePaymentLedger.query.filter_by(invoice_id=invoice_id).count() == 0
        assert int(Product.query.get(product_id).quantity or 0) == 5
        assert net_profit_for_collection_calendar_day(today) == 0


def test_delete_paid_order_removes_delivery_expense_and_pending_commission():
    _fresh_tenant_db(TENANT_SIDE_EFFECTS)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.customer import Customer
    from models.employee import Employee
    from models.employee_commission_line import EmployeeCommissionLine
    from models.expense import Expense
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from routes.orders import delete_order
    from utils.delivery_expense_service import sync_delivery_expense_for_invoice
    from utils.order_shipping import apply_manual_delivery_fee_on_payment
    from utils.payroll_service import sync_commission_line_for_invoice
    from utils.invoice_mutation_policy import set_paid_invoice_mutations_enabled

    with app.app_context():
        g.tenant = TENANT_SIDE_EFFECTS
        init_tenant_db(TENANT_SIDE_EFFECTS)
        set_paid_invoice_mutations_enabled(True)

        customer = Customer(name="Delete Side Effects Customer", phone="07751000000")
        employee = Employee(
            name="Commission Cashier",
            username="commission-cashier",
            password="x",
            role="cashier",
            is_active=True,
            commission_percent=125,
        )
        product = Product(name="Delete Side Effects Item", buy_price=100, sale_price=500, quantity=3, active=True)
        db.session.add_all([customer, employee, product])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            total=1000,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
            paid_amount=1000,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=2,
                price=500,
                cost=100,
                total=1000,
            )
        )
        apply_manual_delivery_fee_on_payment(invoice, 6000, None)
        sync_delivery_expense_for_invoice(invoice)
        sync_commission_line_for_invoice(invoice)
        db.session.commit()

        invoice_id = invoice.id
        assert Expense.query.filter_by(note=f"delivery_fee_invoice:{invoice_id}").count() == 1
        assert AccountTransaction.query.filter_by(type="withdraw", amount=6000).count() == 1
        assert EmployeeCommissionLine.query.filter_by(invoice_id=invoice_id, status="pending").count() == 1

    with app.test_request_context(f"/orders/delete/{invoice_id}", method="POST"):
        g.tenant = TENANT_SIDE_EFFECTS
        data = _json_payload(delete_order(invoice_id))
        assert data["success"], data

    with app.app_context():
        g.tenant = TENANT_SIDE_EFFECTS
        assert Expense.query.filter_by(note=f"delivery_fee_invoice:{invoice_id}").count() == 0
        assert AccountTransaction.query.filter_by(type="withdraw", amount=6000).count() == 0
        assert EmployeeCommissionLine.query.filter_by(invoice_id=invoice_id).count() == 0


def test_paid_delete_is_blocked_by_default_even_with_delete_permission():
    _fresh_tenant_db(TENANT_PAID_COMMISSION)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.employee_commission_line import EmployeeCommissionLine
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from routes.orders import delete_order

    with app.app_context():
        g.tenant = TENANT_PAID_COMMISSION
        init_tenant_db(TENANT_PAID_COMMISSION)

        customer = Customer(name="Paid Commission Customer", phone="07752000000")
        employee = Employee(
            name="Paid Commission Cashier",
            username="paid-commission-cashier",
            password="x",
            role="cashier",
            is_active=True,
            commission_percent=125,
        )
        product = Product(name="Paid Commission Item", buy_price=100, sale_price=500, quantity=3, active=True)
        db.session.add_all([customer, employee, product])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            total=500,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
            paid_amount=500,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=1,
                price=500,
                cost=100,
                total=500,
            )
        )
        db.session.add(
            EmployeeCommissionLine(
                code=EmployeeCommissionLine.make_code(invoice.id, employee.id),
                invoice_id=invoice.id,
                employee_id=employee.id,
                amount=125,
                status="paid",
            )
        )
        db.session.commit()

        invoice_id = invoice.id
        product_id = product.id

    with app.test_request_context(f"/orders/delete/{invoice_id}", method="POST"):
        g.tenant = TENANT_PAID_COMMISSION
        response = delete_order(invoice_id)
        data = _json_payload(response)
        assert data["success"] is False
        assert response[1] == 403

    with app.app_context():
        g.tenant = TENANT_PAID_COMMISSION
        assert Invoice.query.get(invoice_id) is not None
        assert EmployeeCommissionLine.query.filter_by(invoice_id=invoice_id, status="paid").count() == 1
        assert int(Product.query.get(product_id).quantity or 0) == 3


def test_enabled_paid_delete_removes_paid_commission_payroll_share():
    _fresh_tenant_db(TENANT_PAID_PAYROLL)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.customer import Customer
    from models.employee import Employee
    from models.employee_commission_line import EmployeeCommissionLine
    from models.employee_commission_settlement import EmployeeCommissionSettlement
    from models.employee_payment import EmployeePayment
    from models.expense import Expense
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from routes.orders import delete_order
    from utils.invoice_mutation_policy import set_paid_invoice_mutations_enabled
    from utils.payment_ledger import append_payment_ledger_delta
    from utils.payroll_service import (
        settle_employee_commission_payment,
        sync_commission_line_for_invoice,
    )
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    with app.test_request_context("/"):
        g.tenant = TENANT_PAID_PAYROLL
        init_tenant_db(TENANT_PAID_PAYROLL)
        customer = Customer(name="Paid Payroll Customer", phone="07753000000")
        employee = Employee(
            name="Paid Payroll Cashier",
            username="paid-payroll-cashier",
            password="x",
            role="cashier",
            is_active=True,
            commission_percent=125,
        )
        product = Product(name="Paid Payroll Item", buy_price=100, sale_price=500, quantity=3, active=True)
        db.session.add_all([customer, employee, product])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            total=500,
            status="تم التوصيل",
            payment_status="مسدد",
            paid_amount=500,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            price=500,
            cost=100,
            total=500,
        ))
        append_payment_ledger_delta(invoice.id, 500)
        sync_commission_line_for_invoice(invoice)
        db.session.commit()

        cash_account = get_default_cash_account()
        result = settle_employee_commission_payment(
            employee.id,
            treasury_account_id=cash_account.id,
        )
        assert result["ok"], result
        invoice_id = invoice.id
        product_id = product.id
        payment_id = result["payment_id"]
        assert calculate_treasury_balance(cash_account.id) == 375
        set_paid_invoice_mutations_enabled(True)

    with app.test_request_context(f"/orders/delete/{invoice_id}", method="POST"):
        g.tenant = TENANT_PAID_PAYROLL
        data = _json_payload(delete_order(invoice_id))
        assert data["success"], data

    with app.test_request_context("/"):
        g.tenant = TENANT_PAID_PAYROLL
        assert Invoice.query.get(invoice_id) is None
        assert EmployeeCommissionLine.query.filter_by(invoice_id=invoice_id).count() == 0
        assert EmployeePayment.query.get(payment_id) is None
        assert EmployeeCommissionSettlement.query.filter_by(payment_id=payment_id).count() == 0
        assert Expense.query.filter_by(employee_payment_id=payment_id).count() == 0
        assert AccountTransaction.query.filter_by(type="withdraw", amount=125).count() == 0
        assert int(Product.query.get(product_id).quantity or 0) == 4
        assert calculate_treasury_balance(get_default_cash_account().id) == 0


if __name__ == "__main__":
    test_delete_canceled_order_does_not_restore_stock_twice()
    test_delete_paid_order_removes_collection_ledger_from_daily_profit()
    test_delete_paid_order_removes_delivery_expense_and_pending_commission()
    test_paid_delete_is_blocked_by_default_even_with_delete_permission()
    test_enabled_paid_delete_removes_paid_commission_payroll_share()
    print("order delete lifecycle tests passed")
