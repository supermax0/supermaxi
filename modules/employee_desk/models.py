from datetime import datetime

from extensions import db


class EmployeeQuickReply(db.Model):
    __tablename__ = "employee_quick_reply"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, nullable=True)
    text = db.Column(db.String(280), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
