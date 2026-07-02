"""رفع وإدارة مرفقات الأصول الثابتة."""
from __future__ import annotations

import os
import uuid

from flask import current_app, session
from werkzeug.utils import secure_filename

from extensions import db
from models.fixed_asset_attachment import ATTACHMENT_TYPES, FixedAssetAttachment

ALLOWED_EXTENSIONS = frozenset(
    {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".doc", ".docx", ".xls", ".xlsx"}
)
MAX_FILE_MB = 15


def allowed_attachment(filename: str) -> bool:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _uploads_dir(asset_id: int) -> str:
    tenant = (session.get("tenant_slug") or "default").strip() or "default"
    rel = os.path.join("static", "uploads", "fixed_assets", tenant, f"asset_{asset_id}")
    full = os.path.join(current_app.root_path, rel)
    os.makedirs(full, exist_ok=True)
    return full, rel.replace("\\", "/")


def save_asset_attachment(file_storage, asset_id: int, attachment_type: str, user_id=None):
    if attachment_type not in ATTACHMENT_TYPES:
        attachment_type = "other"
    original = secure_filename(file_storage.filename or "")
    if not original:
        raise ValueError("اسم الملف غير صالح")
    if not allowed_attachment(original):
        raise ValueError("نوع الملف غير مسموح")

    full_dir, rel_dir = _uploads_dir(asset_id)
    ext = os.path.splitext(original)[1].lower()
    token = uuid.uuid4().hex[:12]
    stored = f"{token}{ext}"
    full_path = os.path.join(full_dir, stored)
    file_storage.save(full_path)
    size = os.path.getsize(full_path) if os.path.exists(full_path) else None
    if size and size > MAX_FILE_MB * 1024 * 1024:
        os.remove(full_path)
        raise ValueError(f"حجم الملف يتجاوز {MAX_FILE_MB} ميجابايت")

    rel_path = f"{rel_dir}/{stored}"
    row = FixedAssetAttachment(
        asset_id=asset_id,
        file_name=original,
        file_path=rel_path,
        file_type=file_storage.mimetype,
        attachment_type=attachment_type,
        file_size=size,
        uploaded_by=user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def delete_asset_attachment(attachment: FixedAssetAttachment):
    if attachment.file_path:
        full = os.path.join(current_app.root_path, attachment.file_path.replace("/", os.sep))
        if os.path.isfile(full):
            try:
                os.remove(full)
            except OSError:
                pass
    db.session.delete(attachment)
