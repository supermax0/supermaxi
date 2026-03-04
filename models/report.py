# models/report.py
from extensions import db
from datetime import datetime
import json

class Report(db.Model):
    __tablename__ = "report"
    
    id = db.Column(db.Integer, primary_key=True)
    report_number = db.Column(db.String(50), unique=True, nullable=False)
    
    # بيانات الكشف
    orders_data = db.Column(db.Text)  # JSON string of orders
    
    # إجمالي المبلغ
    total_amount = db.Column(db.Integer, default=0)
    
    # عدد الطلبات
    orders_count = db.Column(db.Integer, default=0)
    
    # ملاحظات
    notes = db.Column(db.Text)
    
    # التاريخ
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(100))
    
    def __repr__(self):
        return f"<Report #{self.report_number} | {self.orders_count} orders | {self.total_amount}>"
    
    def to_dict(self):
        return {
            "id": self.id,
            "report_number": self.report_number,
            "orders_data": json.loads(self.orders_data) if self.orders_data else [],
            "total_amount": self.total_amount,
            "orders_count": self.orders_count,
            "notes": self.notes,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "",
            "created_by": self.created_by
        }

