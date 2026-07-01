from __future__ import annotations

import json
import uuid
from datetime import datetime

from extensions import db


class CourierStatementAnalysis(db.Model):
    __tablename__ = "ai_workspace_courier_statement_analyses"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_workspace_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_workspace_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    extraction_result_id = db.Column(db.String(36), nullable=True, index=True)
    tenant_slug = db.Column(db.String(100), index=True, nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="pending")
    courier_company_id = db.Column(db.Integer, nullable=True)
    courier_company_name_detected = db.Column(db.String(200), nullable=True)
    document_kind = db.Column(db.String(50), default="courier_settlement")
    confidence = db.Column(db.Float, default=0.0)
    total_rows = db.Column(db.Integer, default=0)
    matched_rows = db.Column(db.Integer, default=0)
    review_rows = db.Column(db.Integer, default=0)
    unmatched_rows = db.Column(db.Integer, default=0)
    issue_rows = db.Column(db.Integer, default=0)
    duplicate_rows = db.Column(db.Integer, default=0)
    total_collected_amount = db.Column(db.Integer, default=0)
    total_delivery_fees = db.Column(db.Integer, default=0)
    expected_net_amount = db.Column(db.Integer, default=0)
    unmatched_amount = db.Column(db.Integer, default=0)
    total_variance_amount = db.Column(db.Integer, default=0)
    summary_json = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    rows_rel = db.relationship(
        "CourierStatementAnalysisRow",
        backref="analysis",
        lazy=True,
        cascade="all, delete-orphan",
    )
    issues_rel = db.relationship(
        "CourierStatementAnalysisIssue",
        backref="analysis",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def _loads(self, raw):
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}

    def get_summary(self):
        return self._loads(self.summary_json)

    def set_summary(self, data):
        self.summary_json = json.dumps(data or {}, ensure_ascii=False)

    def get_metadata(self):
        return self._loads(self.metadata_json)

    def set_metadata(self, data):
        self.metadata_json = json.dumps(data or {}, ensure_ascii=False)

    def to_dict(self, include_financial=True):
        summary = self.get_summary()
        data = {
            "id": self.id,
            "session_id": self.session_id,
            "document_id": self.document_id,
            "extraction_result_id": self.extraction_result_id,
            "tenant_slug": self.tenant_slug,
            "status": self.status,
            "courier_company_id": self.courier_company_id,
            "courier_company_name_detected": self.courier_company_name_detected,
            "document_kind": self.document_kind,
            "confidence": self.confidence,
            "total_rows": self.total_rows,
            "matched_rows": self.matched_rows,
            "review_rows": self.review_rows,
            "unmatched_rows": self.unmatched_rows,
            "issue_rows": self.issue_rows,
            "duplicate_rows": self.duplicate_rows,
            "total_collected_amount": self.total_collected_amount,
            "total_delivery_fees": self.total_delivery_fees,
            "expected_net_amount": self.expected_net_amount,
            "unmatched_amount": self.unmatched_amount,
            "total_variance_amount": self.total_variance_amount,
            "summary": summary,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_financial and summary.get("financial_preview"):
            data["financial_preview"] = summary["financial_preview"]
        return data
