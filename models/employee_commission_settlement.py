from datetime import datetime

from extensions import db


class EmployeeCommissionSettlement(db.Model):
    """Audit log when employee commission for a month is marked as paid."""

    __tablename__ = "employee_commission_settlement"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)
    order_count = db.Column(db.Integer, nullable=False, default=0)
    amount = db.Column(db.Integer, nullable=False, default=0)
    settled_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    settled_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)

    employee = db.relationship("Employee", foreign_keys=[employee_id], lazy=True)
    settler = db.relationship("Employee", foreign_keys=[settled_by], lazy=True)
