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

publisher_html_bp = Blueprint("publisher_html", __name__)


def _require_login():
    if "user_id" not in session:
        return redirect("/login")
    return None


def _should_use_legacy_ui():
    """
    Transitional switch for migration cutover:
    - Query param legacy=1 forces old pages.
    - Query param spa=1 forces SPA (for manual verification).
    - If SPA assets are missing on server, fall back to legacy to avoid blank page.
    """
    if request.args.get("legacy") == "1":
        return True
    if request.args.get("spa") == "1":
        return False

    assets_root = os.path.join(current_app.static_folder or "", "publisher_frontend", "dist", "assets")
    js_entry = os.path.join(assets_root, "publisher-app.js")
    css_entry = os.path.join(assets_root, "publisher-app.css")
    return not (os.path.isfile(js_entry) and os.path.isfile(css_entry))


def _render_spa(entry_path: str, page_title: str):
    return render_template("publisher/app.html", entry_path=entry_path, page_title=page_title)


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
        return render_template("publisher/dashboard.html")
    return _render_spa("/publisher/", "لوحة الناشر")


@publisher_html_bp.route("/create")
def create_post():
    guard = _require_login()
    if guard:
        return guard
    if _should_use_legacy_ui():
        return render_template("publisher/create_post.html")
    return _render_spa("/publisher/create", "إنشاء منشور")


@publisher_html_bp.route("/media")
def media_library():
    guard = _require_login()
    if guard:
        return guard
    if _should_use_legacy_ui():
        return render_template("publisher/media_library.html")
    return _render_spa("/publisher/media", "مكتبة الوسائط")


@publisher_html_bp.route("/settings")
def settings():
    guard = _require_login()
    if guard:
        return guard
    if _should_use_legacy_ui():
        return render_template("publisher/settings.html")
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
