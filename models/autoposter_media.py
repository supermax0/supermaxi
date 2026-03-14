# وسائط الأوتوبوستر المخزنة — للرفع أولاً ثم النشر لاحقاً
from datetime import datetime
from extensions import db


class AutoposterMedia(db.Model):
    __tablename__ = "autoposter_media"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(64), nullable=True, index=True)
    public_url = db.Column(db.String(512), nullable=False)
    media_type = db.Column(db.String(20), nullable=False)  # image | video
    filename = db.Column(db.String(255), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "public_url": self.public_url,
            "media_type": self.media_type,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
