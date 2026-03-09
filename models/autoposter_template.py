from datetime import datetime

from extensions import db


class AutoposterTemplate(db.Model):
    """قالب منشور للنشر التلقائي — يُخزَّن في قاعدة بيانات الشركة (tenant)."""

    __tablename__ = "autoposter_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    post_type = db.Column(db.String(20), default="post")  # post | story | reels
    image_url = db.Column(db.String(512), nullable=True)
    video_url = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "post_type": self.post_type or "post",
            "image_url": self.image_url,
            "video_url": self.video_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

from datetime import datetime

from extensions import db


class AutoposterTemplate(db.Model):
    """قالب منشور للنشر التلقائي — يُخزَّن في قاعدة بيانات الشركة (tenant)."""

    __tablename__ = "autoposter_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    post_type = db.Column(db.String(20), default="post")  # post | story | reels
    image_url = db.Column(db.String(512), nullable=True)
    video_url = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "post_type": self.post_type or "post",
            "image_url": self.image_url,
            "video_url": self.video_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

