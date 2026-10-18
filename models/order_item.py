# models/order_item.py
from extensions import db

class OrderItem(db.Model):
    __tablename__ = "order_item"
    __table_args__ = (
        db.CheckConstraint(
            "sale_mode IN ('normal', 'exchange')",
            name="_order_item_sale_mode_ck",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)


    invoice_id = db.Column(
        db.Integer,
        db.ForeignKey("invoice.id"),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id"),  # 🔑 هذا المفتاح المهم
        nullable=False
    )

    fulfillment_branch_id = db.Column(
        db.Integer,
        db.ForeignKey("branch.id"),
        nullable=True,
    )

    # =====================
    # Relations
    # =====================
    invoice = db.relationship(
    "Invoice",
    back_populates="items"
)

    product = db.relationship(
        "Product",
        back_populates="order_items",
        foreign_keys=[product_id],
    )

    # =====================
    # Product Snapshot
    # =====================
    product_name = db.Column(
        db.String(150),
        nullable=False
    )

    price = db.Column(
        db.Integer,
        nullable=False
    )  # سعر البيع وقت الطلب

    quantity = db.Column(
        db.Integer,
        nullable=False
    )
    
    cost = db.Column(db.Integer, nullable=False)

    total = db.Column(
        db.Integer,
        nullable=False
    )

    discount_value = db.Column(db.Integer, nullable=True, default=0)
    warehouse_id = db.Column(db.Integer, nullable=True)

    variant_color = db.Column(db.String(80), nullable=True)
    sale_mode = db.Column(db.String(20), nullable=False, default="normal")
    trade_in_source_product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id", ondelete="SET NULL"),
        nullable=True,
    )
    trade_in_source_product_name = db.Column(db.String(150), nullable=True)
    trade_in_source_product = db.relationship(
        "Product",
        foreign_keys=[trade_in_source_product_id],
        lazy=True,
    )

    @property
    def display_name(self):
        name = (self.product_name or "").strip() or (
            (self.product.name or "").strip() if self.product else "منتج"
        )
        parts = [name]
        if (self.variant_color or "").strip():
            parts.append(self.variant_color.strip())
        if (self.sale_mode or "normal") == "exchange":
            parts.append("استبدال")
        else:
            parts.append("بيع")
        return " — ".join(parts)

    # =====================
    # Helper
    # =====================
    def __repr__(self):
        return (
            f"<OrderItem "
            f"Invoice:{self.invoice_id} "
            f"Product:{self.product_name} "
            f"Qty:{self.quantity} "
            f"Total:{self.total}>"
        )
