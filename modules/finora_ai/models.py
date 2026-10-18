"""Persistence owned by the provider-neutral Finora AI layer."""
from __future__ import annotations

import json
from datetime import datetime

from extensions import db


def _dump(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _load(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


class FinoraAIConversation(db.Model):
    __tablename__ = "finora_ai_conversation"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False, default="محادثة Finora AI")
    context_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship(
        "FinoraAIMessage", back_populates="conversation", cascade="all, delete-orphan", lazy=True
    )

    def get_context(self) -> dict:
        return _load(self.context_json, {})

    def set_context(self, value: dict | None) -> None:
        self.context_json = _dump(value or {})


class FinoraAIMessage(db.Model):
    __tablename__ = "finora_ai_message"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("finora_ai_conversation.id"), nullable=False, index=True
    )
    role = db.Column(db.String(30), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False, default="")
    provider = db.Column(db.String(40), nullable=True)
    model = db.Column(db.String(120), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    conversation = db.relationship("FinoraAIConversation", back_populates="messages")

    def set_metadata(self, value: dict | None) -> None:
        self.metadata_json = _dump(value or {})

    def get_metadata(self) -> dict:
        return _load(self.metadata_json, {})


class FinoraAIToolCall(db.Model):
    __tablename__ = "finora_ai_tool_call"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    conversation_id = db.Column(db.Integer, nullable=True, index=True)
    message_id = db.Column(db.Integer, nullable=True, index=True)
    provider = db.Column(db.String(40), nullable=True)
    model = db.Column(db.String(120), nullable=True)
    tool_name = db.Column(db.String(120), nullable=False, index=True)
    arguments_json = db.Column(db.Text, nullable=True)
    result_status = db.Column(db.String(30), nullable=False, default="started", index=True)
    error_code = db.Column(db.String(60), nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    requires_confirmation = db.Column(db.Boolean, nullable=False, default=False)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    def set_arguments(self, value: dict | None) -> None:
        self.arguments_json = _dump(value or {})


class FinoraAISettings(db.Model):
    __tablename__ = "finora_ai_settings"

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    provider = db.Column(db.String(40), nullable=False, default="builtin")
    model = db.Column(db.String(120), nullable=True)
    endpoint = db.Column(db.String(500), nullable=True)
    encrypted_api_key = db.Column(db.Text, nullable=True)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=60)
    context_size = db.Column(db.Integer, nullable=True)
    feature_flags_json = db.Column(db.Text, nullable=True)
    updated_by_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_flags(self) -> dict:
        defaults = {
            "finora_ai_enabled": True,
            "mcp_enabled": True,
            "ai_write_tools_enabled": False,
            "ai_accounting_tools_enabled": True,
            "ai_local_provider_enabled": True,
        }
        defaults.update(_load(self.feature_flags_json, {}))
        # Phase 1 is structurally read-only regardless of a stored flag.
        defaults["ai_write_tools_enabled"] = False
        return defaults

    def set_flags(self, value: dict | None) -> None:
        self.feature_flags_json = _dump(value or {})


class FinoraMCPConnection(db.Model):
    __tablename__ = "finora_mcp_connection"

    id = db.Column(db.String(32), primary_key=True)
    tenant_slug = db.Column(db.String(100), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    secret_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = db.Column(db.DateTime, nullable=True)


AI_TABLES = (
    FinoraAIConversation.__table__,
    FinoraAIMessage.__table__,
    FinoraAIToolCall.__table__,
    FinoraAISettings.__table__,
    FinoraMCPConnection.__table__,
)
