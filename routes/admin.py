# routes/admin.py
import os
import subprocess
import logging
from flask import Blueprint, jsonify, session

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
log = logging.getLogger(__name__)

DEPLOY_ROOT = os.environ.get("FINORA_DEPLOY_ROOT", "/var/www/finora/supermaxi")
SERVICE_NAME = os.environ.get("FINORA_SERVICE_NAME", "finora")


def _is_superadmin():
    return session.get("is_superadmin") is True


@admin_bp.route("/system-update", methods=["POST"])
def system_update():
    if not _is_superadmin():
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    try:
        if not os.path.isdir(DEPLOY_ROOT):
            return jsonify({
                "status": "error",
                "message": f"Deploy path not found: {DEPLOY_ROOT}"
            }), 500

        # تحديث الكود
        git = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=DEPLOY_ROOT,
            capture_output=True,
            text=True
        )

        if git.returncode != 0:
            return jsonify({
                "status": "error",
                "message": git.stderr
            }), 500

        # إعادة تشغيل الخدمة
        restart = subprocess.run(
            ["sudo", "systemctl", "restart", SERVICE_NAME],
            capture_output=True,
            text=True
        )

        if restart.returncode != 0:
            return jsonify({
                "status": "error",
                "message": restart.stderr
            }), 500

        return jsonify({
            "status": "success",
            "message": "Finora updated successfully"
        })

    except Exception as e:
        log.exception("System update failed")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500