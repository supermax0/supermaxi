from types import SimpleNamespace
from unittest.mock import patch


def _memory_app():
    from flask import Flask
    from extensions import db

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="integrity-test",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    import models  # noqa: F401
    import models.delivery_agent  # noqa: F401
    import models.page  # noqa: F401
    import models.system_settings  # noqa: F401
    import models.user  # noqa: F401
    import modules.phone_app.models  # noqa: F401
    import modules.wholesale.models  # noqa: F401

    with app.app_context():
        db.create_all()
    return app


def test_inventory_summary_does_not_hide_reconciliation_gap():
    from utils.inventory_movements import get_product_inventory_summary

    movements = [
        {"type": "opening_stock", "quantity_in": 10, "quantity_out": 0, "balance_after": 10},
        {"type": "sale", "quantity_in": 0, "quantity_out": 3, "balance_after": 7},
        {
            "type": "stock_reconciliation",
            "quantity_in": 2,
            "quantity_out": 0,
            "balance_after": 9,
        },
    ]
    app = _memory_app()
    with app.app_context():
        from extensions import db
        from models.product import Product

        product = Product(id=1, name="Audit Item", buy_price=1, sale_price=2, quantity=9, active=True)
        db.session.add(product)
        db.session.commit()
        with patch("utils.inventory_movements.get_product_inventory_movements", return_value=movements):
            summary = get_product_inventory_summary(1)

    assert summary["calculated_balance"] == 7
    assert summary["actual_quantity"] == 9
    assert summary["difference"] == 2
    assert summary["is_balanced"] is False


def test_installment_partial_alias_is_cash_affecting():
    from utils.cash_calculations import _effective_paid_amount

    invoice = SimpleNamespace(
        total=500_000,
        paid_amount=125_000,
        payment_status="مسدد جزئياً",
        status="تم الطلب",
        is_stock_locked=False,
    )
    assert _effective_paid_amount(invoice) == 125_000


def test_phone_pending_order_does_not_create_phantom_branch_stock():
    import json

    from flask import g
    from extensions import db
    from models.branch import Branch, BranchStock
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.product import Product
    from modules.phone_app.api.v1.orders import orders_confirm
    from modules.phone_app.models import PhoneOrderDraft

    app = _memory_app()
    with app.test_request_context("/api/v1/orders/1/confirm", method="POST", json={}):
        branch = Branch(code="PHONE", name="Phone Branch", is_active=True, is_default=True)
        customer = Customer(name="Phone Customer", phone="07700000123")
        employee = Employee(
            name="Phone Employee",
            username="phone-integrity",
            password="x",
            role="admin",
            is_active=True,
        )
        product = Product(name="Phone Item", buy_price=50, sale_price=100, quantity=5, active=True)
        db.session.add_all([branch, customer, employee, product])
        db.session.flush()
        employee.branch_id = branch.id
        customer.branch_id = branch.id
        product.branch_id = branch.id
        db.session.add(BranchStock(branch_id=branch.id, product_id=product.id, quantity=5, opening_stock=5))
        draft = PhoneOrderDraft(
            employee_id=employee.id,
            customer_id=customer.id,
            client_id="phone-integrity-order",
            idempotency_key="phone-integrity-order",
            status="draft",
            payload_json=json.dumps(
                {
                    "total": 200,
                    "items": [{"product_id": product.id, "qty": 2, "price": 100}],
                    "items_summary": ["Phone Item x2"],
                }
            ),
        )
        db.session.add(draft)
        db.session.commit()
        g.phone_employee = employee

        with patch("utils.order_stock_policy.deferred_stock_enabled", return_value=True):
            response = orders_confirm.__wrapped__(draft.id)
        if isinstance(response, tuple):
            response = response[0]
        assert response.get_json()["ok"] is True

        invoice = db.session.get(Invoice, draft.invoice_id)
        assert invoice.status == "تم الطلب"
        assert invoice.payment_status == "غير مسدد"
        assert invoice.stock_is_deducted is False
        assert db.session.get(Product, product.id).quantity == 5
        assert BranchStock.query.filter_by(branch_id=branch.id, product_id=product.id).one().quantity == 5


def test_beauty_cancel_restores_same_branch_stock_and_removes_cash():
    from datetime import datetime

    from flask import g
    from extensions import db
    from models.account_transaction import AccountTransaction
    from models.beauty_appointment import BeautyAppointment
    from models.beauty_service import BeautyService
    from models.beauty_service_product import BeautyServiceProduct
    from models.branch import Branch, BranchStock
    from models.customer import Customer
    from models.product import Product
    from models.stock_movement import StockMovement
    from routes.beauty import beauty_bp, update_appointment_status

    app = _memory_app()
    app.register_blueprint(beauty_bp)
    with app.app_context():
        branch = Branch(code="BEAUTY", name="Beauty Branch", is_active=True, is_default=True)
        customer = Customer(name="Beauty Customer", phone="07700000456")
        product = Product(name="Beauty Material", buy_price=20, sale_price=30, quantity=5, active=True)
        service = BeautyService(name="Session", price=100, is_active=True)
        db.session.add_all([branch, customer, product, service])
        db.session.flush()
        product.branch_id = branch.id
        customer.branch_id = branch.id
        db.session.add_all([
            BranchStock(branch_id=branch.id, product_id=product.id, quantity=5, opening_stock=5),
            BeautyServiceProduct(service_id=service.id, product_id=product.id, amount_used=1),
        ])
        appointment = BeautyAppointment(
            customer_id=customer.id,
            service_id=service.id,
            appointment_at=datetime.utcnow(),
            status="pending",
        )
        db.session.add(appointment)
        db.session.commit()
        appointment_id = appointment.id
        product_id = product.id
        branch_id = branch.id

    with app.test_request_context(
        f"/beauty/appointments/{appointment_id}/status",
        method="POST",
        data={"status": "done", "paid_amount": "100", "payment_method": "cash"},
    ):
        g.branch = db.session.get(Branch, branch_id)
        update_appointment_status(appointment_id)

    with app.app_context():
        assert BranchStock.query.filter_by(branch_id=branch_id, product_id=product_id).one().quantity == 4
        assert AccountTransaction.query.filter(AccountTransaction.note.like("مركز التجميل - جلسة #%")).count() == 1

    with app.test_request_context(
        f"/beauty/appointments/{appointment_id}/status",
        method="POST",
        data={"status": "cancelled"},
    ):
        g.branch = db.session.get(Branch, branch_id)
        update_appointment_status(appointment_id)

    with app.app_context():
        appointment = db.session.get(BeautyAppointment, appointment_id)
        assert appointment.status == "cancelled"
        assert appointment.paid_amount == 0
        assert BranchStock.query.filter_by(branch_id=branch_id, product_id=product_id).one().quantity == 5
        assert AccountTransaction.query.filter(AccountTransaction.note.like("مركز التجميل - جلسة #%")).count() == 0
        assert StockMovement.query.filter_by(source_type="beauty_appointment", source_id=appointment_id).count() == 2


def test_shipping_cancel_reverses_partial_collection_ledger():
    from flask import g
    from extensions import db
    from models.branch import Branch
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.shipping import ShippingCompany
    from routes.shipping import cancel_order

    app = _memory_app()
    with app.app_context():
        branch = Branch(code="SHIP", name="Shipping Branch", is_active=True, is_default=True)
        customer = Customer(name="Shipping Customer", phone="07700000789")
        company = ShippingCompany(name="Integrity Courier", price=5_000)
        db.session.add_all([branch, customer, company])
        db.session.flush()
        customer.branch_id = branch.id
        company.branch_id = branch.id
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=branch.id,
            shipping_company_id=company.id,
            total=100_000,
            status="تم الطلب",
            payment_status="جزئي",
            paid_amount=25_000,
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            InvoicePaymentLedger(
                branch_id=branch.id,
                invoice_id=invoice.id,
                amount_delta=25_000,
            )
        )
        db.session.commit()
        invoice_id = invoice.id
        branch_id = branch.id

    with app.test_request_context(f"/shipping/cancel/{invoice_id}", method="POST"):
        g.branch = db.session.get(Branch, branch_id)
        response = cancel_order(invoice_id)
        if isinstance(response, tuple):
            response = response[0]
        assert response.get_json() == {"success": True}

    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        ledger_total = (
            db.session.query(db.func.sum(InvoicePaymentLedger.amount_delta))
            .filter(InvoicePaymentLedger.invoice_id == invoice_id)
            .scalar()
        )
        assert invoice.status == "ملغي"
        assert invoice.paid_amount == 0
        assert ledger_total == 0


def test_wholesale_unallocated_receipt_and_bank_supplier_payment_hit_treasury_once():
    from extensions import db
    from models.account_transaction import AccountTransaction
    from models.branch import Branch
    from models.customer import Customer
    from models.supplier import Supplier
    from models.treasury_account import TreasuryAccount
    from modules.wholesale.services.receipt_service import create_receipt
    from modules.wholesale.services.supplier_payment_service import create_payment
    from utils.treasury_calculations import calculate_treasury_balance

    app = _memory_app()
    with app.app_context():
        branch = Branch(code="WHOLE", name="Wholesale Branch", is_active=True, is_default=True)
        customer = Customer(name="Wholesale Customer", phone="07700000999")
        supplier = Supplier(name="Wholesale Supplier", opening_balance=0, total_debt=0, total_paid=0)
        db.session.add_all([branch, customer, supplier])
        db.session.flush()
        customer.branch_id = branch.id
        cash = TreasuryAccount(
            branch_id=branch.id,
            name="الصندوق",
            account_type="cash",
            is_default=True,
            is_active=True,
        )
        bank = TreasuryAccount(
            branch_id=branch.id,
            name="Wholesale Bank",
            account_type="bank",
            is_default=False,
            is_active=True,
        )
        db.session.add_all([cash, bank])
        db.session.flush()
        db.session.add(
            AccountTransaction(
                branch_id=branch.id,
                type="deposit",
                amount=1_000,
                note="bank opening",
                treasury_account_id=bank.id,
            )
        )
        db.session.commit()

        receipt = create_receipt(
            None,
            {
                "customer_id": customer.id,
                "amount": 400,
                "payment_method": "cash",
                "treasury_account_id": cash.id,
            },
        )
        payment = create_payment(
            None,
            {
                "supplier_id": supplier.id,
                "amount": 300,
                "payment_method": "bank",
                "treasury_account_id": bank.id,
            },
        )
        db.session.commit()

        assert receipt["unallocated"] == 400
        assert payment["treasury_account_id"] == bank.id
        assert calculate_treasury_balance(cash.id) == 400
        assert calculate_treasury_balance(bank.id) == 700
        assert AccountTransaction.query.filter_by(treasury_account_id=cash.id).count() == 1
