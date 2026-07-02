from datetime import datetime

from extensions import db


class AnnouncementSendLog(db.Model):
    __tablename__ = "announcement_send_logs"

    id = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(
        db.Integer,
        db.ForeignKey("platform_announcements.id"),
        nullable=False,
        index=True,
    )
    tenant_slug = db.Column(db.String(100), nullable=False, index=True)
    email = db.Column(db.String(150), nullable=False)
    success = db.Column(db.Boolean, default=False, nullable=False)
    error_message = db.Column(db.String(500), nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    announcement = db.relationship("PlatformAnnouncement", back_populates="send_logs")
