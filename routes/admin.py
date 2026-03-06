# routes/admin.py — زر التحديث: رفع على GitHub ثم تحديث على VPS
import os
import subprocess
import logging
from flask import Blueprint, jsonify, session

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
log = logging.getLogger(__name__)


@admin_bp.errorhandler(500)
def handle_500(e):
    log.exception("Admin route 500")
    return jsonify({"status": "error", "message": "خطأ داخلي في الخادم."}), 500

DEPLOY_ROOT = os.environ.get("FINORA_DEPLOY_ROOT", "/var/www/finora/supermaxi")
SERVICE_NAME = os.environ.get("FINORA_SERVICE_NAME", "finora")


def _run(cmd, cwd=None, timeout=60):
    return subprocess.run(
        cmd,
        cwd=cwd or DEPLOY_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_superadmin():
    return session.get("is_superadmin") is True


def _safe_str(s):
    if s is None:
        return ""
    return str(s).strip() or ""


@admin_bp.route("/system-update", methods=["POST"])
def system_update():
    try:
        if not _is_superadmin():
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

        root = os.path.abspath(str(DEPLOY_ROOT or "."))
        if not os.path.isdir(root):
            try:
                from flask import current_app
                root = os.path.abspath(str(current_app.root_path))
            except Exception:
                pass
        if not os.path.isdir(root):
            return jsonify({
                "status": "error",
                "message": "مسار المشروع غير موجود. ضع FINORA_DEPLOY_ROOT في بيئة التشغيل.",
            }), 500

        pushed = False
        _run(["git", "add", "-A"], cwd=root)
        status = _run(["git", "status", "--porcelain"], cwd=root)
        if _safe_str(status.stdout):
            commit = _run(
                ["git", "commit", "-m", "Update from dashboard"],
                cwd=root,
            )
            if commit.returncode == 0:
                push = _run(["git", "push", "origin", "main"], cwd=root)
                pushed = push.returncode == 0
                if not pushed:
                    log.warning("git push failed: %s", push.stderr or push.stdout)

        pull = _run(["git", "pull", "origin", "main"], cwd=root)
        if pull.returncode != 0:
            return jsonify({
                "status": "error",
                "message": _safe_str(pull.stderr) or _safe_str(pull.stdout) or "فشل سحب التحديثات من GitHub.",
            }), 500

        restart = subprocess.run(
            ["sudo", "systemctl", "restart", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if restart.returncode != 0:
            return jsonify({
                "status": "error",
                "message": _safe_str(restart.stderr) or _safe_str(restart.stdout) or "فشل إعادة تشغيل الخدمة.",
            }), 500

        msg = "تم تحديث الموقع على VPS وإعادة تشغيل الخدمة بنجاح."
        if pushed:
            msg = "تم الرفع إلى GitHub وتحديث الموقع على VPS بنجاح."
        return jsonify({"status": "success", "message": msg})
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "انتهت مهلة تنفيذ الأمر."}), 500
    except Exception as e:
        log.exception("System update failed")
        return jsonify({"status": "error", "message": _safe_str(e) or "خطأ غير متوقع."}), 500