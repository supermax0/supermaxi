"""Shopper product favorites (Phase 4)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileFavorite(db.Model):
    __tablename__ = "mobile_favorite"
    __table_args__ = (
        db.UniqueConstraint("user_id", "product_id", name="uq_mobile_favorite_user_product"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
