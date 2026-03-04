# models/shipping_payment.py
from extensions import db
from datetime import datetime


class ShippingPayment(db.Model):
    __tablename__ = "shipping_payment"

    id = db.Column(db.Integer, primary_key=True)

    # =====================
    # Shipping Company
    # =====================
    shipping_company_id = db.Column(
        db.Integer,
        db.ForeignKey("shipping_company.id"),
        nullable=False
    )

    shipping_company = db.relationship(
        "ShippingCompany",
        back_populates="payments"
    )

    # =====================
    # Invoice (اختياري لكن مهم)
    # =====================
    invoice_id = db.Column(
        db.Integer,
        db.ForeignKey("invoice.id"),
        nullable=True
    )

    invoice = db.relationship(
        "Invoice",
        lazy=True
    )

    # =====================
    # Payment Info
    # =====================
    amount = db.Column(
        db.Integer,
        nullable=False
    )

    action = db.Column(
        db.String(50),
        nullable=False
    )  # تسديد / إلغاء / تعديل

    note = db.Column(
        db.String(255)
    )

    # =====================
    # Time
    # =====================
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # =====================
    # Helper
    # =====================
    def __repr__(self):
        return (
            f"<ShippingPayment "
            f"Company:{self.shipping_company_id} "
            f"Amount:{self.amount} "
            f"Action:{self.action}>"
        )
