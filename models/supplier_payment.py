# models/supplier_payment.py
from extensions import db
from datetime import datetime

class SupplierPayment(db.Model):
    __tablename__ = "supplier_payment"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)

    supplier_id = db.Column(
        db.Integer,
        db.ForeignKey("supplier.id"),
        nullable=False
    )

    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    amount = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(255))
    document_number = db.Column(db.String(100), nullable=True)
    currency = db.Column(db.String(10), nullable=True, default="IQD")
    exchange_rate = db.Column(db.Float, nullable=True, default=1.0)
    source_module = db.Column(db.String(40), nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    treasury_account_id = db.Column(
        db.Integer,
        db.ForeignKey("treasury_account.id"),
        nullable=True,
        index=True,
    )

    payment_method = db.Column(db.String(20), default="cash")  # cash | offset
    supplier_sale_id = db.Column(
        db.Integer,
        db.ForeignKey("supplier_sale.id"),
        nullable=True,
        index=True,
    )

    treasury_account = db.relationship("TreasuryAccount", lazy=True)
    supplier_sale = db.relationship("SupplierSale", lazy=True)
    allocations = db.relationship(
        "SupplierPaymentAllocation",
        back_populates="supplier_payment",
        cascade="all, delete-orphan",
        order_by="SupplierPaymentAllocation.id",
        lazy=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SupplierPayment {self.amount}>"
