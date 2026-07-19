"""Hybrid feed ranking + engagement actions."""
from __future__ import annotations

import base64
import json
from datetime import datetime

from extensions import db
from sqlalchemy import and_, or_
from modules.mobile_app.models import (
    MobileFeedEvent,
    MobileVideo,
    MobileVideoLike,
    MobileVideoSave,
    MobileVideoShare,
    MobileVideoView,
)


def _encode_cursor(
    video_id: int,
    priority: int,
    published_at: datetime | None,
    *,
    is_featured: bool,
) -> str:
    payload = {
        "id": video_id,
        "priority": priority,
        "is_featured": bool(is_featured),
        "published_at": published_at.isoformat() if published_at else None,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def get_published_video(video_id: int) -> MobileVideo | None:
    video = db.session.get(MobileVideo, video_id)
    if video is None or video.deleted_at is not None:
        return None
    if video.status not in {"published", "ready"}:
        # ready videos can appear if auto-published; published is preferred
        if video.status != "published" and video.processing_status != "ready":
            return None
        if video.status not in {"published", "ready"}:
            return None
    if video.processing_status != "ready" and video.status != "published":
        return None
    if video.processing_status != "ready":
        return None
    return video if video.status in {"published", "ready"} else None


def list_feed(
    *,
    user_id: int | None,
    cursor: str | None,
    limit: int = 6,
) -> tuple[list[dict], str | None]:
    limit = min(20, max(1, int(limit or 6)))
    query = MobileVideo.query.filter(
        MobileVideo.deleted_at.is_(None),
        MobileVideo.processing_status == "ready",
        MobileVideo.status.in_(["published", "ready"]),
        MobileVideo.visibility == "public",
    ).order_by(
        MobileVideo.is_featured.desc(),
        MobileVideo.priority.desc(),
        MobileVideo.published_at.desc(),
        MobileVideo.id.desc(),
    )

    decoded = _decode_cursor(cursor)
    if decoded and decoded.get("id"):
        # Match the full sort tuple to avoid skipped/duplicated rows when a
        # featured or higher-priority video has a lower numeric id.
        cursor_id = int(decoded["id"])
        cursor_priority = int(decoded.get("priority") or 0)
        cursor_featured = bool(decoded.get("is_featured"))
        published_raw = decoded.get("published_at")
        try:
            cursor_published = (
                datetime.fromisoformat(str(published_raw))
                if published_raw
                else None
            )
        except ValueError:
            cursor_published = None

        same_feature = MobileVideo.is_featured.is_(cursor_featured)
        lower_feature = (
            MobileVideo.is_featured.is_(False) if cursor_featured else None
        )
        lower_priority = and_(
            same_feature,
            MobileVideo.priority < cursor_priority,
        )
        same_priority = and_(
            same_feature,
            MobileVideo.priority == cursor_priority,
        )
        if cursor_published is None:
            lower_timestamp = and_(
                same_priority,
                MobileVideo.published_at.is_(None),
                MobileVideo.id < cursor_id,
            )
        else:
            lower_timestamp = and_(
                same_priority,
                or_(
                    MobileVideo.published_at < cursor_published,
                    MobileVideo.published_at.is_(None),
                    and_(
                        MobileVideo.published_at == cursor_published,
                        MobileVideo.id < cursor_id,
                    ),
                ),
            )
        conditions = [lower_priority, lower_timestamp]
        if lower_feature is not None:
            conditions.insert(0, lower_feature)
        query = query.filter(or_(*conditions))

    rows = query.limit(limit + 1).all()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = _encode_cursor(
            last.id,
            int(last.priority or 0),
            last.published_at,
            is_featured=bool(last.is_featured),
        )

    liked_ids: set[int] = set()
    saved_ids: set[int] = set()
    if user_id and page:
        ids = [v.id for v in page]
        liked_ids = {
            r.video_id
            for r in MobileVideoLike.query.filter(
                MobileVideoLike.user_id == user_id,
                MobileVideoLike.video_id.in_(ids),
            ).all()
        }
        saved_ids = {
            r.video_id
            for r in MobileVideoSave.query.filter(
                MobileVideoSave.user_id == user_id,
                MobileVideoSave.video_id.in_(ids),
            ).all()
        }

    items = [
        v.to_feed_dict(liked=v.id in liked_ids, saved=v.id in saved_ids)
        for v in page
    ]
    return items, next_cursor


def record_view(
    *,
    video: MobileVideo,
    user_id: int | None,
    device_id: str | None,
    watch_ms: int = 0,
    completed: bool = False,
) -> None:
    db.session.add(
        MobileVideoView(
            video_id=video.id,
            user_id=user_id,
            device_id=(device_id or "")[:128] or None,
            watch_ms=max(0, int(watch_ms or 0)),
            completed=bool(completed),
        )
    )
    video.views_count = int(video.views_count or 0) + 1
    db.session.add(
        MobileFeedEvent(
            user_id=user_id,
            video_id=video.id,
            event_type="view",
        )
    )
    db.session.commit()


def toggle_like(*, video: MobileVideo, user_id: int) -> tuple[bool, int]:
    existing = MobileVideoLike.query.filter_by(video_id=video.id, user_id=user_id).first()
    if existing:
        db.session.delete(existing)
        video.likes_count = max(0, int(video.likes_count or 0) - 1)
        liked = False
    else:
        db.session.add(MobileVideoLike(video_id=video.id, user_id=user_id))
        video.likes_count = int(video.likes_count or 0) + 1
        liked = True
        db.session.add(
            MobileFeedEvent(user_id=user_id, video_id=video.id, event_type="like")
        )
    db.session.commit()
    return liked, int(video.likes_count or 0)


def toggle_save(*, video: MobileVideo, user_id: int) -> tuple[bool, int]:
    if not video.allow_saving:
        raise ValueError("الحفظ غير مسموح لهذا الفيديو")
    existing = MobileVideoSave.query.filter_by(video_id=video.id, user_id=user_id).first()
    if existing:
        db.session.delete(existing)
        video.saves_count = max(0, int(video.saves_count or 0) - 1)
        saved = False
    else:
        db.session.add(MobileVideoSave(video_id=video.id, user_id=user_id))
        video.saves_count = int(video.saves_count or 0) + 1
        saved = True
        db.session.add(
            MobileFeedEvent(user_id=user_id, video_id=video.id, event_type="save")
        )
    db.session.commit()
    return saved, int(video.saves_count or 0)


def record_share(*, video: MobileVideo, user_id: int | None, channel: str = "app") -> int:
    if not video.allow_sharing:
        raise ValueError("المشاركة غير مسموحة لهذا الفيديو")
    db.session.add(
        MobileVideoShare(
            video_id=video.id,
            user_id=user_id,
            channel=(channel or "app")[:40],
        )
    )
    video.shares_count = int(video.shares_count or 0) + 1
    db.session.add(
        MobileFeedEvent(user_id=user_id, video_id=video.id, event_type="share")
    )
    db.session.commit()
    return int(video.shares_count or 0)
