from __future__ import annotations

import json
import uuid
from datetime import datetime

from extensions import db

MAX_STORED_TEXT = 50000
TEXT_SAMPLE_LEN = 500


class DocumentExtractionResult(db.Model):
    __tablename__ = "ai_workspace_document_extraction_results"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_workspace_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_workspace_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_slug = db.Column(db.String(100), index=True, nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="pending")
    document_kind = db.Column(db.String(50), nullable=True)
    confidence = db.Column(db.Float, default=0.0)
    signals_json = db.Column(db.Text, nullable=True)
    extracted_text = db.Column(db.Text, nullable=True)
    text_sample = db.Column(db.Text, nullable=True)
    tables_json = db.Column(db.Text, nullable=True)
    normalized_entities_json = db.Column(db.Text, nullable=True)
    pages_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def _loads(self, raw):
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}

    def _dumps(self, data):
        return json.dumps(data or {}, ensure_ascii=False)

    def get_signals(self):
        data = self._loads(self.signals_json)
        return data if isinstance(data, list) else []

    def set_signals(self, signals):
        self.signals_json = json.dumps(list(signals or []), ensure_ascii=False)

    def get_tables(self):
        data = self._loads(self.tables_json)
        if isinstance(data, dict):
            return data.get("tables") or []
        return data if isinstance(data, list) else []

    def set_tables(self, tables, status=None, warnings=None):
        payload = {"tables": tables or [], "status": status, "warnings": warnings or []}
        self.tables_json = self._dumps(payload)

    def get_normalized_entities(self):
        return self._loads(self.normalized_entities_json)

    def set_normalized_entities(self, entities):
        self.normalized_entities_json = self._dumps(entities)

    def get_pages(self):
        data = self._loads(self.pages_json)
        return data if isinstance(data, list) else []

    def set_pages(self, pages):
        self.pages_json = json.dumps(pages or [], ensure_ascii=False)

    def get_metadata(self):
        return self._loads(self.metadata_json)

    def set_metadata(self, data):
        self.metadata_json = self._dumps(data)

    @staticmethod
    def truncate_text(text: str, max_len: int = MAX_STORED_TEXT) -> tuple[str, list[str]]:
        warnings = []
        if not text:
            return "", warnings
        if len(text) > max_len:
            warnings.append(f"تم اقتصاص النص المخزّن إلى {max_len} حرفاً")
            return text[:max_len], warnings
        return text, warnings

    @staticmethod
    def make_sample(text: str, max_len: int = TEXT_SAMPLE_LEN) -> str:
        if not text:
            return ""
        return text[:max_len]

    def to_dict(self):
        meta = self.get_metadata()
        return {
            "id": self.id,
            "document_id": self.document_id,
            "session_id": self.session_id,
            "tenant_slug": self.tenant_slug,
            "user_id": self.user_id,
            "status": self.status,
            "document_kind": self.document_kind,
            "confidence": self.confidence,
            "signals": self.get_signals(),
            "text_sample": self.text_sample,
            "has_full_text": bool(self.extracted_text),
            "tables": self.get_tables(),
            "tables_count": len(self.get_tables()),
            "normalized_entities": self.get_normalized_entities(),
            "pages": self.get_pages(),
            "error_message": self.error_message,
            "extraction_summary": meta.get("extraction_summary") or {},
            "warnings": meta.get("warnings") or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
