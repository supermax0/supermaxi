# models/supplier_payment.py
from extensions import db
from datetime import datetime

class SupplierPayment(db.Model):
    __tablename__ = "supplier_payment"

    id = db.Column(db.Integer, primary_key=True)

    supplier_id = db.Column(
        db.Integer,
        db.ForeignKey("supplier.id"),
        nullable=False
    )

    amount = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SupplierPayment {self.amount}>"
