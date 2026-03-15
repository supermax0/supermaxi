from datetime import datetime
from extensions import db


class PublisherSettings(db.Model):
    """إعدادات ناشر فيسبوك مخزنة في قاعدة البيانات (بديل .env للمستخدم)."""

    __tablename__ = "publisher_settings"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), nullable=True, index=True)

    fb_app_id     = db.Column(db.String(50),   nullable=True)
    fb_app_secret = db.Column(db.Text,          nullable=True)   # مشفر
    # Long-lived user token (اختياري — يُستخدم لجلب الصفحات)
    fb_user_token = db.Column(db.Text,          nullable=True)
    # OpenAI API Key (اختياري — يُستخدم لمساعد الذكاء الاصطناعي في Publisher)
    openai_api_key = db.Column(db.Text,         nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls, tenant_slug):
        obj = cls.query.filter_by(tenant_slug=tenant_slug).first()
        if not obj:
            obj = cls(tenant_slug=tenant_slug)
            db.session.add(obj)
            db.session.commit()
        return obj

    def to_dict(self):
        return {
            "fb_app_id":     self.fb_app_id or "",
            # نُرجع نجوم بدل السر الفعلي للعرض
            "fb_app_secret": "●●●●●●●●" if self.fb_app_secret else "",
            "fb_user_token": "●●●●●●●●" if self.fb_user_token else "",
            "openai_api_key": "●●●●●●●●" if self.openai_api_key else "",
            "has_secret":    bool(self.fb_app_secret),
            "has_token":     bool(self.fb_user_token),
            "has_openai_key": bool(self.openai_api_key),
            "updated_at":    self.updated_at.isoformat() if self.updated_at else None,
        }
