# models/telegram_inbox_message.py — رسائل تيليجرام للعرض في صندوق المحادثات والرد اليدوي
from __future__ import annotations

from datetime import datetime

from extensions import db


class TelegramInboxMessage(db.Model):
    """سجل رسالة واحدة في محادثة تيليجرام مرتبطة بوورك فلو."""

    __tablename__ = "telegram_inbox_messages"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), index=True, nullable=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey("ai_agent_workflows.id"), nullable=False, index=True)
    chat_id = db.Column(db.String(64), nullable=False, index=True)
    # user: رسالة من الزبون | bot: رد من البوت/الوورك فلو | operator: رد يدوي من لوحة التحكم
    role = db.Column(db.String(20), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "workflow_id": self.workflow_id,
            "chat_id": self.chat_id,
            "role": self.role,
            "body": self.body,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
