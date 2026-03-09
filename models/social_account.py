from datetime import datetime

from extensions import db


class SocialAccount(db.Model):
    """حساب سوشيال مرتبط بمستخدم/شركة (إنستجرام، تيك توك، ...)."""

    __tablename__ = "social_accounts"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), nullable=True, index=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)

    platform = db.Column(db.String(50), nullable=False)  # instagram | tiktok | ...
    account_id = db.Column(db.String(128), nullable=False)
    username = db.Column(db.String(150), nullable=True)

    access_token = db.Column(db.String(1024), nullable=False)
    refresh_token = db.Column(db.String(1024), nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "user_id": self.user_id,
            "platform": self.platform,
            "account_id": self.account_id,
            "username": self.username,
            "token_expiry": self.token_expiry.isoformat() if self.token_expiry else None,
        }

