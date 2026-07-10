"""Regression: returning/canceling colored products restores color stock."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT_COLOR = f"test_order_lifecycle_color_stock_{os.getpid()}"
TENANT_SHIPPING = f"test_order_lifecycle_shipping_stock_{os.getpid()}"


def _fresh_tenant_db(tenant: str):
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_cancel_restores_variant_color_stock():
    _fresh_tenant_db(TENANT_COLOR)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from utils.order_lifecycle import process_order_cancel

    with app.app_context():
        g.tenant = TENANT_COLOR
        init_tenant_db(TENANT_COLOR)

        customer = Customer(name="Color Customer", phone="07700000000")
        product = Product(
            name="Color Bag",
            buy_price=100,
            sale_price=150,
            quantity=3,
            opening_stock=5,
            active=True,
            meta_json=json.dumps({"has_colors": True}),
        )
        db.session.add_all([customer, product])
        db.session.flush()

        db.session.add(ProductColorVariant(product_id=product.id, color_name="red", quantity=3))
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=300,
            status="تم الطلب",
            payment_status="غير مسدد",
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=2,
                price=150,
                cost=100,
                total=300,
                variant_color="red",
            )
        )
        db.session.commit()

        process_order_cancel(invoice)
        db.session.commit()

        refreshed = Product.query.get(product.id)
        color = ProductColorVariant.query.filter_by(product_id=product.id, color_name="red").first()
        assert int(color.quantity or 0) == 5
        assert int(refreshed.quantity or 0) == 5


def test_cancel_does_not_restore_shipping_fee_item_to_stock():
    _fresh_tenant_db(TENANT_SHIPPING)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from utils.order_lifecycle import process_order_cancel
    from utils.order_shipping import SHIPPING_BARCODE, SHIPPING_PRODUCT_NAME

    with app.app_context():
        g.tenant = TENANT_SHIPPING
        init_tenant_db(TENANT_SHIPPING)

        customer = Customer(name="Shipping Customer", phone="07720000000")
        shipping_product = Product(
            name=SHIPPING_PRODUCT_NAME,
            barcode=SHIPPING_BARCODE,
            buy_price=0,
            sale_price=0,
            quantity=0,
            active=False,
        )
        db.session.add_all([customer, shipping_product])
        db.session.flush()

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=10000,
            status="تم الطلب",
            payment_status="غير مسدد",
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=shipping_product.id,
                product_name=SHIPPING_PRODUCT_NAME,
                quantity=1,
                price=0,
                cost=10000,
                total=0,
            )
        )
        db.session.commit()

        process_order_cancel(invoice)
        db.session.commit()

        refreshed = Product.query.get(shipping_product.id)
        assert int(refreshed.quantity or 0) == 0


if __name__ == "__main__":
    test_cancel_restores_variant_color_stock()
    test_cancel_does_not_restore_shipping_fee_item_to_stock()
    print("order lifecycle color stock tests passed")
