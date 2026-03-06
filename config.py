# config.py — إعدادات التطبيق (تطوير / إنتاج)
import os

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

    # Email Settings (SMTP)
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.hostinger.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "465"))
    MAIL_USE_TLS = False
    MAIL_USE_SSL = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
    CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")


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
