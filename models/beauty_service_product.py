from extensions import db


class BeautyServiceProduct(db.Model):
    __tablename__ = "beauty_service_product"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("beauty_service.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    amount_used = db.Column(db.Integer, nullable=False, default=1)

    service = db.relationship("BeautyService", back_populates="product_mappings")
    product = db.relationship("Product")

    def __repr__(self):
        return f"<BeautyServiceProduct service={self.service_id} product={self.product_id}>"
