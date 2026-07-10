"""Regression: supplier receivables must not reduce supplier liabilities."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = "test_supplier_debt_calculations"


def _fresh_tenant_db(tenant=TENANT):
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_supplier_debts_ignore_negative_remaining_balances():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.supplier import Supplier
    from routes.purchases import _get_purchase_stats
    from utils.accounting_calculations import calculate_supplier_debts

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        db.session.add_all(
            [
                Supplier(name="Supplier Debt", total_debt=1000, total_paid=200),
                Supplier(name="Supplier Receivable", total_debt=300, total_paid=900),
                Supplier(name="Supplier Settled", total_debt=500, total_paid=500),
            ]
        )
        db.session.commit()

        assert calculate_supplier_debts() == 800
        stats = _get_purchase_stats()
        assert stats["total_supplier_debts"] == 800
        assert stats["suppliers_with_debt"] == 1


def test_supplier_repair_counts_unlocked_purchase_but_not_clean_draft():
    tenant = f"{TENANT}_repair"
    _fresh_tenant_db(tenant)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.product import Product
    from models.purchase import Purchase
    from models.supplier import Supplier
    from utils.supplier_accounting_repair import expected_supplier_totals

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        supplier = Supplier(name="Repair Supplier")
        product = Product(name="Repair Product", buy_price=100, sale_price=150, quantity=0, opening_stock=0, active=True)
        db.session.add_all([supplier, product])
        db.session.flush()
        db.session.add_all(
            [
                Purchase(
                    supplier_id=supplier.id,
                    product_id=product.id,
                    quantity=1,
                    price=1000,
                    total=1000,
                    grand_total=1000,
                    paid_total=300,
                    remaining_total=700,
                    status="draft",
                    stock_applied=True,
                ),
                Purchase(
                    supplier_id=supplier.id,
                    product_id=product.id,
                    quantity=1,
                    price=900,
                    total=900,
                    grand_total=900,
                    paid_total=200,
                    remaining_total=700,
                    status="draft",
                    stock_applied=False,
                ),
            ]
        )
        db.session.commit()

        assert expected_supplier_totals(supplier.id) == (1000, 300)


if __name__ == "__main__":
    test_supplier_debts_ignore_negative_remaining_balances()
    test_supplier_repair_counts_unlocked_purchase_but_not_clean_draft()
    print("supplier debt calculation tests passed")
