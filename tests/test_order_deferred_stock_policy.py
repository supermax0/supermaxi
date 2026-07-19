"""Regression coverage for deferred pending-order inventory."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_deferred_stock_{os.getpid()}"


def _response(result):
    if isinstance(result, tuple):
        return result[0].get_json(), result[1]
    return result.get_json(), 200


def test_deferred_cancel_transition_and_manual_bulk_allocation():
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.system_settings import SystemSettings
    from routes.orders import bulk_status, payment
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import get_branch_stock, set_branch_stock
    from utils.invoice_schema_guard import ensure_invoice_schema
    from utils.order_lifecycle import process_order_cancel
    from utils.order_stock_policy import POLICY_FLAG, POLICY_INITIALIZED_FLAG
    from utils.order_stock_policy import set_deferred_stock_policy

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags()
        flags[POLICY_FLAG] = False
        flags[POLICY_INITIALIZED_FLAG] = True
        settings.set_ui_flags(flags)

        customer = Customer(name="Deferred Customer", phone="07790000000")
        product = Product(name="One Piece", buy_price=100, sale_price=200, quantity=0, active=True)
        db.session.add_all([customer, product])
        db.session.flush()
        branch = get_default_branch()

        legacy_unpaid_product = Product(name="Legacy Unpaid", buy_price=10, sale_price=20, quantity=0, active=True)
        legacy_partial_product = Product(name="Legacy Partial", buy_price=10, sale_price=20, quantity=0, active=True)
        db.session.add_all([legacy_unpaid_product, legacy_partial_product])
        db.session.flush()
        legacy_unpaid = Invoice(
            customer_id=customer.id, customer_name=customer.name, branch_id=branch.id,
            total=40, status="تم الطلب", payment_status="غير مسدد", stock_is_deducted=True,
        )
        legacy_partial = Invoice(
            customer_id=customer.id, customer_name=customer.name, branch_id=branch.id,
            total=20, status="تم الطلب", payment_status="جزئي", paid_amount=10,
            stock_is_deducted=True,
        )
        db.session.add_all([legacy_unpaid, legacy_partial])
        db.session.flush()
        db.session.add_all([
            OrderItem(invoice_id=legacy_unpaid.id, product_id=legacy_unpaid_product.id, product_name=legacy_unpaid_product.name, quantity=2, price=20, cost=10, total=40, fulfillment_branch_id=branch.id),
            OrderItem(invoice_id=legacy_partial.id, product_id=legacy_partial_product.id, product_name=legacy_partial_product.name, quantity=1, price=20, cost=10, total=20, fulfillment_branch_id=branch.id),
        ])
        db.session.commit()
        migration = set_deferred_stock_policy(True)
        assert migration["restored_orders"] == 1
        assert get_branch_stock(branch.id, legacy_unpaid_product.id) == 2
        assert legacy_unpaid.stock_is_deducted is False
        assert get_branch_stock(branch.id, legacy_partial_product.id) == 0
        assert legacy_partial.stock_is_deducted is True

        set_branch_stock(branch.id, product.id, 1)

        cancel_invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=branch.id,
            total=200,
            status="تم الطلب",
            payment_status="غير مسدد",
            stock_is_deducted=False,
        )
        db.session.add(cancel_invoice)
        db.session.flush()
        db.session.add(OrderItem(
            invoice_id=cancel_invoice.id, product_id=product.id, product_name=product.name,
            quantity=1, price=200, cost=100, total=200,
        ))
        db.session.commit()
        process_order_cancel(cancel_invoice)
        db.session.commit()
        assert get_branch_stock(branch.id, product.id) == 1
        assert cancel_invoice.stock_is_deducted is False

        orders = []
        for suffix in ("A", "B"):
            invoice = Invoice(
                customer_id=customer.id,
                customer_name=f"{customer.name} {suffix}",
                branch_id=branch.id,
                total=200,
                status="تم الطلب",
                payment_status="غير مسدد",
                stock_is_deducted=False,
            )
            db.session.add(invoice)
            db.session.flush()
            db.session.add(OrderItem(
                invoice_id=invoice.id, product_id=product.id, product_name=product.name,
                quantity=1, price=200, cost=100, total=200,
            ))
            orders.append(invoice)
        db.session.commit()
        ids = [o.id for o in orders]

    with app.test_request_context("/orders/bulk-status", method="POST", json={"order_ids": ids, "status": "معباة"}):
        g.tenant = TENANT
        data, status = _response(bulk_status())
        assert status == 409
        assert data["code"] == "STOCK_SELECTION_REQUIRED"
        assert len(data["orders"]) == 2

    with app.test_request_context("/orders/bulk-status", method="POST", json={
        "order_ids": ids, "selected_order_ids": [ids[0]], "status": "معباة",
    }):
        g.tenant = TENANT
        data, status = _response(bulk_status())
        assert status == 200
        assert data["success"] is True
        assert data["updated_ids"] == [ids[0]]

    with app.app_context():
        g.tenant = TENANT
        first = Invoice.query.get(ids[0])
        second = Invoice.query.get(ids[1])
        branch = get_default_branch()
        assert first.status == "معباة"
        assert first.stock_is_deducted is True
        assert second.status == "تم الطلب"
        assert second.stock_is_deducted is False
        assert get_branch_stock(branch.id, first.items[0].product_id) == 0

    with app.test_request_context("/orders/payment", method="POST", json={
        "id": ids[1], "payment": "جزئي", "paid_amount": 50,
    }):
        g.tenant = TENANT
        data, status = _response(payment())
        assert status == 409
        assert data["code"] == "INSUFFICIENT_STOCK"

    with app.app_context():
        g.tenant = TENANT
        second = Invoice.query.get(ids[1])
        assert second.status == "تم الطلب"
        assert second.payment_status == "غير مسدد"
        assert int(second.paid_amount or 0) == 0
        assert second.stock_is_deducted is False
