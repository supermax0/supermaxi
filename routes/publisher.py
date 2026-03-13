from datetime import datetime
from pathlib import Path
from typing import List, Optional

from flask import Blueprint, jsonify, request, current_app, g
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from extensions import db
from models.publisher_channel import PublisherChannel
from models.publisher_job import PublisherJob
from services.publisher_service import create_jobs_for_channels

publisher_bp = Blueprint("publisher", __name__, url_prefix="/publisher")


def _get_tenant_slug() -> str:
    return getattr(g, "tenant", None) or ""


def _save_media(file: FileStorage) -> Optional[dict]:
    if not file or not file.filename:
        return None
    filename = secure_filename(file.filename)
    if not filename:
        return {"error": "اسم الملف غير صالح"}

    uploads_root = Path(current_app.root_path) / "uploads" / "publisher"
    uploads_root.mkdir(parents=True, exist_ok=True)
    unique_name = datetime.utcnow().strftime("%Y%m%d%H%M%S%f_") + filename
    dest = uploads_root / unique_name
    file.save(str(dest))

    ext = dest.suffix.lower()
    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        media_type = "image"
    else:
        media_type = "video"

    public_url = f"/uploads/publisher/{unique_name}"
    return {"url": public_url, "type": media_type}


@publisher_bp.route("/channels", methods=["GET"])
def list_channels():
    tenant_slug = _get_tenant_slug()
    q = PublisherChannel.query
    if tenant_slug:
        q = q.filter_by(tenant_slug=tenant_slug)
    chans: List[PublisherChannel] = q.order_by(PublisherChannel.created_at.desc()).all()
    return jsonify(
        {
            "success": True,
            "channels": [
                {
                    "id": c.id,
                    "type": c.type,
                    "name": c.name,
                    "external_id": c.external_id,
                    "is_active": c.is_active,
                }
                for c in chans
            ],
        }
    )


@publisher_bp.route("/jobs", methods=["POST"])
def create_jobs():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "لا يوجد مستأجر محدد (tenant)."}), 400

    form = request.form
    text = (form.get("text") or form.get("content") or "").strip()
    scheduled_raw = (form.get("scheduled_at") or "").strip()
    channels_ids = form.getlist("channel_ids") or form.getlist("channel_ids[]")

    if not channels_ids:
        return jsonify({"success": False, "error": "يجب اختيار قناة أو أكثر للنشر."}), 400

    media_info = None
    file = request.files.get("media") or request.files.get("file")
    if file and file.filename:
        media_info = _save_media(file)
        if media_info and media_info.get("error"):
            return jsonify({"success": False, "error": media_info["error"]}), 400

    if not text and not media_info:
        return jsonify({"success": False, "error": "أدخل محتوى نصي أو ارفع صورة/فيديو."}), 400

    if scheduled_raw:
        try:
            scheduled_at = datetime.fromisoformat(scheduled_raw.replace("Z", "+00:00"))
        except Exception:
            return jsonify({"success": False, "error": "صيغة التاريخ غير صحيحة."}), 400
    else:
        scheduled_at = datetime.utcnow()

    chans = (
        PublisherChannel.query.filter(
            PublisherChannel.tenant_slug == tenant_slug,
            PublisherChannel.id.in_(channels_ids),
            PublisherChannel.is_active.is_(True),
        ).all()
    )
    if not chans:
        return jsonify({"success": False, "error": "لم يتم العثور على القنوات المحددة."}), 400

    jobs = create_jobs_for_channels(
        channels=chans,
        content=text,
        media_url=(media_info or {}).get("url"),
        media_type=(media_info or {}).get("type"),
        scheduled_at=scheduled_at,
    )

    return jsonify(
        {
            "success": True,
            "jobs": [
                {
                    "id": j.id,
                    "channel_id": j.channel_id,
                    "status": j.status,
                    "scheduled_at": j.scheduled_at.isoformat(),
                }
                for j in jobs
            ],
        }
    )

