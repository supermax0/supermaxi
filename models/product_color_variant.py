from extensions import db


class ProductColorVariant(db.Model):
    __tablename__ = "product_color_variant"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    color_name = db.Column(db.String(80), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)

    product = db.relationship("Product", backref=db.backref("color_variants", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("product_id", "color_name", name="_product_color_uc"),
    )

    def __repr__(self):
        return f"<ProductColorVariant product={self.product_id} color={self.color_name} qty={self.quantity}>"
