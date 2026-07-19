"""Investment planning proposal persistence."""
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


class InvestmentProposal(db.Model):
    __tablename__ = "investment_proposal"

    id = db.Column(db.Integer, primary_key=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    period_type = db.Column(db.String(40), default="last_30_days", nullable=False, index=True)
    date_from = db.Column(db.Date, nullable=True)
    date_to = db.Column(db.Date, nullable=True)
    risk_profile = db.Column(db.String(30), default="balanced", nullable=False)
    objective = db.Column(db.String(80), default="growth", nullable=False)
    external_research_enabled = db.Column(db.Boolean, default=False, nullable=False)
    selected_index = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(30), default="generated", nullable=False, index=True)
    title = db.Column(db.String(220), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    financial_snapshot_json = db.Column(db.Text, nullable=True)
    proposals_json = db.Column(db.Text, nullable=True)
    sources_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.relationship("Employee", lazy=True)

    def get_financial_snapshot(self) -> dict:
        return _loads(self.financial_snapshot_json, {})

    def set_financial_snapshot(self, data: dict | None) -> None:
        self.financial_snapshot_json = _dumps(data)

    def get_payload(self) -> dict:
        return _loads(self.proposals_json, {})

    def set_payload(self, data: dict | None) -> None:
        self.proposals_json = _dumps(data)

    def get_sources(self) -> list:
        return _loads(self.sources_json, [])

    def set_sources(self, data: list | None) -> None:
        self.sources_json = json.dumps(data or [], ensure_ascii=False)

    def selected_proposal(self) -> dict:
        payload = self.get_payload()
        proposals = payload.get("proposals") or []
        if not proposals:
            return {}
        index = max(0, min(int(self.selected_index or 0), len(proposals) - 1))
        return proposals[index]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary or "",
            "period_type": self.period_type,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "risk_profile": self.risk_profile,
            "objective": self.objective,
            "external_research_enabled": bool(self.external_research_enabled),
            "selected_index": int(self.selected_index or 0),
            "status": self.status,
            "payload": self.get_payload(),
            "financial_snapshot": self.get_financial_snapshot(),
            "sources": self.get_sources(),
            "error_message": self.error_message or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
