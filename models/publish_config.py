from datetime import datetime

from extensions import db


class PublishConfig(db.Model):
    """إعدادات نظام النشر (مثل App ID والسر) لكل مستأجر."""

    __tablename__ = "publish_config"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(64), nullable=False, unique=True, index=True)

    facebook_app_id = db.Column(db.String(128), nullable=True)
    facebook_app_secret = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

