"""Mobile Finora AI conversation models (Phase 7)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileAIConversation(db.Model):
    __tablename__ = "mobile_ai_conversation"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False, default="محادثة جديدة")
    status = db.Column(db.String(20), nullable=False, default="active")  # active | archived
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    messages = db.relationship(
        "MobileAIMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="MobileAIMessage.id",
    )


class MobileAIMessage(db.Model):
    __tablename__ = "mobile_ai_message"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("mobile_ai_conversation.id"), nullable=False, index=True
    )
    role = db.Column(db.String(20), nullable=False)  # user | assistant | system | tool
    content = db.Column(db.Text, nullable=False, default="")
    meta_json = db.Column(db.Text)  # products, pending_actions, ui_actions
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    conversation = db.relationship("MobileAIConversation", back_populates="messages", lazy=True)


class MobileAIToolExecution(db.Model):
    __tablename__ = "mobile_ai_tool_execution"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("mobile_ai_conversation.id"), nullable=False, index=True
    )
    message_id = db.Column(db.Integer, db.ForeignKey("mobile_ai_message.id"), index=True)
    tool_name = db.Column(db.String(80), nullable=False, index=True)
    arguments_json = db.Column(db.Text)
    result_json = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="ok")
    # ok | error | pending_confirmation | confirmed | cancelled
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
