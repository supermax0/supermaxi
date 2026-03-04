from extensions import db
from datetime import datetime

class AIFeedback(db.Model):
    __tablename__ = "ai_feedback"

    id = db.Column(db.Integer, primary_key=True)

    raw_text = db.Column(db.Text)

    corrected_name = db.Column(db.String(150))
    corrected_phone = db.Column(db.String(20))
    corrected_city = db.Column(db.String(50))
    corrected_address = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
