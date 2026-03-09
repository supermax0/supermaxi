from datetime import datetime

from extensions import db


class SocialPostPlatform(db.Model):
    """ربط منشور SocialPost بمنصة/حساب معيّن (إنستجرام، تيك توك...)."""

    __tablename__ = "social_post_platforms"

    id = db.Column(db.Integer, primary_key=True)

    post_id = db.Column(db.Integer, db.ForeignKey("social_posts.id"), nullable=False, index=True)
    platform = db.Column(db.String(50), nullable=False)  # instagram | tiktok | ...
    account_id = db.Column(db.String(128), nullable=False)

    remote_post_id = db.Column(db.String(128), nullable=True)

    status = db.Column(
        db.String(20),
        default="pending",
        nullable=False,
    )  # pending | publishing | published | failed

    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "post_id": self.post_id,
            "platform": self.platform,
            "account_id": self.account_id,
            "remote_post_id": self.remote_post_id,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

