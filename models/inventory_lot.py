from extensions import db
from datetime import datetime


class InventoryLot(db.Model):
    __tablename__ = "inventory_lot"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    purchase_item_id = db.Column(db.Integer, db.ForeignKey("purchase_item.id"), nullable=True, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    variant_color = db.Column(db.String(80), nullable=True, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    remaining_quantity = db.Column(db.Integer, nullable=False, default=0)
    unit_cost = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    product = db.relationship("Product", lazy=True)
    purchase_item = db.relationship("PurchaseItem", lazy=True)


class OrderItemCostLayer(db.Model):
    __tablename__ = "order_item_cost_layer"

    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey("order_item.id"), nullable=False, index=True)
    inventory_lot_id = db.Column(db.Integer, db.ForeignKey("inventory_lot.id"), nullable=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    unit_cost = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    order_item = db.relationship("OrderItem", lazy=True)
    inventory_lot = db.relationship("InventoryLot", lazy=True)
    product = db.relationship("Product", lazy=True)
