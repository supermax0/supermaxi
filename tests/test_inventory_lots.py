import os
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
TENANT = f"test_inventory_lots_{os.getpid()}"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_fifo_lots_keep_each_purchase_cost_and_restore_on_return():
    _fresh_tenant_db()

    from extensions import db
    from models.branch import Branch, BranchStock
    from models.customer import Customer
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from models.employee import Employee  # noqa: F401
    from models.inventory_lot import InventoryLot, OrderItemCostLayer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.page import Page  # noqa: F401
    from models.product import Product
    from models.purchase import Purchase  # noqa: F401
    from models.purchase_item import PurchaseItem  # noqa: F401
    from models.shipping import ShippingCompany  # noqa: F401
    from models.supplier import Supplier  # noqa: F401
    from models.tenant import Tenant  # noqa: F401
    from models.user import User
    from utils.accounting_calculations import calculate_inventory_value, calculate_total_cogs
    from utils.branch_stock_service import receive_stock
    from utils.inventory_lots import ensure_inventory_lot_schema
    from utils.order_stock_lock import StockAction, apply_stock_actions
    from utils.order_stock_policy import restore_order_stock

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{ROOT / 'tenants' / f'{TENANT}.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY="test",
    )
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(
            bind=db.engine,
            tables=[
                Tenant.__table__,
                User.__table__,
                Branch.__table__,
                BranchStock.__table__,
                Customer.__table__,
                Employee.__table__,
                Supplier.__table__,
                Product.__table__,
                ShippingCompany.__table__,
                DeliveryAgent.__table__,
                Page.__table__,
                Purchase.__table__,
                PurchaseItem.__table__,
                Invoice.__table__,
                OrderItem.__table__,
                InventoryLot.__table__,
                OrderItemCostLayer.__table__,
            ],
        )
        ensure_inventory_lot_schema()
        branch = Branch(code="main", name="Main", is_default=True)
        db.session.add(branch)
        db.session.flush()

        customer = Customer(name="Lot Customer", phone="07710000000")
        product = Product(name="Lot Product", buy_price=200, sale_price=300, quantity=0, active=True)
        db.session.add_all([customer, product])
        db.session.flush()

        receive_stock(branch.id, product.id, 45)
        db.session.add_all(
            [
                InventoryLot(
                    product_id=product.id,
                    branch_id=branch.id,
                    quantity=43,
                    remaining_quantity=43,
                    unit_cost=198,
                ),
                InventoryLot(
                    product_id=product.id,
                    branch_id=branch.id,
                    quantity=2,
                    remaining_quantity=2,
                    unit_cost=200,
                ),
            ]
        )
        db.session.flush()

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=44 * 300,
            status="مسدد",
            payment_status="مسدد",
            paid_amount=44 * 300,
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        item = OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=44,
            price=300,
            cost=product.buy_price,
            total=44 * 300,
        )
        db.session.add(item)
        db.session.flush()

        apply_stock_actions([StockAction(product.id, 44, branch.id)], invoice=invoice)
        invoice.stock_is_deducted = True
        db.session.commit()

        layers = OrderItemCostLayer.query.filter_by(order_item_id=item.id).order_by(OrderItemCostLayer.id).all()
        assert [(layer.quantity, layer.unit_cost) for layer in layers] == [(43, 198), (1, 200)]
        assert calculate_total_cogs() == (43 * 198) + 200
        assert calculate_inventory_value() == 200

        first_lot, second_lot = InventoryLot.query.order_by(InventoryLot.id).all()
        assert first_lot.remaining_quantity == 0
        assert second_lot.remaining_quantity == 1

        restore_order_stock(invoice)
        db.session.commit()

        first_lot, second_lot = InventoryLot.query.order_by(InventoryLot.id).all()
        assert first_lot.remaining_quantity == 43
        assert second_lot.remaining_quantity == 2
        assert OrderItemCostLayer.query.filter_by(order_item_id=item.id).count() == 0
