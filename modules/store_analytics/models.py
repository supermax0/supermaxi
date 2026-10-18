from __future__ import annotations

from datetime import datetime

from extensions import db


class StoreVital(db.Model):
    """One page load's Core Web Vitals from a real visitor's browser. No identifier of any kind."""

    __tablename__ = "store_vital"

    id = db.Column(db.Integer, primary_key=True)
    page = db.Column(db.String(16), nullable=False, index=True)  # home | category | search | product | cart | checkout | other
    lcp_ms = db.Column(db.Integer, nullable=True)
    cls_milli = db.Column(db.Integer, nullable=True)  # CLS × 1000
    inp_ms = db.Column(db.Integer, nullable=True)
    mobile = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
