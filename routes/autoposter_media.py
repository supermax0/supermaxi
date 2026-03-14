# مكتبة وسائط الأوتوبوستر — Media Library
# Routes: /autoposter/media, /autoposter/api/media/upload, /autoposter/api/media (list)
from pathlib import Path
import uuid
from flask import Blueprint, current_app, jsonify, render_template, request, session, send_from_directory
from werkzeug.utils import secure_filename
from sqlalchemy.exc import OperationalError
from extensions import db
from models.autoposter_media import AutoposterMedia

autoposter_media_bp = Blueprint("autoposter_media", __name__, url_prefix="/autoposter")

# صيغ مسموحة (المواصفة: jpg, png, webp, mp4, mov) — حد 500MB
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXT = {".mp4", ".mov"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB


def _upload_dir():
    """مجلد رفع مكتبة الوسائط: uploads/media/ تحت جذر التطبيق."""
    root = Path(current_app.root_path)
    base = root / "uploads" / "media"
    base.mkdir(parents=True, exist_ok=True)
    return base


@autoposter_media_bp.route("/serve/media/<path:filename>")
def serve_media(filename):
    """تقديم ملفات مكتبة الوسائط (للمعاينة والنشر)."""
    dir_path = _upload_dir()
    return send_from_directory(dir_path, filename, as_attachment=False)


@autoposter_media_bp.route("/media")
def media_library_page():
    """صفحة مكتبة الوسائط — عرض شبكة فيديو/صور مع معاينة."""
    from functools import wraps
    if not session.get("user_id"):
        from flask import redirect, url_for
        return redirect(url_for("index.login") + "?next=" + request.path)
    return render_template("autoposter/media_library.html")


@autoposter_media_bp.route("/api/media", methods=["GET"])
def api_media_list():
    """قائمة الوسائط للشركة الحالية (للاستخدام في إنشاء المنشور)."""
    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 401
    tenant_slug = session.get("tenant_slug")
    q = AutoposterMedia.query.order_by(AutoposterMedia.created_at.desc()).limit(200)
    if tenant_slug:
        q = q.filter_by(tenant_slug=tenant_slug)
    items = q.all()
    return jsonify({"media": [m.to_dict() for m in items]})


@autoposter_media_bp.route("/api/media/upload", methods=["POST"])
def api_media_upload():
    """
    رفع وسائط إلى مكتبة الوسائط.
    multipart/form-data، المفتاح: file.
    الحفظ في uploads/media/، اكتشاف النوع، حد 500MB، صيغ: jpg, png, webp, mp4, mov.
    """
    from flask import current_app
    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 401
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "media missing", "message": "لم يُرفع ملف"}), 400
    filename = secure_filename(file.filename) or "file"
    ext = (Path(filename).suffix or "").lower()
    if ext in ALLOWED_IMAGE_EXT:
        media_type = "image"
    elif ext in ALLOWED_VIDEO_EXT:
        media_type = "video"
    else:
        return jsonify({
            "ok": False,
            "error": "unsupported_type",
            "message": "الصيغ المسموحة: jpg, png, webp, mp4, mov.",
        }), 400
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_UPLOAD_BYTES:
        return jsonify({
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
        current_app.logger.exception("autoposter_media save failed: %s", e)
        return jsonify({"ok": False, "error": "save_failed", "message": "تعذر حفظ الملف"}), 500
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
        # في حال كان جدول مكتبة الوسائط غير موجود على قاعدة البيانات في السيرفر
        current_app.logger.exception("autoposter_media db operational error, trying create_all: %s", e)
        db.session.rollback()
        try:
            db.create_all()
            db.session.add(rec)
            db.session.commit()
        except Exception as e2:
            current_app.logger.exception("autoposter_media db failed after create_all: %s", e2)
            db.session.rollback()
            return jsonify({"ok": False, "error": "db_failed", "message": "تعذر حفظ بيانات الوسائط"}), 500
    except Exception as e:
        current_app.logger.exception("autoposter_media db failed: %s", e)
        db.session.rollback()
        return jsonify({"ok": False, "error": "db_failed", "message": "تعذر حفظ بيانات الوسائط"}), 500
    return jsonify({
        "ok": True,
        "id": rec.id,
        "media_type": media_type,
        "file_name": filename,
        "file_path": rel_path,
        "file_size": size,
        "public_url": public_url,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    })
