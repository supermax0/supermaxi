from __future__ import annotations

import json
import uuid
from datetime import datetime

from extensions import db


def _default_windows():
    return [
        {
            "id": "win_doc_1",
            "type": "document_viewer",
            "title": "معاينة المستند",
            "status": "idle",
            "position": {"x": 520, "y": 100, "width": 420, "height": 520},
            "placement": "right",
            "z_index": 10,
            "opened_by_step_id": "session_created",
            "reason": "عرض المستند المرفوع",
            "props": {"scan_active": False, "scan_progress": 0},
            "interactive": False,
        },
        {
            "id": "win_report_1",
            "type": "live_report",
            "title": "تقرير التحليل",
            "status": "ready",
            "position": {"x": 40, "y": 100, "width": 380, "height": 480},
            "placement": "left",
            "z_index": 11,
            "opened_by_step_id": "session_created",
            "reason": "بث نتائج التحليل",
            "props": {"lines": []},
            "interactive": False,
        },
    ]


def _default_avatar():
    return {
        "mode": "idle",
        "position": {"x": 0.5, "y": 0.55},
        "speech": "أهلاً، جاهز لتحليل المستندات.",
        "progress": 0,
    }


class WorkspaceSession(db.Model):
    __tablename__ = "ai_workspace_sessions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_slug = db.Column(db.String(100), index=True, nullable=True)
    user_id = db.Column(db.Integer, index=True, nullable=True)
    workflow_type = db.Column(db.String(50), nullable=False, default="mock_workspace")
    status = db.Column(db.String(30), nullable=False, default="created")
    current_step_id = db.Column(db.String(80), nullable=True, default="session_created")
    windows_json = db.Column(db.Text, nullable=True)
    avatar_state_json = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    audit_events = db.relationship(
        "WorkspaceAuditEvent",
        backref="session",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def _loads(self, raw, default):
        if not raw:
            return default() if callable(default) else default
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return default() if callable(default) else default

    def get_windows(self):
        return self._loads(self.windows_json, _default_windows)

    def set_windows(self, windows):
        self.windows_json = json.dumps(windows, ensure_ascii=False)

    def get_avatar_state(self):
        return self._loads(self.avatar_state_json, _default_avatar)

    def set_avatar_state(self, state):
        self.avatar_state_json = json.dumps(state, ensure_ascii=False)

    def get_metadata(self):
        return self._loads(self.metadata_json, {})

    def set_metadata(self, data):
        self.metadata_json = json.dumps(data or {}, ensure_ascii=False)

    def to_dict(self):
        meta = self.get_metadata()
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "user_id": self.user_id,
            "workflow_type": self.workflow_type,
            "status": self.status,
            "current_step_id": self.current_step_id,
            "windows": self.get_windows(),
            "avatar_state": self.get_avatar_state(),
            "metadata": meta,
            "workflow_state": {
                "completed_steps": meta.get("completed_steps") or [],
                "pending_actions": meta.get("pending_actions") or [],
                "last_event_id": meta.get("last_event_id"),
            },
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
