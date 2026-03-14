"""
modules/publisher/__init__.py
-----------------------------
Creates and exports the publisher_bp Blueprint.
Registers all sub-blueprints (API + HTML routes).
Starts the background scheduler (Gunicorn-safe via file lock).
"""

from flask import Blueprint

publisher_bp = Blueprint(
    "publisher",
    __name__,
    template_folder="../../templates",
    static_folder="../../static",
)

# ── Register API sub-blueprints ───────────────────────────────────────────────
from modules.publisher.api.pages_api import pages_api_bp
from modules.publisher.api.media_api import media_api_bp
from modules.publisher.api.posts_api import posts_api_bp
from modules.publisher.api.ai_api import ai_api_bp
from modules.publisher.api.settings_api import settings_api_bp
from modules.publisher.routes import publisher_html_bp

publisher_bp.register_blueprint(pages_api_bp)
publisher_bp.register_blueprint(media_api_bp)
publisher_bp.register_blueprint(posts_api_bp)
publisher_bp.register_blueprint(ai_api_bp)
publisher_bp.register_blueprint(settings_api_bp)
publisher_bp.register_blueprint(publisher_html_bp)


# ── Start scheduler (safe: file lock prevents multi-worker duplication) ───────
def _init_scheduler(app):
    try:
        from modules.publisher.services.scheduler_service import start_scheduler
        start_scheduler(app)
    except Exception as exc:
        import logging
        logging.getLogger("publisher").error("Scheduler init error: %s", exc)


def init_publisher(app):
    """Call this after registering publisher_bp in app.py."""
    _init_scheduler(app)
