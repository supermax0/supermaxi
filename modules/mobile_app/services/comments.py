"""Comment CRUD, likes, reports, and light moderation."""
from __future__ import annotations

import re
from datetime import datetime

from extensions import db
from modules.mobile_app.models import (
    MobileBlockedUser,
    MobileComment,
    MobileCommentLike,
    MobileCommentReport,
    MobileModerationRule,
    MobileUser,
    MobileVideo,
)


class CommentError(Exception):
    def __init__(self, message: str, code: str = "comment_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _assert_not_blocked(user_id: int) -> None:
    blocked = MobileBlockedUser.query.filter_by(user_id=user_id).first()
    if blocked:
        raise CommentError("تم حظر حسابك من التعليق", "user_blocked")


def _moderate_body(body: str) -> tuple[str, str]:
    """Return (status, cleaned_body). status: visible|pending_review|rejected."""
    text = (body or "").strip()
    if not text:
        raise CommentError("نص التعليق مطلوب", "empty_body")
    if len(text) > 2000:
        raise CommentError("التعليق طويل جداً", "body_too_long")

    # Basic HTML/script strip
    cleaned = re.sub(r"<[^>]+>", "", text)

    rules = MobileModerationRule.query.filter_by(is_active=True).all()
    lowered = cleaned.lower()
    for rule in rules:
        pattern = (rule.pattern or "").strip().lower()
        if not pattern:
            continue
        if pattern in lowered:
            action = (rule.action or "reject").lower()
            if action == "pending_review":
                return "pending_review", cleaned
            if action == "hide":
                return "hidden", cleaned
            raise CommentError("التعليق يحتوي على محتوى غير مسموح", "moderation_rejected")
    return "visible", cleaned


def _author_name(user_id: int | None, *, company: bool = False) -> str:
    if company:
        return "Finora"
    if not user_id:
        return "مستخدم"
    user = db.session.get(MobileUser, user_id)
    if user and user.name:
        return user.name
    if user and user.phone:
        return user.phone
    return "مستخدم"


def _get_ready_video(video_id: int) -> MobileVideo:
    video = db.session.get(MobileVideo, video_id)
    if video is None or video.deleted_at is not None:
        raise CommentError("الفيديو غير موجود", "not_found")
    if not video.allow_comments:
        raise CommentError("التعليقات مغلقة على هذا الفيديو", "comments_closed")
    return video


def list_comments_for_video(
    *,
    video_id: int,
    viewer_user_id: int | None,
    limit: int = 30,
    offset: int = 0,
) -> list[dict]:
    limit = min(50, max(1, int(limit or 30)))
    offset = max(0, int(offset or 0))
    roots = (
        MobileComment.query.filter(
            MobileComment.video_id == video_id,
            MobileComment.parent_id.is_(None),
            MobileComment.deleted_at.is_(None),
            MobileComment.status.in_(["visible", "reported"]),
        )
        .order_by(MobileComment.is_pinned.desc(), MobileComment.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    if not roots:
        return []

    root_ids = [c.id for c in roots]
    replies = (
        MobileComment.query.filter(
            MobileComment.parent_id.in_(root_ids),
            MobileComment.deleted_at.is_(None),
            MobileComment.status.in_(["visible", "reported"]),
        )
        .order_by(MobileComment.id.asc())
        .all()
    )
    all_ids = root_ids + [r.id for r in replies]
    liked: set[int] = set()
    if viewer_user_id and all_ids:
        liked = {
            row.comment_id
            for row in MobileCommentLike.query.filter(
                MobileCommentLike.user_id == viewer_user_id,
                MobileCommentLike.comment_id.in_(all_ids),
            ).all()
        }

    replies_by_parent: dict[int, list[MobileComment]] = {}
    for reply in replies:
        replies_by_parent.setdefault(int(reply.parent_id), []).append(reply)

    result = []
    for comment in roots:
        nested = [
            r.to_public_dict(
                author_name=_author_name(r.user_id, company=r.is_company_reply),
                liked_by_me=r.id in liked,
            )
            for r in replies_by_parent.get(comment.id, [])
        ]
        result.append(
            comment.to_public_dict(
                author_name=_author_name(comment.user_id, company=comment.is_company_reply),
                liked_by_me=comment.id in liked,
                replies=nested,
            )
        )
    return result


def create_comment(
    *,
    video_id: int,
    user_id: int,
    body: str,
    parent_id: int | None = None,
) -> MobileComment:
    _assert_not_blocked(user_id)
    video = _get_ready_video(video_id)
    status, cleaned = _moderate_body(body)

    parent = None
    if parent_id is not None:
        parent = db.session.get(MobileComment, parent_id)
        if parent is None or parent.deleted_at is not None or parent.video_id != video.id:
            raise CommentError("التعليق الأصلي غير موجود", "parent_not_found")
        if parent.parent_id is not None:
            # Force 2-level UI: reply-to-reply attaches to root parent
            parent = db.session.get(MobileComment, parent.parent_id) or parent

    comment = MobileComment(
        video_id=video.id,
        user_id=user_id,
        parent_id=parent.id if parent else None,
        body=cleaned,
        status=status,
    )
    db.session.add(comment)
    db.session.flush()
    if parent is not None:
        parent.replies_count = int(parent.replies_count or 0) + 1
    video.comments_count = int(video.comments_count or 0) + 1
    db.session.commit()
    return comment


def soft_delete_comment(*, comment_id: int, user_id: int) -> MobileComment:
    comment = db.session.get(MobileComment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise CommentError("التعليق غير موجود", "not_found")
    if comment.user_id != user_id:
        raise CommentError("لا يمكن حذف تعليق شخص آخر", "forbidden")
    comment.status = "deleted"
    comment.deleted_at = datetime.utcnow()
    video = db.session.get(MobileVideo, comment.video_id)
    if video and int(video.comments_count or 0) > 0:
        video.comments_count = int(video.comments_count or 0) - 1
    if comment.parent_id:
        parent = db.session.get(MobileComment, comment.parent_id)
        if parent and int(parent.replies_count or 0) > 0:
            parent.replies_count = int(parent.replies_count or 0) - 1
    db.session.commit()
    return comment


def toggle_comment_like(*, comment_id: int, user_id: int) -> tuple[bool, int]:
    _assert_not_blocked(user_id)
    comment = db.session.get(MobileComment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise CommentError("التعليق غير موجود", "not_found")
    existing = MobileCommentLike.query.filter_by(
        comment_id=comment.id, user_id=user_id
    ).first()
    if existing:
        db.session.delete(existing)
        comment.likes_count = max(0, int(comment.likes_count or 0) - 1)
        liked = False
    else:
        db.session.add(MobileCommentLike(comment_id=comment.id, user_id=user_id))
        comment.likes_count = int(comment.likes_count or 0) + 1
        liked = True
    db.session.commit()
    return liked, int(comment.likes_count or 0)


def report_comment(
    *,
    comment_id: int,
    reporter_user_id: int,
    reason: str | None = None,
    details: str | None = None,
) -> MobileCommentReport:
    comment = db.session.get(MobileComment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise CommentError("التعليق غير موجود", "not_found")
    report = MobileCommentReport(
        comment_id=comment.id,
        reporter_user_id=reporter_user_id,
        reason=(reason or "other")[:200],
        details=(details or "")[:2000] or None,
        status="open",
    )
    db.session.add(report)
    comment.reports_count = int(comment.reports_count or 0) + 1
    if comment.status == "visible":
        comment.status = "reported"
    db.session.commit()
    return report


# ── Admin moderation ──────────────────────────────────────────────────────

def admin_hide_comment(comment_id: int) -> MobileComment:
    comment = db.session.get(MobileComment, comment_id)
    if comment is None:
        raise CommentError("التعليق غير موجود", "not_found")
    comment.status = "hidden"
    db.session.commit()
    return comment


def admin_pin_comment(comment_id: int, pinned: bool = True) -> MobileComment:
    comment = db.session.get(MobileComment, comment_id)
    if comment is None:
        raise CommentError("التعليق غير موجود", "not_found")
    if comment.parent_id is not None:
        raise CommentError("يمكن تثبيت التعليقات الرئيسية فقط", "invalid_pin")
    comment.is_pinned = bool(pinned)
    db.session.commit()
    return comment


def admin_company_reply(
    *,
    video_id: int,
    parent_id: int | None,
    body: str,
    employee_id: int | None,
) -> MobileComment:
    video = _get_ready_video(video_id)
    status, cleaned = _moderate_body(body)
    if status == "rejected":
        raise CommentError("نص غير مقبول", "moderation_rejected")
    parent = None
    if parent_id is not None:
        parent = db.session.get(MobileComment, parent_id)
        if parent is None or parent.video_id != video.id:
            raise CommentError("التعليق الأصلي غير موجود", "parent_not_found")
    comment = MobileComment(
        video_id=video.id,
        user_id=None,
        parent_id=parent.id if parent else None,
        body=cleaned,
        status="visible",
        is_company_reply=True,
        staff_employee_id=employee_id,
    )
    db.session.add(comment)
    db.session.flush()
    if parent is not None:
        parent.replies_count = int(parent.replies_count or 0) + 1
    video.comments_count = int(video.comments_count or 0) + 1
    db.session.commit()
    return comment


def admin_block_user(*, user_id: int, employee_id: int | None, reason: str | None) -> MobileBlockedUser:
    existing = MobileBlockedUser.query.filter_by(user_id=user_id).first()
    if existing:
        existing.reason = reason
        db.session.commit()
        return existing
    row = MobileBlockedUser(
        user_id=user_id,
        reason=reason,
        blocked_by_employee_id=employee_id,
    )
    db.session.add(row)
    db.session.commit()
    return row


def list_admin_comments(*, status: str | None = None, limit: int = 50) -> list[MobileComment]:
    query = MobileComment.query.filter(MobileComment.deleted_at.is_(None))
    if status:
        query = query.filter(MobileComment.status == status)
    return query.order_by(MobileComment.id.desc()).limit(min(100, max(1, limit))).all()
