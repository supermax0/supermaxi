"""Server-side cart models for mobile shoppers (Phase 5)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileCart(db.Model):
    __tablename__ = "mobile_cart"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, unique=True, index=True)
    coupon_code = db.Column(db.String(64))
    points_to_redeem = db.Column(db.Integer, nullable=False, default=0)
    source_video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), index=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    items = db.relationship(
        "MobileCartItem",
        back_populates="cart",
        cascade="all, delete-orphan",
        lazy=True,
    )


class MobileCartItem(db.Model):
    __tablename__ = "mobile_cart_item"
    __table_args__ = (
        db.UniqueConstraint("cart_id", "product_id", name="uq_mobile_cart_item_product"),
    )

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("mobile_cart.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price_snapshot = db.Column(db.Integer)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    cart = db.relationship("MobileCart", back_populates="items", lazy=True)


class MobileOrderAttribution(db.Model):
    __tablename__ = "mobile_order_attribution"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), index=True)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), index=True)
    campaign_id = db.Column(db.Integer, index=True)
    coupon_id = db.Column(db.Integer, index=True)
    source = db.Column(db.String(40), nullable=False, default="mobile_app")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
