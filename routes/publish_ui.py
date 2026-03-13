from flask import Blueprint, render_template

publish_ui_bp = Blueprint("publish_ui", __name__, url_prefix="/publish")


@publish_ui_bp.route("/dashboard")
def dashboard():
    """لوحة تحكم النشر الجديد (تستخدم API تحت /publish/api)."""
    return render_template("publish/dashboard.html")


@publish_ui_bp.route("/settings")
def settings():
    """صفحة إعدادات النشر (App ID / Secret)."""
    return render_template("publish/settings.html")

