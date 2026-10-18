from datetime import datetime

from extensions import db


class SupplierPaymentAllocation(db.Model):
    """Audit link between one supplier payment and the obligation it clears."""

    __tablename__ = "supplier_payment_allocation"
    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_supplier_payment_allocation_amount_positive"),
        db.CheckConstraint(
            "(allocation_type = 'purchase' AND purchase_id IS NOT NULL) OR "
            "(allocation_type != 'purchase' AND purchase_id IS NULL)",
            name="ck_supplier_payment_allocation_target",
        ),
        db.UniqueConstraint(
            "supplier_payment_id",
            "target_key",
            name="uq_supplier_payment_allocation_target_key",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    supplier_payment_id = db.Column(
        db.Integer,
        db.ForeignKey("supplier_payment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purchase_id = db.Column(
        db.Integer,
        db.ForeignKey("purchase.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    allocation_type = db.Column(
        db.String(30),
        nullable=False,
        default="purchase",
    )  # purchase | opening_balance | on_account
    target_key = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    supplier_payment = db.relationship(
        "SupplierPayment",
        back_populates="allocations",
        lazy=True,
    )
    purchase = db.relationship(
        "Purchase",
        back_populates="supplier_payment_allocations",
        lazy=True,
    )

    def __repr__(self):
        return (
            f"<SupplierPaymentAllocation payment={self.supplier_payment_id} "
            f"type={self.allocation_type} amount={self.amount}>"
        )
