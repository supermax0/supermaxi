from extensions import db
from datetime import datetime

class Purchase(db.Model):
    __tablename__ = "purchase"

    id = db.Column(db.Integer, primary_key=True)

    # =====================
    # Relations (FK فقط)
    # =====================
    supplier_id = db.Column(
        db.Integer,
        db.ForeignKey("supplier.id"),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id"),
        nullable=False
    )

    # =====================
    # Purchase Info
    # =====================
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)   # سعر الشراء للوحدة
    total = db.Column(db.Integer, nullable=False)   # price * quantity

    purchase_date = db.Column(db.Date, default=datetime.utcnow().date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ❌ لا تكتب relationships هنا
    # ❌ لا backref هنا

    def __repr__(self):
        return f"<Purchase #{self.id} | Product:{self.product_id} | Qty:{self.quantity}>"
