from datetime import datetime
from extensions import db


class PurchasePayment(db.Model):
    __tablename__ = "purchase_payment"

    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False, default=0)
    paid_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    payment_method = db.Column(db.String(30), nullable=True)  # cash / bank / credit
    account_name = db.Column(db.String(80), nullable=True)
    note = db.Column(db.String(255), nullable=True)

    purchase = db.relationship("Purchase", back_populates="payments", lazy=True)

    def __repr__(self):
        return f"<PurchasePayment purchase={self.purchase_id} amount={self.amount}>"
