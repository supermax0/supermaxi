"""Regression tests for purchase cancellation/reopen accounting effects."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_purchase_cancel_reopen_accounting_{os.getpid()}"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def _login(emp_id):
    from flask import session

    session["user_id"] = emp_id
    session["role"] = "admin"


def _json(resp):
    if isinstance(resp, tuple):
        resp = resp[0]
    return resp.get_json()


def _purchase_payload(supplier_id, product_id, cash_id, total, paid, qty=5):
    return {
        "supplier_id": supplier_id,
        "purchase_date": "2026-07-10",
        "status": "confirmed",
        "purchase_mode": "mixed",
        "items": [{"product_id": product_id, "quantity": qty, "unit_cost": total // qty}],
        "payments": [
            {
                "amount": paid,
                "payment_method": "cash",
                "treasury_account_id": cash_id,
            }
        ],
    }


def test_cancelled_purchase_delete_and_reopen_do_not_double_reverse_cash():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.employee import Employee
    from models.product import Product
    from models.purchase import Purchase
    from models.supplier import Supplier
    from routes.purchases import cancel_purchase, delete_purchase, purchases_create, reopen_purchase, update_purchase
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        emp = Employee(name="Admin", username="admin_pcr", password="pw", role="admin", is_active=True)
        product = Product(name="Accounting Item", buy_price=1000, sale_price=1500, quantity=0, opening_stock=0, active=True)
        supplier = Supplier(name="Accounting Supplier")
        db.session.add_all([emp, product, supplier])
        db.session.flush()
        cash = get_default_cash_account()
        db.session.add(
            AccountTransaction(
                type="deposit",
                amount=10000,
                note="opening cash for purchase tests",
                treasury_account_id=cash.id,
            )
        )
        db.session.commit()
        emp_id, product_id, supplier_id, cash_id = emp.id, product.id, supplier.id, cash.id

    def create_purchase(total=5000, paid=3000, qty=5):
        payload = _purchase_payload(supplier_id, product_id, cash_id, total, paid, qty)
        with app.test_request_context("/purchases/create", method="POST", json=payload):
            g.tenant = TENANT
            _login(emp_id)
            data = _json(purchases_create())
            assert data["success"], data
            return data["purchase_id"]

    first_purchase_id = create_purchase()
    with app.app_context():
        g.tenant = TENANT
        supplier = Supplier.query.get(supplier_id)
        assert calculate_treasury_balance(cash_id) == 7000
        assert int(supplier.total_debt or 0) == 5000
        assert int(supplier.total_paid or 0) == 3000

    with app.test_request_context(f"/purchases/api/{first_purchase_id}/cancel", method="POST"):
        g.tenant = TENANT
        _login(emp_id)
        data = _json(cancel_purchase(first_purchase_id))
        assert data["success"], data

    with app.app_context():
        g.tenant = TENANT
        supplier = Supplier.query.get(supplier_id)
        assert calculate_treasury_balance(cash_id) == 10000
        assert int(supplier.total_debt or 0) == 0
        assert int(supplier.total_paid or 0) == 0

    with app.test_request_context(f"/purchases/api/{first_purchase_id}/delete", method="POST"):
        g.tenant = TENANT
        _login(emp_id)
        data = _json(delete_purchase(first_purchase_id))
        assert data["success"], data

    with app.app_context():
        g.tenant = TENANT
        supplier = Supplier.query.get(supplier_id)
        assert calculate_treasury_balance(cash_id) == 10000
        assert int(supplier.total_debt or 0) == 0
        assert int(supplier.total_paid or 0) == 0

    second_purchase_id = create_purchase()
    with app.test_request_context(f"/purchases/api/{second_purchase_id}/cancel", method="POST"):
        g.tenant = TENANT
        _login(emp_id)
        data = _json(cancel_purchase(second_purchase_id))
        assert data["success"], data

    with app.test_request_context(f"/purchases/api/{second_purchase_id}/reopen", method="POST"):
        g.tenant = TENANT
        _login(emp_id)
        data = _json(reopen_purchase(second_purchase_id))
        assert data["success"], data

    update_payload = _purchase_payload(supplier_id, product_id, cash_id, total=4000, paid=1000, qty=4)
    with app.test_request_context(f"/purchases/api/{second_purchase_id}/update", method="POST", json=update_payload):
        g.tenant = TENANT
        _login(emp_id)
        data = _json(update_purchase(second_purchase_id))
        assert data["success"], data

    with app.app_context():
        g.tenant = TENANT
        supplier = Supplier.query.get(supplier_id)
        purchase = Purchase.query.get(second_purchase_id)
        assert calculate_treasury_balance(cash_id) == 9000
        assert int(supplier.total_debt or 0) == 4000
        assert int(supplier.total_paid or 0) == 1000
        assert [int(p.amount or 0) for p in purchase.payments] == [1000]


if __name__ == "__main__":
    test_cancelled_purchase_delete_and_reopen_do_not_double_reverse_cash()
    print("purchase cancel/reopen accounting tests passed")
