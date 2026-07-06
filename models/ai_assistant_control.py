"""Persistent AI assistant chat, audit, and action-control models."""
from __future__ import annotations

import json
from datetime import datetime

from extensions import db


def _loads(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _dumps(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


class AIChatSession(db.Model):
    __tablename__ = "ai_chat_session"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    title = db.Column(db.String(180), nullable=True)
    context_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = db.relationship("Employee", lazy=True)
    messages = db.relationship("AIChatMessage", back_populates="chat_session", cascade="all, delete-orphan", lazy=True)

    def get_context(self) -> dict:
        return _loads(self.context_json, {})

    def set_context(self, data: dict | None) -> None:
        self.context_json = _dumps(data)


class AIChatMessage(db.Model):
    __tablename__ = "ai_chat_message"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("ai_chat_session.id"), nullable=False, index=True)
    role = db.Column(db.String(30), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    chat_session = db.relationship("AIChatSession", back_populates="messages")

    def get_metadata(self) -> dict:
        return _loads(self.metadata_json, {})

    def set_metadata(self, data: dict | None) -> None:
        self.metadata_json = _dumps(data)


class AIUploadedFile(db.Model):
    __tablename__ = "ai_uploaded_file"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("ai_chat_session.id"), nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(600), nullable=False)
    file_type = db.Column(db.String(50), default="inventory_audit", nullable=False)
    size_bytes = db.Column(db.Integer, default=0, nullable=False)
    preview_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="uploaded", nullable=False, index=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    chat_session = db.relationship("AIChatSession", lazy=True)
    employee = db.relationship("Employee", lazy=True)

    def get_preview(self) -> dict:
        return _loads(self.preview_json, {})

    def set_preview(self, data: dict | None) -> None:
        self.preview_json = _dumps(data)


class AIActionPlan(db.Model):
    __tablename__ = "ai_action_plan"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("ai_chat_session.id"), nullable=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    executed_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    title = db.Column(db.String(220), nullable=False)
    plan_type = db.Column(db.String(80), nullable=False, index=True)
    status = db.Column(db.String(30), default="draft", nullable=False, index=True)
    summary = db.Column(db.Text, nullable=True)
    risk_level = db.Column(db.String(20), default="medium", nullable=False)
    impact_json = db.Column(db.Text, nullable=True)
    approval_note = db.Column(db.Text, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    execution_result_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    approved_at = db.Column(db.DateTime, nullable=True)
    executed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chat_session = db.relationship("AIChatSession", lazy=True)
    created_by = db.relationship("Employee", foreign_keys=[created_by_id], lazy=True)
    approved_by = db.relationship("Employee", foreign_keys=[approved_by_id], lazy=True)
    executed_by = db.relationship("Employee", foreign_keys=[executed_by_id], lazy=True)
    items = db.relationship("AIActionItem", back_populates="plan", cascade="all, delete-orphan", lazy=True)

    def get_impact(self) -> dict:
        return _loads(self.impact_json, {})

    def set_impact(self, data: dict | None) -> None:
        self.impact_json = _dumps(data)

    def get_execution_result(self) -> dict:
        return _loads(self.execution_result_json, {})

    def set_execution_result(self, data: dict | None) -> None:
        self.execution_result_json = _dumps(data)

    def to_dict(self, include_items: bool = True) -> dict:
        data = {
            "id": self.id,
            "title": self.title,
            "plan_type": self.plan_type,
            "status": self.status,
            "summary": self.summary or "",
            "risk_level": self.risk_level,
            "impact": self.get_impact(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "rejection_reason": self.rejection_reason or "",
            "execution_result": self.get_execution_result(),
        }
        if include_items:
            data["items"] = [item.to_dict() for item in self.items]
        return data


class AIActionItem(db.Model):
    __tablename__ = "ai_action_item"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("ai_action_plan.id"), nullable=False, index=True)
    item_type = db.Column(db.String(80), nullable=False, index=True)
    target_type = db.Column(db.String(80), nullable=True)
    target_id = db.Column(db.Integer, nullable=True, index=True)
    title = db.Column(db.String(220), nullable=False)
    description = db.Column(db.Text, nullable=True)
    before_json = db.Column(db.Text, nullable=True)
    after_json = db.Column(db.Text, nullable=True)
    payload_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="pending", nullable=False, index=True)
    result_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    executed_at = db.Column(db.DateTime, nullable=True)

    plan = db.relationship("AIActionPlan", back_populates="items")

    def get_before(self) -> dict:
        return _loads(self.before_json, {})

    def set_before(self, data: dict | None) -> None:
        self.before_json = _dumps(data)

    def get_after(self) -> dict:
        return _loads(self.after_json, {})

    def set_after(self, data: dict | None) -> None:
        self.after_json = _dumps(data)

    def get_payload(self) -> dict:
        return _loads(self.payload_json, {})

    def set_payload(self, data: dict | None) -> None:
        self.payload_json = _dumps(data)

    def get_result(self) -> dict:
        return _loads(self.result_json, {})

    def set_result(self, data: dict | None) -> None:
        self.result_json = _dumps(data)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "item_type": self.item_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "title": self.title,
            "description": self.description or "",
            "before": self.get_before(),
            "after": self.get_after(),
            "payload": self.get_payload(),
            "status": self.status,
            "result": self.get_result(),
        }


class AIScheduledAudit(db.Model):
    __tablename__ = "ai_scheduled_audit"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    audit_type = db.Column(db.String(60), default="comprehensive", nullable=False, index=True)
    interval_minutes = db.Column(db.Integer, default=1440, nullable=False)
    severity_threshold = db.Column(db.String(20), default="warning", nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    settings_json = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    last_run_at = db.Column(db.DateTime, nullable=True)
    next_run_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.relationship("Employee", lazy=True)

    def get_settings(self) -> dict:
        return _loads(self.settings_json, {})

    def set_settings(self, data: dict | None) -> None:
        self.settings_json = _dumps(data)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "audit_type": self.audit_type,
            "interval_minutes": self.interval_minutes,
            "severity_threshold": self.severity_threshold,
            "is_active": bool(self.is_active),
            "settings": self.get_settings(),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AIAuditRun(db.Model):
    __tablename__ = "ai_audit_run"

    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey("ai_scheduled_audit.id"), nullable=True, index=True)
    run_type = db.Column(db.String(60), default="manual", nullable=False, index=True)
    status = db.Column(db.String(30), default="running", nullable=False, index=True)
    summary = db.Column(db.Text, nullable=True)
    result_json = db.Column(db.Text, nullable=True)
    action_plan_id = db.Column(db.Integer, db.ForeignKey("ai_action_plan.id"), nullable=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)

    schedule = db.relationship("AIScheduledAudit", lazy=True)
    action_plan = db.relationship("AIActionPlan", lazy=True)

    def get_result(self) -> dict:
        return _loads(self.result_json, {})

    def set_result(self, data: dict | None) -> None:
        self.result_json = _dumps(data)


class AIToolCallLog(db.Model):
    __tablename__ = "ai_tool_call_log"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("ai_chat_session.id"), nullable=True, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("ai_action_plan.id"), nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    tool_name = db.Column(db.String(120), nullable=False, index=True)
    mode = db.Column(db.String(30), default="read", nullable=False)
    input_json = db.Column(db.Text, nullable=True)
    output_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="success", nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_input(self, data: dict | None) -> None:
        self.input_json = _dumps(data)

    def set_output(self, data: dict | None) -> None:
        self.output_json = _dumps(data)
