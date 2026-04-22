from extensions import db


class PurchaseItem(db.Model):
    __tablename__ = "purchase_item"

    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)

    quantity = db.Column(db.Integer, nullable=False, default=0)
    unit_cost_before_discount = db.Column(db.Integer, nullable=False, default=0)
    discount_value = db.Column(db.Integer, nullable=False, default=0)
    final_unit_cost = db.Column(db.Integer, nullable=False, default=0)
    line_total = db.Column(db.Integer, nullable=False, default=0)

    purchase = db.relationship("Purchase", back_populates="items", lazy=True)
    product = db.relationship("Product", lazy=True)

    def __repr__(self):
        return f"<PurchaseItem purchase={self.purchase_id} product={self.product_id} qty={self.quantity}>"
