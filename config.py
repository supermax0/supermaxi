# config.py — إعدادات التطبيق (تطوير / إنتاج)
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _database_uri():
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://finora:password@localhost/finora_db"
    )


class Config:
    """إعدادات مشتركة."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "super-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # مدة بقاء الجلسة (السوبر أدمن والعادي): 7 أيام بدل انتهائها عند إغلاق المتصفح أو بعد وقت قصير
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Email Settings (SMTP)
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.hostinger.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "465"))
    MAIL_USE_TLS = False
    MAIL_USE_SSL = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
    CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")

    # النشر التلقائي لفيسبوك (Autoposter)
    FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID", "")
    FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "")
    FACEBOOK_API_VERSION = os.environ.get("FACEBOOK_API_VERSION", "v21.0")

    # الذكاء الاصطناعي (AI Agent / OpenAI / Gemini)
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "dall-e-3")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    # تكامل واتساب Cloud API (لرسائل الوكلاء)
    WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()

    # بوت تيليجرام (AI bot)
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or ""


class DevelopmentConfig(Config):
    """إعدادات بيئة التطوير."""
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PREFERRED_URL_SCHEME = "http"


class ProductionConfig(Config):
    """إعدادات بيئة الإنتاج."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PREFERRED_URL_SCHEME = "https"
    # تدعم finora.company و www.finora.company
    SESSION_COOKIE_DOMAIN = os.environ.get("SESSION_COOKIE_DOMAIN", ".finora.company")
