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

    treasury_account_id = db.Column(
        db.Integer,
        db.ForeignKey("treasury_account.id"),
        nullable=True,
        index=True,
    )

    treasury_account = db.relationship("TreasuryAccount", lazy=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SupplierPayment {self.amount}>"
