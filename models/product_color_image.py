from extensions import db


class ProductColorImage(db.Model):
    """Catalog media kept separate from stock and offline reservations."""
    __tablename__ = "product_color_image"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True)
    color_name = db.Column(db.String(80), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    product = db.relationship("Product", backref=db.backref("color_image_records", cascade="all, delete-orphan"))
    __table_args__ = (db.UniqueConstraint("product_id", "color_name", name="uq_product_color_image"),)
