from datetime import datetime
from extensions import db


class PublisherMedia(db.Model):
    """وسائط (صور/فيديوهات) مكتبة الناشر."""

    __tablename__ = "publisher_media"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), nullable=True, index=True)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=True)
    media_type = db.Column(db.String(20), nullable=False)   # image | video
    size_bytes = db.Column(db.Integer, nullable=True)
    url_path = db.Column(db.String(512), nullable=False)    # /media/<tenant>/images/file.jpg
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "filename": self.filename,
            "original_name": self.original_name,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "url_path": self.url_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
