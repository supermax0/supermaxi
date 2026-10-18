from __future__ import annotations

from datetime import datetime

from extensions import db


class StoreEvent(db.Model):
    """One anonymous shopping signal (view, search, cart, recommendation click…) — for measurement only.

    ``sid`` is a random per-session id; nothing here identifies a person."""

    __tablename__ = "store_event"

    id = db.Column(db.Integer, primary_key=True)
    sid = db.Column(db.String(16), nullable=False, index=True)
    event_type = db.Column(db.String(16), nullable=False, index=True)
    product_id = db.Column(db.Integer, nullable=True, index=True)
    category = db.Column(db.String(60), nullable=True)
    value = db.Column(db.String(120), nullable=True)  # search text / recommendation section
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
