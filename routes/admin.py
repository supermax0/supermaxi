# routes/admin.py — مسارات إدارية (تحديث النظام، إلخ)
import os
import subprocess
from flask import Blueprint, request, jsonify, session

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# مسار المشروع على السيرفر (يمكن تغييره عبر متغير بيئة)
DEPLOY_ROOT = os.environ.get("FINORA_DEPLOY_ROOT", "/var/www/finora/supermaxi")
SERVICE_NAME = os.environ.get("FINORA_SERVICE_NAME", "finora")


def _is_superadmin():
    return session.get("is_superadmin") is True


@admin_bp.route("/system-update", methods=["POST"])
def system_update():
    """تشغيل git pull وإعادة تشغيل خدمة finora — للمدير العام (Super Admin) فقط."""
    if not _is_superadmin():
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    try:
        # تشغيل git pull في مجلد المشروع
        r1 = subprocess.run(
            ["git", "pull"],
            cwd=DEPLOY_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r1.returncode != 0:
            return jsonify({
                "status": "error",
                "message": r1.stderr or r1.stdout or "git pull failed",
            }), 500

        # إعادة تشغيل الخدمة
        r2 = subprocess.run(
            ["systemctl", "restart", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r2.returncode != 0:
            return jsonify({
                "status": "error",
                "message": r2.stderr or r2.stdout or "systemctl restart failed",
            }), 500

        return jsonify({"status": "success"})
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "Command timed out"}), 500
    except FileNotFoundError as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
