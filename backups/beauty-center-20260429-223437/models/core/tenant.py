from extensions import db
from datetime import datetime

class Tenant(db.Model):
    __tablename__ = 'tenants'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    db_path = db.Column(db.String(255), nullable=False)
    subscription_end_date = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_subscription_valid(self):
        if not self.is_active:
            return False
        if not self.subscription_end_date:
            return False
        return datetime.utcnow() <= self.subscription_end_date
