"""
routes.py
---------
HTML page routes for the Publisher module (dashboard, create post, media library).
"""

from flask import Blueprint, render_template, session, redirect, url_for

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
