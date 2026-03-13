from __future__ import annotations

"""
خدمة موحّدة للتعامل مع وسائط النشر (صور / فيديو) في نظام Autoposter.

المسؤوليات:
- تحديد مسارات التخزين تحت مجلد static.
- التحقق من نوع الملف (MIME + الامتداد) والحجم.
- حفظ ملف الرفع باسم آمن (UUID).
- استخراج معلومات أساسية عن الميديا (الحجم بالميجا، الأبعاد، مدة الفيديو إن أمكن).
- معالجة اختيارية:
  - ضغط / تصغير الصور الكبيرة.
  - إنشاء صورة مصغّرة (thumbnail) للصور.

ملاحظة:
- تعتمد المعالجة المتقدمة على مكتبات اختيارية:
  - Pillow للصور (PIL).
  - ffmpeg للفيديو (إن كان متوفراً في PATH).
- في حال عدم توفر هذه الأدوات، سيستمر الرفع مع إرجاع معلومات أبسط بدون كسر الطلب.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Tuple, Dict, Any

import os
import uuid

from flask import current_app


MediaKind = Literal["image", "video"]


@dataclass
class SavedFileInfo:
    kind: MediaKind
    path: Path           # المسار على السيرفر (Filesystem path)
    public_url: str      # الرابط الذي يمكن للفرونتند استخدامه
    size_mb: float
    width: Optional[int] = None
    height: Optional[int] = None
    duration_sec: Optional[float] = None
    thumbnail_url: Optional[str] = None
    thumbnail_path: Optional[Path] = None


IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
}

ALLOWED_MIME_TYPES = IMAGE_MIME_TYPES | VIDEO_MIME_TYPES

ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".mp4",
    ".mov",
    ".webm",
}


def get_media_root() -> Path:
    """المجلد الجذر لملفات static داخل التطبيق."""
    root = Path(current_app.root_path)
    return root / "static"


def get_autoposter_upload_dir() -> Path:
    """
    مجلد رفع الوسائط الخاص بالـ Autoposter.
    مثال: <app_root>/static/autoposter/uploads
    """
    base = get_media_root() / "autoposter" / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_autoposter_thumb_dir() -> Path:
    """
    مجلد الثمبنايل للـ Autoposter.
    مثال: <app_root>/static/autoposter/uploads/thumbs
    """
    base = get_autoposter_upload_dir() / "thumbs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_video_upload_root() -> Path:
    """
    جذر مجلد رفع الفيديوهات. إن وُجد UPLOAD_VIDEO_ROOT في الإعدادات أو البيئة يُستخدم،
    وإلا في الإنتاج يُفترض /var/www/finora/uploads/videos، ومحلياً مجلد تحت root_path.
    """
    root = (
        (current_app.config.get("UPLOAD_VIDEO_ROOT") or "").strip()
        or os.environ.get("UPLOAD_VIDEO_ROOT", "").strip()
    )
    if root:
        return Path(root)
    # محلياً: مجلد uploads/videos تحت مجلد التطبيق
    return Path(current_app.root_path) / "uploads" / "videos"


def get_thumbnail_upload_root() -> Path:
    """جذر مجلد صور الثمبنايل للفيديو. نفس منطق get_video_upload_root."""
    root = (
        (current_app.config.get("UPLOAD_THUMBNAIL_ROOT") or "").strip()
        or os.environ.get("UPLOAD_THUMBNAIL_ROOT", "").strip()
    )
    if root:
        return Path(root)
    return Path(current_app.root_path) / "uploads" / "thumbnails"


def _normalize_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";")[0].strip().lower()


def detect_kind(content_type: str) -> Optional[MediaKind]:
    """تحديد نوع الوسيط (صورة / فيديو) من MIME."""
    ct = _normalize_content_type(content_type)
    if ct in IMAGE_MIME_TYPES:
        return "image"
    if ct in VIDEO_MIME_TYPES:
        return "video"
    return None


def validate_mime_and_extension(
    content_type: str | None,
    filename: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    التحقق من نوع الملف:
    - يتأكد أن الـ MIME ضمن الأنواع المسموحة.
    - يتأكد أن الامتداد متوافق تقريباً مع النوع.

    يرجع:
    - is_ok: هل التحقق ناجح.
    - error_code: كود خطأ موحد أو None.
    - message: رسالة نصية عربية للواجهة.
    """
    ct = _normalize_content_type(content_type)
    if not ct or ct not in ALLOWED_MIME_TYPES:
        return (
            False,
            "unsupported_type",
            "نوع الملف غير مدعوم. استخدم صورة (jpg, png, gif, webp) أو فيديو (mp4 / mov / webm).",
        )

    ext = (Path(filename).suffix or "").lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        # لا نرفض مباشرة، لكن نرجّح امتداد متوافق
        return (
            False,
            "bad_extension",
            "امتداد الملف غير متوافق مع النوع. استخدم الامتدادات الشائعة مثل .jpg أو .png أو .mp4 أو .mov.",
        )

    kind = detect_kind(ct)
    if not kind:
        return (
            False,
            "unsupported_type",
            "نوع الملف غير مدعوم. استخدم صورة (jpg, png, gif, webp) أو فيديو (mp4 / mov / webm).",
        )

    return True, None, None


def validate_size_bytes(
    size_bytes: int,
    max_mb: int,
) -> Tuple[bool, Optional[str], Optional[str], float]:
    """
    التحقق من حجم الملف بالميجا.

    يرجع:
    - is_ok
    - error_code
    - message
    - size_mb (للاستخدام في الاستجابة)
    """
    size_mb = round(size_bytes / (1024 * 1024), 2)
    if size_mb > max_mb:
        return (
            False,
            "file_too_large",
            f"حجم الملف أكبر من {max_mb} ميجا",
            size_mb,
        )
    return True, None, None, size_mb


def _safe_import_pillow():
    try:
        from PIL import Image  # type: ignore[import-untyped]

        return Image
    except Exception:
        return None


def _run_ffprobe(path: Path) -> Optional[Dict[str, Any]]:
    """
    استدعاء مبسّط لـ ffprobe (إن وجد) للحصول على مدة الفيديو وأبعاده.
    لا يرفع استثناءات، فقط يرجع None عند الفشل.
    """
    try:
        import json
        import subprocess

        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-of",
            "json",
            str(path),
        ]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return None
        s = streams[0]
        return {
            "width": int(float(s.get("width"))) if s.get("width") else None,
            "height": int(float(s.get("height"))) if s.get("height") else None,
            "duration": float(s.get("duration")) if s.get("duration") else None,
        }
    except Exception:
        return None


def inspect_media(path: Path, kind: MediaKind) -> Tuple[Optional[int], Optional[int], Optional[float]]:
    """
    استخراج عرض/ارتفاع ومدة تقريبية للميديا إن أمكن.
    لا يرفع استثناءات؛ أي خطأ يرجع (None, None, None).
    """
    if kind == "image":
        Image = _safe_import_pillow()
        if not Image:
            return None, None, None
        try:
            with Image.open(path) as im:
                w, h = im.size
            return int(w), int(h), None
        except Exception:
            return None, None, None

    # فيديو
    info = _run_ffprobe(path)
    if not info:
        return None, None, None
    return info.get("width"), info.get("height"), info.get("duration")


def process_image(
    path: Path,
    *,
    max_width: int = 1920,
    max_height: int = 1080,
    quality: int = 85,
) -> None:
    """
    تصغير الصورة لو كانت أكبر من الحدود المحددة، مع ضغط بسيط.
    لا يرفع استثناءات؛ أي خطأ يعني ترك الملف كما هو.
    """
    Image = _safe_import_pillow()
    if not Image:
        return
    try:
        with Image.open(path) as im:
            im_format = im.format
            w, h = im.size
            if w <= max_width and h <= max_height:
                return
            im.thumbnail((max_width, max_height))
            im.save(path, format=im_format or "JPEG", quality=quality, optimize=True)
    except Exception:
        return


def generate_image_thumbnail(
    path: Path,
    *,
    width: int = 480,
    height: int = 480,
) -> Optional[Tuple[Path, str]]:
    """
    إنشاء صورة مصغرة للصورة الأصلية، تحفظ في مجلد thumbs.

    يرجع:
    - (thumbnail_path, public_url) أو None عند الفشل.
    """
    Image = _safe_import_pillow()
    if not Image:
        return None
    try:
        thumb_dir = get_autoposter_thumb_dir()
        name = f"{uuid.uuid4().hex}{path.suffix.lower() or '.jpg'}"
        thumb_path = thumb_dir / name

        with Image.open(path) as im:
            im.thumbnail((width, height))
            im.save(thumb_path, format=im.format or "JPEG", quality=80, optimize=True)

        # بناء الـ URL النسبي تحت static
        rel = thumb_path.relative_to(get_media_root())
        public_url = f"{current_app.static_url_path}/{rel.as_posix()}"
        return thumb_path, public_url
    except Exception:
        return None


def save_uploaded_file(file_storage, max_mb: int = 200) -> Dict[str, Any]:
    """
    معالجة كاملة لرفع ملف واحد من نوع Werkzeug FileStorage:
    - يتحقق من النوع والحجم.
    - يحفظ الملف في مجلد الرفع.
    - يحاول استخراج معلومات الميديا وإنشاء ثَمبنايل للصور.

    يرجع JSON جاهز للـ API:
    {
      \"ok\": bool,
      \"error_code\": str | null,
      \"message\": str | null,
      \"url\": str | null,
      \"type\": \"image\" | \"video\" | null,
      \"thumbnail_url\": str | null,
      \"size_mb\": float | null,
      \"width\": int | null,
      \"height\": int | null,
      \"duration_sec\": float | null
    }
    """
    from werkzeug.datastructures import FileStorage  # type: ignore[import-untyped]

    if not isinstance(file_storage, FileStorage):
        return {
            "ok": False,
            "error_code": "no_file",
            "message": "لم يُرفع ملف",
        }

    filename = file_storage.filename or ""
    if not filename:
        return {
            "ok": False,
            "error_code": "no_file",
            "message": "لم يُرفع ملف",
        }

    ct = _normalize_content_type(file_storage.content_type or "")
    is_ok, code, msg = validate_mime_and_extension(ct, filename)
    if not is_ok:
        return {
            "ok": False,
            "error_code": code,
            "message": msg,
        }

    kind = detect_kind(ct)
    if kind is None:
        return {
            "ok": False,
            "error_code": "unsupported_type",
            "message": "نوع الملف غير مدعوم.",
        }

    # تجهيز اسم آمن
    ext = (Path(filename).suffix or "").lower()
    if not ext or ext not in ALLOWED_EXTENSIONS:
        ext = ".mp4" if kind == "video" else ".jpg"
    safe_name = f"{uuid.uuid4().hex}{ext}"

    # مسار الحفظ: الصور تحت static/autoposter/uploads، الفيديو من get_video_upload_root (قابل للتكوين)
    if kind == "video":
        upload_dir = get_video_upload_root()
    else:
        upload_dir = get_autoposter_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / safe_name

    try:
        file_storage.save(str(dest_path))
    except Exception as e:  # pragma: no cover - يعتمد على نظام الملفات
        current_app.logger.exception("Media upload: failed to save file: %s", e)
        return {
            "ok": False,
            "error_code": "save_failed",
            "message": "تعذر حفظ الملف على الخادم.",
        }

    # التحقق من الحجم بعد الحفظ
    try:
        size_bytes = os.path.getsize(dest_path)
    except Exception:
        size_bytes = 0

    is_ok, size_code, size_msg, size_mb = validate_size_bytes(size_bytes, max_mb)
    if not is_ok:
        try:
            dest_path.unlink(missing_ok=True)
        except Exception:
            pass
        return {
            "ok": False,
            "error_code": size_code,
            "message": size_msg,
            "size_mb": size_mb,
        }

    # معالجة / استخراج معلومات
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    thumb_url: Optional[str] = None

    try:
        if kind == "image":
            # تصغير إذا كانت كبيرة جداً ثم استخراج الأبعاد
            process_image(dest_path)
            width, height, _ = inspect_media(dest_path, kind="image")
            thumb_res = generate_image_thumbnail(dest_path)
            if thumb_res:
                _, thumb_url = thumb_res
        else:
            # فيديو: معالجة متقدمة (تحويل MOV → MP4 + thumbnail + metadata)
            final_path = dest_path

            # إن كان الامتداد MOV حوّله إلى MP4 للحفظ النهائي
            if final_path.suffix.lower() == ".mov":
                try:
                    import subprocess

                    mp4_name = final_path.with_suffix(".mp4")
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(final_path),
                        "-vcodec",
                        "libx264",
                        "-acodec",
                        "aac",
                        str(mp4_name),
                    ]
                    proc = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                        text=True,
                    )
                    if proc.returncode == 0 and mp4_name.exists():
                        # حذف الملف الأصلي واستبداله بالـ mp4
                        try:
                            final_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                        final_path = mp4_name
                except Exception:
                    # في حال فشل ffmpeg نُبقي الملف كما هو (MOV) ونستمر
                    final_path = dest_path

            # استخراج معلومات الفيديو عبر ffprobe (موجودة في inspect_media)
            width, height, duration = inspect_media(final_path, kind="video")

            # إنشاء thumbnail عند ثانية 3 إن أمكن
            try:
                import subprocess

                thumb_dir = get_thumbnail_upload_root()
                thumb_dir.mkdir(parents=True, exist_ok=True)
                thumb_name = f"{uuid.uuid4().hex}.jpg"
                thumb_path = thumb_dir / thumb_name
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(final_path),
                    "-ss",
                    "00:00:03",
                    "-vframes",
                    "1",
                    str(thumb_path),
                ]
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    text=True,
                )
                if proc.returncode == 0 and thumb_path.exists():
                    thumb_url = f"/autoposter/serve/thumbnail/{thumb_name}"
            except Exception:
                # thumbnail اختياري؛ أي خطأ هنا لا يكسر الرفع
                pass

            # تحديث dest_path إن تم التحويل إلى mp4
            dest_path = final_path
    except Exception:
        # أي خطأ في هذه المرحلة لا يمنع استخدام الملف
        pass

    # بناء URL عام للفيديو: تقديم عبر التطبيق (/autoposter/serve/) ليعمل بدون إعداد Nginx لـ /uploads/
    video_root_str = str(get_video_upload_root())
    thumb_root_str = str(get_thumbnail_upload_root())
    if kind == "video" and (str(dest_path).startswith(video_root_str) or "/uploads/videos" in str(dest_path)):
        public_url = f"/autoposter/serve/video/{dest_path.name}"
    else:
        rel = dest_path.relative_to(get_media_root())
        public_url = f"{current_app.static_url_path}/{rel.as_posix()}"

    return {
        "ok": True,
        "error_code": None,
        "message": None,
        "url": public_url,
        "type": kind,
        "thumbnail_url": thumb_url,
        "size_mb": size_mb,
        "width": width,
        "height": height,
        "duration_sec": duration,
    }

