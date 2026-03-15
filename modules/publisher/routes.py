"""
routes.py
---------
HTML page routes for the Publisher module (dashboard, create post, media library).
"""

import os

from flask import (
    Blueprint,
    render_template,
    session,
    redirect,
    abort,
    current_app,
    send_from_directory,
    request,
)
from jinja2 import TemplateNotFound

publisher_html_bp = Blueprint("publisher_html", __name__)


def _require_login():
    if "user_id" not in session:
        return redirect("/login")
    return None


def _should_use_legacy_ui():
    """
    UI switch:
    - Default: use the redesigned template pages (legacy templates).
    - Query param spa=1 forces SPA for manual verification.
    - Query param legacy=0 can also force SPA.
    """
    if request.args.get("spa") == "1":
        return False
    if request.args.get("legacy") == "0":
        return False
    return True


def _should_use_dev_ui():
    """
    Development UI switch (isolated from stable UI):
    - Disabled by default.
    - Enabled only when query param dev=1 is used.
    """
    return request.args.get("dev") == "1"


def _render_spa(entry_path: str, page_title: str):
    return render_template("publisher/app.html", entry_path=entry_path, page_title=page_title)


def _render_locked_or_dev_template(dev_template: str, stable_template: str):
    """
    Render stable template by default.
    If dev=1 is requested, try isolated publisher_dev template first.
    """
    if _should_use_dev_ui():
        try:
            return render_template(dev_template)
        except TemplateNotFound:
            return render_template(stable_template)
    return render_template(stable_template)


@publisher_html_bp.route("/publisher")
def normalize_duplicate_prefix_root():
    """Handle accidental /publisher/publisher URL and redirect to canonical /publisher/."""
    guard = _require_login()
    if guard:
        return guard
    qs = request.query_string.decode("utf-8")
    target = "/publisher/"
    if qs:
        target = f"{target}?{qs}"
    return redirect(target, code=302)


@publisher_html_bp.route("/publisher/<path:subpath>")
def normalize_duplicate_prefix_path(subpath):
    """Handle accidental /publisher/publisher/<path> and redirect to /publisher/<path>."""
    guard = _require_login()
    if guard:
        return guard
    qs = request.query_string.decode("utf-8")
    target = f"/publisher/{subpath}"
    if qs:
        target = f"{target}?{qs}"
    return redirect(target, code=302)


@publisher_html_bp.route("/")
def dashboard():
    guard = _require_login()
    if guard:
        return guard
    if _should_use_legacy_ui():
        return _render_locked_or_dev_template(
            "publisher_dev/dashboard.html",
            "publisher/dashboard.html",
        )
    return _render_spa("/publisher/", "لوحة الناشر")


@publisher_html_bp.route("/create")
def create_post():
    guard = _require_login()
    if guard:
        return guard
    if _should_use_legacy_ui():
        return _render_locked_or_dev_template(
            "publisher_dev/create_post.html",
            "publisher/create_post.html",
        )
    return _render_spa("/publisher/create", "إنشاء منشور")


@publisher_html_bp.route("/media")
def media_library():
    guard = _require_login()
    if guard:
        return guard
    if _should_use_legacy_ui():
        return _render_locked_or_dev_template(
            "publisher_dev/media_library.html",
            "publisher/media_library.html",
        )
    return _render_spa("/publisher/media", "مكتبة الوسائط")


@publisher_html_bp.route("/settings")
def settings():
    guard = _require_login()
    if guard:
        return guard
    if _should_use_legacy_ui():
        return _render_locked_or_dev_template(
            "publisher_dev/settings.html",
            "publisher/settings.html",
        )
    return _render_spa("/publisher/settings", "إعدادات الناشر")


@publisher_html_bp.route("/media-file/<tenant_slug>/<media_kind>/<filename>")
def serve_media_file(tenant_slug, media_kind, filename):
    """
    Serve publisher media files from disk.
    URL form: /publisher/media-file/<tenant>/<images|videos>/<filename>
    """
    guard = _require_login()
    if guard:
        return guard

    if media_kind not in {"images", "videos"}:
        return abort(404)
    if ".." in filename or filename.startswith("/"):
        return abort(400)

    media_root = current_app.config.get("PUBLISHER_MEDIA_ROOT") or os.path.join(current_app.root_path, "media")
    folder = os.path.join(media_root, tenant_slug or "default", media_kind)
    if not os.path.isdir(folder):
        return abort(404)
    return send_from_directory(folder, filename)
