# models/delivery_agent.py
from extensions import db
from datetime import datetime


class DeliveryAgent(db.Model):
    __tablename__ = "delivery_agent"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    shipping_company_id = db.Column(db.Integer, db.ForeignKey("shipping_company.id"), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    username = db.Column(db.String(50), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    salary = db.Column(db.Integer, default=0)
    pay_type = db.Column(db.String(30), default="none")
    pay_day_of_month = db.Column(db.Integer, default=25)
    pay_weekday = db.Column(db.Integer, default=4)
    payroll_effective_from = db.Column(db.Date, nullable=True)
    last_salary_paid_at = db.Column(db.DateTime, nullable=True)
    total_orders = db.Column(db.Integer, default=0)
    total_amount = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    shipping_company = db.relationship("ShippingCompany", backref="delivery_agents")

    def __repr__(self):
        return f"<DeliveryAgent {self.name}>"
