from datetime import datetime

from extensions import db


class PublisherJob(db.Model):
    """
    مهمة نشر واحدة لقناة واحدة (صفحة فيسبوك معينة، رقم واتساب، ...).
    """

    __tablename__ = "publish_jobs"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(64), nullable=False, index=True)

    channel_id = db.Column(db.Integer, db.ForeignKey("publish_channels.id"), nullable=False)
    channel_type = db.Column(db.String(50), nullable=False)  # نفس قيمة PublisherChannel.type للسهولة

    content = db.Column(db.Text, nullable=False, default="")
    media_url = db.Column(db.String(512), nullable=True)
    media_type = db.Column(db.String(20), nullable=True)  # image / video

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
        index=True,
    )  # pending / processing / published / failed
    scheduled_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    published_at = db.Column(db.DateTime, nullable=True)

    retry_count = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

