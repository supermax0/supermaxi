"""Accounting invariants for FIFO supplier-payment allocation."""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _tenant_name(suffix: str) -> str:
    return f"test_supplier_allocation_{os.getpid()}_{suffix}"


def _fresh_tenant_db(tenant: str) -> None:
    db_file = ROOT / "tenants" / f"{tenant}.db"
    for candidate in (
        db_file,
        Path(str(db_file) + "-shm"),
        Path(str(db_file) + "-wal"),
    ):
        if candidate.exists():
            candidate.unlink()


def _create_purchase(
    *,
    supplier,
    product,
    invoice_no: str,
    amount: int,
    purchase_date: date,
    paid_total: int = 0,
    created_at: datetime | None = None,
):
    from models.purchase import Purchase

    return Purchase(
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=1,
        price=amount,
        total=amount,
        invoice_no=invoice_no,
        status="confirmed",
        grand_total=amount,
        paid_total=paid_total,
        remaining_total=max(amount - paid_total, 0),
        purchase_date=purchase_date,
        created_at=created_at or datetime.utcnow(),
        stock_applied=True,
    )


def test_fifo_allocation_clears_oldest_invoices_before_unitemized_opening_balance():
    tenant = _tenant_name("fifo")
    _fresh_tenant_db(tenant)

    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.product import Product
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment
    from models.supplier_payment_allocation import SupplierPaymentAllocation
    from utils.supplier_accounting_repair import expected_supplier_totals
    from routes.suppliers import _supplier_statement_context
    from utils.supplier_payment_allocation import (
        OPENING_BALANCE,
        PURCHASE,
        allocate_supplier_payment_fifo,
        effective_purchase_payment_totals,
    )

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)

        supplier = Supplier(
            name="FIFO Supplier",
            opening_balance=200,
            total_debt=2200,
            total_paid=100,
        )
        product = Product(
            name="FIFO Product",
            buy_price=1000,
            sale_price=1200,
            quantity=2,
        )
        db.session.add_all([supplier, product])
        db.session.flush()

        old_purchase = _create_purchase(
            supplier=supplier,
            product=product,
            invoice_no="PUR-OLD",
            amount=1000,
            paid_total=100,
            purchase_date=date.today() - timedelta(days=2),
        )
        new_purchase = _create_purchase(
            supplier=supplier,
            product=product,
            invoice_no="PUR-NEW",
            amount=1000,
            purchase_date=date.today() - timedelta(days=1),
        )
        db.session.add_all([old_purchase, new_purchase])
        db.session.flush()

        payment = SupplierPayment(
            supplier_id=supplier.id,
            amount=1400,
            payment_method="cash",
            created_at=datetime.utcnow(),
        )
        supplier.total_paid += payment.amount
        db.session.add(payment)
        db.session.flush()
        result = allocate_supplier_payment_fifo(payment, supplier=supplier)
        db.session.commit()

        allocations = (
            SupplierPaymentAllocation.query.filter_by(
                supplier_payment_id=payment.id
            )
            .order_by(SupplierPaymentAllocation.id)
            .all()
        )
        assert sum(row.amount for row in allocations) == 1400
        assert [
            (row.allocation_type, row.purchase_id, row.amount)
            for row in allocations
        ] == [
            (PURCHASE, old_purchase.id, 900),
            (PURCHASE, new_purchase.id, 500),
        ]
        assert result.opening_balance_amount == 0
        assert result.purchase_amount == 1400

        assert effective_purchase_payment_totals(old_purchase) == (1000, 0, 900)
        assert effective_purchase_payment_totals(new_purchase) == (500, 500, 500)

        # Initial invoice payments + supplier payments are counted once each.
        assert expected_supplier_totals(supplier.id) == (2200, 1500)
        assert supplier.total_paid == 1500
        assert supplier.remaining == 700

        statement = _supplier_statement_context(supplier)
        invoice_rows = {
            row["invoice_no"]: row for row in statement["purchase_invoices"]
        }
        assert invoice_rows["PUR-OLD"]["paid_total"] == 1000
        assert invoice_rows["PUR-OLD"]["remaining_total"] == 0
        assert invoice_rows["PUR-NEW"]["paid_total"] == 500
        assert invoice_rows["PUR-NEW"]["remaining_total"] == 500


def test_legacy_backfill_is_idempotent_and_deleting_payment_reverses_only_its_allocations():
    tenant = _tenant_name("legacy")
    _fresh_tenant_db(tenant)

    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.product import Product
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment
    from models.supplier_payment_allocation import SupplierPaymentAllocation
    from utils.supplier_payment_allocation import (
        backfill_supplier_payment_allocations,
        effective_purchase_payment_totals,
    )

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)

        base_time = datetime(2026, 7, 4, 10, 0, 0)
        supplier = Supplier(
            name="Legacy Supplier",
            opening_balance=34_093_575,
            total_debt=37_772_325,
            total_paid=4_050_000,
        )
        product = Product(
            name="Legacy Product",
            buy_price=1,
            sale_price=2,
            quantity=3,
        )
        db.session.add_all([supplier, product])
        db.session.flush()

        invoices = [
            _create_purchase(
                supplier=supplier,
                product=product,
                invoice_no="PUR-1",
                amount=1_161_000,
                purchase_date=date(2026, 7, 4),
                created_at=base_time,
            ),
            _create_purchase(
                supplier=supplier,
                product=product,
                invoice_no="PUR-2",
                amount=904_500,
                purchase_date=date(2026, 7, 4),
                created_at=base_time + timedelta(hours=2),
            ),
            _create_purchase(
                supplier=supplier,
                product=product,
                invoice_no="PUR-3",
                amount=904_500,
                purchase_date=date(2026, 7, 5),
                created_at=base_time + timedelta(days=1),
            ),
            _create_purchase(
                supplier=supplier,
                product=product,
                invoice_no="PUR-4",
                amount=708_750,
                purchase_date=date(2026, 7, 5),
                created_at=base_time + timedelta(days=1, hours=2),
            ),
        ]
        payments = [
            SupplierPayment(
                supplier_id=supplier.id,
                amount=2_700_000,
                payment_method="cash",
                created_at=base_time + timedelta(minutes=37),
            ),
            SupplierPayment(
                supplier_id=supplier.id,
                amount=1_350_000,
                payment_method="cash",
                created_at=base_time + timedelta(days=1, hours=3),
            ),
        ]
        db.session.add_all([*invoices, *payments])
        db.session.commit()

        assert backfill_supplier_payment_allocations(supplier.id) == 5_217_750
        db.session.commit()
        assert backfill_supplier_payment_allocations(supplier.id) == 0
        db.session.commit()

        assert effective_purchase_payment_totals(invoices[0]) == (
            1_161_000,
            0,
            1_161_000,
        )
        assert effective_purchase_payment_totals(invoices[1]) == (
            904_500,
            0,
            904_500,
        )
        assert effective_purchase_payment_totals(invoices[2]) == (
            904_500,
            0,
            904_500,
        )
        assert effective_purchase_payment_totals(invoices[3]) == (
            708_750,
            0,
            708_750,
        )
        opening_allocated = sum(
            row.amount
            for row in SupplierPaymentAllocation.query.filter_by(
                allocation_type="opening_balance"
            ).all()
        )
        assert opening_allocated == 371_250

        payment_id = payments[0].id
        db.session.delete(payments[0])
        db.session.commit()
        assert (
            SupplierPaymentAllocation.query.filter_by(
                supplier_payment_id=payment_id
            ).count()
            == 0
        )
        assert effective_purchase_payment_totals(invoices[0]) == (
            0,
            1_161_000,
            0,
        )


def test_on_account_credit_is_applied_when_a_later_invoice_becomes_available():
    tenant = _tenant_name("cutoff")
    _fresh_tenant_db(tenant)

    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.product import Product
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment
    from utils.supplier_payment_allocation import (
        ON_ACCOUNT,
        allocate_supplier_payment_fifo,
        backfill_supplier_payment_allocations,
        effective_purchase_payment_totals,
    )

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)

        now = datetime.utcnow()
        supplier = Supplier(
            name="Advance Supplier",
            opening_balance=0,
            total_debt=500,
            total_paid=500,
        )
        product = Product(
            name="Advance Product",
            buy_price=500,
            sale_price=600,
            quantity=1,
        )
        db.session.add_all([supplier, product])
        db.session.flush()

        future_purchase = _create_purchase(
            supplier=supplier,
            product=product,
            invoice_no="PUR-FUTURE",
            amount=500,
            purchase_date=date.today(),
            created_at=now + timedelta(hours=1),
        )
        payment = SupplierPayment(
            supplier_id=supplier.id,
            amount=500,
            payment_method="cash",
            created_at=now,
        )
        db.session.add_all([future_purchase, payment])
        db.session.flush()
        result = allocate_supplier_payment_fifo(payment, supplier=supplier)
        db.session.commit()

        assert result.purchase_amount == 0
        assert result.on_account_amount == 500
        assert payment.allocations[0].allocation_type == ON_ACCOUNT
        assert effective_purchase_payment_totals(future_purchase) == (0, 500, 0)

        assert backfill_supplier_payment_allocations(supplier.id) == 500
        db.session.commit()
        assert effective_purchase_payment_totals(future_purchase) == (500, 0, 500)


if __name__ == "__main__":
    pytest.main([__file__])
