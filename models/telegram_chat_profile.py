from __future__ import annotations

from datetime import datetime

from extensions import db


class TelegramChatProfile(db.Model):
    """Structured booking memory per workflow/chat."""

    __tablename__ = "telegram_chat_profiles"
    __table_args__ = (
        db.UniqueConstraint("workflow_id", "chat_id", name="uq_tg_chat_profile_workflow_chat"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), index=True, nullable=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey("ai_agent_workflows.id"), nullable=False, index=True)
    chat_id = db.Column(db.String(64), nullable=False, index=True)

    customer_name = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    booking_items_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        index=True,
    )

