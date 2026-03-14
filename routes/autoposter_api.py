# Autoposter API — GET /autoposter/api/media (filesystem-based list)
# Scans media directories and returns uploaded files as JSON.
# Does not depend on database; safe when DB table is empty or missing.
import os
from pathlib import Path

from flask import Blueprint, current_app, jsonify

autoposter_api_bp = Blueprint("autoposter_api", __name__, url_prefix="/autoposter")

# Folders to scan (relative to project root), and URL prefix for each
MEDIA_SCAN_DIRS = [
    ("media", "/media"),
    ("uploads/images", "/uploads/images"),
    ("uploads/videos", "/uploads/videos"),
    ("uploads/media", "/uploads/media"),
]

# Allowed file extensions for listing (images + videos)
ALLOWED_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".mp4", ".mov", ".webm", ".avi",
}


def _project_root():
    """Project root: AUTOPOSTER_MEDIA_ROOT or app root_path."""
    custom = current_app.config.get("AUTOPOSTER_MEDIA_ROOT")
    if custom:
        return Path(custom)
    return Path(current_app.root_path)


def _ensure_dir(path: Path) -> None:
    """Create directory if missing; ignore errors."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _scan_media():
    """Scan configured folders and return list of { name, url }."""
    root = _project_root()
    seen = set()
    out = []
    for rel_dir, url_prefix in MEDIA_SCAN_DIRS:
        folder = root / rel_dir
        _ensure_dir(folder)
        try:
            for name in os.listdir(folder):
                if name.startswith("."):
                    continue
                path = folder / name
                if not path.is_file():
                    continue
                ext = path.suffix.lower()
                if ext not in ALLOWED_EXT:
                    continue
                key = (rel_dir, name)
                if key in seen:
                    continue
                seen.add(key)
                url = f"{url_prefix.rstrip('/')}/{name}"
                out.append({"name": name, "url": url})
        except OSError:
            continue
    return out


@autoposter_api_bp.route("/api/media", methods=["GET"])
def api_media_list():
    """
    List uploaded media by scanning media directories.
    Returns JSON: { success: true, media: [ { name, url } ] }.
    Never raises; returns empty list if folders missing or on error.
    """
    try:
        items = _scan_media()
        return jsonify({"success": True, "media": items})
    except Exception as e:
        if current_app.logger:
            current_app.logger.exception("autoposter_api /api/media failed: %s", e)
        return jsonify({"success": False, "media": []})
