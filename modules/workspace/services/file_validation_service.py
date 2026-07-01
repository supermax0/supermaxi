from __future__ import annotations

import mimetypes
import os
from typing import Optional, Tuple

from flask import current_app
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
}

EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class FileValidationError(ValueError):
    pass


def get_max_upload_bytes() -> int:
    mb = current_app.config.get("WORKSPACE_UPLOAD_MAX_MB", 20)
    try:
        mb = int(mb)
    except (TypeError, ValueError):
        mb = 20
    return mb * 1024 * 1024


def normalize_extension(filename: str) -> str:
    _, ext = os.path.splitext(filename or "")
    return ext.lower()


def validate_upload(filename: str, mime_type: Optional[str], file_size: int) -> Tuple[str, str]:
    ext = normalize_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError("نوع الملف غير مدعوم. المسموح: PDF, PNG, JPG, WEBP")

    if file_size <= 0:
        raise FileValidationError("الملف فارغ")

    max_bytes = get_max_upload_bytes()
    if file_size > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise FileValidationError(f"حجم الملف يتجاوز الحد المسموح ({max_mb}MB)")

    expected_mime = EXT_TO_MIME.get(ext)
    guessed, _ = mimetypes.guess_type(filename)
    resolved_mime = (mime_type or guessed or expected_mime or "").split(";")[0].strip().lower()

    if resolved_mime and resolved_mime not in ALLOWED_MIME_TYPES:
        if expected_mime and resolved_mime != expected_mime:
            raise FileValidationError("نوع MIME للملف غير مسموح")

    if not resolved_mime:
        resolved_mime = expected_mime or "application/octet-stream"

    safe_name = secure_filename(os.path.basename(filename or "document"))
    if not safe_name:
        safe_name = f"document{ext}"

    return safe_name, resolved_mime
