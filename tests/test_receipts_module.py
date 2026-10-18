"""Receipts & settlements — allocation + create/cancel flow."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_fifo_allocation_preview():
    from modules.receipts.services.allocation import preview_allocations

    invoices = [
        SimpleNamespace(id=1, invoice_no="INV-001", total=300000, paid_amount=0),
        SimpleNamespace(id=2, invoice_no="INV-002", total=250000, paid_amount=0),
        SimpleNamespace(id=3, invoice_no="INV-003", total=500000, paid_amount=0),
    ]
    prev = preview_allocations(
        open_invoices=invoices,
        amount=700000,
        allocation_method="oldest_first",
        balance_before=1050000,
    )
    assert prev["amount"] == 700000
    assert prev["balance_after"] == 350000
    assert len(prev["allocations"]) == 3
    assert prev["allocations"][0]["amount"] == 300000
    assert prev["allocations"][1]["amount"] == 250000
    assert prev["allocations"][2]["amount"] == 150000
    assert prev["allocations"][2]["status_after"] == "جزئي"


def test_receipt_permissions_listed():
    from routes.permissions import DEFAULT_PERMISSIONS

    names = {name for name, _ in DEFAULT_PERMISSIONS}
    assert "view_receipts" in names
    assert "create_receipts" in names
    assert "print_receipts" in names
    assert "cancel_receipts" in names


def test_receipts_blueprints_importable():
    from modules.receipts.api.routes import receipts_api_bp
    from modules.receipts.web.routes import receipts_web_bp

    assert receipts_api_bp.url_prefix == "/api/receipts"
    assert receipts_web_bp.url_prefix == "/receipts"


def _make_app():
    from flask import Flask

    from extensions import db

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    import models  # noqa: F401
    import models.receipt  # noqa: F401
    import models.invoice  # noqa: F401
    import models.customer  # noqa: F401
    import models.delivery_agent  # noqa: F401
    import models.shipping  # noqa: F401
    import models.treasury_account  # noqa: F401
    import models.invoice_payment_ledger  # noqa: F401
    import models.account  # noqa: F401
    import models.journal_entry  # noqa: F401
    import models.employee  # noqa: F401
    import models.branch  # noqa: F401
    import models.page  # noqa: F401
    import models.user  # noqa: F401
    import models.tenant  # noqa: F401
    import models.role  # noqa: F401
    import models.supplier  # noqa: F401
    import models.supplier_payment  # noqa: F401
    import models.supplier_payment_allocation  # noqa: F401
    import models.expense  # noqa: F401
    import models.account_transaction  # noqa: F401
    import models.employee_payment  # noqa: F401
    import models.purchase  # noqa: F401
    import modules.wholesale.models.warehouse  # noqa: F401

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
    return app


def test_create_and_cancel_customer_receipt():
    app = _make_app()
    from extensions import db
    from models.account import Account
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.receipt import Receipt
    from models.treasury_account import TreasuryAccount
    from modules.receipts.services import receipt_service

    with app.app_context():
        cash = TreasuryAccount(name="الصندوق", account_type="cash", is_default=True, is_active=True)
        cust = Customer(name="زبون اختبار", phone="07700000000")
        db.session.add_all([cash, cust])
        db.session.flush()

        inv1 = Invoice(
            customer_id=cust.id,
            customer_name=cust.name,
            total=300000,
            paid_amount=0,
            payment_status="غير مسدد",
            status="تم التوصيل",
        )
        inv2 = Invoice(
            customer_id=cust.id,
            customer_name=cust.name,
            total=200000,
            paid_amount=0,
            payment_status="غير مسدد",
            status="تم التوصيل",
        )
        db.session.add_all(
            [
                inv1,
                inv2,
                Account(name="الصندوق", code="1001", account_type="asset"),
                Account(name="ذمم العملاء", code="1201", account_type="asset"),
            ]
        )
        db.session.commit()

        result = receipt_service.create_receipt(
            None,
            {
                "source_type": "customer",
                "source_id": cust.id,
                "amount": 400000,
                "payment_method": "cash",
                "treasury_account_id": cash.id,
                "allocation_method": "oldest_first",
                "idempotency_key": "test-key-1",
                "receipt_date": date.today().isoformat(),
            },
            employee_id=None,
        )
        db.session.commit()

        assert result["amount"] == 400000
        assert result["receipt_number"].startswith("RC-")
        assert len(result["allocations"]) == 2
        assert result["allocations"][0]["amount"] == 300000
        assert result["allocations"][1]["amount"] == 100000

        db.session.refresh(inv1)
        db.session.refresh(inv2)
        assert inv1.payment_status == "مسدد"
        assert inv1.paid_amount == 300000
        assert inv2.payment_status == "جزئي"
        assert inv2.paid_amount == 100000
        assert sum(row.amount_delta for row in InvoicePaymentLedger.query.all()) == 400000

        again = receipt_service.create_receipt(
            None,
            {
                "source_type": "customer",
                "source_id": cust.id,
                "amount": 400000,
                "idempotency_key": "test-key-1",
            },
        )
        assert again["id"] == result["id"]
        assert Receipt.query.count() == 1

        cancelled = receipt_service.cancel_receipt(result["id"], reason="اختبار")
        db.session.commit()
        assert cancelled["status"] == "ملغى"

        db.session.refresh(inv1)
        db.session.refresh(inv2)
        assert inv1.paid_amount == 0
        assert inv1.payment_status == "غير مسدد"
        assert inv2.paid_amount == 0
        assert inv2.payment_status == "غير مسدد"
        assert sum(row.amount_delta for row in InvoicePaymentLedger.query.all()) == 0


def test_receipt_rejects_overpayment_and_incomplete_manual_allocation():
    app = _make_app()
    from extensions import db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.treasury_account import TreasuryAccount
    from modules.receipts.services import receipt_service
    from modules.receipts.services.helpers import ReceiptError

    with app.app_context():
        cash = TreasuryAccount(name="الصندوق", account_type="cash", is_default=True, is_active=True)
        customer = Customer(name="عميل الذمة", phone="07711111111")
        db.session.add_all([cash, customer])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=100000,
            paid_amount=0,
            payment_status="غير مسدد",
            status="تم التوصيل",
        )
        db.session.add(invoice)
        db.session.commit()

        with pytest.raises(ReceiptError, match="أكبر من الذمة"):
            receipt_service.create_receipt(
                None,
                {
                    "source_type": "customer",
                    "source_id": customer.id,
                    "amount": 120000,
                    "treasury_account_id": cash.id,
                },
            )
        db.session.rollback()

        with pytest.raises(ReceiptError, match="توزيع كامل"):
            receipt_service.create_receipt(
                None,
                {
                    "source_type": "customer",
                    "source_id": customer.id,
                    "amount": 100000,
                    "allocation_method": "manual",
                    "allocations": [{"invoice_id": invoice.id, "amount": 60000}],
                    "treasury_account_id": cash.id,
                },
            )


def test_courier_receipts_include_undelivered_unpaid_orders():
    """طلبات المندوب غير المسددة تظهر حتى لو الحالة ليست «تم التوصيل»."""
    app = _make_app()
    from extensions import db
    from models.customer import Customer
    from models.delivery_agent import DeliveryAgent
    from models.invoice import Invoice
    from modules.receipts.services.source_summary import courier_open_invoices

    with app.app_context():
        customer = Customer(name="عميل", phone="07722222222")
        courier = DeliveryAgent(name="مندوب اختبار", is_active=True)
        db.session.add_all([customer, courier])
        db.session.flush()
        pending = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            delivery_agent_id=courier.id,
            total=50000,
            paid_amount=0,
            payment_status="غير مسدد",
            status="جاري الشحن",
        )
        delivered = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            delivery_agent_id=courier.id,
            total=70000,
            paid_amount=0,
            payment_status="غير مسدد",
            status="تم التوصيل",
        )
        paid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            delivery_agent_id=courier.id,
            total=40000,
            paid_amount=40000,
            payment_status="مسدد",
            status="تم التوصيل",
        )
        db.session.add_all([pending, delivered, paid])
        db.session.commit()

        ids = [row.id for row in courier_open_invoices(courier.id)]
        assert ids == [pending.id, delivered.id]
        assert paid.id not in ids


def test_shipping_receipt_and_cancel_keep_shipping_and_treasury_ledgers_in_sync():
    app = _make_app()
    from extensions import db
    from models.account import Account
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.shipping import ShippingCompany
    from models.shipping_payment import ShippingPayment
    from models.treasury_account import TreasuryAccount
    from modules.receipts.services import receipt_service
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_calculations import get_treasury_movements

    with app.app_context():
        cash = TreasuryAccount(name="الصندوق", account_type="cash", is_default=True, is_active=True)
        customer = Customer(name="عميل شحن", phone="07733333333")
        company = ShippingCompany(name="شركة اختبار", phone="07800000000")
        db.session.add_all([cash, customer, company])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            shipping_company_id=company.id,
            total=150000,
            paid_amount=0,
            payment_status="غير مسدد",
            status="تم التوصيل",
            shipping_status="قيد الشحن",
        )
        db.session.add_all(
            [
                invoice,
                Account(name="الصندوق", code="1001", account_type="asset"),
                Account(name="ذمم العملاء", code="1201", account_type="asset"),
            ]
        )
        db.session.commit()

        result = receipt_service.create_receipt(
            None,
            {
                "source_type": "shipping_company",
                "source_id": company.id,
                "amount": 150000,
                "treasury_account_id": cash.id,
            },
        )
        db.session.commit()

        shipping_row = ShippingPayment.query.one()
        assert shipping_row.amount == 150000
        assert shipping_row.note == f"سند قبض {result['receipt_number']}"
        assert invoice.shipping_status == "تم التسديد"
        assert sum(row.amount_delta for row in InvoicePaymentLedger.query.all()) == 150000
        assert calculate_treasury_balance(cash.id) == 150000
        receipt_service.cancel_receipt(result["id"], reason="اختبار عكس الشحن")
        db.session.commit()

        assert ShippingPayment.query.count() == 0
        assert invoice.shipping_status == "قيد الشحن"
        assert invoice.paid_amount == 0
        assert sum(row.amount_delta for row in InvoicePaymentLedger.query.all()) == 0
        assert calculate_treasury_balance(cash.id) == 0


def test_supplier_cash_payment_ops_and_reject_overpay():
    app = _make_app()
    from extensions import db
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment
    from models.treasury_account import TreasuryAccount
    from models.account_transaction import AccountTransaction
    from utils.supplier_payment_ops import SupplierPaymentError, create_supplier_cash_payment

    with app.app_context():
        from flask import g

        g.independent_branches_enabled = False
        cash = TreasuryAccount(name="الصندوق", account_type="cash", is_default=True, is_active=True)
        supplier = Supplier(name="مورد اختبار", total_debt=500000, total_paid=0)
        db.session.add_all([cash, supplier])
        db.session.flush()
        db.session.add(
            AccountTransaction(
                type="deposit", amount=1000000, note="seed", treasury_account_id=cash.id
            )
        )
        db.session.commit()

        result = create_supplier_cash_payment(
            supplier.id,
            amount=200000,
            treasury_account_id=cash.id,
            document_number="DOC-1",
            note="دفعة اختبار",
            commit=True,
        )
        assert result["amount"] == 200000
        assert result["kind"] == "supplier_payment"
        assert SupplierPayment.query.count() == 1
        db.session.refresh(supplier)
        assert int(supplier.total_paid or 0) == 200000

        with pytest.raises(SupplierPaymentError, match="أكبر من المتبقي"):
            create_supplier_cash_payment(
                supplier.id,
                amount=400000,
                treasury_account_id=cash.id,
                commit=True,
            )


def test_expense_settlement_and_unified_movements(monkeypatch):
    app = _make_app()
    from extensions import db
    from models.account_transaction import AccountTransaction
    from models.expense import Expense
    from models.receipt import Receipt
    from models.supplier import Supplier
    from models.treasury_account import TreasuryAccount
    from modules.receipts.services import movements_feed
    from modules.receipts.services import settlements
    from utils.expense_quick_add import create_quick_expense
    from utils.supplier_payment_ops import create_supplier_cash_payment
    from datetime import date

    with app.app_context():
        from flask import g

        g.independent_branches_enabled = False
        monkeypatch.setattr(
            "modules.receipts.services.settlements.check_permission", lambda _p: True
        )

        cash = TreasuryAccount(name="الصندوق", account_type="cash", is_default=True, is_active=True)
        supplier = Supplier(name="مورد حركات", total_debt=300000, total_paid=0)
        db.session.add_all([cash, supplier])
        db.session.flush()
        db.session.add(
            AccountTransaction(
                type="deposit", amount=2000000, note="seed", treasury_account_id=cash.id
            )
        )
        db.session.commit()

        create_supplier_cash_payment(
            supplier.id, amount=100000, treasury_account_id=cash.id, commit=True
        )
        expense_result = create_quick_expense(
            {
                "title": "راتب اختبار",
                "category": "salary",
                "amount": 150000,
                "treasury_account_id": cash.id,
            },
            commit=True,
        )
        assert expense_result["kind"] == "expense"
        assert Expense.query.count() == 1

        via_settlements = settlements.create_settlement(
            None,
            {
                "movement_type": "expense",
                "title": "إيجار مكتب",
                "category": "rent",
                "amount": 50000,
                "treasury_account_id": cash.id,
            },
        )
        db.session.commit()
        assert via_settlements["amount"] == 50000

        with pytest.raises(Exception):
            settlements.create_settlement(
                None,
                {
                    "movement_type": "supplier_payment",
                    "supplier_id": supplier.id,
                    "amount": 999999999,
                    "treasury_account_id": cash.id,
                },
            )
        db.session.rollback()

        feed = movements_feed.list_movements(
            {
                "date_from": date.today().isoformat(),
                "date_to": date.today().isoformat(),
            }
        )
        kinds = {row["kind"] for row in feed["items"]}
        assert "supplier_payment" in kinds
        assert "expense" in kinds
        assert feed["stats"]["outbound_total"] >= 100000 + 150000 + 50000

        only_pay = movements_feed.list_movements(
            {
                "kind": "supplier_payment",
                "date_from": date.today().isoformat(),
                "date_to": date.today().isoformat(),
            }
        )
        assert only_pay["items"]
        assert all(r["kind"] == "supplier_payment" for r in only_pay["items"])


def test_payroll_settlement_blocks_double_pay(monkeypatch):
    app = _make_app()
    from extensions import db
    from models.account_transaction import AccountTransaction
    from models.employee import Employee
    from models.treasury_account import TreasuryAccount
    from modules.receipts.services import settlements
    from modules.receipts.services.helpers import ReceiptError

    with app.app_context():
        from flask import g

        g.independent_branches_enabled = False
        monkeypatch.setattr(
            "modules.receipts.services.settlements.check_permission", lambda _p: True
        )

        cash = TreasuryAccount(name="الصندوق", account_type="cash", is_default=True, is_active=True)
        emp = Employee(
            name="موظف راتب",
            username="emp_salary_test",
            password="x",
            role="employee",
            is_active=True,
            salary=250000,
            pay_type="monthly",
            pay_day_of_month=1,
        )
        db.session.add_all([cash, emp])
        db.session.flush()
        db.session.add(
            AccountTransaction(
                type="deposit", amount=2000000, note="seed", treasury_account_id=cash.id
            )
        )
        db.session.commit()

        calls = {"n": 0}

        def _fake_pay_salary(payee, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "ok": True,
                    "payment_id": 11,
                    "expense_id": 22,
                    "amount": 250000,
                    "payee_type": "employee",
                    "payee_id": emp.id,
                    "payee_name": emp.name,
                }
            return {"ok": False, "error": "تم صرف راتب هذه الدورة مسبقاً"}

        monkeypatch.setattr("utils.payroll_service.pay_salary", _fake_pay_salary)

        first = settlements.create_settlement(
            None,
            {
                "movement_type": "payroll",
                "payee_type": "employee",
                "payee_id": emp.id,
                "treasury_account_id": cash.id,
                "manual": True,
            },
        )
        assert first["amount"] == 250000
        assert first["kind"] == "payroll"

        with pytest.raises(ReceiptError, match="مسبقاً"):
            settlements.create_settlement(
                None,
                {
                    "movement_type": "payroll",
                    "payee_type": "employee",
                    "payee_id": emp.id,
                    "treasury_account_id": cash.id,
                    "manual": True,
                },
            )
