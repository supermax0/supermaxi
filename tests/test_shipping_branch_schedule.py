import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_shipping_branch_schedule_{os.getpid()}"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_shipping_schedule_keeps_explicit_fulfillment_branch():
    _fresh_tenant_db()

    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from utils.branch_migration import ensure_branch_schema, get_default_branch
    from utils.branch_stock_service import get_branch_stock, set_branch_stock
    from utils.invoice_schema_guard import ensure_invoice_schema
    from utils.order_stock_policy import ensure_stock_for_transition
    from utils.shipping_branch_schedule import apply_shipping_branch_schedule, set_shipping_branch_schedule

    ordered = "\u062a\u0645 \u0627\u0644\u0637\u0644\u0628"
    unpaid = "\u063a\u064a\u0631 \u0645\u0633\u062f\u062f"
    shipping = "\u062c\u0627\u0631\u064a \u0627\u0644\u0634\u062d\u0646"

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_invoice_schema()
        ensure_branch_schema()

        main = get_default_branch()
        scheduled = Branch(code="SCHEDULED", name="Scheduled Branch", is_active=True, is_default=False)
        customer = Customer(name="Branch Customer", phone="07700000003")
        product = Product(name="Branch Item", buy_price=100, sale_price=500, quantity=0, active=True)
        db.session.add_all([scheduled, customer, product])
        db.session.flush()

        set_branch_stock(main.id, product.id, 1)
        set_branch_stock(scheduled.id, product.id, 0)
        set_shipping_branch_schedule(
            enabled=True,
            day_branch_id=scheduled.id,
            night_branch_id=scheduled.id,
            day_start="00:00",
            day_end="23:59",
        )

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=main.id,
            total=500,
            status=ordered,
            payment_status=unpaid,
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=1,
                price=500,
                cost=100,
                total=500,
                fulfillment_branch_id=main.id,
            )
        )
        db.session.commit()

        ensure_stock_for_transition(invoice, target_status=shipping)
        apply_shipping_branch_schedule(invoice, previous_status=invoice.status)
        invoice.status = shipping
        invoice.shipping_status = shipping
        db.session.commit()

        db.session.refresh(invoice)
        item = OrderItem.query.filter_by(invoice_id=invoice.id).one()
        assert invoice.branch_id == main.id
        assert item.fulfillment_branch_id == main.id
        assert invoice.stock_is_deducted is True
        assert get_branch_stock(main.id, product.id) == 0
        assert get_branch_stock(scheduled.id, product.id) == 0
