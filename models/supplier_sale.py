from datetime import datetime

from extensions import db


class SupplierSale(db.Model):
    __tablename__ = "supplier_sale"

    id = db.Column(db.Integer, primary_key=True)

    supplier_id = db.Column(
        db.Integer,
        db.ForeignKey("supplier.id"),
        nullable=False,
        index=True,
    )

    invoice_no = db.Column(db.String(60), nullable=True, index=True)
    status = db.Column(db.String(30), default="confirmed")  # confirmed / cancelled
    grand_total = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, nullable=True)
    sale_date = db.Column(db.Date, default=datetime.utcnow().date)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)
    created_by_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship(
        "SupplierSaleItem",
        back_populates="supplier_sale",
        cascade="all, delete-orphan",
        lazy=True,
    )
    supplier = db.relationship("Supplier", backref="supplier_sales", lazy=True)
    created_by = db.relationship("Employee", foreign_keys=[created_by_employee_id], lazy=True)

    def __repr__(self):
        return f"<SupplierSale #{self.id} inv={self.invoice_no or '-'} total={self.grand_total}>"
