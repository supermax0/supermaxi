"""Initial distribution session (multi-branch spec, phase 5) — a document in front of the proven engines.

The session only stores WHAT the admin chose and what happened to each item. Every effect (stock transfer,
cash transfer, staff assignment) goes through the same service that does it everywhere else, so valuation,
journals and permissions are never re-implemented here.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class BranchDistribution(db.Model):
    __tablename__ = "branch_distribution"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), nullable=False, unique=True)
    title = db.Column(db.String(150), nullable=False)
    # draft | ready | executing | completed | failed | cancelled
    status = db.Column(db.String(12), nullable=False, default="draft", index=True)
    items = db.Column(db.Text, nullable=False, default="[]")  # JSON list; per-item state lives inside
    backup_path = db.Column(db.String(500), nullable=True)  # restore copy taken right before the first execution
    created_by_id = db.Column(db.Integer, nullable=True)
    approved_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
