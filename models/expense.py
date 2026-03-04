from extensions import db
from datetime import datetime

class Expense(db.Model):
    __tablename__ = "expense"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100))
    amount = db.Column(db.Integer, nullable=False)

    note = db.Column(db.String(255))
    expense_date = db.Column(db.Date, default=datetime.utcnow)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Expense {self.title} - {self.amount}>"
