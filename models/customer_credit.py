# models/customer_credit.py
from datetime import datetime

from extensions import db


class CustomerCreditPlan(db.Model):
    __tablename__ = "customer_credit_plan"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    entry_type = db.Column(db.String(20), nullable=False)  # opening | products | manual
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=True)
    description = db.Column(db.String(255), nullable=True)
    total_amount = db.Column(db.Integer, nullable=False, default=0)
    paid_amount = db.Column(db.Integer, nullable=False, default=0)
    installments_count = db.Column(db.Integer, nullable=False, default=1)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship("Customer", backref=db.backref("credit_plans", lazy=True))
    invoice = db.relationship("Invoice", lazy=True)
    employee = db.relationship("Employee", lazy=True)
    installments = db.relationship(
        "CustomerInstallment",
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="CustomerInstallment.sequence",
    )
    payments = db.relationship(
        "CustomerCreditPayment",
        back_populates="plan",
        lazy=True,
    )

    @property
    def remaining(self):
        return max(0, int(self.total_amount or 0) - int(self.paid_amount or 0))

    def __repr__(self):
        return f"<CustomerCreditPlan {self.id} customer={self.customer_id} type={self.entry_type}>"


class CustomerInstallment(db.Model):
    __tablename__ = "customer_installment"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("customer_credit_plan.id"), nullable=False)
    sequence = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    paid_amount = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="pending")

    plan = db.relationship("CustomerCreditPlan", back_populates="installments")

    @property
    def remaining(self):
        return max(0, int(self.amount or 0) - int(self.paid_amount or 0))

    def __repr__(self):
        return f"<CustomerInstallment plan={self.plan_id} seq={self.sequence}>"


class CustomerCreditPayment(db.Model):
    __tablename__ = "customer_credit_payment"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("customer_credit_plan.id"), nullable=True)
    installment_id = db.Column(db.Integer, db.ForeignKey("customer_installment.id"), nullable=True)
    amount = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(255), nullable=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship("Customer", backref=db.backref("credit_payments", lazy=True))
    plan = db.relationship("CustomerCreditPlan", back_populates="payments")
    installment = db.relationship("CustomerInstallment", lazy=True)
    employee = db.relationship("Employee", lazy=True)

    def __repr__(self):
        return f"<CustomerCreditPayment {self.amount} customer={self.customer_id}>"
