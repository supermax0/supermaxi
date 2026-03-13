from flask import Blueprint, render_template, session

publish_ui_bp = Blueprint("publish_ui", __name__, url_prefix="/publish")


@publish_ui_bp.route("/dashboard")
def dashboard():
    """لوحة تحكم النشر الجديد (تستخدم API تحت /publish/api)."""
    if "user_id" not in session:
        from flask import redirect

        return redirect("/login")
    return render_template("publish/dashboard.html")

