from datetime import datetime
from typing import Optional

from flask import Blueprint, jsonify, request

from extensions import db
from models.publish_channel import PublishChannel
from models.publish_job import PublishJob
from services.publish_service import create_jobs_for_channels, get_channels_for_tenant


publish_api_bp = Blueprint("publish_api", __name__, url_prefix="/publish/api")


def _get_tenant_slug() -> Optional[str]:
    """في وضع التطبيق المنفصل نستخدم مستأجراً ثابتاً واحداً."""
    return "global"


# ============== Channels ==============


@publish_api_bp.route("/channels", methods=["GET"])
def list_channels():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400

    chans = (
        PublishChannel.query.filter_by(tenant_slug=tenant_slug)
        .order_by(PublishChannel.created_at.desc())
        .all()
    )
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


@publish_api_bp.route("/channels", methods=["POST"])
def create_channel():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400

    data = request.get_json() or {}
    ch_type = (data.get("type") or "").strip()
    name = (data.get("name") or "").strip()
    external_id = (data.get("external_id") or "").strip()
    credentials = (data.get("credentials") or "").strip() or None

    if not ch_type or not name or not external_id:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "type, name, external_id مطلوبة لإنشاء قناة.",
                }
            ),
            400,
        )

    ch = PublishChannel(
        tenant_slug=tenant_slug,
        type=ch_type,
        name=name,
        external_id=external_id,
        credentials=credentials,
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(ch)
    db.session.commit()

    return jsonify({"success": True, "channel": {"id": ch.id}})


@publish_api_bp.route("/channels/<int:channel_id>", methods=["PATCH"])
def update_channel(channel_id: int):
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400

    ch = PublishChannel.query.filter_by(
        id=channel_id, tenant_slug=tenant_slug
    ).first()
    if not ch:
        return jsonify({"success": False, "error": "NOT_FOUND"}), 404

    data = request.get_json() or {}
    if "name" in data:
        ch.name = (data.get("name") or "").strip() or ch.name
    if "is_active" in data:
        ch.is_active = bool(data.get("is_active"))

    db.session.commit()
    return jsonify({"success": True})


@publish_api_bp.route("/channels/<int:channel_id>", methods=["DELETE"])
def delete_channel(channel_id: int):
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400

    ch = PublishChannel.query.filter_by(
        id=channel_id, tenant_slug=tenant_slug
    ).first()
    if not ch:
        return jsonify({"success": False, "error": "NOT_FOUND"}), 404

    db.session.delete(ch)
    db.session.commit()
    return jsonify({"success": True})


# ============== Jobs ==============


@publish_api_bp.route("/jobs", methods=["GET"])
def list_jobs():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400

    status = request.args.get("status")
    channel_id = request.args.get("channel_id", type=int)

    q = PublishJob.query.filter_by(tenant_slug=tenant_slug)
    if status:
        q = q.filter_by(status=status)
    if channel_id:
        q = q.filter_by(channel_id=channel_id)

    q = q.order_by(PublishJob.created_at.desc()).limit(100)
    jobs = q.all()

    return jsonify(
        {
            "success": True,
            "jobs": [
                {
                    "id": j.id,
                    "channel_id": j.channel_id,
                    "status": j.status,
                    "scheduled_at": j.scheduled_at.isoformat()
                    if j.scheduled_at
                    else None,
                    "published_at": j.published_at.isoformat()
                    if j.published_at
                    else None,
                    "title": j.title,
                    "text": (j.text or "")[:160],
                    "media_url": j.media_url,
                    "media_type": j.media_type,
                    "error_message": j.error_message,
                }
                for j in jobs
            ],
        }
    )


@publish_api_bp.route("/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id: int):
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400

    job = PublishJob.query.filter_by(
        id=job_id, tenant_slug=tenant_slug
    ).first()
    if not job:
        return jsonify({"success": False, "error": "NOT_FOUND"}), 404

    return jsonify(
        {
            "success": True,
            "job": {
                "id": job.id,
                "channel_id": job.channel_id,
                "status": job.status,
                "scheduled_at": job.scheduled_at.isoformat()
                if job.scheduled_at
                else None,
                "published_at": job.published_at.isoformat()
                if job.published_at
                else None,
                "title": job.title,
                "text": job.text,
                "media_url": job.media_url,
                "media_type": job.media_type,
                "retry_count": job.retry_count,
                "max_retries": job.max_retries,
                "error_code": job.error_code,
                "error_message": job.error_message,
            },
        }
    )


@publish_api_bp.route("/jobs", methods=["POST"])
def create_jobs():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400

    data = request.get_json() or {}
    text = (data.get("text") or data.get("content") or "").strip()
    title = (data.get("title") or "").strip() or None
    media_url = (data.get("media_url") or "").strip() or None
    media_type = (data.get("media_type") or "").strip() or None

    channel_ids = data.get("channel_ids") or []
    if not isinstance(channel_ids, list):
        return (
            jsonify(
                {"success": False, "error": "channel_ids يجب أن تكون قائمة من الأرقام."}
            ),
            400,
        )

    if not text and not media_url:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "الرجاء إدخال نص أو توفير رابط وسائط للمهمة.",
                }
            ),
            400,
        )

    scheduled_raw = (data.get("scheduled_at") or "").strip()
    if scheduled_raw:
        try:
            scheduled_at = datetime.fromisoformat(
                scheduled_raw.replace("Z", "+00:00")
            )
        except Exception:
            return (
                jsonify({"success": False, "error": "صيغة التاريخ غير صحيحة."}),
                400,
            )
    else:
        scheduled_at = datetime.utcnow()

    chans = get_channels_for_tenant(
        tenant_slug=tenant_slug,
        channel_ids=channel_ids,
        require_active=True,
    )
    if not chans:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "لم يتم العثور على القنوات المحددة أو أنها غير مفعّلة.",
                }
            ),
            400,
        )

    try:
        jobs = create_jobs_for_channels(
            tenant_slug=tenant_slug,
            channels=chans,
            text=text,
            media_url=media_url,
            media_type=media_type,
            scheduled_at=scheduled_at,
            title=title,
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    return jsonify(
        {
            "success": True,
            "scheduled_at": scheduled_at.isoformat(),
            "job_ids": [j.id for j in jobs],
        }
    )


@publish_api_bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
def cancel_job(job_id: int):
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400

    job = PublishJob.query.filter_by(
        id=job_id, tenant_slug=tenant_slug
    ).first()
    if not job:
        return jsonify({"success": False, "error": "NOT_FOUND"}), 404

    if job.status in ("published", "cancelled"):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "لا يمكن إلغاء مهمة منشورة أو ملغاة بالفعل.",
                }
            ),
            400,
        )

    job.status = "cancelled"
    db.session.commit()
    return jsonify({"success": True})

