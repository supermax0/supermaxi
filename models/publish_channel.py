from datetime import datetime

from extensions import db


class PublishChannel(db.Model):
    """قناة نشر واحدة (صفحة فيسبوك، قناة تيليجرام، ...)."""

    __tablename__ = "publish_channels"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(64), nullable=False, index=True)

    # نوع القناة: facebook_page / telegram_chat / instagram_account / whatsapp_number ...
    type = db.Column(db.String(50), nullable=False, index=True)

    # اسم ودّي يظهر في الواجهة
    name = db.Column(db.String(255), nullable=False)

    # المعرّف الخارجي في المنصة (page id, chat id, phone ...)
    external_id = db.Column(db.String(255), nullable=False)

    # بيانات الوصول يمكن أن تكون توكن بسيط أو JSON (مثل app_id, app_secret, token)
    credentials = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

