# مكتبة وسائط الأوتوبوستر — Media Library
# Routes: /autoposter/media, /autoposter/api/media, /autoposter/api/media/upload
# لا تغيير أسماء المسارات أو مخطط قاعدة البيانات — إصلاحات فقط.
from pathlib import Path
import uuid
import traceback
from flask import Blueprint, current_app, jsonify, request, session, send_from_directory, redirect, url_for
from werkzeug.utils import secure_filename
from sqlalchemy.exc import OperationalError
from extensions import db
from models.autoposter_media import AutoposterMedia

autoposter_media_bp = Blueprint("autoposter_media", __name__, url_prefix="/autoposter")

# صيغ مسموحة: jpg, png, webp, mp4, mov — حد 500MB
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXT = {".mp4", ".mov"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB


def _upload_dir():
    """
    مجلد رفع الوسائط: من الإعداد AUTOPOSTER_MEDIA_ROOT أو جذر التطبيق/media
    (على السيرفر: /var/www/finora/supermaxi/media). يُنشأ المجلد تلقائياً إن لم يكن موجوداً.
    """
    custom = current_app.config.get("AUTOPOSTER_MEDIA_ROOT")
    base = Path(custom) if custom else Path(current_app.root_path) / "media"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        if current_app.logger:
            current_app.logger.exception("autoposter_media: failed to create upload dir %s: %s", base, e)
        raise
    return base


@autoposter_media_bp.route("/serve/media/<path:filename>")
def serve_media(filename):
    """تقديم ملفات مكتبة الوسائط (للمعاينة والنشر)."""
    dir_path = _upload_dir()
    return send_from_directory(dir_path, filename, as_attachment=False)


@autoposter_media_bp.route("/media")
def media_library_page():
    """إعادة التوجيه إلى صفحة رفع الوسائط."""
    if not session.get("user_id"):
        return redirect(url_for("index.login") + "?next=" + request.path)
    return redirect(url_for("autoposter.upload_page"))


@autoposter_media_bp.route("/api/media", methods=["GET"])
def api_media_list():
    """قائمة الوسائط للشركة الحالية (للاستخدام في إنشاء المنشور)."""
    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 401
    try:
        q = AutoposterMedia.query.order_by(AutoposterMedia.created_at.desc()).limit(200)
        items = q.all()
        return jsonify({
            "success": True,
            "media": [
                {
                    "name": (m.file_name or m.filename),
                    "url": m.public_url or f"/autoposter/serve/media/{m.filename}",
                    **m.to_dict(),
                }
                for m in items
            ],
        })
    except OperationalError as e:
        # في حال كان جدول مكتبة الوسائط غير موجود، نحاول إنشاءه ثم نرجع قائمة فارغة
        from flask import current_app
        current_app.logger.exception("autoposter_media list operational error, trying create_all: %s", e)
        db.session.rollback()
        try:
            db.create_all()
        except Exception:
            db.session.rollback()
        # حتى لو فشل create_all، نرجع JSON بدون إسقاط السيرفر
        return jsonify({"success": False, "media": []})
    except Exception as e:
        from flask import current_app
        current_app.logger.exception("autoposter_media list failed: %s", e)
        db.session.rollback()
        return jsonify({"success": False, "media": []})


@autoposter_media_bp.route("/api/media/upload", methods=["POST"])
def api_media_upload():
    """
    رفع وسائط (FormData، المفتاح: file).
    صيغ: jpg, png, webp, mp4, mov — حد 500MB. الرد دائماً JSON (لا إعادة توجيه).
    """
    try:
        return _api_media_upload_impl()
    except Exception as e:
        current_app.logger.exception(
            "autoposter_media upload unhandled error: %s\n%s",
            e,
            traceback.format_exc(),
        )
        return jsonify({
            "success": False,
            "ok": False,
            "error": "server_error",
            "message": "خطأ أثناء الرفع. راجع سجلات الخادم.",
        }), 500


def _api_media_upload_impl():
    """تنفيذ رفع الوسائط — يُستدعى من api_media_upload مع معالجة الأخطاء."""
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "unauthorized"}), 401
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"success": False, "ok": False, "error": "media missing", "message": "لم يُرفع ملف"}), 400
    filename = secure_filename(file.filename) or "file"
    ext = (Path(filename).suffix or "").lower()
    if ext in ALLOWED_IMAGE_EXT:
        media_type = "image"
    elif ext in ALLOWED_VIDEO_EXT:
        media_type = "video"
    else:
        return jsonify({
            "success": False,
            "ok": False,
            "error": "unsupported_type",
            "message": "الصيغ المسموحة: jpg, png, webp, mp4, mov.",
        }), 400
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_UPLOAD_BYTES:
        return jsonify({
            "success": False,
            "ok": False,
            "error": "file_too_large",
            "message": "حد الحجم 500 ميجابايت.",
        }), 400
    upload_dir = _upload_dir()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / safe_name
    try:
        file.save(str(file_path))
    except Exception as e:
        current_app.logger.exception("autoposter_media save failed (file %s): %s", file_path, e)
        return jsonify({"success": False, "ok": False, "error": "save_failed", "message": "تعذر حفظ الملف"}), 500
    rel_path = f"uploads/media/{safe_name}"
    public_url = f"/autoposter/serve/media/{safe_name}"
    tenant_slug = session.get("tenant_slug")
    rec = AutoposterMedia(
        tenant_slug=tenant_slug,
        media_type=media_type,
        file_name=filename,
        filename=safe_name,
        file_path=rel_path,
        file_size=size,
        size_bytes=size,
        public_url=public_url,
    )
    try:
        db.session.add(rec)
        db.session.commit()
    except OperationalError as e:
        current_app.logger.exception("autoposter_media db operational error, trying create_all: %s", e)
        db.session.rollback()
        try:
            db.create_all()
            db.session.add(rec)
            db.session.commit()
        except Exception as e2:
            current_app.logger.exception("autoposter_media db failed after create_all: %s", e2)
            db.session.rollback()
            return jsonify({"success": False, "ok": False, "error": "db_failed", "message": "تعذر حفظ بيانات الوسائط"}), 500
    except Exception as e:
        current_app.logger.exception("autoposter_media db failed: %s", e)
        db.session.rollback()
        return jsonify({"success": False, "ok": False, "error": "db_failed", "message": "تعذر حفظ بيانات الوسائط"}), 500
    return jsonify({
        "success": True,
        "ok": True,
        "url": public_url,
        "id": rec.id,
        "media_type": media_type,
        "file_name": filename,
        "file_path": rel_path,
        "file_size": size,
        "public_url": public_url,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    })
