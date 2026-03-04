from extensions import db
from datetime import datetime

class PaymentLog(db.Model):
    __tablename__ = "payment_log"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("payment_order.id"), nullable=False)
    event_type = db.Column(db.String(100), nullable=False) # callback / user_action / redirect
    raw_data = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<PaymentLog Order:{self.order_id} Event:{self.event_type}>"
