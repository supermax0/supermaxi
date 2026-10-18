"""Advanced quick-sale checkout: customer, partial payment, bank and delivery agent."""
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_quick_sale_advanced_{os.getpid()}"


def _fresh_tenant_db():
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_advanced_quick_sale_saves_customer_partial_bank_and_agent():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.branch import Branch
    from models.customer import Customer
    from models.delivery_agent import DeliveryAgent
    from models.employee import Employee
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.product import Product
    from models.tenant import Tenant
    from models.treasury_account import TreasuryAccount
    from routes.quick_sale import add_customer as add_quick_customer
    from routes.quick_sale import execute, search_customers
    from utils.branch_stock_service import set_branch_stock

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        tenant = Tenant(
            name="Advanced Quick Sale",
            subdomain=TENANT,
            feature_overrides_json=json.dumps({"quick_sale_advanced_checkout": True}),
        )
        employee = Employee(
            name="Quick Admin",
            username=f"quick-admin-{os.getpid()}",
            password="x",
            role="admin",
            is_active=True,
        )
        branch = Branch(name="Main", code="MAIN", is_default=True, is_active=True)
        product = Product(name="Quick Item", buy_price=500, sale_price=1000, quantity=2, active=True)
        bank = TreasuryAccount(name="بطاقة ماستر", account_type="bank", is_active=True)
        agent = DeliveryAgent(name="مندوب بغداد", is_active=True)
        db.session.add_all([tenant, employee, branch, product, bank, agent])
        db.session.flush()
        set_branch_stock(branch.id, product.id, 2)
        db.session.commit()
        employee_id = employee.id
        product_id = product.id
        bank_id = bank.id
        agent_id = agent.id

    customer_payload = {
            "name": "علي حسن",
            "phone": "07701234567",
            "phone2": "07801234567",
            "city": "بغداد",
            "address": "بغداد - الكرادة",
    }
    with app.test_request_context("/quick-sale/customers", method="POST", json=customer_payload):
        g.tenant = TENANT
        session["user_id"] = employee_id
        response = add_quick_customer()
        data = response.get_json()
        assert data["success"], data
        customer_id = data["customer"]["id"]

    with app.test_request_context("/quick-sale/customers?q=077012", method="GET"):
        g.tenant = TENANT
        session["user_id"] = employee_id
        data = search_customers().get_json()
        assert data["success"]
        assert [row["id"] for row in data["customers"]] == [customer_id]

    payload = {
        "advanced_checkout": True,
        "customer": {"enabled": False, "customer_id": customer_id},
        "items": [{"product_id": product_id, "qty": 1, "price": 1000}],
        "payment_type": "partial",
        "paid_amount": 400,
        "treasury_account_id": bank_id,
        "delivery_agent_id": agent_id,
        "delivery_fee": 0,
    }
    with app.test_request_context("/quick-sale/execute", method="POST", json=payload):
        g.tenant = TENANT
        session["user_id"] = employee_id
        response = execute()
        data = response.get_json()
        assert data["success"], data
        invoice_id = data["invoice_id"]

    with app.app_context():
        g.tenant = TENANT
        invoice = Invoice.query.get(invoice_id)
        customer = Customer.query.get(invoice.customer_id)
        ledger = InvoicePaymentLedger.query.filter_by(invoice_id=invoice_id).one()
        assert invoice.payment_status == "جزئي"
        assert invoice.status == "تم الطلب"
        assert invoice.delivery_agent_id == agent_id
        assert int(invoice.paid_amount or 0) == 400
        assert customer.name == "علي حسن"
        assert customer.phone == "07701234567"
        assert customer.phone2 == "07801234567"
        assert customer.address == "بغداد - الكرادة"
        assert int(ledger.amount_delta or 0) == 400
        assert ledger.treasury_account_id == bank_id

    credit_payload = dict(payload)
    credit_payload.update({
        "payment_type": "credit",
        "paid_amount": 0,
        "treasury_account_id": None,
        "delivery_agent_id": None,
    })
    with app.test_request_context("/quick-sale/execute", method="POST", json=credit_payload):
        g.tenant = TENANT
        session["user_id"] = employee_id
        response = execute()
        data = response.get_json()
        assert data["success"], data
        credit_invoice_id = data["invoice_id"]

    with app.app_context():
        g.tenant = TENANT
        credit_invoice = Invoice.query.get(credit_invoice_id)
        assert credit_invoice.payment_status == "غير مسدد"
        assert int(credit_invoice.paid_amount or 0) == 0
        assert InvoicePaymentLedger.query.filter_by(invoice_id=credit_invoice_id).count() == 0
