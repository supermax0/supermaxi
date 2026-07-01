from __future__ import annotations

import json
import uuid
from datetime import datetime

from extensions import db


class CourierStatementAnalysisIssue(db.Model):
    __tablename__ = "ai_workspace_courier_statement_analysis_issues"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_workspace_courier_statement_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_id = db.Column(db.String(36), nullable=True, index=True)
    issue_type = db.Column(db.String(60), nullable=False, index=True)
    severity = db.Column(db.String(20), nullable=False, default="warning")
    message = db.Column(db.String(500), nullable=False)
    details_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_details(self):
        if not self.details_json:
            return {}
        try:
            return json.loads(self.details_json)
        except (TypeError, json.JSONDecodeError):
            return {}

    def set_details(self, data):
        self.details_json = json.dumps(data or {}, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "analysis_id": self.analysis_id,
            "row_id": self.row_id,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "message": self.message,
            "details": self.get_details(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
