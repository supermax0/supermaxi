import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_order_stock_branch_selection_{os.getpid()}"


def test_selected_branch_is_used_for_payment_stock_deduction():
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
    from utils.branch_stock_service import get_branch_stock, set_branch_stock
    from utils.invoice_schema_guard import ensure_invoice_schema
    from utils.order_stock_policy import (
        OrderStockError,
        ensure_stock_for_transition,
        select_order_stock_branch,
    )
    from utils.order_lifecycle import process_order_return
    from utils.shipping_branch_schedule import set_shipping_branch_schedule

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()
        ensure_branch_schema()

        default_branch = get_default_branch()
        selected_branch = Branch(code="PAY", name="فرع التسديد", is_active=True, is_default=False)
        customer = Customer(name="Payment Branch Customer", phone="07700000991")
        product = Product(name="Payment Branch Item", buy_price=100, sale_price=500, quantity=0, active=True)
        db.session.add_all([selected_branch, customer, product])
        db.session.flush()
        set_branch_stock(default_branch.id, product.id, 0)
        set_branch_stock(selected_branch.id, product.id, 2)

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=default_branch.id,
            total=500,
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
            price=500,
            cost=100,
            total=500,
        )
        db.session.add(item)
        set_shipping_branch_schedule(
            enabled=True,
            day_branch_id=selected_branch.id,
            night_branch_id=selected_branch.id,
            day_start="00:00",
            day_end="23:59",
        )
        db.session.commit()

        # No explicit branch: payment must follow the configured time schedule,
        # not the company's default branch.
        select_order_stock_branch(invoice, None)
        assert ensure_stock_for_transition(invoice, target_payment_status="مسدد") is True
        db.session.commit()

        db.session.refresh(invoice)
        db.session.refresh(item)
        assert invoice.branch_id == selected_branch.id
        assert item.fulfillment_branch_id == selected_branch.id
        assert invoice.stock_is_deducted is True
        assert get_branch_stock(selected_branch.id, product.id) == 1
        assert get_branch_stock(default_branch.id, product.id) == 0

        with pytest.raises(OrderStockError, match="لا يمكن تغيير الفرع"):
            select_order_stock_branch(invoice, default_branch.id)

        invoice.status = "تم التوصيل"
        invoice.payment_status = "مسدد"
        invoice.barcode = "RETURN-TO-BRANCH"
        db.session.commit()

        already_returned, _message = process_order_return(
            invoice,
            "RETURN-TO-BRANCH",
            return_branch_id=default_branch.id,
        )
        db.session.commit()

        assert already_returned is False
        assert invoice.return_branch_id == default_branch.id
        assert invoice.stock_is_deducted is False
        assert get_branch_stock(selected_branch.id, product.id) == 1
        assert get_branch_stock(default_branch.id, product.id) == 1
