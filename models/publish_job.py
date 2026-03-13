from datetime import datetime

from extensions import db


class PublishJob(db.Model):
    """مهمة نشر واحدة على قناة محددة."""

    __tablename__ = "publish_jobs"

    id = db.Column(db.Integer, primary_key=True)

    tenant_slug = db.Column(db.String(64), nullable=False, index=True)

    channel_id = db.Column(
        db.Integer,
        db.ForeignKey("publish_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # تكرار نوع القناة لتسهيل الاستعلام بدون join
    channel_type = db.Column(db.String(50), nullable=False)

    title = db.Column(db.String(255), nullable=True)
    text = db.Column(db.Text, nullable=False, default="")

    # رابط وسائط واحد كبداية (يمكن التوسعة لاحقاً لجدول منفصل)
    media_url = db.Column(db.String(512), nullable=True)
    media_type = db.Column(db.String(32), nullable=True)  # image, video, link, none

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
        index=True,
    )  # pending, processing, published, failed, cancelled

    scheduled_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    published_at = db.Column(db.DateTime, nullable=True)

    retry_count = db.Column(db.Integer, nullable=False, default=0)
    max_retries = db.Column(db.Integer, nullable=False, default=5)

    error_code = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    # بيانات إضافية (JSON كسلسلة) لاستخدامات مستقبلية
    extra_payload = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

