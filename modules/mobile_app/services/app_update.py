"""Resolve Finora Social in-app APK update metadata for bootstrap."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import current_app, has_request_context, request

DEFAULT_APK_PATH = "/static/downloads/finora-social.apk"
VERSION_JSON_NAME = "finora-social-version.json"
DEFAULT_MESSAGE = "يتوفر تحديث جديد لتطبيق Finora. حدّث الآن لتحسين الأداء والحماية."


def _downloads_dir() -> Path:
    root = Path(current_app.root_path)
    return root / "static" / "downloads"


def _read_version_json() -> dict[str, Any]:
    path = _downloads_dir() / VERSION_JSON_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _absolute_apk_url(raw: str) -> str:
    url = (raw or "").strip() or DEFAULT_APK_PATH
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url.startswith("/"):
        url = "/" + url
    if has_request_context():
        # Prefer public HTTPS host when behind nginx/proxy.
        proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",")[0].strip()
        host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
        if host:
            if proto not in {"http", "https"}:
                proto = "https"
            return f"{proto}://{host}{url}"
        return request.url_root.rstrip("/") + url
    return url


def get_app_update_payload() -> dict[str, Any]:
    """Build bootstrap `app_update` block (version.json overrides env)."""
    file_meta = _read_version_json()

    latest_version = (
        str(file_meta.get("latest_version") or "").strip()
        or _env("APP_SOCIAL_APK_VERSION", "1.2.0")
        or "1.2.0"
    )
    latest_build = _as_int(
        file_meta.get("latest_build")
        if file_meta.get("latest_build") is not None
        else _env("APP_SOCIAL_APK_BUILD", "3"),
        3,
    )
    min_version = (
        str(file_meta.get("min_version") or "").strip()
        or _env("APP_SOCIAL_APK_MIN_VERSION", "1.0.0")
        or "1.0.0"
    )
    min_build = _as_int(
        file_meta.get("min_build")
        if file_meta.get("min_build") is not None
        else _env("APP_SOCIAL_APK_MIN_BUILD", "1"),
        1,
    )
    apk_url = _absolute_apk_url(
        str(file_meta.get("apk_url") or "").strip()
        or _env("APP_SOCIAL_APK_URL", DEFAULT_APK_PATH)
        or DEFAULT_APK_PATH
    )
    message = (
        str(file_meta.get("message") or "").strip()
        or _env("APP_SOCIAL_APK_UPDATE_MESSAGE", DEFAULT_MESSAGE)
        or DEFAULT_MESSAGE
    )
    force_flag = file_meta.get("force")
    if force_flag is None:
        force_flag = _env("APP_SOCIAL_APK_FORCE", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    else:
        force_flag = bool(force_flag)

    return {
        "latest_version": latest_version,
        "latest_build": latest_build,
        "min_version": min_version,
        "min_build": min_build,
        "apk_url": apk_url,
        "force": bool(force_flag),
        "message": message,
    }
