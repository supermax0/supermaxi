# models/shipping.py
from extensions import db
from datetime import datetime
import secrets

class ShippingCompany(db.Model):
    __tablename__ = "shipping_company"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(50))
    price = db.Column(db.Integer, default=0)  # سعر التوصيل
    notes = db.Column(db.Text)
    access_token = db.Column(db.String(64), unique=True, nullable=True)  # رابط خاص للوصول العام
    username = db.Column(db.String(50), unique=True, nullable=True)  # اسم المستخدم لتسجيل الدخول
    password = db.Column(db.String(200), nullable=True)  # كلمة المرور

    payments = db.relationship(
    "ShippingPayment",
    back_populates="shipping_company",
    cascade="all, delete-orphan",
    lazy=True
)


    invoices = db.relationship(
    "Invoice",
    back_populates="shipping_company",
    lazy=True
)


    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def __repr__(self):
        return f"<ShippingCompany {self.name}>"