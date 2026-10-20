"""The same company clock setting for the website and native client."""
from flask import jsonify, request
from modules.desktop_api.routes import desktop_api_bp, _error
from modules.desktop_api.branches import _authorize
from utils.time_format import get_time_format, set_time_format


@desktop_api_bp.route("/display-preferences", methods=["GET", "POST"])
def display_preferences():
    denial = _authorize(admin=request.method == "POST", permission="manage_settings")
    if denial is not None:
        return denial
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get("time_format") not in ("12", "24"):
            return _error("اختر تنسيق الوقت 12 أو 24 ساعة", 400, "invalid_time_format")
        set_time_format(data["time_format"])
    return jsonify(ok=True, time_format=get_time_format(), timezone="Asia/Baghdad")
