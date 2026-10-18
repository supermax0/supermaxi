"""Call recording attachments: upload from device, authenticated playback."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g, request, send_file

from extensions import db
from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.models import PhoneAuditLog, PhoneCallLog
from modules.phone_app.schemas import api_error, api_ok
from modules.phone_app.services.feature_flags import require_feature

MAX_RECORDING_BYTES = 120 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    "mp3", "m4a", "aac", "amr", "wav", "ogg", "opus", "3gp", "3gpp",
}
MIME_BY_EXT = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "amr": "audio/amr",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
    "3gp": "audio/3gpp",
    "3gpp": "audio/3gpp",
}


def _recordings_root() -> Path:
    root = (os.environ.get("PHONE_RECORDINGS_ROOT") or "").strip()
    base = Path(root) if root else Path(current_app.root_path) / "uploads" / "phone_recordings"
    return base


def _tenant_dir() -> Path:
    slug = re.sub(r"[^a-z0-9_-]", "", str(getattr(g, "tenant", "") or "default").lower())
    path = _recordings_root() / (slug or "default")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_call(call_id: int) -> PhoneCallLog | None:
    return PhoneCallLog.query.filter_by(id=call_id).first()


@phone_api_v1_bp.post("/calls/<int:call_id>/recording")
@require_phone_auth
def upload_call_recording(call_id: int):
    blocked = require_feature("recording")
    if blocked is not None:
        return blocked

    row = _find_call(call_id)
    if row is None:
        return api_error("Call not found", 404, code="not_found")
    if row.employee_id != g.phone_employee.id:
        return api_error("Not your call", 403, code="forbidden")

    if getattr(row, "recording_path", None):
        return api_ok({"duplicate": True, "has_recording": True})

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return api_error("file required", 400, code="validation_error")

    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return api_error("Unsupported audio type", 400, code="validation_error")

    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size <= 0:
        return api_error("Empty file", 400, code="validation_error")
    if size > MAX_RECORDING_BYTES:
        return api_error("File too large", 413, code="too_large")

    duration = None
    raw_duration = request.form.get("duration_sec")
    if raw_duration:
        try:
            duration = max(0, int(float(raw_duration)))
        except ValueError:
            duration = None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"call_{row.id}_{stamp}.{ext}"
    dest = _tenant_dir() / filename
    upload.save(str(dest))

    row.recording_path = str(dest.relative_to(_recordings_root()))
    row.recording_size = size
    row.recording_duration_sec = duration
    row.recording_mime = MIME_BY_EXT.get(ext, "application/octet-stream")
    row.recording_uploaded_at = datetime.utcnow()
    row.recording_uploaded_by = g.phone_employee.id
    db.session.add(
        PhoneAuditLog(
            employee_id=g.phone_employee.id,
            device_id=getattr(g, "phone_device", None)
            and getattr(g.phone_device, "device_uuid", None),
            action="call_recording_upload",
            detail=f"call={row.id};size={size}",
        )
    )
    db.session.commit()
    return api_ok(
        {
            "created": True,
            "has_recording": True,
            "recording_duration_sec": row.recording_duration_sec,
            "recording_size": row.recording_size,
        }
    )


@phone_api_v1_bp.get("/calls/<int:call_id>/recording")
@require_phone_auth
def stream_call_recording(call_id: int):
    blocked = require_feature("recording")
    if blocked is not None:
        return blocked

    row = _find_call(call_id)
    if row is None or not getattr(row, "recording_path", None):
        return api_error("Recording not found", 404, code="not_found")

    path = (_recordings_root() / row.recording_path).resolve()
    if not str(path).startswith(str(_recordings_root().resolve())) or not path.exists():
        return api_error("Recording not found", 404, code="not_found")

    return send_file(
        str(path),
        mimetype=row.recording_mime or "application/octet-stream",
        conditional=True,
    )
