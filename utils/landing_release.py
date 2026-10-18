"""Public metadata for the desktop installer actually shipped with this site."""
import json
import re
from pathlib import Path


def get_desktop_release(static_folder):
    downloads = Path(static_folder) / "downloads"
    try:
        manifest = json.loads((downloads / "finora-management.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return None
        filename = manifest.get("filename", "")
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9._-]+\.exe", filename):
            return None
        size = (downloads / filename).stat().st_size
        if size <= 0 or size != manifest.get("size_bytes"):
            return None
        return {
            "version": str(manifest.get("version", "")),
            "platform": str(manifest.get("platform", "Windows")),
            "url": "/static/downloads/" + filename,
            "size_mb": round(size / 1024 / 1024, 1),
        }
    except (OSError, ValueError, TypeError):
        return None
