from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Blueprint, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

from routes.inventory import check_permission
from services.media_service import (
    VIDEO_EXTENSIONS,
    detect_kind,
    get_thumbnail_upload_root,
    get_video_upload_root,
    save_uploaded_file,
)


media_library_bp = Blueprint("media_library", __name__)


def _ensure_inventory_access():
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    return None


def _format_video_item(path: Path) -> dict:
    public_url = url_for("media_library.serve_video", filename=path.name)
    absolute_url = request.url_root.rstrip("/") + public_url
    stat = path.stat()
    return {
        "name": path.name,
        "url": public_url,
        "absolute_url": absolute_url,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
    }


def _list_videos() -> list[dict]:
    root = get_video_upload_root()
    if not root.exists():
        return []
    items: list[Path] = [
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    items.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [_format_video_item(path) for path in items]


@media_library_bp.route("/inventory/videos", methods=["GET"])
def inventory_video_library():
    guard = _ensure_inventory_access()
    if guard:
        return guard
    return render_template("inventory_video_library.html", videos=_list_videos())


@media_library_bp.route("/inventory/videos/upload", methods=["POST"])
def upload_inventory_video():
    guard = _ensure_inventory_access()
    if guard:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    file = request.files.get("video")
    if not file or not file.filename:
        return jsonify({"success": False, "error": "يرجى اختيار ملف فيديو."}), 400

    if detect_kind(file.content_type or "") != "video" and Path(file.filename).suffix.lower() not in VIDEO_EXTENSIONS:
        return jsonify({"success": False, "error": "الملف المرسل ليس فيديو مدعوماً."}), 400

    result = save_uploaded_file(file, max_mb=500)
    if not result.get("ok"):
        return jsonify({"success": False, "error": result.get("message") or "فشل رفع الفيديو."}), 400

    public_url = str(result.get("url") or "").strip()
    filename = Path(public_url).name
    item = {
        "name": filename,
        "url": public_url,
        "absolute_url": request.url_root.rstrip("/") + public_url,
        "size_mb": result.get("size_mb"),
        "modified_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "thumbnail_url": result.get("thumbnail_url"),
        "duration_sec": result.get("duration_sec"),
        "width": result.get("width"),
        "height": result.get("height"),
    }
    return jsonify({"success": True, "message": "تم رفع الفيديو بنجاح.", "item": item})


@media_library_bp.route("/inventory/videos/<path:filename>", methods=["DELETE"])
def delete_inventory_video(filename: str):
    guard = _ensure_inventory_access()
    if guard:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    safe_name = Path(filename).name
    root = get_video_upload_root()
    path = root / safe_name
    if not path.exists() or not path.is_file():
        return jsonify({"success": False, "error": "الفيديو غير موجود."}), 404

    try:
        path.unlink()
    except Exception:
        return jsonify({"success": False, "error": "تعذر حذف الفيديو من الخادم."}), 500

    return jsonify({"success": True, "message": "تم حذف الفيديو.", "filename": safe_name})


@media_library_bp.route("/autoposter/serve/video/<path:filename>", methods=["GET"])
def serve_video(filename: str):
    safe_name = Path(filename).name
    root = get_video_upload_root()
    path = root / safe_name
    if not path.exists() or not path.is_file():
        abort(404)
    return send_from_directory(str(root), safe_name, conditional=True)


@media_library_bp.route("/autoposter/serve/thumbnail/<path:filename>", methods=["GET"])
def serve_thumbnail(filename: str):
    safe_name = Path(filename).name
    root = get_thumbnail_upload_root()
    path = root / safe_name
    if not path.exists() or not path.is_file():
        abort(404)
    return send_from_directory(str(root), safe_name, conditional=True)
