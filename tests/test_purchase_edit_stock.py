"""Regression test: editing a confirmed purchase applies only the quantity delta.

Scenario that used to fail:
1. Create a confirmed purchase with qty 2 -> stock +2, stock_applied=1.
2. Unlock the invoice for editing (status becomes draft, stock_applied stays 1).
3. Any later request ran a schema guard that reset stock_applied to 0 for
   draft invoices, so saving the edit skipped the stock reversal and applied
   the new quantity again.
4. Change qty 2 -> 3. The final stock must be 3, never 5.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = "test_purchase_edit_stock"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def _login(sess_target, emp_id):
    from flask import session

    session["user_id"] = emp_id
    session["role"] = "admin"


def test_purchase_edit_keeps_stock():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.employee import Employee
    from models.product import Product
    from models.supplier import Supplier

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        emp = Employee(name="Admin", username="admin_pes", password="pw", role="admin", is_active=True)
        product = Product(name="Test TV", buy_price=100, sale_price=150, quantity=0, opening_stock=0, active=True)
        supplier = Supplier(name="Test Supplier")
        db.session.add_all([emp, product, supplier])
        db.session.commit()
        emp_id, product_id, supplier_id = emp.id, product.id, supplier.id

    from routes.purchases import (
        _ensure_purchase_schema,
        purchases_create,
        unlock_purchase_for_edit,
        update_purchase,
    )
    from models.purchase import Purchase

    payload = {
        "supplier_id": supplier_id,
        "purchase_date": "2026-07-07",
        "status": "confirmed",
        "purchase_mode": "credit",
        "items": [{"product_id": product_id, "quantity": 2, "unit_cost": 100}],
    }

    # 1) Create confirmed purchase qty 2
    with app.test_request_context("/purchases/create", method="POST", json=payload):
        g.tenant = TENANT
        _login(None, emp_id)
        resp = purchases_create()
        data = resp.get_json() if hasattr(resp, "get_json") else resp[0].get_json()
        assert data["success"], data
        purchase_id = data["purchase_id"]

    with app.app_context():
        g.tenant = TENANT
        qty = int(Product.query.get(product_id).quantity or 0)
        assert qty == 2, f"expected stock 2 after create, got {qty}"
        assert bool(Purchase.query.get(purchase_id).stock_applied)
    print("create confirmed qty=2 -> stock=2 ok")

    # 2) Unlock the confirmed invoice for editing
    with app.test_request_context(f"/purchases/api/{purchase_id}/unlock-edit", method="POST"):
        g.tenant = TENANT
        _login(None, emp_id)
        resp = unlock_purchase_for_edit(purchase_id)
        data = resp.get_json() if hasattr(resp, "get_json") else resp[0].get_json()
        assert data["success"], data

    # 3) Simulate other requests running the schema guard before the save.
    #    This is what used to reset stock_applied for draft invoices.
    with app.app_context():
        g.tenant = TENANT
        _ensure_purchase_schema()
        purchase = Purchase.query.get(purchase_id)
        assert (purchase.status or "").lower() == "draft"
        assert bool(purchase.stock_applied), (
            "stock_applied must survive schema guard after unlock-edit"
        )
    print("unlock-edit keeps stock_applied=1 after schema guard ok")

    # 4) Save the edit (qty 2 -> 3, confirmed)
    edited_payload = {
        **payload,
        "items": [{**payload["items"][0], "quantity": 3}],
    }
    with app.test_request_context(f"/purchases/api/{purchase_id}/update", method="POST", json=edited_payload):
        g.tenant = TENANT
        _login(None, emp_id)
        resp = update_purchase(purchase_id)
        data = resp.get_json() if hasattr(resp, "get_json") else resp[0].get_json()
        assert data["success"], data

    with app.app_context():
        g.tenant = TENANT
        qty = int(Product.query.get(product_id).quantity or 0)
        assert qty == 3, f"stock duplicated on edit: expected 3, got {qty}"

        from models.stock_movement import StockMovement

        movements = StockMovement.query.filter_by(
            source_type="purchase",
            source_id=purchase_id,
        ).all()
        assert len(movements) == 3
        assert sum(m.quantity for m in movements if m.direction == "in") == 5
        assert sum(m.quantity for m in movements if m.direction == "out") == 2

        from utils.inventory_movements import get_product_inventory_summary

        summary = get_product_inventory_summary(product_id)
        assert summary["is_balanced"], summary
    print("edit confirmed purchase qty 2 -> 3 keeps stock=3 and movement keys unique")


if __name__ == "__main__":
    test_purchase_edit_keeps_stock()
    print("purchase edit stock tests passed")
