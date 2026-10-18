from __future__ import annotations

from datetime import datetime

from extensions import db


class ProductRelation(db.Model):
    """A curated link: «this stand fits this screen». Only VERIFIED relations are ever shown to shoppers."""

    __tablename__ = "store_product_relation"
    __table_args__ = (db.UniqueConstraint("source_product_id", "target_product_id", "relation_type", name="uq_store_relation"),)

    id = db.Column(db.Integer, primary_key=True)
    source_product_id = db.Column(db.Integer, nullable=False, index=True)
    target_product_id = db.Column(db.Integer, nullable=False, index=True)
    relation_type = db.Column(db.String(12), nullable=False)  # accessory | compatible | upgrade | service
    compatibility_note = db.Column(db.String(255), nullable=True)  # «VESA 300×300», «حتى 65 بوصة» …
    priority = db.Column(db.Integer, nullable=False, default=50)
    verified = db.Column(db.Boolean, nullable=False, default=False)
    created_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Bundle(db.Model):
    """«جهّز مطبخك» — a curated list of products. Its price is the plain sum of current prices (no fake saving)."""

    __tablename__ = "store_bundle"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    product_ids_json = db.Column(db.Text, nullable=False, default="[]")
    active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


ALL_TABLES = (ProductRelation, Bundle)
