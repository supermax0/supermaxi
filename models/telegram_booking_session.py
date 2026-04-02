# models/telegram_booking_session.py — جلسة حجز FSM لتيليجرام (تخزين دائم)
from __future__ import annotations

from datetime import datetime

from extensions import db


class TelegramBookingSession(db.Model):
    """حالة محادثة حجز لكل (workflow + chat_id) داخل قاعدة المستأجر."""

    __tablename__ = "telegram_booking_sessions"
    __table_args__ = (
        db.UniqueConstraint("workflow_id", "user_id", name="uq_tg_booking_session_wf_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey("ai_agent_workflows.id"), nullable=False, index=True)
    tenant_slug = db.Column(db.String(100), index=True, nullable=True)

    step = db.Column(db.String(32), nullable=False, default="ASK_ADDRESS")
    address = db.Column(db.String(500), nullable=True)
    quantity = db.Column(db.Integer, nullable=True)
    date = db.Column(db.String(100), nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "workflow_id": self.workflow_id,
            "step": self.step,
            "address": self.address,
            "quantity": self.quantity,
            "date": self.date,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
