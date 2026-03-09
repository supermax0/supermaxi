from extensions import db
from datetime import datetime
import json


class SystemSettings(db.Model):
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)

    # General company / system info
    default_currency = db.Column(db.String(20), default="د.ع")
    default_language = db.Column(db.String(10), default="ar")

    # UI / appearance
    default_theme = db.Column(db.String(10), default="system")  # system / light / dark
    font_scale = db.Column(db.String(10), default="md")        # sm / md / lg

    # Dashboard widgets & features (JSON flags for future use)
    ui_flags = db.Column(db.Text, default="{}")

    # AI assistant toggle (global switch)
    ai_enabled = db.Column(db.Boolean, default=True)

    # النشر التلقائي لفيسبوك (اختياري — إن تُركا فارغين يُستخدم .env)
    facebook_app_id = db.Column(db.String(100), nullable=True)
    facebook_app_secret = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_ui_flags(self):
        """Return ui_flags as dict."""
        try:
            return json.loads(self.ui_flags) if self.ui_flags else {}
        except Exception:
            return {}

    def set_ui_flags(self, flags: dict):
        """Persist ui_flags from dict."""
        self.ui_flags = json.dumps(flags or {})

    @staticmethod
    def get_settings():
        """Get or create the single SystemSettings row."""
        settings = SystemSettings.query.first()
        if not settings:
            settings = SystemSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SystemSettings {self.id}>"

