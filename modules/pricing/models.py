from __future__ import annotations

from datetime import datetime

from extensions import db


class PriceRule(db.Model):
    """Margin policy. The most specific active rule wins: product > brand > category > company default."""

    __tablename__ = "store_price_rule"

    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(10), nullable=False)  # default | category | brand | product
    scope_value = db.Column(db.String(120), nullable=True)  # category / brand name, or product id
    target_margin_pct = db.Column(db.Float, nullable=False)  # 0 < m < 90 — margin on the selling price
    minimum_margin_pct = db.Column(db.Float, nullable=False, default=0)
    extra_cost = db.Column(db.Integer, nullable=False, default=0)  # fees per unit included in the cost basis
    rounding_step = db.Column(db.Integer, nullable=False, default=1000)  # 1 000 or 5 000 dinars …
    automatic = db.Column(db.Boolean, nullable=False, default=False)
    max_auto_change_pct = db.Column(db.Float, nullable=False, default=10)
    approval_required = db.Column(db.Boolean, nullable=False, default=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SupplierOffer(db.Model):
    """What a supplier currently asks — the replacement cost. Not the recorded inventory cost."""

    __tablename__ = "supplier_offer"
    __table_args__ = (db.UniqueConstraint("supplier_ref", "product_id", name="uq_supplier_offer_product"),)

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, nullable=True, index=True)
    supplier_ref = db.Column(db.String(120), nullable=False)  # supplier id or the file / list name
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    supplier_sku = db.Column(db.String(80), nullable=True)
    purchase_price = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="IQD")
    reported_quantity = db.Column(db.Integer, nullable=True)
    lead_time_days = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(10), nullable=False, default="active")
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceBatch(db.Model):
    """A set of proposed selling-price changes: from a price file or from the rules. Applied once, after approval."""

    __tablename__ = "store_price_batch"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(20), nullable=False)  # file | rules | manual
    label = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="draft")  # draft | applied | rejected
    created_by_id = db.Column(db.Integer, nullable=True)
    approved_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)


class PriceProposal(db.Model):
    __tablename__ = "store_price_proposal"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("store_price_batch.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, nullable=True, index=True)
    row_ref = db.Column(db.String(120), nullable=True)  # what the file said (barcode / sku / model)
    old_price = db.Column(db.Integer, nullable=True)
    new_price = db.Column(db.Integer, nullable=True)
    cost_basis = db.Column(db.Integer, nullable=True)
    minimum_price = db.Column(db.Integer, nullable=True)
    verdict = db.Column(db.String(16), nullable=False)  # up | down | same | below_minimum | unmatched | invalid
    note = db.Column(db.String(255), nullable=True)
    applied = db.Column(db.Boolean, nullable=False, default=False)


class PriceHistory(db.Model):
    """Every selling-price change, whoever / whatever made it. Append-only."""

    __tablename__ = "store_price_history"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, nullable=False, index=True)
    old_price = db.Column(db.Integer, nullable=False)
    new_price = db.Column(db.Integer, nullable=False)
    source = db.Column(db.String(20), nullable=False)  # batch | promotion_start | promotion_end | manual
    reason = db.Column(db.String(255), nullable=True)
    batch_id = db.Column(db.Integer, nullable=True)
    approved_by_id = db.Column(db.Integer, nullable=True)
    effective_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Promotion(db.Model):
    """A time-boxed selling price. At start the product price becomes ``promo_price`` (the regular price is shown as
    the old price → a REAL discount); at the end the regular price comes back unless someone changed it meanwhile."""

    __tablename__ = "store_promotion"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, nullable=False, index=True)
    promo_price = db.Column(db.Integer, nullable=False)
    regular_price = db.Column(db.Integer, nullable=True)  # captured when the promotion starts
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default="scheduled")  # scheduled | running | ended | cancelled | conflict
    note = db.Column(db.String(255), nullable=True)
    created_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


ALL_TABLES = (PriceRule, SupplierOffer, PriceBatch, PriceProposal, PriceHistory, Promotion)
