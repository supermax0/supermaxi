"""Master catalogue service: entries, duplicate guard, store listings, activation, availability requests.

Hard rules:
* nothing here writes a quantity, a cost, a stock movement or a ledger row;
* a catalogue entry never reaches the POS — only an *activated* inventory product can, and activation creates it
  with quantity 0 (stock arrives through purchases / transfers, as for every product);
* a barcode belongs to one entry; brand + model + regional version identifies an entry (no silent duplicates).
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Any

from extensions import db
from modules.catalog.models import (
    ALL_TABLES,
    AvailabilityRequest,
    CatalogBarcode,
    CatalogMedia,
    CatalogProduct,
    CatalogSource,
    StoreListing,
)

FLAG = "catalog_layer"
STATUSES = ("pending", "gathering", "matched", "needs_review", "verified", "published", "failed")


class CatalogError(Exception):
    def __init__(self, message: str, code: str = "validation", status: int = 400, **extra: Any):
        super().__init__(message)
        self.code, self.status, self.extra = code, status, extra


# ───────────────────────────── switches & schema ─────────────────────────────


def enabled() -> bool:
    try:
        from models.system_settings import SystemSettings

        return bool(SystemSettings.get_settings().get_ui_flags().get(FLAG))
    except Exception:
        return False


def ensure_tables() -> None:
    from sqlalchemy import inspect, text

    conn = db.session.connection()
    for model in ALL_TABLES:
        model.__table__.create(bind=conn, checkfirst=True)
    # Expand-only migration for databases that got the first version of the table
    if "field_sources_json" not in {c["name"] for c in inspect(conn).get_columns("catalog_product")}:
        conn.execute(text("ALTER TABLE catalog_product ADD COLUMN field_sources_json TEXT"))


def tables_exist() -> bool:
    from sqlalchemy import inspect

    try:
        return inspect(db.session.connection()).has_table(StoreListing.__tablename__)
    except Exception:
        return False


# ───────────────────────────── normalisation ─────────────────────────────

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def norm_key(value: Any) -> str:
    """Case / spacing / digit-script insensitive key: 'TCL 55C7K' == 'tcl-55c7k' == 'TCL55C7K'."""
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_ARABIC_DIGITS).casefold()
    return re.sub(r"[\s\-_./]+", "", text)[:80]


def norm_barcode(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or "").translate(_ARABIC_DIGITS))[:40]


# ───────────────────────────── entries ─────────────────────────────


def find_duplicate(*, brand: str, model_number: str, regional_version: str = "", barcodes: list[str] = (),
                   exclude_id: int | None = None) -> CatalogProduct | None:
    codes = [c for c in (norm_barcode(b) for b in barcodes) if c]
    if codes:
        hit = CatalogBarcode.query.filter(CatalogBarcode.code.in_(codes)).first()
        if hit is not None and hit.catalog_product_id != exclude_id:
            return db.session.get(CatalogProduct, hit.catalog_product_id)
    bkey, mkey = norm_key(brand), norm_key(model_number)
    if bkey and mkey:
        query = CatalogProduct.query.filter_by(brand_key=bkey, model_key=mkey)
        rows = [r for r in query.all() if norm_key(r.regional_version) == norm_key(regional_version)]
        rows = [r for r in rows if r.id != exclude_id]
        if rows:
            return rows[0]
    return None


def _attributes(raw: Any) -> str | None:
    if raw in (None, "", {}):
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise CatalogError("المواصفات يجب أن تكون قائمة «خاصية: قيمة»") from None
    if not isinstance(raw, dict):
        raise CatalogError("المواصفات يجب أن تكون قائمة «خاصية: قيمة»")
    clean = {str(k).strip()[:60]: str(v).strip()[:200] for k, v in raw.items() if str(k).strip() and str(v).strip()}
    return json.dumps(clean, ensure_ascii=False) if clean else None


def save_entry(data: dict, *, by: int | None, entry_id: int | None = None) -> CatalogProduct:
    ensure_tables()
    name = str(data.get("canonical_name") or data.get("name") or "").strip()
    if len(name) < 3:
        raise CatalogError("اكتب اسم المنتج")
    brand = str(data.get("brand") or "").strip()[:80]
    model_number = str(data.get("model_number") or data.get("model") or "").strip()[:80]
    regional = str(data.get("regional_version") or "").strip()[:40]
    barcodes = [norm_barcode(b) for b in (data.get("barcodes") or []) if norm_barcode(b)]
    if any(len(b) < 8 for b in barcodes):
        raise CatalogError("الباركود يجب أن يكون 8 أرقام أو أكثر")
    duplicate = find_duplicate(brand=brand, model_number=model_number, regional_version=regional, barcodes=barcodes,
                               exclude_id=entry_id)
    if duplicate is not None:
        raise CatalogError("هذا الموديل موجود في الكتالوج مسبقاً", "duplicate", 409, existing_id=duplicate.id)
    status = str(data.get("verification_status") or "pending")
    if status not in STATUSES:
        raise CatalogError("حالة تحقق غير معروفة")
    entry = db.session.get(CatalogProduct, int(entry_id)) if entry_id else CatalogProduct(created_by_id=by)
    if entry is None:
        raise CatalogError("المنتج غير موجود في الكتالوج", "not_found", 404)
    entry.canonical_name, entry.brand, entry.model_number, entry.regional_version = name[:200], brand or None, \
        model_number or None, regional or None
    entry.brand_key, entry.model_key = norm_key(brand) or None, norm_key(model_number) or None
    entry.category = str(data.get("category") or "").strip()[:80] or None
    entry.description = str(data.get("description") or "").strip() or None
    entry.attributes_json = _attributes(data.get("attributes"))
    entry.verification_status = status
    db.session.add(entry)
    db.session.flush()
    if "barcodes" in data:
        CatalogBarcode.query.filter_by(catalog_product_id=entry.id).delete()
        for code in dict.fromkeys(barcodes):
            db.session.add(CatalogBarcode(catalog_product_id=entry.id, code=code))
    if "media" in data:
        # media are only ever ADDED here (uploaded / verified photos are managed by modules.catalog.images)
        known = {m.url for m in CatalogMedia.query.filter_by(catalog_product_id=entry.id).all()}
        start = len(known)
        for i, m in enumerate(data.get("media") or [], start=start):
            if str((m or {}).get("url") or "").strip() in known:
                continue
            url = str((m or {}).get("url") or "").strip()
            if not url.startswith(("/static/", "https://")):
                raise CatalogError("رابط الصورة يجب أن يكون https أو ملفاً مرفوعاً للمتجر")
            db.session.add(CatalogMedia(catalog_product_id=entry.id, url=url[:500], sort_order=i,
                                        image_role=str(m.get("role") or "")[:20] or None,
                                        source_url=str(m.get("source_url") or "")[:500] or None,
                                        usage_rights=str(m.get("usage_rights") or "")[:40] or None))
    if data.get("source"):
        src = data["source"]
        db.session.add(CatalogSource(catalog_product_id=entry.id, source_type=str(src.get("type") or "manual")[:20],
                                     source_url=str(src.get("url") or "")[:500] or None,
                                     source_reference=str(src.get("reference") or "")[:200] or None,
                                     source_priority=int(src.get("priority") or 50), last_verified_at=datetime.utcnow()))
    db.session.flush()
    return entry


def serialize(entry: CatalogProduct) -> dict[str, Any]:
    listing = StoreListing.query.filter_by(catalog_product_id=entry.id).first()
    return {
        "id": entry.id, "canonical_name": entry.canonical_name, "brand": entry.brand or "",
        "model_number": entry.model_number or "", "regional_version": entry.regional_version or "",
        "category": entry.category or "", "description": entry.description or "",
        "attributes": json.loads(entry.attributes_json) if entry.attributes_json else {},
        "verification_status": entry.verification_status,
        "field_sources": json.loads(entry.field_sources_json) if entry.field_sources_json else {},
        "barcodes": [b.code for b in CatalogBarcode.query.filter_by(catalog_product_id=entry.id).all()],
        "media": [{"id": m.id, "url": m.url, "role": m.image_role or "", "rights": m.usage_rights or "",
                   "verified": m.verification_status == "verified"} for m in
                  CatalogMedia.query.filter_by(catalog_product_id=entry.id).order_by(CatalogMedia.sort_order).all()],
        "listing": None if listing is None else {
            "is_published": listing.is_published, "fulfillment_policy": listing.fulfillment_policy,
            "inventory_product_id": listing.inventory_product_id, "is_featured": listing.is_featured},
    }


def search(q: str = "", *, limit: int = 30, offset: int = 0) -> tuple[list[CatalogProduct], int]:
    ensure_tables()
    query = CatalogProduct.query
    text = str(q or "").strip()
    if text:
        code = norm_barcode(text)
        key = norm_key(text)
        ids_by_code = [b.catalog_product_id for b in CatalogBarcode.query.filter_by(code=code).all()] if code else []
        like = f"%{text}%"
        query = query.filter(db.or_(CatalogProduct.id.in_(ids_by_code or [0]), CatalogProduct.canonical_name.ilike(like),
                                    CatalogProduct.model_key.contains(key) if key else db.false(),
                                    CatalogProduct.brand.ilike(like)))
    total = query.count()
    return query.order_by(CatalogProduct.id.desc()).limit(limit).offset(offset).all(), total


# ───────────────────────────── listings ─────────────────────────────


def set_listing(entry_id: int, *, publish: bool, policy: str = "request", featured: bool = False) -> StoreListing:
    ensure_tables()
    entry = db.session.get(CatalogProduct, int(entry_id))
    if entry is None:
        raise CatalogError("المنتج غير موجود في الكتالوج", "not_found", 404)
    if policy not in ("request", "stock_only"):
        raise CatalogError("سياسة التوفير غير معروفة")
    if publish and entry.verification_status not in ("verified", "published"):
        raise CatalogError("لا يُنشر منتج قبل مراجعة بياناته (الحالة: موثّق)", "unverified", 409)
    listing = StoreListing.query.filter_by(catalog_product_id=entry.id).first() or StoreListing(catalog_product_id=entry.id)
    listing.is_published, listing.fulfillment_policy, listing.is_featured = bool(publish), policy, bool(featured)
    if publish and not listing.published_at:
        listing.published_at = datetime.utcnow()
    if publish:
        entry.verification_status = "published"
    db.session.add(listing)
    db.session.flush()
    return listing


def activate(entry_id: int, *, sale_price: int, branch_id: int | None = None, pos_visible: bool = False,
             by: int | None = None) -> int:
    """Create (once) the inventory product of a catalogue entry — quantity 0, no stock balance, no movement.
    ``pos_visible`` defaults to False: the cashier sees it only when the company decides so."""
    from models.product import Product

    ensure_tables()
    entry = db.session.get(CatalogProduct, int(entry_id))
    if entry is None:
        raise CatalogError("المنتج غير موجود في الكتالوج", "not_found", 404)
    listing = StoreListing.query.filter_by(catalog_product_id=entry.id).first()
    if listing is not None and listing.inventory_product_id:
        return int(listing.inventory_product_id)  # replay-safe: never a second product
    if int(sale_price or 0) <= 0:
        raise CatalogError("حدد سعر البيع قبل التفعيل في المخزون")
    if branch_id is None:
        from utils.branch_migration import get_default_branch

        branch_id = get_default_branch().id
    meta = {"brand": entry.brand or "", "model": entry.model_number or "", "category": entry.category or "",
            "catalog_product_id": entry.id}
    if entry.attributes_json:
        meta["specs_items"] = [{"label": k, "value": v} for k, v in json.loads(entry.attributes_json).items()]
    media = CatalogMedia.query.filter_by(catalog_product_id=entry.id).order_by(CatalogMedia.sort_order).all()
    barcode = CatalogBarcode.query.filter_by(catalog_product_id=entry.id).first()
    if barcode is not None:
        clash = (Product.query.execution_options(skip_branch_scope=True)
                 .filter_by(barcode=barcode.code, branch_id=int(branch_id)).first())
        if clash is not None:
            raise CatalogError("يوجد منتج في المخزون بنفس الباركود — اربطه به بدل إنشاء منتج جديد", "exists", 409,
                               product_id=clash.id)
    product = Product(name=entry.canonical_name[:150], sku=(entry.model_number or None), barcode=barcode.code if barcode else None,
                      buy_price=0, sale_price=int(sale_price), quantity=0, active=True, store_visible=True,
                      pos_visible=bool(pos_visible), branch_id=int(branch_id), description=entry.description,
                      image_url=media[0].url if media else None,
                      meta_json=json.dumps({**meta, "gallery": [m.url for m in media[1:]]}, ensure_ascii=False))
    db.session.add(product)
    db.session.flush()
    listing = listing or StoreListing(catalog_product_id=entry.id)
    listing.inventory_product_id = product.id
    db.session.add(listing)
    db.session.flush()
    return int(product.id)


def link(entry_id: int, product_id: int) -> None:
    """Attach an entry to an inventory product that already exists (no new product, nothing else changes)."""
    from models.product import Product

    ensure_tables()
    entry = db.session.get(CatalogProduct, int(entry_id))
    product = Product.query.execution_options(skip_branch_scope=True).get(int(product_id))
    if entry is None or product is None:
        raise CatalogError("المنتج غير موجود", "not_found", 404)
    taken = StoreListing.query.filter(StoreListing.inventory_product_id == product.id,
                                      StoreListing.catalog_product_id != entry.id).first()
    if taken is not None:
        raise CatalogError("هذا المنتج مربوط بموديل آخر في الكتالوج", "conflict", 409)
    listing = StoreListing.query.filter_by(catalog_product_id=entry.id).first() or StoreListing(catalog_product_id=entry.id)
    listing.inventory_product_id = product.id
    db.session.add(listing)
    db.session.flush()


# ───────────────────────────── storefront read model ─────────────────────────────


_SCHEMA_CHECKED: set[str] = set()


def _schema_ready() -> bool:
    """Tables exist AND carry every column of this version (an older tenant gets the Expand step once)."""
    from flask import g

    if not tables_exist():
        return False
    key = str(getattr(g, "tenant", "") or "")
    if key not in _SCHEMA_CHECKED:
        ensure_tables()
        _SCHEMA_CHECKED.add(key)
    return True


def published_catalog_only(q: str = "", category: str = "") -> list[CatalogProduct]:
    """Published entries the company does NOT stock (no inventory product) offered on request."""
    if not _schema_ready():
        return []
    query = (CatalogProduct.query.join(StoreListing, StoreListing.catalog_product_id == CatalogProduct.id)
             .filter(StoreListing.is_published.is_(True), StoreListing.inventory_product_id.is_(None),
                     StoreListing.fulfillment_policy == "request"))
    text = str(q or "").strip()
    if text:
        code = norm_barcode(text)
        ids = [b.catalog_product_id for b in CatalogBarcode.query.filter_by(code=code).all()] if code else []
        query = query.filter(db.or_(CatalogProduct.canonical_name.ilike(f"%{text}%"), CatalogProduct.brand.ilike(f"%{text}%"),
                                    CatalogProduct.model_key.contains(norm_key(text)), CatalogProduct.id.in_(ids or [0])))
    if category:
        query = query.filter(CatalogProduct.category == category)
    return query.order_by(StoreListing.is_featured.desc(), CatalogProduct.id.desc()).all()


def card(entry: CatalogProduct, shop_slug: str) -> dict[str, Any]:
    """A storefront card for a model offered on request: no price (none is known yet) and never 'in stock'."""
    from flask import url_for

    media = CatalogMedia.query.filter_by(catalog_product_id=entry.id).order_by(CatalogMedia.sort_order).all()
    attrs = json.loads(entry.attributes_json) if entry.attributes_json else {}
    return {
        "kind": "catalog", "id": entry.id, "name": entry.canonical_name, "brand": entry.brand or "",
        "model": entry.model_number or "", "category": entry.category or "", "badge": entry.category or "",
        "image_url": media[0].url if media else "", "gallery": [m.url for m in media][:5],
        "specs": [{"label": k, "value": v} for k, v in attrs.items()], "price": 0, "old_price": 0,
        "discount_percent": 0, "price_currency": "IQD", "is_available": False, "is_reservation": False,
        "is_on_request": True, "description": entry.description or "",
        "url": url_for("storefront.catalog_detail", tenant_slug=shop_slug, entry_id=entry.id),
    }


def request_availability(entry_id: int, data: dict) -> AvailabilityRequest:
    ensure_tables()
    entry = db.session.get(CatalogProduct, int(entry_id))
    listing = StoreListing.query.filter_by(catalog_product_id=int(entry_id)).first() if entry else None
    if entry is None or listing is None or not listing.is_published:
        raise CatalogError("المنتج غير متاح", "not_found", 404)
    name = str(data.get("customer_name") or "").strip()
    digits = norm_barcode(data.get("phone"))
    if digits.startswith("964"):
        digits = "0" + digits[3:]
    if len(name) < 2:
        raise CatalogError("اكتب اسمك")
    if not re.fullmatch(r"07\d{9}", digits):
        raise CatalogError("اكتب رقم هاتف عراقي صحيح يبدأ بـ 07")
    row = AvailabilityRequest(catalog_product_id=entry.id, customer_name=name[:120], phone=digits,
                              city=str(data.get("city") or "").strip()[:60] or None,
                              note=str(data.get("note") or "").strip()[:255] or None)
    db.session.add(row)
    db.session.flush()
    return row
