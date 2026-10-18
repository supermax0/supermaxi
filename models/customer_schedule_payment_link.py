"""Append-only attribution added when a schedule follows an existing voucher."""
from datetime import datetime

from extensions import db


class CustomerSchedulePaymentLink(db.Model):
    __tablename__ = "customer_schedule_payment_link"

    id = db.Column(db.Integer, primary_key=True)
    invoice_allocation_id = db.Column(db.Integer, db.ForeignKey("voucher_allocations.id"), nullable=False, unique=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("customer_credit_payment.id"), nullable=False, unique=True)
    reversal_payment_id = db.Column(db.Integer, db.ForeignKey("customer_credit_payment.id"), unique=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
