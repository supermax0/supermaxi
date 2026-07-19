"""Rewards ledger, tiers, and redemption models (Phase 6)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileRewardAccount(db.Model):
    __tablename__ = "mobile_reward_account"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, unique=True, index=True)
    # Cached confirmed balance; ledger remains source of truth.
    balance = db.Column(db.Integer, nullable=False, default=0)
    lifetime_earned = db.Column(db.Integer, nullable=False, default=0)
    lifetime_redeemed = db.Column(db.Integer, nullable=False, default=0)
    tier_key = db.Column(db.String(40), nullable=False, default="silver")
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileRewardTransaction(db.Model):
    __tablename__ = "mobile_reward_transaction"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    type = db.Column(db.String(40), nullable=False, index=True)
    points = db.Column(db.Integer, nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # credit | debit
    status = db.Column(db.String(20), nullable=False, default="confirmed", index=True)
    # pending | confirmed | cancelled | expired
    reference_type = db.Column(db.String(40))
    reference_id = db.Column(db.Integer, index=True)
    description = db.Column(db.String(255))
    expires_at = db.Column(db.DateTime)
    created_by = db.Column(db.Integer)  # staff employee id for manual adjustments
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class MobileRewardRule(db.Model):
    __tablename__ = "mobile_reward_rule"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    rule_type = db.Column(db.String(40), nullable=False, index=True)
    # welcome_bonus | purchase_reward | points_redemption_rate | first_order_bonus
    points = db.Column(db.Integer, nullable=False, default=0)
    # For purchase_reward: points per IQD unit (see amount_per_point)
    amount_per_point = db.Column(db.Integer, nullable=False, default=1000)
    # 1 point earned per amount_per_point IQD spent
    multiplier = db.Column(db.Float, nullable=False, default=1.0)
    confirm_statuses = db.Column(db.String(255), nullable=False, default="مكتمل,مسدد,تم التوصيل")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    meta_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileRewardTier(db.Model):
    __tablename__ = "mobile_reward_tier"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), nullable=False, unique=True, index=True)
    name = db.Column(db.String(80), nullable=False)
    min_lifetime_points = db.Column(db.Integer, nullable=False, default=0)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    perks_json = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class MobileRewardRedemption(db.Model):
    __tablename__ = "mobile_reward_redemption"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    points_spent = db.Column(db.Integer, nullable=False)
    discount_amount = db.Column(db.Integer, nullable=False, default=0)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("mobile_reward_transaction.id"))
    status = db.Column(db.String(20), nullable=False, default="applied")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
