# models/order_item.py
from extensions import db

class OrderItem(db.Model):
    __tablename__ = "order_item"

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

    # =====================
    # Relations
    # =====================
    invoice = db.relationship(
    "Invoice",
    back_populates="items"
)

    product = db.relationship("Product", back_populates="order_items")

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
