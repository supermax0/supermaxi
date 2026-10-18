"""Autosaved wholesale operation drafts (tabs)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class WholesaleDraft(db.Model):
    __tablename__ = "wholesale_draft"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    op_type = db.Column(db.String(20), nullable=False)  # sale|receipt|purchase|payment
    title = db.Column(db.String(120), nullable=True)
    payload_json = db.Column(db.Text, nullable=False, default="{}")
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
