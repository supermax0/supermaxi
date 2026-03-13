from datetime import datetime

from extensions import db


class PublisherChannel(db.Model):
    """
    قناة نشر عامة (فيسبوك صفحة، رقم واتساب، بوت تيليجرام، ...).
    """

    __tablename__ = "publish_channels"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(64), nullable=False, index=True)
    type = db.Column(db.String(50), nullable=False)  # facebook_page / whatsapp_number / telegram_bot ...
    name = db.Column(db.String(255), nullable=False)
    external_id = db.Column(db.String(255), nullable=False)  # page_id, phone number, chat_id ...
    access_token = db.Column(db.Text, nullable=True)  # token أو مفاتيح الربط حسب القناة

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

