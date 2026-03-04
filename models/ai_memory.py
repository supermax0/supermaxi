from extensions import db
from datetime import datetime

class AIMemory(db.Model):
    __tablename__ = "ai_memory"

    id = db.Column(db.Integer, primary_key=True)

    raw_text = db.Column(db.Text, nullable=False)
    corrected_text = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
