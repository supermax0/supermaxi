"""Long-lived POS API keys for machine clients (voice Core)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class PosApiKey(db.Model):
    __tablename__ = "pos_api_key"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    token_prefix = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True, index=True)

    employee = db.relationship("Employee", lazy=True)

    def is_active(self) -> bool:
        return self.revoked_at is None
