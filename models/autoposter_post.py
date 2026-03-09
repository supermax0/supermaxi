# نموذج منشور النشر التلقائي — يُخزّن في قاعدة بيانات الشركة (tenant)
from datetime import datetime
from extensions import db


class AutoposterPost(db.Model):
    __tablename__ = "autoposter_posts"

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.String(64), nullable=False)
    page_name = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(512), nullable=True)
    video_url = db.Column(db.String(512), nullable=True)
    status = db.Column(db.String(20), default="draft")
    scheduled_at = db.Column(db.DateTime, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)
    facebook_post_id = db.Column(db.String(128), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "page_id": self.page_id,
            "page_name": self.page_name,
            "content": self.content,
            "image_url": self.image_url,
            "video_url": self.video_url,
            "status": self.status,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "error_message": self.error_message,
        }
