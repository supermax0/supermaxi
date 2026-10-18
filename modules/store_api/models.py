"""Long-lived tokens for the public store catalog API."""

from __future__ import annotations

from datetime import datetime

from extensions import db


class StoreApiKey(db.Model):
    __tablename__ = "store_api_key"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    token_prefix = db.Column(db.String(40), nullable=False)
    created_by = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True, index=True)

    def is_active(self) -> bool:
        return self.revoked_at is None
