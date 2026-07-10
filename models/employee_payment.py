from datetime import datetime

from extensions import db


class EmployeePayment(db.Model):
    """سجل صرف راتب أو عمولة لموظف أو مندوب توصيل."""

    __tablename__ = "employee_payment"

    id = db.Column(db.Integer, primary_key=True)
    payee_type = db.Column(db.String(20), nullable=False)  # employee | delivery_agent
    payee_id = db.Column(db.Integer, nullable=False, index=True)
    payment_kind = db.Column(db.String(30), nullable=False)  # salary_weekly | salary_monthly | commission
    amount = db.Column(db.Integer, nullable=False, default=0)
    period_start = db.Column(db.Date, nullable=True)
    period_end = db.Column(db.Date, nullable=True)
    paid_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    treasury_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expense.id"), nullable=True)
    settled_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    note = db.Column(db.String(255), nullable=True)

    expense = db.relationship("Expense", foreign_keys=[expense_id], lazy=True)
    settler = db.relationship("Employee", foreign_keys=[settled_by], lazy=True)
    commission_lines = db.relationship(
        "EmployeeCommissionLine",
        back_populates="payment",
        lazy=True,
    )

    def __repr__(self):
        return f"<EmployeePayment {self.payee_type}:{self.payee_id} {self.payment_kind} {self.amount}>"
