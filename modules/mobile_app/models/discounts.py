"""Coupons, discounts, and campaigns (Phase 6)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileCampaign(db.Model):
    __tablename__ = "mobile_campaign"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(80), unique=True, index=True)
    description = db.Column(db.Text)
    starts_at = db.Column(db.DateTime)
    ends_at = db.Column(db.DateTime)
    bonus_multiplier = db.Column(db.Float, nullable=False, default=1.0)
    priority = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileDiscount(db.Model):
    __tablename__ = "mobile_discount"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    discount_type = db.Column(db.String(40), nullable=False, default="percent")
    # percent | fixed | free_shipping | first_order
    value = db.Column(db.Integer, nullable=False, default=0)
    min_subtotal = db.Column(db.Integer, nullable=False, default=0)
    max_discount = db.Column(db.Integer)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), index=True)
    category = db.Column(db.String(120))
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("mobile_campaign.id"), index=True)
    starts_at = db.Column(db.DateTime)
    ends_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileCoupon(db.Model):
    __tablename__ = "mobile_coupon"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(150), nullable=False, default="")
    discount_type = db.Column(db.String(20), nullable=False, default="percent")
    # percent | fixed
    value = db.Column(db.Integer, nullable=False, default=0)
    min_subtotal = db.Column(db.Integer, nullable=False, default=0)
    max_discount = db.Column(db.Integer)
    max_uses = db.Column(db.Integer)
    max_uses_per_user = db.Column(db.Integer, nullable=False, default=1)
    starts_at = db.Column(db.DateTime)
    ends_at = db.Column(db.DateTime)
    campaign_id = db.Column(db.Integer, db.ForeignKey("mobile_campaign.id"), index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileCouponRedemption(db.Model):
    __tablename__ = "mobile_coupon_redemption"

    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey("mobile_coupon.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), index=True)
    discount_amount = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
