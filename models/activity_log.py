"""Central activity / audit log for tenant operations."""
from __future__ import annotations

import json
from datetime import datetime

from extensions import db


class ActivityLog(db.Model):
    __tablename__ = "activity_log"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    employee_name = db.Column(db.String(150), nullable=True)
    action = db.Column(db.String(30), nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=True, index=True)
    entity_id = db.Column(db.String(64), nullable=True, index=True)
    summary = db.Column(db.Text, nullable=False)
    payload_json = db.Column(db.Text, nullable=True)
    request_method = db.Column(db.String(10), nullable=True)
    request_path = db.Column(db.String(500), nullable=True)
    status_code = db.Column(db.Integer, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    employee = db.relationship("Employee", foreign_keys=[employee_id], lazy=True)

    def get_payload(self) -> dict:
        if not self.payload_json:
            return {}
        try:
            return json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError):
            return {}

    def set_payload(self, payload: dict | None) -> None:
        self.payload_json = json.dumps(payload or {}, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "action": self.action,
            "category": self.category,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "summary": self.summary,
            "payload": self.get_payload(),
            "request_method": self.request_method,
            "request_path": self.request_path,
            "status_code": self.status_code,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "branch_id": self.branch_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
