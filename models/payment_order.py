from extensions import db
from datetime import datetime
import uuid

class PaymentOrder(db.Model):
    __tablename__ = "payment_order"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False)
    plan_key = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(10), default="IQD")
    billing_period = db.Column(db.String(20), default="monthly") # monthly / yearly
    
    status = db.Column(db.String(20), default="pending") # pending / success / failed
    transaction_id = db.Column(db.String(100), unique=True, default=lambda: str(uuid.uuid4()))
    
    gateway_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<PaymentOrder {self.id} Status:{self.status}>"
