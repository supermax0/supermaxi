"""Regression tests for supplier statement accounting totals."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = "test_supplier_statement_context"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_supplier_statement_uses_invoice_totals_and_offsets():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.product import Product
    from models.purchase import Purchase
    from models.purchase_item import PurchaseItem
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment
    from models.supplier_sale import SupplierSale
    from routes.suppliers import _supplier_statement_context

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)

        supplier = Supplier(
            name="Statement Supplier",
            opening_balance=1000,
            total_debt=6000,
            total_paid=2500,
        )
        product = Product(name="Statement Product", buy_price=2500, sale_price=3000, quantity=10)
        db.session.add_all([supplier, product])
        db.session.flush()

        purchase = Purchase(
            supplier_id=supplier.id,
            product_id=product.id,
            quantity=2,
            price=2500,
            total=5000,
            invoice_no="PUR-1",
            status="confirmed",
            grand_total=5000,
            paid_total=1500,
            remaining_total=3500,
            purchase_date=date.today(),
        )
        db.session.add(purchase)
        db.session.flush()
        db.session.add(
            PurchaseItem(
                purchase_id=purchase.id,
                product_id=product.id,
                quantity=2,
                final_unit_cost=2500,
                line_total=5000,
            )
        )

        sale = SupplierSale(
            supplier_id=supplier.id,
            invoice_no="SS-1",
            status="confirmed",
            grand_total=1000,
            sale_date=date.today(),
        )
        db.session.add(sale)
        db.session.flush()
        db.session.add_all(
            [
                SupplierPayment(
                    supplier_id=supplier.id,
                    amount=1500,
                    payment_method="cash",
                    note="cash payment",
                ),
                SupplierPayment(
                    supplier_id=supplier.id,
                    amount=1000,
                    payment_method="offset",
                    supplier_sale_id=sale.id,
                    note="supplier sale offset",
                ),
            ]
        )
        db.session.commit()

        statement = _supplier_statement_context(supplier)

        assert statement["total_purchase"] == 5000
        assert statement["total_sales"] == 1000
        assert statement["total_cash_paid"] == 1500
        assert statement["total_offset_paid"] == 1000
        assert statement["total_paid"] == 2500
        assert statement["total_debt"] == 6000
        assert statement["remaining"] == 3500
        assert statement["purchase_invoices"][0]["grand_total"] == 5000
        assert statement["purchase_invoices"][0]["remaining_total"] == 3500


if __name__ == "__main__":
    test_supplier_statement_uses_invoice_totals_and_offsets()
    print("supplier statement context tests passed")
