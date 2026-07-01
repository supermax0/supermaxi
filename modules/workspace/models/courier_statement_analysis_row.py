from __future__ import annotations

import json
import uuid
from datetime import datetime

from extensions import db


class CourierStatementAnalysisRow(db.Model):
    __tablename__ = "ai_workspace_courier_statement_analysis_rows"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_workspace_courier_statement_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_index = db.Column(db.Integer, default=0)
    source_table_index = db.Column(db.Integer, nullable=True)
    source_page = db.Column(db.Integer, nullable=True)
    raw_row_json = db.Column(db.Text, nullable=True)
    raw_order_number = db.Column(db.String(80), nullable=True)
    normalized_order_number = db.Column(db.String(80), nullable=True, index=True)
    customer_name = db.Column(db.String(200), nullable=True)
    customer_phone = db.Column(db.String(40), nullable=True)
    collected_amount = db.Column(db.Integer, nullable=True)
    delivery_fee = db.Column(db.Integer, nullable=True)
    net_amount = db.Column(db.Integer, nullable=True)
    statement_date = db.Column(db.String(30), nullable=True)
    matched_invoice_id = db.Column(db.Integer, nullable=True, index=True)
    match_score = db.Column(db.Float, default=0.0)
    match_status = db.Column(db.String(30), default="unmatched")
    match_reasons_json = db.Column(db.Text, nullable=True)
    warnings_json = db.Column(db.Text, nullable=True)
    issues_json = db.Column(db.Text, nullable=True)
    invoice_snapshot_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def _loads_list(self, raw):
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    def get_match_reasons(self):
        return self._loads_list(self.match_reasons_json)

    def set_match_reasons(self, reasons):
        self.match_reasons_json = json.dumps(list(reasons or []), ensure_ascii=False)

    def get_warnings(self):
        return self._loads_list(self.warnings_json)

    def set_warnings(self, warnings):
        self.warnings_json = json.dumps(list(warnings or []), ensure_ascii=False)

    def get_invoice_snapshot(self):
        if not self.invoice_snapshot_json:
            return None
        try:
            return json.loads(self.invoice_snapshot_json)
        except (TypeError, json.JSONDecodeError):
            return None

    def set_invoice_snapshot(self, snap):
        self.invoice_snapshot_json = json.dumps(snap or {}, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "analysis_id": self.analysis_id,
            "row_index": self.row_index,
            "source_table_index": self.source_table_index,
            "source_page": self.source_page,
            "raw_row": self._loads_list(self.raw_row_json) if self.raw_row_json else [],
            "raw_order_number": self.raw_order_number,
            "normalized_order_number": self.normalized_order_number,
            "customer_name": self.customer_name,
            "customer_phone": self.customer_phone,
            "collected_amount": self.collected_amount,
            "delivery_fee": self.delivery_fee,
            "net_amount": self.net_amount,
            "statement_date": self.statement_date,
            "matched_invoice_id": self.matched_invoice_id,
            "match_score": self.match_score,
            "match_status": self.match_status,
            "match_reasons": self.get_match_reasons(),
            "warnings": self.get_warnings(),
            "invoice_snapshot": self.get_invoice_snapshot(),
        }

    def set_raw_row(self, row):
        self.raw_row_json = json.dumps(list(row or []), ensure_ascii=False)
