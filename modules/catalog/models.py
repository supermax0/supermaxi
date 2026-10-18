"""Master catalogue tables. Each company has its own tenant database, so isolation is by database (no tenant_id)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class CatalogProduct(db.Model):
    __tablename__ = "catalog_product"
    __table_args__ = (db.Index("ix_catalog_product_brand_model", "brand_key", "model_key"),)

    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(80), nullable=True)
    brand_key = db.Column(db.String(80), nullable=True, index=True)  # normalised, for duplicate detection
    model_number = db.Column(db.String(80), nullable=True)
    model_key = db.Column(db.String(80), nullable=True, index=True)
    regional_version = db.Column(db.String(40), nullable=True)  # a different regional version = a different entry
    canonical_name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(80), nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)
    attributes_json = db.Column(db.Text, nullable=True)  # {"label": "value", …}
    verification_status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    # {"field": {"source": "...", "confidence": 0..100}} — where each important value came from
    field_sources_json = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CatalogBarcode(db.Model):
    """GTIN / EAN / UPC — a model may carry several; one barcode belongs to one entry only."""

    __tablename__ = "catalog_barcode"

    id = db.Column(db.Integer, primary_key=True)
    catalog_product_id = db.Column(db.Integer, db.ForeignKey("catalog_product.id"), nullable=False, index=True)
    code = db.Column(db.String(40), nullable=False, unique=True)


class CatalogMedia(db.Model):
    __tablename__ = "catalog_media"

    id = db.Column(db.Integer, primary_key=True)
    catalog_product_id = db.Column(db.Integer, db.ForeignKey("catalog_product.id"), nullable=False, index=True)
    url = db.Column(db.String(500), nullable=False)
    source_url = db.Column(db.String(500), nullable=True)
    image_role = db.Column(db.String(20), nullable=True)  # front | side | detail | ports | box
    usage_rights = db.Column(db.String(40), nullable=True)
    verification_status = db.Column(db.String(16), nullable=False, default="pending")
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class CatalogSource(db.Model):
    __tablename__ = "catalog_source"

    id = db.Column(db.Integer, primary_key=True)
    catalog_product_id = db.Column(db.Integer, db.ForeignKey("catalog_product.id"), nullable=False, index=True)
    source_type = db.Column(db.String(20), nullable=False)  # manufacturer | agent | database | supplier | manual
    source_url = db.Column(db.String(500), nullable=True)
    source_reference = db.Column(db.String(200), nullable=True)
    source_priority = db.Column(db.Integer, nullable=False, default=50)
    last_verified_at = db.Column(db.DateTime, nullable=True)


class StoreListing(db.Model):
    """Whether / how a catalogue entry shows in the shop. ``inventory_product_id`` links an activated product."""

    __tablename__ = "store_listing"

    id = db.Column(db.Integer, primary_key=True)
    catalog_product_id = db.Column(db.Integer, db.ForeignKey("catalog_product.id"), nullable=False, unique=True)
    inventory_product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True, index=True)
    is_published = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_featured = db.Column(db.Boolean, nullable=False, default=False)
    fulfillment_policy = db.Column(db.String(16), nullable=False, default="request")  # request | stock_only
    category_override = db.Column(db.String(80), nullable=True)
    seo_slug = db.Column(db.String(200), nullable=True, unique=True)
    published_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AvailabilityRequest(db.Model):
    """A shopper asking for a model the company does not stock yet. Not an order: no price, no stock, no invoice."""

    __tablename__ = "store_availability_request"

    id = db.Column(db.Integer, primary_key=True)
    catalog_product_id = db.Column(db.Integer, db.ForeignKey("catalog_product.id"), nullable=False, index=True)
    customer_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    city = db.Column(db.String(60), nullable=True)
    note = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(12), nullable=False, default="new", index=True)  # new | contacted | closed
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class CatalogImportBatch(db.Model):
    __tablename__ = "catalog_import_batch"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    file_sha256 = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default="preview")  # preview | applied | discarded
    counts_json = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    applied_at = db.Column(db.DateTime, nullable=True)


class CatalogImportRow(db.Model):
    __tablename__ = "catalog_import_row"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("catalog_import_batch.id"), nullable=False, index=True)
    row_no = db.Column(db.Integer, nullable=False)
    data_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(16), nullable=False)  # new | matched | linked | duplicate | needs_review | invalid
    issues_json = db.Column(db.Text, nullable=True)
    match_entry_id = db.Column(db.Integer, nullable=True)
    match_product_id = db.Column(db.Integer, nullable=True)
    applied_entry_id = db.Column(db.Integer, nullable=True)


ALL_TABLES = (CatalogProduct, CatalogBarcode, CatalogMedia, CatalogSource, StoreListing, AvailabilityRequest,
              CatalogImportBatch, CatalogImportRow)
