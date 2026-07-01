from __future__ import annotations

import json
from datetime import datetime

from extensions import db


class WorkspaceAuditEvent(db.Model):
    __tablename__ = "ai_workspace_audit_events"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_workspace_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = db.Column(db.String(80), nullable=False, index=True)
    message = db.Column(db.Text, nullable=True)
    payload_json = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def get_payload(self):
        if not self.payload_json:
            return {}
        try:
            return json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError):
            return {}

    def set_payload(self, payload):
        self.payload_json = json.dumps(payload or {}, ensure_ascii=False)

    def to_sse_dict(self):
        return {
            "id": self.id,
            "type": self.event_type,
            "event_id": self.id,
            "payload": self.get_payload(),
            "message": self.message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
