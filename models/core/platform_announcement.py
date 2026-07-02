from datetime import datetime

from extensions import db


class PlatformAnnouncement(db.Model):
    __tablename__ = "platform_announcements"

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(255), nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    body_plain = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft | sent
    is_weekly_active = db.Column(db.Boolean, default=False, nullable=False)
    created_by = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_sent_at = db.Column(db.DateTime, nullable=True)
    send_count = db.Column(db.Integer, default=0, nullable=False)

    send_logs = db.relationship(
        "AnnouncementSendLog",
        back_populates="announcement",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
