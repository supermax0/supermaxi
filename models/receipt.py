"""Unified cash receipts (قبض) for customers, couriers, and shipping companies."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class Receipt(db.Model):
    __tablename__ = "receipts"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=True, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)

    receipt_number = db.Column(db.String(40), nullable=False, unique=True, index=True)

    source_type = db.Column(db.String(30), nullable=False, index=True)
    # customer | courier | shipping_company
    source_id = db.Column(db.Integer, nullable=False, index=True)
    source_name = db.Column(db.String(150), nullable=True)

    amount = db.Column(db.Integer, nullable=False, default=0)
    payment_method = db.Column(db.String(40), nullable=True)
    treasury_account_id = db.Column(
        db.Integer, db.ForeignKey("treasury_account.id"), nullable=True, index=True
    )

    receipt_date = db.Column(db.Date, nullable=False, index=True)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    allocation_method = db.Column(db.String(30), nullable=False, default="oldest_first")
    # oldest_first | manual | on_account

    status = db.Column(db.String(20), nullable=False, default="معتمد", index=True)
    # معتمد | ملغى

    balance_before = db.Column(db.Integer, nullable=True, default=0)
    balance_after = db.Column(db.Integer, nullable=True, default=0)

    journal_entry_id = db.Column(db.Integer, nullable=True)
    reverse_journal_entry_id = db.Column(db.Integer, nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    cancelled_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancel_reason = db.Column(db.Text, nullable=True)

    idempotency_key = db.Column(db.String(80), nullable=True, unique=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    allocations = db.relationship(
        "ReceiptAllocation",
        back_populates="receipt",
        cascade="all, delete-orphan",
        lazy=True,
    )
    treasury_account = db.relationship("TreasuryAccount", lazy=True)
    creator = db.relationship("Employee", foreign_keys=[created_by], lazy=True)
    canceller = db.relationship("Employee", foreign_keys=[cancelled_by], lazy=True)

    def __repr__(self):
        return f"<Receipt {self.receipt_number} {self.amount}>"


class ReceiptAllocation(db.Model):
    __tablename__ = "receipt_allocations"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=True, index=True)
    receipt_id = db.Column(
        db.Integer, db.ForeignKey("receipts.id"), nullable=False, index=True
    )

    reference_type = db.Column(db.String(30), nullable=False, default="invoice")
    # invoice
    reference_id = db.Column(db.Integer, nullable=False, index=True)
    reference_label = db.Column(db.String(80), nullable=True)

    allocated_amount = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    receipt = db.relationship("Receipt", back_populates="allocations")

    def __repr__(self):
        return f"<ReceiptAllocation {self.reference_type}:{self.reference_id}={self.allocated_amount}>"
