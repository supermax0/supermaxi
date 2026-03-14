from datetime import datetime
from extensions import db


class PublisherPage(db.Model):
    """صفحة فيسبوك مرتبطة بحساب المتجر."""

    __tablename__ = "publisher_pages"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), nullable=True, index=True)
    page_id = db.Column(db.String(128), nullable=False)
    page_name = db.Column(db.String(255), nullable=True)
    # Fernet-encrypted access token stored as bytes (base64 text)
    page_token = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "page_id": self.page_id,
            "page_name": self.page_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
