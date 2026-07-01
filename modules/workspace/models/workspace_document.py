from __future__ import annotations

import json
import uuid
from datetime import datetime

from extensions import db


class WorkspaceDocument(db.Model):
    __tablename__ = "ai_workspace_documents"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_workspace_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_slug = db.Column(db.String(100), index=True, nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(512), nullable=False)
    public_preview_path = db.Column(db.String(512), nullable=True)
    mime_type = db.Column(db.String(120), nullable=False)
    file_ext = db.Column(db.String(20), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    sha256 = db.Column(db.String(64), nullable=True)
    page_count = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="uploaded")
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_metadata(self):
        if not self.metadata_json:
            return {}
        try:
            return json.loads(self.metadata_json)
        except (TypeError, json.JSONDecodeError):
            return {}

    def set_metadata(self, data):
        self.metadata_json = json.dumps(data or {}, ensure_ascii=False)

    def preview_url(self):
        return f"/workspace/api/documents/{self.id}/preview"

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tenant_slug": self.tenant_slug,
            "user_id": self.user_id,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "mime_type": self.mime_type,
            "file_ext": self.file_ext,
            "file_size": self.file_size,
            "sha256": self.sha256,
            "page_count": self.page_count,
            "status": self.status,
            "preview_url": self.preview_url(),
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
