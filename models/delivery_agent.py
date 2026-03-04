# models/delivery_agent.py
from extensions import db
from datetime import datetime

class DeliveryAgent(db.Model):
    __tablename__ = "delivery_agent"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # اسم المندوب
    name = db.Column(db.String(100), nullable=False)
    
    # ربط بشركة النقل (اختياري)
    shipping_company_id = db.Column(
        db.Integer,
        db.ForeignKey("shipping_company.id"),
        nullable=True
    )
    
    # الهاتف
    phone = db.Column(db.String(20), nullable=True)
    
    # حساب تسجيل الدخول
    username = db.Column(db.String(50), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=True)
    
    # ملاحظات
    notes = db.Column(db.Text, nullable=True)
    
    # إحصائيات (محسوبة ديناميكياً)
    total_orders = db.Column(db.Integer, default=0)
    total_amount = db.Column(db.Integer, default=0)
    
    # التاريخ
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    shipping_company = db.relationship(
        "ShippingCompany",
        backref="delivery_agents"
    )
    
    def __repr__(self):
        return f"<DeliveryAgent {self.name}>"
