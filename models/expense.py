from extensions import db
from datetime import datetime

class Expense(db.Model):
    __tablename__ = "expense"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)

    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100))
    amount = db.Column(db.Integer, nullable=False)

    note = db.Column(db.String(255))
    expense_date = db.Column(db.Date, default=datetime.utcnow)
    # ساعة الصرف المجدولة (اختياري) — إن وُجدت لا يُخصم قبل حلولها في يوم المصروف
    post_time = db.Column(db.Time, nullable=True)
    # معرّف سلسلة التكرار (يربط تكرار 1/N … N/N)
    repeat_series_id = db.Column(db.String(36), nullable=True, index=True)

    # حساب الصرف (صندوق/بنك)
    treasury_account_id = db.Column(
        db.Integer,
        db.ForeignKey("treasury_account.id"),
        nullable=True,
        index=True,
    )
    # هل خُصم المبلغ من الصندوق؟
    cash_posted = db.Column(db.Boolean, default=True, nullable=False)

    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    employee_payment_id = db.Column(db.Integer, db.ForeignKey("employee_payment.id"), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Expense {self.title} - {self.amount}>"
