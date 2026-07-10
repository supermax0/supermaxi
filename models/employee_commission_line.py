from datetime import datetime

from extensions import db


class EmployeeCommissionLine(db.Model):
    """سطر عمولة فريد لكل طلب — يمنع السداد المزدوج."""

    __tablename__ = "employee_commission_line"
    __table_args__ = (
        db.UniqueConstraint("invoice_id", "employee_id", name="_commission_line_invoice_employee_uc"),
        db.UniqueConstraint("code", name="_commission_line_code_uc"),
    )

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | paid | void
    payment_id = db.Column(db.Integer, db.ForeignKey("employee_payment.id"), nullable=True, index=True)
    accrued_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    invoice = db.relationship("Invoice", lazy=True)
    employee = db.relationship("Employee", lazy=True)
    payment = db.relationship("EmployeePayment", back_populates="commission_lines", lazy=True)

    @staticmethod
    def make_code(invoice_id: int, employee_id: int) -> str:
        return f"COM-{invoice_id}-{employee_id}"

    def __repr__(self):
        return f"<EmployeeCommissionLine {self.code} {self.status}>"
