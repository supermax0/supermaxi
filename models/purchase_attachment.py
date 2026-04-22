from datetime import datetime
from extensions import db


class PurchaseAttachment(db.Model):
    __tablename__ = "purchase_attachment"

    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase.id"), nullable=False, index=True)
    file_path = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=True)
    mime_type = db.Column(db.String(120), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    purchase = db.relationship("Purchase", back_populates="attachments", lazy=True)

    def __repr__(self):
        return f"<PurchaseAttachment purchase={self.purchase_id} name={self.original_name or self.file_path}>"
