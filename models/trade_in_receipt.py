from datetime import datetime

from extensions import db


class TradeInReceipt(db.Model):
    __tablename__ = "trade_in_receipt"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'received', 'reversed')",
            name="_trade_in_receipt_status_ck",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.Integer,
        db.ForeignKey("invoice.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_item_id = db.Column(
        db.Integer,
        db.ForeignKey("order_item.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    source_product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_product_name = db.Column(db.String(150), nullable=False)
    replacement_product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=True,
    )
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    received_at = db.Column(db.DateTime, nullable=True)
    reversed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    invoice = db.relationship("Invoice", lazy=True)
    order_item = db.relationship("OrderItem", lazy=True)
    source_product = db.relationship("Product", foreign_keys=[source_product_id], lazy=True)
    replacement_product = db.relationship(
        "Product", foreign_keys=[replacement_product_id], lazy=True
    )

    def __repr__(self):
        return (
            f"<TradeInReceipt invoice={self.invoice_id} item={self.order_item_id} "
            f"qty={self.quantity} status={self.status}>"
        )
