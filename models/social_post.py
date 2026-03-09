from datetime import datetime

from extensions import db


class SocialPost(db.Model):
    """منشور تم توليده/إدارته عبر نظام AI Social."""

    __tablename__ = "social_posts"

    id = db.Column(db.Integer, primary_key=True)

    tenant_slug = db.Column(db.String(100), nullable=True, index=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)

    topic = db.Column(db.String(255), nullable=True)
    caption = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(512), nullable=True)
    video_url = db.Column(db.String(512), nullable=True)

    status = db.Column(
        db.String(20),
        default="draft",
        nullable=False,
    )  # draft | scheduled | publishing | published | failed

    publish_time = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    source = db.Column(db.String(50), default="manual")  # manual | auto_ai_daily | ...
    error_message = db.Column(db.Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "user_id": self.user_id,
            "topic": self.topic,
            "caption": self.caption,
            "image_url": self.image_url,
            "video_url": self.video_url,
            "status": self.status,
            "publish_time": self.publish_time.isoformat() if self.publish_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source": self.source,
            "error_message": self.error_message,
        }

