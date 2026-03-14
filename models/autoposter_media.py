# وسائط الأوتوبوستر المخزنة — مكتبة الوسائط (Media Library)
from datetime import datetime
from extensions import db


class AutoposterMedia(db.Model):
    __tablename__ = "autoposter_media"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(64), nullable=True, index=True)
    tenant_id = db.Column(db.Integer, nullable=True, index=True)  # optional, for compatibility
    media_type = db.Column(db.String(20), nullable=False)  # image | video
    file_name = db.Column(db.String(255), nullable=True)  # original filename
    filename = db.Column(db.String(255), nullable=True)  # stored filename (legacy)
    file_path = db.Column(db.String(512), nullable=True)  # path under uploads/media/
    file_size = db.Column(db.BigInteger, nullable=True)  # bytes
    size_bytes = db.Column(db.BigInteger, nullable=True)  # legacy alias
    public_url = db.Column(db.String(512), nullable=True)  # URL for preview/publish
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "media_type": self.media_type,
            "file_name": getattr(self, "file_name", None) or self.filename,
            "file_path": getattr(self, "file_path", None),
            "file_size": getattr(self, "file_size", None) or self.size_bytes,
            "public_url": self.public_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
