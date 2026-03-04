from extensions import db
from datetime import datetime

class POSAILog(db.Model):
    __tablename__ = "pos_ai_log"

    id = db.Column(db.Integer, primary_key=True)

    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"))

    raw_text = db.Column(db.Text)        # النص المستخرج
    source = db.Column(db.String(50))    # image / camera / manual

    name_conf = db.Column(db.Integer)
    phone_conf = db.Column(db.Integer)
    city_conf = db.Column(db.Integer)
    address_conf = db.Column(db.Integer)

    corrected = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<POS AI Log #{self.id}>"
