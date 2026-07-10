from extensions import db


class SupplierSaleItem(db.Model):
    __tablename__ = "supplier_sale_item"

    id = db.Column(db.Integer, primary_key=True)
    supplier_sale_id = db.Column(
        db.Integer,
        db.ForeignKey("supplier_sale.id"),
        nullable=False,
        index=True,
    )
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    product_name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    unit_price = db.Column(db.Integer, nullable=False, default=0)
    line_total = db.Column(db.Integer, nullable=False, default=0)
    cost = db.Column(db.Integer, nullable=False, default=0)
    variant_color = db.Column(db.String(80), nullable=True)
    fulfillment_branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)

    supplier_sale = db.relationship("SupplierSale", back_populates="items", lazy=True)
    product = db.relationship("Product", lazy=True)

    def __repr__(self):
        return (
            f"<SupplierSaleItem sale={self.supplier_sale_id} "
            f"product={self.product_id} qty={self.quantity}>"
        )
