"""
HTML routes for Finora AI Workspace (LEON).
"""

from flask import Blueprint, redirect, render_template, request, session

workspace_html_bp = Blueprint("workspace_html", __name__)


def _require_login():
    if "user_id" not in session:
        return redirect("/login")
    return None


@workspace_html_bp.route("/")
def workspace_home():
    denied = _require_login()
    if denied:
        return denied

    if request.args.get("dev") == "1":
        return render_template("workspace_dev/app.html")

    return render_template("workspace/app.html")
