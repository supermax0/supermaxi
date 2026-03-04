# models/system_alert.py
from extensions import db
from datetime import datetime

class SystemAlert(db.Model):
    """نموذج تنبيهات النظام"""
    __tablename__ = "system_alert"

    id = db.Column(db.Integer, primary_key=True)
    
    # نوع التنبيه
    alert_type = db.Column(db.String(50), nullable=False)  # low_stock, payment_due, error, etc.
    
    # العنوان
    title = db.Column(db.String(200), nullable=False)
    
    # الرسالة
    message = db.Column(db.Text, nullable=False)
    
    # مستوى الأهمية
    priority = db.Column(db.String(20), default="medium")  # high, medium, low
    
    # حالة التنبيه
    is_read = db.Column(db.Boolean, default=False)
    is_dismissed = db.Column(db.Boolean, default=False)
    
    # البيانات المرتبطة
    related_id = db.Column(db.Integer, nullable=True)  # ID للعنصر المرتبط (invoice_id, product_id, etc.)
    related_type = db.Column(db.String(50), nullable=True)  # invoice, product, customer, etc.
    
    # الوقت
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f"<SystemAlert {self.alert_type} - {self.title}>"
