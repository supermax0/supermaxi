"""Exactly-once inventory protection for deferred order workflows."""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_order_stock_exactly_once_{os.getpid()}"


def test_branch_selection_status_retries_and_restore_touch_stock_once():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.branch import Branch
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from utils.branch_migration import ensure_branch_schema, get_default_branch
    from utils.branch_sales import reassign_item_fulfillment_branch
    from utils.branch_stock_service import get_branch_stock, receive_stock, set_branch_stock
    from utils.invoice_schema_guard import ensure_invoice_schema
    from utils.order_stock_policy import (
        ensure_stock_for_transition,
        repair_duplicate_order_restores,
        restore_order_stock,
        set_packed_stock_deduction_policy,
    )
    from utils.stock_movement_guard import claim_stock_movement

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()
        ensure_branch_schema()
        set_packed_stock_deduction_policy(True)

        original_branch = get_default_branch()
        selected_branch = Branch(
            code="ONCE",
            name="فرع الحماية",
            is_active=True,
            is_default=False,
        )
        customer = Customer(name="Exactly Once Customer", phone="07700000888")
        product = Product(
            name="Exactly Once Item",
            buy_price=100,
            sale_price=200,
            quantity=0,
            active=True,
        )
        db.session.add_all([selected_branch, customer, product])
        db.session.flush()
        set_branch_stock(original_branch.id, product.id, 5)
        set_branch_stock(selected_branch.id, product.id, 5)

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=original_branch.id,
            total=200,
            status="تم الطلب",
            payment_status="غير مسدد",
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        item = OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            price=200,
            cost=100,
            total=200,
        )
        db.session.add(item)
        db.session.commit()

        # Agent-report preparation may select a branch, but it must not reserve
        # or deduct physical inventory while the invoice guard is false.
        reassign_item_fulfillment_branch(
            item,
            selected_branch.id,
            inventory_is_deducted=invoice.stock_is_deducted,
        )
        invoice.branch_id = selected_branch.id
        db.session.commit()
        assert item.fulfillment_branch_id == selected_branch.id
        assert get_branch_stock(original_branch.id, product.id) == 5
        assert get_branch_stock(selected_branch.id, product.id) == 5

        # First stock-owning status deducts once. Repeating status transitions
        # cannot deduct again because the invoice flag was atomically claimed.
        assert ensure_stock_for_transition(invoice, target_status="معباة") is True
        invoice.status = "معباة"
        db.session.commit()
        assert invoice.stock_is_deducted is True
        assert get_branch_stock(selected_branch.id, product.id) == 4

        assert ensure_stock_for_transition(invoice, target_status="معباة") is False
        assert ensure_stock_for_transition(invoice, target_status="جاري الشحن") is False
        invoice.status = "جاري الشحن"
        db.session.commit()
        assert get_branch_stock(selected_branch.id, product.id) == 4

        # Once deducted, changing the branch moves the same reserved unit; it
        # does not create a second reservation.
        reassign_item_fulfillment_branch(
            item,
            original_branch.id,
            inventory_is_deducted=invoice.stock_is_deducted,
        )
        invoice.branch_id = original_branch.id
        db.session.commit()
        assert get_branch_stock(selected_branch.id, product.id) == 5
        assert get_branch_stock(original_branch.id, product.id) == 4

        # Return/cancel restoration is also guarded and therefore idempotent.
        assert restore_order_stock(invoice) is True
        db.session.commit()
        assert get_branch_stock(original_branch.id, product.id) == 5
        assert restore_order_stock(invoice) is False
        db.session.commit()
        assert get_branch_stock(original_branch.id, product.id) == 5

        # A stale/manual flag must never allow another inbound restore when no
        # newer outbound deduction exists.
        invoice.stock_is_deducted = True
        db.session.commit()
        assert restore_order_stock(invoice) is False
        db.session.commit()
        assert get_branch_stock(original_branch.id, product.id) == 5

        from models.stock_movement import StockMovement

        movements = StockMovement.query.filter_by(
            source_type="invoice",
            source_id=invoice.id,
        ).all()
        assert len(movements) == 4
        assert len({m.movement_key for m in movements}) == 4
        assert sum(m.quantity for m in movements if m.direction == "in") == 2
        assert sum(m.quantity for m in movements if m.direction == "out") == 2

        # Simulate a historical duplicate already applied before the guard was
        # introduced, then verify the auditable one-time repair removes only
        # the excess unit and remains idempotent.
        claim_stock_movement(
            f"order:{invoice.id}:item:{item.id}:restore:v2",
            movement_type="order_restore",
            direction="in",
            product_id=product.id,
            branch_id=original_branch.id,
            quantity=1,
            unit_cost=100,
            source_type="invoice",
            source_id=invoice.id,
            source_line_id=item.id,
            details={"return_branch_id": original_branch.id, "variant_color": None},
        )
        receive_stock(original_branch.id, product.id, 1)
        db.session.commit()
        assert get_branch_stock(original_branch.id, product.id) == 6

        repaired = repair_duplicate_order_restores(invoice.id)
        db.session.commit()
        assert repaired["repaired"] == 1
        assert repaired["repaired_units"] == 1
        assert repaired["errors"] == []
        assert get_branch_stock(original_branch.id, product.id) == 5

        repeated = repair_duplicate_order_restores(invoice.id)
        db.session.commit()
        assert repeated["repaired"] == 0
        assert repeated["skipped"] == 1
        assert get_branch_stock(original_branch.id, product.id) == 5

        # Exact production regression: one unit left the main branch, was
        # returned wrongly to another branch, then returned correctly to main.
        # Keep the main return and reverse the unrelated branch increase.
        product2 = Product(
            name="Duplicate Branch Return Item",
            buy_price=120,
            sale_price=240,
            quantity=0,
            active=True,
        )
        db.session.add(product2)
        db.session.flush()
        invoice2 = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=original_branch.id,
            total=240,
            status="تم الطلب",
            payment_status="غير مسدد",
            stock_is_deducted=False,
        )
        db.session.add(invoice2)
        db.session.flush()
        item2 = OrderItem(
            invoice_id=invoice2.id,
            product_id=product2.id,
            product_name=product2.name,
            quantity=1,
            price=240,
            cost=120,
            total=240,
            fulfillment_branch_id=original_branch.id,
        )
        db.session.add(item2)
        db.session.flush()
        claim_stock_movement(
            f"order:{invoice2.id}:item:{item2.id}:deduct:v1",
            movement_type="order_deduct",
            direction="out",
            product_id=product2.id,
            branch_id=original_branch.id,
            quantity=1,
            unit_cost=120,
            source_type="invoice",
            source_id=invoice2.id,
            source_line_id=item2.id,
            details={"variant_color": None},
        )
        claim_stock_movement(
            f"order:{invoice2.id}:item:{item2.id}:restore:v1",
            movement_type="order_restore",
            direction="in",
            product_id=product2.id,
            branch_id=selected_branch.id,
            quantity=1,
            unit_cost=120,
            source_type="invoice",
            source_id=invoice2.id,
            source_line_id=item2.id,
            details={"return_branch_id": selected_branch.id, "variant_color": None},
        )
        claim_stock_movement(
            f"order:{invoice2.id}:item:{item2.id}:restore:v2",
            movement_type="order_restore",
            direction="in",
            product_id=product2.id,
            branch_id=original_branch.id,
            quantity=1,
            unit_cost=120,
            source_type="invoice",
            source_id=invoice2.id,
            source_line_id=item2.id,
            details={"return_branch_id": original_branch.id, "variant_color": None},
        )
        set_branch_stock(original_branch.id, product2.id, 1)
        set_branch_stock(selected_branch.id, product2.id, 1)
        db.session.commit()

        branch_repair = repair_duplicate_order_restores(invoice2.id)
        db.session.commit()
        assert branch_repair["repaired"] == 1
        assert branch_repair["errors"] == []
        assert get_branch_stock(original_branch.id, product2.id) == 1
        assert get_branch_stock(selected_branch.id, product2.id) == 0
        correction = StockMovement.query.filter_by(
            reversal_of_key=f"order:{invoice2.id}:item:{item2.id}:restore:v1",
            movement_type="order_restore_correction",
        ).one()
        assert correction.branch_id == selected_branch.id
