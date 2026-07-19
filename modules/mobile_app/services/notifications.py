"""In-app + queued push notifications (Phase 8)."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from extensions import db
from modules.mobile_app.models import (
    MobileNotification,
    MobileNotificationDelivery,
    MobileNotificationPreference,
    MobileUser,
    MobileUserDevice,
)

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    def __init__(self, message: str, code: str = "notification_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _prefs(user_id: int) -> MobileNotificationPreference:
    row = MobileNotificationPreference.query.filter_by(user_id=user_id).first()
    if row:
        return row
    row = MobileNotificationPreference(user_id=user_id)
    db.session.add(row)
    db.session.flush()
    return row


def get_preferences(user_id: int) -> dict:
    p = _prefs(user_id)
    db.session.commit()
    return {
        "orders_enabled": bool(p.orders_enabled),
        "marketing_enabled": bool(p.marketing_enabled),
        "rewards_enabled": bool(p.rewards_enabled),
        "comments_enabled": bool(p.comments_enabled),
        "push_enabled": bool(p.push_enabled),
    }


def update_preferences(user_id: int, payload: dict) -> dict:
    p = _prefs(user_id)
    for key in (
        "orders_enabled",
        "marketing_enabled",
        "rewards_enabled",
        "comments_enabled",
        "push_enabled",
    ):
        if key in payload:
            setattr(p, key, bool(payload[key]))
    p.updated_at = datetime.utcnow()
    db.session.commit()
    return get_preferences(user_id)


def create_user_notification(
    *,
    user_id: int,
    title: str,
    body: str,
    notification_type: str = "general",
    data: dict | None = None,
    respect_prefs: bool = True,
) -> MobileNotification | None:
    if respect_prefs:
        prefs = _prefs(user_id)
        if notification_type.startswith("order") and not prefs.orders_enabled:
            return None
        if notification_type.startswith("reward") and not prefs.rewards_enabled:
            return None
        if notification_type.startswith("marketing") and not prefs.marketing_enabled:
            return None
        if notification_type.startswith("comment") and not prefs.comments_enabled:
            return None

    notif = MobileNotification(
        user_id=user_id,
        title=(title or "").strip()[:200],
        body=(body or "").strip(),
        notification_type=notification_type,
        data_json=json.dumps(data or {}, ensure_ascii=False),
        audience="user",
        status="sent",
        sent_at=datetime.utcnow(),
    )
    db.session.add(notif)
    db.session.flush()
    db.session.add(
        MobileNotificationDelivery(
            notification_id=notif.id,
            user_id=user_id,
            channel="in_app",
            status="delivered",
        )
    )
    # Optional push delivery record (actual FCM provider later)
    prefs = _prefs(user_id)
    if prefs.push_enabled:
        device = (
            MobileUserDevice.query.filter_by(user_id=user_id)
            .filter(MobileUserDevice.push_token.isnot(None))
            .order_by(MobileUserDevice.last_seen_at.desc())
            .first()
        )
        if device and device.push_token:
            delivery = MobileNotificationDelivery(
                notification_id=notif.id,
                user_id=user_id,
                channel="push",
                status="queued",
            )
            db.session.add(delivery)
            db.session.flush()
            try:
                from modules.mobile_app.providers.push import send_push
                import json as _json

                payload = {}
                if notif.data_json:
                    try:
                        payload = _json.loads(notif.data_json)
                    except Exception:
                        payload = {}
                ok = send_push(
                    token=device.push_token,
                    title=notif.title,
                    body=notif.body,
                    data=payload,
                )
                delivery.status = "delivered" if ok else "failed"
            except Exception:
                logger.exception("push send failed notification=%s", notif.id)
                delivery.status = "failed"
    db.session.commit()
    return notif


def list_notifications(user_id: int, *, limit: int = 40, unread_only: bool = False) -> list[dict]:
    q = (
        db.session.query(MobileNotification, MobileNotificationDelivery)
        .join(
            MobileNotificationDelivery,
            MobileNotificationDelivery.notification_id == MobileNotification.id,
        )
        .filter(
            MobileNotificationDelivery.user_id == user_id,
            MobileNotificationDelivery.channel == "in_app",
        )
        .order_by(MobileNotification.id.desc())
    )
    if unread_only:
        q = q.filter(MobileNotificationDelivery.read_at.is_(None))
    rows = q.limit(limit).all()
    out = []
    for notif, delivery in rows:
        data = {}
        if notif.data_json:
            try:
                data = json.loads(notif.data_json)
            except json.JSONDecodeError:
                data = {}
        out.append(
            {
                "id": notif.id,
                "delivery_id": delivery.id,
                "title": notif.title,
                "body": notif.body,
                "type": notif.notification_type,
                "data": data,
                "read": delivery.read_at is not None,
                "read_at": delivery.read_at.isoformat() if delivery.read_at else None,
                "created_at": notif.created_at.isoformat() if notif.created_at else None,
            }
        )
    return out


def mark_read(user_id: int, notification_id: int) -> dict:
    delivery = (
        MobileNotificationDelivery.query.filter_by(
            notification_id=notification_id, user_id=user_id, channel="in_app"
        ).first()
    )
    if delivery is None:
        raise NotificationError("الإشعار غير موجود", "not_found")
    if delivery.read_at is None:
        delivery.read_at = datetime.utcnow()
        db.session.commit()
    return {"id": notification_id, "read": True}


def unread_count(user_id: int) -> int:
    return (
        MobileNotificationDelivery.query.filter_by(
            user_id=user_id, channel="in_app"
        )
        .filter(MobileNotificationDelivery.read_at.is_(None))
        .count()
    )


def register_device(
    *,
    user_id: int,
    device_id: str,
    platform: str = "unknown",
    push_token: str | None = None,
    app_version: str | None = None,
) -> dict:
    device_id = (device_id or "").strip()
    if not device_id:
        raise NotificationError("device_id مطلوب", "validation_error")
    row = MobileUserDevice.query.filter_by(user_id=user_id, device_id=device_id).first()
    if row is None:
        row = MobileUserDevice(user_id=user_id, device_id=device_id)
        db.session.add(row)
    row.platform = (platform or "unknown")[:30]
    if push_token is not None:
        row.push_token = (push_token or "")[:512] or None
    if app_version is not None:
        row.app_version = (app_version or "")[:40] or None
    row.last_seen_at = datetime.utcnow()
    db.session.commit()
    return {
        "id": row.id,
        "device_id": row.device_id,
        "platform": row.platform,
        "has_push_token": bool(row.push_token),
    }


def unregister_device(*, user_id: int, device_row_id: int) -> None:
    row = MobileUserDevice.query.filter_by(id=device_row_id, user_id=user_id).first()
    if row is None:
        raise NotificationError("الجهاز غير موجود", "not_found")
    row.push_token = None
    db.session.commit()


def _resolve_audience_user_ids(audience: str) -> list[int]:
    audience = (audience or "all").strip().lower()
    users = MobileUser.query.filter_by(is_active=True).all()
    if audience == "all":
        return [u.id for u in users]
    if audience in {"tier_gold", "gold"}:
        from modules.mobile_app.models import MobileRewardAccount

        ids = [
            a.user_id
            for a in MobileRewardAccount.query.filter_by(tier_key="gold").all()
        ]
        return ids
    if audience in {"tier_vip", "vip"}:
        from modules.mobile_app.models import MobileRewardAccount

        return [
            a.user_id
            for a in MobileRewardAccount.query.filter_by(tier_key="vip").all()
        ]
    return [u.id for u in users]


def enqueue_broadcast(
    *,
    title: str,
    body: str,
    notification_type: str = "marketing",
    audience: str = "all",
    data: dict | None = None,
    created_by: int | None = None,
    tenant_slug: str | None = None,
) -> dict:
    """Queue a broadcast and deliver in a background thread (not inside request hot path)."""
    notif = MobileNotification(
        user_id=None,
        title=(title or "").strip()[:200],
        body=(body or "").strip(),
        notification_type=notification_type,
        data_json=json.dumps(data or {}, ensure_ascii=False),
        audience=audience,
        status="queued",
        created_by=created_by,
    )
    db.session.add(notif)
    db.session.commit()
    notif_id = notif.id

    def _worker():
        try:
            from flask import g
            from app import app

            with app.app_context():
                if tenant_slug:
                    g.tenant = tenant_slug
                    from modules.mobile_app.schema_guard import ensure_mobile_app_schema

                    ensure_mobile_app_schema()
                row = db.session.get(MobileNotification, notif_id)
                if row is None:
                    return
                row.status = "sending"
                db.session.commit()
                user_ids = _resolve_audience_user_ids(row.audience)
                payload = {}
                if row.data_json:
                    try:
                        payload = json.loads(row.data_json)
                    except json.JSONDecodeError:
                        payload = {}
                for uid in user_ids:
                    create_user_notification(
                        user_id=uid,
                        title=row.title,
                        body=row.body,
                        notification_type=row.notification_type,
                        data=payload,
                        respect_prefs=True,
                    )
                row.status = "sent"
                row.sent_at = datetime.utcnow()
                db.session.commit()
        except Exception:
            logger.exception("broadcast notification failed id=%s", notif_id)
            try:
                from flask import g
                from app import app

                with app.app_context():
                    if tenant_slug:
                        g.tenant = tenant_slug
                    row = db.session.get(MobileNotification, notif_id)
                    if row:
                        row.status = "failed"
                        db.session.commit()
            except Exception:
                logger.exception("failed to mark broadcast failed")

    try:
        from flask import current_app

        if current_app.config.get("TESTING"):
            _worker()
            return {"notification_id": notif_id, "status": "sent", "audience": audience}
    except Exception:
        pass

    threading.Thread(target=_worker, daemon=True, name=f"mobile-notif-{notif_id}").start()
    return {"notification_id": notif_id, "status": "queued", "audience": audience}
