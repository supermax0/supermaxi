"""Regression: shipping settlement payments must hit the selected treasury account."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_treasury_shipping_settlement_{os.getpid()}"
TENANT_SYNC = f"test_treasury_shipping_sync_{os.getpid()}"
TENANT_LEDGER = f"test_treasury_ledger_movements_{os.getpid()}"


def _fresh_tenant_db(tenant: str = TENANT):
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_shipping_invoice_settlement_uses_selected_treasury_account():
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
    from utils.treasury_calculations import calculate_treasury_balance, get_treasury_movements
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)

        cash = get_default_cash_account()
        bank = TreasuryAccount(name="Settlement Bank", account_type="bank", is_active=True)
        customer = Customer(name="Shipping Customer", phone="07700000000")
        company = ShippingCompany(name="Courier", phone="07710000000")
        db.session.add_all([bank, customer, company])
        db.session.flush()

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            shipping_company_id=company.id,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
            total=1000,
            paid_amount=1000,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            ShippingPayment(
                shipping_company_id=company.id,
                invoice_id=invoice.id,
                amount=1000,
                action="\u062a\u0633\u062f\u064a\u062f",
                treasury_account_id=bank.id,
                note="settled via bank",
            )
        )
        db.session.commit()

        assert calculate_treasury_balance(cash.id) == 0
        assert calculate_treasury_balance(bank.id) == 1000

        cash_movements = get_treasury_movements(cash.id)
        bank_movements = get_treasury_movements(bank.id)
        assert all(m["reference_type"] != "invoice" for m in cash_movements)
        assert any(
            m["reference_type"] == "shipping_payment" and m["amount"] == 1000
            for m in bank_movements
        )


def test_paid_shipping_order_sync_creates_collection_without_cash_duplication():
    _fresh_tenant_db(TENANT_SYNC)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.shipping import ShippingCompany
    from models.shipping_payment import ShippingPayment
    from utils.shipping_settlement_service import ensure_paid_shipping_order_settled
    from utils.treasury_calculations import calculate_treasury_balance, get_treasury_movements
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT_SYNC
        init_tenant_db(TENANT_SYNC)

        cash = get_default_cash_account()
        customer = Customer(name="Paid Shipping Customer", phone="07720000000")
        company = ShippingCompany(name="Courier", phone="07730000000")
        db.session.add_all([customer, company])
        db.session.flush()

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            shipping_company_id=company.id,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
            total=737000,
            paid_amount=737000,
        )
        db.session.add(invoice)
        db.session.flush()

        ensure_paid_shipping_order_settled(invoice)
        db.session.commit()

        settlement = ShippingPayment.query.filter_by(
            invoice_id=invoice.id,
            action="\u062a\u0633\u062f\u064a\u062f",
        ).one()
        assert settlement.amount == 737000
        assert invoice.shipping_status == "\u062a\u0645 \u0627\u0644\u062a\u0633\u062f\u064a\u062f"
        assert calculate_treasury_balance(cash.id) == 737000

        movements = get_treasury_movements(cash.id)
        assert all(m["reference_type"] != "invoice" for m in movements)
        assert sum(
            m["amount"]
            for m in movements
            if m["reference_type"] == "shipping_payment"
        ) == 737000


def test_invoice_ledger_collection_uses_recorded_date_for_cash_movement():
    _fresh_tenant_db(TENANT_LEDGER)
    from datetime import datetime

    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from utils.treasury_calculations import calculate_treasury_balance, get_treasury_movements
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT_LEDGER
        init_tenant_db(TENANT_LEDGER)

        cash = get_default_cash_account()
        customer = Customer(name="Agent Customer", phone="07740000000")
        db.session.add(customer)
        db.session.flush()

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
            total=3182000,
            paid_amount=3182000,
            created_at=datetime(2026, 7, 11, 11, 39, 25),
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            InvoicePaymentLedger(
                invoice_id=invoice.id,
                amount_delta=3182000,
                recorded_at=datetime(2026, 7, 12, 10, 6, 37),
            )
        )
        db.session.commit()

        assert calculate_treasury_balance(cash.id) == 3182000
        movements = get_treasury_movements(cash.id)
        invoice_movements = [
            m for m in movements if m["reference_type"] == "invoice_payment_ledger"
        ]
        assert len(invoice_movements) == 1
        assert invoice_movements[0]["amount"] == 3182000
        assert invoice_movements[0]["date"].isoformat() == "2026-07-12"


if __name__ == "__main__":
    test_shipping_invoice_settlement_uses_selected_treasury_account()
    test_paid_shipping_order_sync_creates_collection_without_cash_duplication()
    test_invoice_ledger_collection_uses_recorded_date_for_cash_movement()
    print("treasury shipping settlement tests passed")
