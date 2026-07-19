"""Comment / moderation models for mobile social commerce (Phase 3)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileComment(db.Model):
    __tablename__ = "mobile_comment"

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("mobile_comment.id"), index=True)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="visible", index=True)
    is_pinned = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_company_reply = db.Column(db.Boolean, nullable=False, default=False)
    staff_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), index=True)
    likes_count = db.Column(db.Integer, nullable=False, default=0)
    replies_count = db.Column(db.Integer, nullable=False, default=0)
    reports_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at = db.Column(db.DateTime)

    parent = db.relationship(
        "MobileComment",
        remote_side=[id],
        backref=db.backref("replies", lazy=True),
    )

    def to_public_dict(
        self,
        *,
        author_name: str = "",
        liked_by_me: bool = False,
        replies: list | None = None,
    ) -> dict:
        return {
            "id": self.id,
            "video_id": self.video_id,
            "user_id": self.user_id,
            "parent_id": self.parent_id,
            "body": self.body or "",
            "status": self.status,
            "is_pinned": bool(self.is_pinned),
            "is_company_reply": bool(self.is_company_reply),
            "likes_count": int(self.likes_count or 0),
            "replies_count": int(self.replies_count or 0),
            "liked_by_me": liked_by_me,
            "author_name": author_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "replies": replies or [],
        }

    def to_admin_dict(self) -> dict:
        data = self.to_public_dict()
        data["reports_count"] = int(self.reports_count or 0)
        data["staff_employee_id"] = self.staff_employee_id
        data["deleted_at"] = self.deleted_at.isoformat() if self.deleted_at else None
        return data


class MobileCommentLike(db.Model):
    __tablename__ = "mobile_comment_like"
    __table_args__ = (
        db.UniqueConstraint("comment_id", "user_id", name="uq_mobile_comment_like_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(
        db.Integer, db.ForeignKey("mobile_comment.id"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileCommentReport(db.Model):
    __tablename__ = "mobile_comment_report"

    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(
        db.Integer, db.ForeignKey("mobile_comment.id"), nullable=False, index=True
    )
    reporter_user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), index=True)
    reason = db.Column(db.String(200))
    details = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="open", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)


class MobileBlockedUser(db.Model):
    __tablename__ = "mobile_blocked_user"
    __table_args__ = (
        db.UniqueConstraint("user_id", name="uq_mobile_blocked_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    reason = db.Column(db.Text)
    blocked_by_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileModerationRule(db.Model):
    __tablename__ = "mobile_moderation_rule"

    id = db.Column(db.Integer, primary_key=True)
    rule_type = db.Column(db.String(40), nullable=False, default="blocked_word", index=True)
    pattern = db.Column(db.String(200), nullable=False)
    action = db.Column(db.String(40), nullable=False, default="reject")  # reject|pending_review|hide
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
