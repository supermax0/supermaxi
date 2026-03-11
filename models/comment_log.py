# models/comment_log.py — سجل تعليقات الرد التلقائي (Comment Automation)
from __future__ import annotations

from datetime import datetime

from extensions import db


class CommentLog(db.Model):
    """سجل أحداث التعليقات والردود الآلية (للإحصائيات وعدم الرد مرتين)."""

    __tablename__ = "comment_logs"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), index=True, nullable=True)

    platform = db.Column(db.String(30), nullable=False, index=True)  # facebook | instagram | tiktok
    comment_id = db.Column(db.String(128), nullable=False, index=True)
    username = db.Column(db.String(150), nullable=True)
    comment_text = db.Column(db.Text, nullable=False)
    ai_reply = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # للربط مع تنفيذ الوكيل إن وُجد
    execution_id = db.Column(db.Integer, db.ForeignKey("ai_agent_executions.id"), nullable=True, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "comment_id": self.comment_id,
            "username": self.username,
            "comment_text": self.comment_text,
            "ai_reply": self.ai_reply,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


def is_comment_already_replied(tenant_slug: str | None, platform: str, comment_id: str) -> bool:
    """تحقق إن كان تم الرد على هذا التعليق مسبقاً (حماية من التكرار)."""
    q = CommentLog.query.filter_by(platform=platform, comment_id=str(comment_id))
    if tenant_slug:
        q = q.filter_by(tenant_slug=tenant_slug)
    return q.first() is not None
