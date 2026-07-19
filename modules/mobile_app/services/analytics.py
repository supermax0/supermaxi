"""Batched analytics + conversion summary (Phase 8)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from extensions import db
from modules.mobile_app.models import MobileAnalyticsEvent

ALLOWED_EVENTS = frozenset(
    {
        "app_open",
        "video_view",
        "video_like",
        "video_save",
        "video_share",
        "product_view",
        "search",
        "add_to_cart",
        "remove_from_cart",
        "checkout_started",
        "order_placed",
        "coupon_applied",
        "points_applied",
        "ai_message",
        "favorite_add",
        "notification_open",
        "screen_view",
    }
)


class AnalyticsError(Exception):
    def __init__(self, message: str, code: str = "analytics_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def ingest_events(
    *,
    user_id: int | None,
    events: list[dict],
    device_id: str | None = None,
) -> dict:
    if not isinstance(events, list) or not events:
        raise AnalyticsError("events مطلوبة", "validation_error")
    if len(events) > 50:
        raise AnalyticsError("الحد الأقصى 50 حدثاً لكل دفعة", "batch_too_large")

    accepted = 0
    rejected = 0
    for raw in events:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        name = str(raw.get("event_name") or raw.get("name") or "").strip()
        if name not in ALLOWED_EVENTS:
            rejected += 1
            continue
        client_ts = None
        ts_raw = raw.get("client_ts") or raw.get("timestamp")
        if ts_raw:
            try:
                client_ts = datetime.fromisoformat(str(ts_raw).replace("Z", ""))
            except ValueError:
                client_ts = None
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        # Drop oversized property blobs
        props_json = json.dumps(props, ensure_ascii=False)[:2000]
        row = MobileAnalyticsEvent(
            user_id=user_id,
            device_id=(device_id or raw.get("device_id") or "")[:128] or None,
            event_name=name,
            session_id=str(raw.get("session_id") or "")[:64] or None,
            video_id=_safe_int(raw.get("video_id") or props.get("video_id")),
            product_id=_safe_int(raw.get("product_id") or props.get("product_id")),
            order_id=_safe_int(raw.get("order_id") or props.get("order_id")),
            campaign_id=_safe_int(raw.get("campaign_id") or props.get("campaign_id")),
            properties_json=props_json,
            client_ts=client_ts,
        )
        db.session.add(row)
        accepted += 1
    db.session.commit()
    return {"accepted": accepted, "rejected": rejected}


def _safe_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def conversion_summary(*, days: int = 7) -> dict:
    days = max(1, min(90, int(days or 7)))
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.session.query(
            MobileAnalyticsEvent.event_name,
            db.func.count(MobileAnalyticsEvent.id),
        )
        .filter(MobileAnalyticsEvent.created_at >= since)
        .group_by(MobileAnalyticsEvent.event_name)
        .all()
    )
    counts = {name: int(cnt) for name, cnt in rows}
    views = counts.get("product_view", 0) + counts.get("video_view", 0)
    carts = counts.get("add_to_cart", 0)
    checkouts = counts.get("checkout_started", 0)
    orders = counts.get("order_placed", 0)

    from modules.mobile_app.models import (
        MobileComment,
        MobileOrderAttribution,
        MobileVideo,
        MobileVideoLike,
        MobileVideoShare,
        MobileVideoView,
    )

    video_views = MobileVideoView.query.filter(MobileVideoView.created_at >= since).count()
    likes = MobileVideoLike.query.filter(MobileVideoLike.created_at >= since).count()
    shares = MobileVideoShare.query.filter(MobileVideoShare.created_at >= since).count()
    comments = MobileComment.query.filter(
        MobileComment.created_at >= since,
        MobileComment.deleted_at.is_(None),
    ).count()
    attributed_orders = MobileOrderAttribution.query.filter(
        MobileOrderAttribution.created_at >= since
    ).count()
    published_videos = MobileVideo.query.filter(
        MobileVideo.deleted_at.is_(None),
        MobileVideo.status.in_(["published", "ready"]),
    ).count()

    return {
        "days": days,
        "counts": counts,
        "funnel": {
            "views": views,
            "add_to_cart": carts,
            "checkout_started": checkouts,
            "order_placed": orders,
            "view_to_cart_rate": round(carts / views, 4) if views else 0.0,
            "cart_to_order_rate": round(orders / carts, 4) if carts else 0.0,
        },
        "engagement": {
            "published_videos": published_videos,
            "video_views": video_views,
            "likes": likes,
            "shares": shares,
            "comments": comments,
            "attributed_orders": attributed_orders,
        },
    }
