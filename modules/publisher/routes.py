"""
routes.py
---------
HTML page routes for the Publisher module (dashboard, create post, media library).
"""

import os

from flask import Blueprint, render_template, session, redirect, abort, current_app, send_from_directory

from modules.publisher.models.publisher_page import PublisherPage
from modules.publisher.models.publisher_post import PublisherPost

publisher_html_bp = Blueprint("publisher_html", __name__)


def _require_login():
    if "user_id" not in session:
        return redirect("/login")
    return None


@publisher_html_bp.route("/")
def dashboard():
    guard = _require_login()
    if guard:
        return guard
    return render_template("publisher/dashboard.html")


@publisher_html_bp.route("/create")
def create_post():
    guard = _require_login()
    if guard:
        return guard
    return render_template("publisher/create_post.html")


@publisher_html_bp.route("/media")
def media_library():
    guard = _require_login()
    if guard:
        return guard
    return render_template("publisher/media_library.html")


@publisher_html_bp.route("/settings")
def settings():
    guard = _require_login()
    if guard:
        return guard
    return render_template("publisher/settings.html")


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
