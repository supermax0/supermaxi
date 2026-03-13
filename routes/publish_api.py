from datetime import datetime
from typing import Optional
import json

import requests
from flask import Blueprint, jsonify, request, session, g, redirect, url_for
from sqlalchemy import inspect

from extensions import db
from models.publish_channel import PublishChannel
from models.publish_job import PublishJob
from models.publish_config import PublishConfig
from services.publish_service import create_jobs_for_channels, get_channels_for_tenant


publish_api_bp = Blueprint("publish_api", __name__, url_prefix="/publish/api")


def _require_login() -> bool:
    return "user_id" in session


def _get_tenant_slug() -> Optional[str]:
    """استخدام tenant_slug من جلسة النظام الأساسية (SaaS)."""
    slug = session.get("tenant_slug")
    if slug:
        g.tenant = slug
    return slug


def _ensure_publish_config_table() -> None:
    """
    ضمان وجود جدول publish_config في قاعدة بيانات المستأجر الحالية.
    هذا مهم لأن بعض قواعد بيانات الـ tenants قد لا تحتوي على الجدول بعد.
    """
    bind = db.session.get_bind()
    if not bind:
        return

    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if "publish_config" not in tables:
        PublishConfig.__table__.create(bind, checkfirst=True)


def _ensure_publish_core_tables() -> None:
    """
    ضمان وجود جداول القنوات والمهام الأساسية للنشر.
    يعالج حالة عدم تشغيل db.create_all() لبعض قواعد بيانات الـ tenants.
    """
    bind = db.session.get_bind()
    if not bind:
        return

    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "publish_channels" not in tables:
        PublishChannel.__table__.create(bind, checkfirst=True)
    if "publish_jobs" not in tables:
        PublishJob.__table__.create(bind, checkfirst=True)


def _get_facebook_app_config(tenant_slug: str) -> Optional[PublishConfig]:
    _ensure_publish_config_table()
    cfg = PublishConfig.query.filter_by(tenant_slug=tenant_slug).first()
    if not cfg or not cfg.facebook_app_id or not cfg.facebook_app_secret:
        return None
    return cfg


@publish_api_bp.before_request
def _guard():
    if not _require_login():
        return jsonify({"success": False, "error": "UNAUTHENTICATED"}), 401


# ============== Channels ==============


@publish_api_bp.route("/channels", methods=["GET"])
def list_channels():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400
    _ensure_publish_core_tables()

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
    _ensure_publish_core_tables()

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

    _ensure_publish_core_tables()

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

    _ensure_publish_core_tables()

    ch = PublishChannel.query.filter_by(
        id=channel_id, tenant_slug=tenant_slug
    ).first()
    if not ch:
        return jsonify({"success": False, "error": "NOT_FOUND"}), 404

    db.session.delete(ch)
    db.session.commit()
    return jsonify({"success": True})


# ============== Facebook Integration (OAuth + Pages) ==============


@publish_api_bp.route("/facebook/login-url", methods=["GET"])
def facebook_login_url():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400

    cfg = _get_facebook_app_config(tenant_slug)
    if not cfg:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "يرجى إدخال Facebook App ID و App Secret في صفحة الإعدادات أولاً.",
                }
            ),
            400,
        )

    redirect_uri = request.host_url.rstrip("/") + url_for(
        "publish_api.facebook_callback"
    )
    params = {
        "client_id": cfg.facebook_app_id,
        "redirect_uri": redirect_uri,
        "scope": "pages_show_list,pages_read_engagement,pages_manage_posts",
        "response_type": "code",
    }
    base_url = "https://www.facebook.com/v19.0/dialog/oauth"
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    login_url = f"{base_url}?{query}"

    return jsonify({"success": True, "login_url": login_url})


@publish_api_bp.route("/facebook/callback", methods=["GET"])
def facebook_callback():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        # لا توجد جلسة، نعيد إلى صفحة الدخول العامة
        return redirect("/login")

    cfg = _get_facebook_app_config(tenant_slug)
    if not cfg:
        return redirect(url_for("publish_ui.settings"))

    code = request.args.get("code")
    error = request.args.get("error")
    if error or not code:
        return redirect(url_for("publish_ui.dashboard"))

    redirect_uri = request.host_url.rstrip("/") + url_for(
        "publish_api.facebook_callback"
    )

    # 1) تبديل code بـ user access token
    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    try:
        resp = requests.get(
            token_url,
            params={
                "client_id": cfg.facebook_app_id,
                "client_secret": cfg.facebook_app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=10,
        )
        data = resp.json()
        access_token = data.get("access_token")
    except Exception:
        access_token = None

    if not access_token:
        return redirect(url_for("publish_ui.dashboard"))

    # 2) جلب صفحات المستخدم
    pages_url = "https://graph.facebook.com/v19.0/me/accounts"
    pages = []
    try:
        resp = requests.get(
            pages_url,
            params={"access_token": access_token},
            timeout=10,
        )
        data = resp.json()
        pages = data.get("data") or []
    except Exception:
        pages = []

    # 3) تخزين الصفحات كقنوات publish_channels
    for page in pages:
        page_id = page.get("id")
        name = page.get("name") or "Facebook Page"
        page_token = page.get("access_token")
        if not page_id:
            continue

        ch = PublishChannel.query.filter_by(
            tenant_slug=tenant_slug, type="facebook_page", external_id=page_id
        ).first()
        if not ch:
            ch = PublishChannel(
                tenant_slug=tenant_slug,
                type="facebook_page",
                name=name,
                external_id=page_id,
            )
            db.session.add(ch)

        creds = {"page_access_token": page_token, "source": "facebook_oauth"}
        ch.credentials = json.dumps(creds, ensure_ascii=False)

    db.session.commit()

    return redirect(url_for("publish_ui.dashboard"))


# ============== Jobs ==============


@publish_api_bp.route("/jobs", methods=["GET"])
def list_jobs():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400
    _ensure_publish_core_tables()

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

    _ensure_publish_core_tables()

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
    _ensure_publish_core_tables()

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

    _ensure_publish_core_tables()

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


# ============== Settings (App ID / Secret) ==============


@publish_api_bp.route("/settings", methods=["GET"])
def get_settings():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400
    _ensure_publish_config_table()

    cfg = PublishConfig.query.filter_by(tenant_slug=tenant_slug).first()
    return jsonify(
        {
            "success": True,
            "settings": {
                "facebook_app_id": cfg.facebook_app_id if cfg else None,
                "facebook_app_secret": cfg.facebook_app_secret if cfg else None,
            },
        }
    )


@publish_api_bp.route("/settings", methods=["POST"])
def save_settings():
    tenant_slug = _get_tenant_slug()
    if not tenant_slug:
        return jsonify({"success": False, "error": "NO_TENANT"}), 400
    _ensure_publish_config_table()

    data = request.get_json() or {}
    app_id = (data.get("facebook_app_id") or "").strip() or None
    app_secret = (data.get("facebook_app_secret") or "").strip() or None

    cfg = PublishConfig.query.filter_by(tenant_slug=tenant_slug).first()
    if not cfg:
        cfg = PublishConfig(tenant_slug=tenant_slug)
        db.session.add(cfg)

    cfg.facebook_app_id = app_id
    cfg.facebook_app_secret = app_secret
    db.session.commit()

    return jsonify({"success": True})

