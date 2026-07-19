"""Shopper profile addresses (Phase gap-fill)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileUserAddress(db.Model):
    __tablename__ = "mobile_user_address"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    label = db.Column(db.String(80), nullable=False, default="المنزل")
    full_name = db.Column(db.String(150), nullable=False, default="")
    phone = db.Column(db.String(32), nullable=False, default="")
    city = db.Column(db.String(100), nullable=False, default="")
    address = db.Column(db.String(255), nullable=False, default="")
    notes = db.Column(db.String(255))
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
