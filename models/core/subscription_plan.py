from extensions import db
from datetime import datetime
import json

class SubscriptionPlan(db.Model):
    __tablename__ = 'subscription_plans'
    
    id = db.Column(db.Integer, primary_key=True)
    plan_key = db.Column(db.String(50), unique=True, nullable=False) # basic, pro, enterprise
    name = db.Column(db.String(100), nullable=False)
    price_monthly = db.Column(db.Integer, default=0)
    price_yearly = db.Column(db.Integer, default=0)
    
    # Original prices (for discounts)
    original_price_monthly = db.Column(db.Integer, nullable=True)
    original_price_yearly = db.Column(db.Integer, nullable=True)
    
    max_users = db.Column(db.Integer, nullable=True) # None for unlimited
    max_orders_monthly = db.Column(db.Integer, nullable=True) # None for unlimited
    
    # Store features as JSON string
    features_json = db.Column(db.Text, default='{}')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_features(self):
        try:
            return json.loads(self.features_json)
        except:
            return {}

    def set_features(self, features_dict):
        self.features_json = json.dumps(features_dict)

    def to_dict(self):
        return {
            "key": self.plan_key,
            "name": self.name,
            "price_monthly": self.price_monthly,
            "price_yearly": self.price_yearly,
            "original_price_monthly": self.original_price_monthly,
            "original_price_yearly": self.original_price_yearly,
            "max_users": self.max_users,
            "max_orders_monthly": self.max_orders_monthly,
            "features": self.get_features()
        }
