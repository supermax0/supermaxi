"""Regression: delivery fees are expenses and must not reduce invoice revenue twice."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_delivery_fee_accounting_{os.getpid()}"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_delivery_fee_counts_once_in_profit_and_cash():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.customer import Customer
    from models.expense import Expense
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from utils.accounting_calculations import calculate_net_profit
    from utils.cash_calculations import calculate_cash_balance
    from utils.delivery_expense_service import restore_missing_delivery_fee_withdrawals, sync_delivery_expense_for_invoice
    from utils.order_shipping import apply_manual_delivery_fee_on_payment, get_shipping_fee_from_invoice

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)

        customer = Customer(name="Delivery Fee Customer", phone="07760000000")
        product = Product(name="Delivered Product", buy_price=100000, sale_price=195000, quantity=1, active=True)
        db.session.add_all([customer, product])
        db.session.flush()

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=195000,
            paid_amount=195000,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=1,
                price=195000,
                cost=100000,
                total=195000,
            )
        )
        apply_manual_delivery_fee_on_payment(invoice, 6000, None)
        sync_delivery_expense_for_invoice(invoice)
        db.session.commit()

        db.session.refresh(invoice)
        assert int(invoice.total or 0) == 195000
        assert int(invoice.paid_amount or 0) == 195000
        assert get_shipping_fee_from_invoice(invoice) == 6000
        assert Expense.query.filter_by(amount=6000).count() == 1

        assert calculate_net_profit() == 89000
        assert Expense.query.filter_by(amount=6000, cash_posted=True).count() == 1
        assert calculate_cash_balance() == 189000

        AccountTransaction.query.filter_by(type="withdraw", amount=6000).delete()
        db.session.commit()
        assert calculate_cash_balance() == 195000

        restored = restore_missing_delivery_fee_withdrawals()
        assert restored == {"count": 1, "total": 6000}
        assert AccountTransaction.query.filter_by(type="withdraw", amount=6000).count() == 1
        assert calculate_cash_balance() == 189000


if __name__ == "__main__":
    test_delivery_fee_counts_once_in_profit_and_cash()
    print("delivery fee accounting tests passed")
