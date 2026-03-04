# models/shipping_report.py
from extensions import db
from datetime import datetime
import json

class ShippingReport(db.Model):
    __tablename__ = "shipping_report"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # رقم الكشف (فريد)
    report_number = db.Column(db.String(50), unique=True, nullable=False)
    
    # شركة النقل
    shipping_company_id = db.Column(
        db.Integer,
        db.ForeignKey("shipping_company.id"),
        nullable=False
    )
    
    # اسم شركة النقل (للاحتفاظ بالاسم حتى لو تم حذف الشركة)
    shipping_company_name = db.Column(db.String(150), nullable=False)
    
    # بيانات الطلبات (JSON)
    orders_data = db.Column(db.Text)  # JSON string of orders
    
    # إجمالي المبلغ
    total_amount = db.Column(db.Integer, default=0)
    
    # عدد الطلبات
    orders_count = db.Column(db.Integer, default=0)
    
    # ملاحظات
    notes = db.Column(db.Text)
    
    # التاريخ
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(100))  # اسم من أنشأ الكشف
    
    # حالة التنفيذ
    is_executed = db.Column(db.Boolean, default=False)  # تم تنفيذ التغييرات أم لا
    order_status_selections = db.Column(db.Text)  # JSON string لتخزين اختيارات شركة النقل لكل طلب
    
    # Relationship
    shipping_company = db.relationship(
        "ShippingCompany",
        backref="reports"
    )
    
    def __repr__(self):
        return f"<ShippingReport #{self.report_number} | {self.shipping_company_name} | {self.orders_count} orders | {self.total_amount}>"
    
    def to_dict(self):
        return {
            "id": self.id,
            "report_number": self.report_number,
            "shipping_company_id": self.shipping_company_id,
            "shipping_company_name": self.shipping_company_name,
            "orders_data": json.loads(self.orders_data) if self.orders_data else [],
            "total_amount": self.total_amount,
            "orders_count": self.orders_count,
            "notes": self.notes,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "",
            "created_by": self.created_by
        }

