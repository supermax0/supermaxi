"""Write access for the online store: catalog, storefront orders, and storefront settings."""

from __future__ import annotations

import json
import base64
import binascii
import hashlib
import os
import re
from datetime import datetime
from urllib.parse import urlparse

import requests
from flask import current_app
from sqlalchemy import or_

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.system_settings import SystemSettings
from modules.installments.models import InstallmentProduct
from modules.store_api.services.catalog import get_public_product, public_product, store_profile
from modules.storefront.services.catalog_service import (
    cash_store_product_is_visible,
    has_shared_installment_catalog,
)
from modules.storefront.services.product_presenter import product_card, product_meta
from modules.storefront.services.settings_service import StorefrontSettingsService, safe_hex_color, safe_int

STORE_NOTE_PREFIX = "طلب من متجر المنتجات"
SERVICE_BARCODES = ("__SF_SHIPPING__", "__SF_DISCOUNT__")
ORDER_STATUSES = ("تم الطلب", "قيد التجهيز", "قيد الشحن", "تم التوصيل", "مكتمل", "ملغي")
PAYMENT_STATUSES = ("غير مسدد", "جزئي", "مسدد", "مرتجع")
CARD_STYLES = {"modern", "compact", "showcase", "minimal", "bordered", "overlay"}
THEME_PRESETS = {"custom", "ocean", "sunset", "emerald"}
THEME_MODES = {"light", "dark", "auto"}
HERO_MODES = {"auto", "manual", "both"}

PERMISSIONS = [
    "catalog:read",
    "catalog:write",
    "orders:read",
    "orders:write",
    "customers:read",
    "customers:write",
    "settings:read",
    "settings:write",
]

IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class StoreControlError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _settings() -> SystemSettings:
    row = SystemSettings.get_settings()
    if row is None:
        raise StoreControlError("إعدادات المتجر غير متاحة", 500, "settings_unavailable")
    return row


def _tenant_id() -> int | None:
    tenant_id = db.session.query(Product.tenant_id).filter(Product.tenant_id.isnot(None)).limit(1).scalar()
    if tenant_id:
        return int(tenant_id)
    from models.tenant import Tenant

    tenant = Tenant.query.order_by(Tenant.id.asc()).first()
    return int(tenant.id) if tenant else None


def _default_branch_id() -> int | None:
    from utils.branch_migration import get_default_branch

    branch = get_default_branch()
    return int(branch.id) if branch else None


def _slug(name: str, product_id: int) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", str(name or "").strip().lower()).strip("-")
    if len(base) < 2:
        base = f"item-{product_id}"
    return f"{base}-{product_id}"[:180]


def _merge_meta(product: Product, updates: dict) -> None:
    meta = product_meta(product)
    meta.update(updates)
    product.meta_json = json.dumps(meta, ensure_ascii=False)


def _price_currency(value) -> str:
    raw = str(value or "").strip().upper()
    if raw in {"USD", "$", "DOLLAR", "دولار"}:
        return "USD"
    return "IQD"


_STORE_CATEGORY_RULES = (
    ("غسالات صحون", ("غسالات صحون", "غسالة صحون", "غساله صحون", "جلاية", "جلايه", "غسالة اطباق", "غسالة أطباق", "غساله اطباق", "غساله أطباق", "dishwasher", "dish washer")),
    ("غسالات", ("غسالة ملابس", "غساله ملابس", "غسالات ملابس", "غسالة", "غساله", "غسالات", "نشافة", "نشافه", "دراير", "washer", "washing machine", "dryer")),
    ("شاشات", ("شاشة", "شاشه", "شاشات", "تلفزيون", "تلفاز", "سمارت", "smart tv", " tv", "led", "qled", "oled", "uhd", "4k")),
    ("ثلاجات", ("ثلاجة", "ثلاجه", "ثلاجات", "فريزر", "مجمدة", "مجمده", "براد", "تبريد", "refrigerator", "fridge", "freezer")),
    ("مكيفات", ("مكيف", "مكيفات", "سبلت", "سبليت", "تكييف", "air conditioner", "split", " ac ", "طن")),
    ("طباخات وأفران", ("طباخ", "طباخة", "طباخه", "فرن", "افران", "أفران", "غاز", "cooker", "oven", "stove")),
    ("أجهزة مطبخ", ("خلاط", "عجانة", "عجانه", "قلاية", "قلايه", "مايكرويف", "ميكروويف", "غلاية", "غلايه", "محمصة")),
    ("تنظيف", ("مكنسة", "مكنسه", "مكنسات", "بخار", "تنظيف", "vacuum")),
)


def _canonical_store_category(*values: str) -> str:
    text = " ".join(str(value or "").strip() for value in values if str(value or "").strip())
    folded = text.lower()
    for label, keywords in _STORE_CATEGORY_RULES:
        if any(keyword.lower() in folded for keyword in keywords):
            return label
    raw = str(values[0] if values else "").strip()
    if not raw or len(raw) > 40:
        return ""
    if re.search(r"\d|موديل|model|كيلو|kg|بوصة|انج|انش|سمارت", raw, flags=re.IGNORECASE):
        return ""
    return raw[:120]


def _store_product_image_data_url(url: str) -> str | None:
    raw = str(url or "").strip()
    match = re.match(r"^data:(image/(?:jpeg|jpg|png|webp|gif));base64,(.+)$", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    content_type = match.group(1).lower()
    ext = IMAGE_EXTENSIONS.get(content_type)
    if not ext:
        return None
    try:
        payload = re.sub(r"\s+", "", match.group(2))
        data = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None
    if not data or len(data) > 8 * 1024 * 1024:
        return None
    digest = hashlib.sha256(data).hexdigest()[:24]
    upload_folder = os.path.join(current_app.root_path, "static", "uploads", "products")
    os.makedirs(upload_folder, exist_ok=True)
    filename = f"store_api_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{digest}{ext}"
    path = os.path.join(upload_folder, filename)
    if not os.path.exists(path):
        with open(path, "wb") as handle:
            handle.write(data)
    return f"/static/uploads/products/{filename}"


def _store_remote_product_image(url: str) -> str | None:
    """Download a remote product image into static/uploads/products and return its public path."""
    raw = str(url or "").strip()
    if raw.lower().startswith("data:image/"):
        return _store_product_image_data_url(raw)
    if not raw.lower().startswith(("https://", "http://")):
        return raw[:512] or None
    try:
        parsed = urlparse(raw)
        if not parsed.netloc:
            return None
        response = requests.get(
            raw,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            stream=True,
        )
        response.raise_for_status()
        content_type = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        ext = IMAGE_EXTENSIONS.get(content_type)
        if not ext:
            path_ext = os.path.splitext(parsed.path)[1].lower()
            ext = path_ext if path_ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ""
        if not ext:
            return raw[:512]

        limit = 8 * 1024 * 1024
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                return raw[:512]
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            return raw[:512]

        digest = hashlib.sha256(data).hexdigest()[:24]
        upload_folder = os.path.join(current_app.root_path, "static", "uploads", "products")
        os.makedirs(upload_folder, exist_ok=True)
        filename = f"store_api_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{digest}{ext}"
        path = os.path.join(upload_folder, filename)
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(data)
        return f"/static/uploads/products/{filename}"
    except Exception:
        return raw[:512]


def _store_remote_product_gallery(urls: list) -> list[str]:
    saved: list[str] = []
    for item in urls[:8]:
        raw = str(item or "").strip()
        if not raw:
            continue
        saved_url = _store_remote_product_image(raw)
        if raw.lower().startswith("data:image/") and not str(saved_url or "").startswith("/static/"):
            raise StoreControlError("تعذر حفظ صورة المعرض المولّدة")
        if saved_url and saved_url not in saved:
            saved.append(saved_url)
    return saved


def _static_media_path(url: str) -> str | None:
    raw = str(url or "").strip()
    if raw.startswith("/static/"):
        relative = raw[len("/static/"):].lstrip("/")
    elif raw.startswith("uploads/"):
        relative = raw
    else:
        return None
    if not relative or ".." in relative.split("/"):
        return None
    return relative[:500]


def _saved_product_images(product: Product) -> list[str]:
    meta = product_meta(product)
    urls: list[str] = []
    if product.image_url:
        urls.append(str(product.image_url))
    gallery = meta.get("gallery")
    if isinstance(gallery, list):
        urls.extend(str(item or "") for item in gallery)
    paths: list[str] = []
    for url in urls:
        relative = _static_media_path(url)
        if relative and relative not in paths:
            paths.append(relative)
    return paths


def _replace_installment_images(product: Product) -> None:
    """The shop page shows installment media before the inventory image."""
    from modules.installments.models import InstallmentProductMedia

    item = InstallmentProduct.query.filter_by(product_id=product.id).first()
    paths = _saved_product_images(product)
    if item is None or not paths:
        return
    for media in list(item.media):
        if media.media_type == "image":
            db.session.delete(media)
    db.session.flush()
    mime_for = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    static_root = current_app.static_folder or ""
    for index, relative in enumerate(paths[:8]):
        extension = os.path.splitext(relative)[1].lower()
        full_path = os.path.join(static_root, relative.replace("/", os.sep))
        try:
            size = os.path.getsize(full_path)
        except OSError:
            size = 1
        db.session.add(
            InstallmentProductMedia(
                tenant_id=item.tenant_id,
                installment_product_id=item.id,
                media_type="image",
                file_path=relative,
                original_name=(os.path.basename(relative) or "image")[:255],
                mime_type=mime_for.get(extension, "image/jpeg"),
                size_bytes=max(1, int(size)),
                is_main=index == 0,
                sort_order=index,
            )
        )


def _sync_installment(product: Product, *, visible: bool | None = None, featured: bool | None = None) -> None:
    item = InstallmentProduct.query.filter_by(product_id=product.id).first()
    if item is None:
        if not visible or not has_shared_installment_catalog():
            return
        tenant_id = _tenant_id()
        if tenant_id is None:
            raise StoreControlError("لا توجد شركة لربط المنتج بالمتجر", 400, "tenant_required")
        item = InstallmentProduct(
            tenant_id=tenant_id,
            product_id=product.id,
            title=str(product.name or "")[:180],
            slug=_slug(product.name, product.id),
            short_description=(product.description or "")[:500] or None,
            full_description=product.description,
            cash_price=int(product.sale_price or 0),
            category=(product.catalog_category or "")[:120] or None,
            status="published",
            featured=bool(featured),
        )
        db.session.add(item)
        return
    item.title = str(product.name or item.title)[:180]
    item.cash_price = int(product.sale_price or 0)
    item.short_description = (product.description or "")[:500] or item.short_description
    item.full_description = product.description or item.full_description
    if product.catalog_category:
        item.category = str(product.catalog_category)[:120]
    if visible is True:
        item.status = "published"
    elif visible is False:
        item.status = "disabled"
    if featured is not None:
        item.featured = bool(featured)


def sync_product_publication(product: Product, *, visible: bool) -> None:
    """Publish an explicitly enabled inventory product in the existing catalogue.

    Hiding the cash-store flag must not disable a separately published installment item.
    Existing catalogue copy, prices, media and plans stay intact. The caller commits.
    """
    if not visible:
        return
    item = InstallmentProduct.query.filter_by(product_id=product.id).first()
    if item is None:
        _sync_installment(product, visible=visible)
    else:
        item.status = "published"


def _managed_card(product: Product, tenant_slug: str, *, currency: str) -> dict:
    linked = InstallmentProduct.query.filter_by(product_id=product.id).first()
    catalog_item = linked if linked is not None and linked.status == "published" else None
    meta = product_meta(product)
    card = public_product(
        product_card(product, tenant_slug, catalog_item=catalog_item),
        currency=currency,
    )
    card["store_visible"] = cash_store_product_is_visible(product)
    card["active"] = bool(product.active)
    card["featured"] = bool(linked.featured) if linked is not None else False
    card["source_url"] = str(meta.get("source_url") or "").strip()
    card["source_website"] = str(meta.get("source_website") or "").strip()
    card["external_id"] = str(meta.get("external_id") or "").strip()
    return card


def list_managed_products(tenant_slug: str, *, q: str = "", page: int = 1, per_page: int = 24) -> dict:
    query = Product.query.filter(or_(Product.barcode.is_(None), ~Product.barcode.in_(SERVICE_BARCODES)))
    q_norm = str(q or "").strip()
    if q_norm:
        like = f"%{q_norm}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.description.ilike(like)))
    query = query.order_by(Product.id.desc())
    total = query.count()
    page = max(1, int(page or 1))
    per_page = min(100, max(1, int(per_page or 24)))
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    profile = store_profile(tenant_slug)
    return {
        "store": profile,
        "products": [_managed_card(row, tenant_slug, currency=profile["currency"]) for row in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_more": page * per_page < total,
        "include_hidden": True,
    }


def get_managed_product(tenant_slug: str, product_id: int) -> dict | None:
    product = db.session.get(Product, int(product_id))
    if product is None or product.barcode in SERVICE_BARCODES:
        return None
    return _managed_card(product, tenant_slug, currency=store_profile(tenant_slug)["currency"])


def create_product(tenant_slug: str, data: dict) -> dict:
    name = str(data.get("name") or "").strip()
    if len(name) < 2:
        raise StoreControlError("اسم المنتج مطلوب")
    if "price" not in data and "sale_price" not in data:
        raise StoreControlError("سعر البيع مطلوب")
    price = safe_int(data.get("price", data.get("sale_price")), -1)
    if price < 0:
        raise StoreControlError("سعر البيع غير صالح")
    cost = safe_int(data.get("cost", data.get("buy_price")), 0)
    if cost < 0:
        raise StoreControlError("التكلفة غير صالحة")
    visible = bool(data.get("store_visible", data.get("visible", True)))
    quantity = max(0, safe_int(data.get("quantity", data.get("stock")), 0))
    branch_id = _default_branch_id()
    raw_image = str(
        data.get("image_data_url")
        or data.get("image_source_url")
        or data.get("source_image_url")
        or data.get("image_url")
        or ""
    ).strip()
    image_url = _store_remote_product_image(raw_image)
    if raw_image.lower().startswith("data:image/") and not str(image_url or "").startswith("/static/"):
        raise StoreControlError("تعذر حفظ صورة المنتج المولّدة")
    product = Product(
        name=name[:150],
        sku=str(data.get("sku") or "").strip()[:100] or None,
        buy_price=cost,
        sale_price=price,
        quantity=0,
        active=True,
        store_visible=visible,
        description=str(data.get("description") or "").strip() or None,
        image_url=image_url,
        branch_id=branch_id,
        tenant_id=_tenant_id(),
    )
    meta = {}
    category = _canonical_store_category(data.get("category"), name, data.get("description"))
    if category:
        meta["category"] = category[:120]
    for key in ("source_url", "source_website", "external_id"):
        value = str(data.get(key) or "").strip()
        if value:
            meta[key] = value[:512 if key == "source_url" else 160]
    if data.get("old_price") not in (None, ""):
        meta["old_price"] = max(0, safe_int(data.get("old_price"), 0))
    if any(key in data for key in ("currency", "price_currency")):
        meta["price_currency"] = _price_currency(data.get("currency", data.get("price_currency")))
    data_gallery = data.get("gallery_data_urls")
    source_gallery = data.get("gallery_source_urls")
    gallery = data.get("gallery")
    if isinstance(data_gallery, list):
        saved_gallery = _store_remote_product_gallery(data_gallery)
        if saved_gallery:
            meta["gallery"] = saved_gallery
            if not product.image_url:
                product.image_url = saved_gallery[0]
    elif isinstance(source_gallery, list):
        saved_gallery = _store_remote_product_gallery(source_gallery)
        if saved_gallery:
            meta["gallery"] = saved_gallery
            if not product.image_url:
                product.image_url = saved_gallery[0]
    elif isinstance(gallery, list):
        saved_gallery = _store_remote_product_gallery(gallery)
        if saved_gallery:
            meta["gallery"] = saved_gallery
            if not product.image_url:
                product.image_url = saved_gallery[0]
    if meta:
        product.meta_json = json.dumps(meta, ensure_ascii=False)
    db.session.add(product)
    db.session.flush()
    if quantity and branch_id:
        from utils.branch_stock_service import adjust_branch_stock

        adjust_branch_stock(branch_id, product.id, quantity)
    _sync_installment(product, visible=visible, featured=bool(data.get("featured")) if "featured" in data else None)
    if image_url or any(key in data for key in ("gallery", "gallery_source_urls", "gallery_data_urls")):
        _replace_installment_images(product)
    db.session.commit()
    return {"product": get_managed_product(tenant_slug, product.id)}


def update_product(tenant_slug: str, product_id: int, data: dict) -> dict:
    product = db.session.get(Product, int(product_id))
    if product is None or product.barcode in SERVICE_BARCODES:
        raise StoreControlError("المنتج غير موجود", 404, "not_found")
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if len(name) < 2:
            raise StoreControlError("اسم المنتج غير صالح")
        product.name = name[:150]
    if "price" in data or "sale_price" in data:
        price = safe_int(data.get("price", data.get("sale_price")), -1)
        if price < 0:
            raise StoreControlError("سعر البيع غير صالح")
        product.sale_price = price
    if "description" in data:
        product.description = str(data.get("description") or "").strip() or None
    if "sku" in data:
        product.sku = str(data.get("sku") or "").strip()[:100] or None
    images_touched = any(
        key in data
        for key in (
            "image_url",
            "image_source_url",
            "source_image_url",
            "image_data_url",
            "gallery",
            "gallery_source_urls",
            "gallery_data_urls",
        )
    )
    if any(key in data for key in ("image_url", "image_source_url", "source_image_url", "image_data_url")):
        raw_image = str(
            data.get("image_data_url")
            or data.get("image_source_url")
            or data.get("source_image_url")
            or data.get("image_url")
            or ""
        ).strip()
        saved_image = _store_remote_product_image(raw_image)
        if raw_image.lower().startswith("data:image/") and not str(saved_image or "").startswith("/static/"):
            raise StoreControlError("تعذر حفظ صورة المنتج المولّدة")
        if saved_image:
            product.image_url = saved_image
    if "active" in data:
        product.active = bool(data.get("active"))
    visible = None
    if "store_visible" in data or "visible" in data:
        visible = bool(data.get("store_visible", data.get("visible")))
        product.store_visible = visible
    meta_updates = {}
    if "category" in data:
        meta_updates["category"] = _canonical_store_category(data.get("category"), product.name, product.description)[:120]
    if "old_price" in data:
        meta_updates["old_price"] = max(0, safe_int(data.get("old_price"), 0))
    if "currency" in data or "price_currency" in data:
        meta_updates["price_currency"] = _price_currency(data.get("currency", data.get("price_currency")))
    if "brand" in data:
        meta_updates["brand"] = str(data.get("brand") or "").strip()[:120]
    for key in ("source_url", "source_website", "external_id"):
        if key in data:
            meta_updates[key] = str(data.get(key) or "").strip()[:512 if key == "source_url" else 160]
    if "gallery" in data or "gallery_source_urls" in data or "gallery_data_urls" in data:
        gallery = (
            data.get("gallery_data_urls")
            if "gallery_data_urls" in data
            else data.get("gallery_source_urls")
            if "gallery_source_urls" in data
            else data.get("gallery")
        )
        if not isinstance(gallery, list):
            raise StoreControlError("معرض الصور يجب أن يكون قائمة")
        urls = _store_remote_product_gallery(gallery)
        meta_updates["gallery"] = urls
        if urls and not any(key in data for key in ("image_url", "image_source_url", "source_image_url", "image_data_url")):
            product.image_url = urls[0]
    if "specs" in data:
        specs = data.get("specs")
        if not isinstance(specs, list):
            raise StoreControlError("المواصفات يجب أن تكون قائمة")
        clean = []
        for row in specs[:30]:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()[:48] or "مواصفة"
            value = str(row.get("value") or "").strip()[:200]
            if value:
                clean.append({"label": label, "value": value})
        meta_updates["specs_items"] = clean
    if meta_updates:
        _merge_meta(product, meta_updates)
    if "quantity" in data or "stock" in data:
        target = safe_int(data.get("quantity", data.get("stock")), -1)
        if target < 0:
            raise StoreControlError("الكمية غير صالحة")
        branch_id = product.branch_id or _default_branch_id()
        if branch_id:
            from utils.branch_stock_service import adjust_branch_stock, get_branch_stock

            current = int(get_branch_stock(branch_id, product.id) or 0)
            delta = target - current
            if delta:
                adjust_branch_stock(branch_id, product.id, delta)
        else:
            product.quantity = target
    featured = bool(data.get("featured")) if "featured" in data else None
    _sync_installment(product, visible=visible, featured=featured)
    if images_touched:
        _replace_installment_images(product)
    db.session.commit()
    return {"product": get_managed_product(tenant_slug, product.id)}


def bulk_visibility(tenant_slug: str, data: dict) -> dict:
    raw_ids = data.get("ids") if "ids" in data else data.get("product_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise StoreControlError("أرسل قائمة ids")
    visible = bool(data.get("store_visible", data.get("visible", True)))
    updated: list[int] = []
    missing: list[int] = []
    for raw in raw_ids[:100]:
        product_id = safe_int(raw, 0)
        if product_id <= 0:
            continue
        try:
            update_product(tenant_slug, product_id, {"store_visible": visible})
        except StoreControlError as exc:
            if exc.status == 404:
                missing.append(product_id)
                continue
            raise
        updated.append(product_id)
    return {"updated": updated, "missing": missing, "store_visible": visible}


def rename_category(tenant_slug: str, data: dict) -> dict:
    source = str(data.get("from") or "").strip()
    target = str(data.get("to") or "").strip()
    if not source or not target:
        raise StoreControlError("أرسل from و to")
    if source == target:
        raise StoreControlError("القسم الجديد مطابق للقديم")
    renamed = 0
    products = Product.query.filter(or_(Product.barcode.is_(None), ~Product.barcode.in_(SERVICE_BARCODES))).all()
    for product in products:
        meta = product_meta(product)
        current = str(meta.get("category") or meta.get("store_badge") or product.catalog_category or "").strip()
        linked = InstallmentProduct.query.filter_by(product_id=product.id).first()
        linked_category = str(linked.category or "").strip() if linked is not None else ""
        if current != source and linked_category != source:
            continue
        if current == source:
            _merge_meta(product, {"category": target[:120]})
        if linked is not None and linked_category == source:
            linked.category = target[:120]
        renamed += 1
    db.session.commit()
    return {"renamed": renamed, "category": target[:120]}


def _store_customer_ids():
    return (
        db.session.query(Invoice.customer_id)
        .filter(Invoice.note.ilike(f"{STORE_NOTE_PREFIX}%"), Invoice.customer_id.isnot(None))
        .distinct()
    )


def _customer_payload(customer: Customer) -> dict:
    return {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "city": customer.city,
        "address": customer.address,
        "notes": customer.notes,
    }


def list_customers(*, q: str = "", page: int = 1, per_page: int = 24) -> dict:
    query = Customer.query.filter(Customer.id.in_(_store_customer_ids()))
    q_norm = str(q or "").strip()
    if q_norm:
        like = f"%{q_norm}%"
        query = query.filter(or_(Customer.name.ilike(like), Customer.phone.ilike(like), Customer.city.ilike(like)))
    total = query.count()
    page = max(1, int(page or 1))
    per_page = min(100, max(1, int(per_page or 24)))
    rows = query.order_by(Customer.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "customers": [_customer_payload(row) for row in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_more": page * per_page < total,
    }


def update_customer(customer_id: int, data: dict) -> dict:
    customer = db.session.get(Customer, int(customer_id))
    if customer is None or customer.id not in {row[0] for row in _store_customer_ids().all()}:
        raise StoreControlError("الزبون غير موجود في المتجر", 404, "not_found")
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if len(name) < 2:
            raise StoreControlError("اسم الزبون غير صالح")
        customer.name = name[:150]
        Invoice.query.filter_by(customer_id=customer.id).filter(Invoice.note.ilike(f"{STORE_NOTE_PREFIX}%")).update(
            {Invoice.customer_name: customer.name},
            synchronize_session=False,
        )
    if "phone" in data:
        phone = str(data.get("phone") or "").strip()
        if len(re.sub(r"\D+", "", phone)) < 8:
            raise StoreControlError("رقم الهاتف غير صالح")
        customer.phone = phone[:20]
    if "city" in data:
        customer.city = str(data.get("city") or "").strip()[:100] or None
    if "address" in data:
        customer.address = str(data.get("address") or "").strip()[:255] or None
    if "notes" in data:
        customer.notes = str(data.get("notes") or "").strip()[:1000] or None
    db.session.commit()
    return {"customer": _customer_payload(customer)}


def unpublish_product(tenant_slug: str, product_id: int) -> dict:
    payload = update_product(tenant_slug, product_id, {"store_visible": False})
    payload["removed_from_store"] = True
    return payload


def _store_orders():
    return Invoice.query.filter(Invoice.note.ilike(f"{STORE_NOTE_PREFIX}%")).order_by(Invoice.id.desc())


def _order_payload(invoice: Invoice) -> dict:
    customer = db.session.get(Customer, invoice.customer_id) if invoice.customer_id else None
    items = (
        OrderItem.query.filter_by(invoice_id=invoice.id)
        .filter(~OrderItem.product_name.in_(["خصم كوبون"]))
        .all()
    )
    return {
        "id": invoice.id,
        "status": invoice.status,
        "payment_status": invoice.payment_status,
        "total": int(invoice.total or 0),
        "paid_amount": int(invoice.paid_amount or 0),
        "customer_name": invoice.customer_name,
        "phone": getattr(customer, "phone", None),
        "city": getattr(customer, "city", None),
        "address": getattr(customer, "address", None),
        "note": invoice.note,
        "created_at": invoice.created_at.isoformat() + "Z" if invoice.created_at else None,
        "items": [
            {
                "product_id": row.product_id,
                "name": row.product_name,
                "variant_color": row.variant_color or "",
                "display_name": row.display_name,
                "quantity": int(row.quantity or 0),
                "price": int(row.price or 0),
                "total": int(row.total or 0),
            }
            for row in items
            if row.product_name != "خصم كوبون"
        ],
    }


def list_orders(*, page: int = 1, per_page: int = 24, status: str = "") -> dict:
    query = _store_orders()
    if status:
        if status not in ORDER_STATUSES:
            raise StoreControlError("حالة الطلب غير معروفة")
        query = query.filter(Invoice.status == status)
    total = query.count()
    page = max(1, int(page or 1))
    per_page = min(100, max(1, int(per_page or 24)))
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "orders": [_order_payload(row) for row in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_more": page * per_page < total,
    }


def get_order(order_id: int) -> dict | None:
    invoice = _store_orders().filter(Invoice.id == int(order_id)).first()
    if invoice is None:
        return None
    return _order_payload(invoice)


def update_order(order_id: int, data: dict) -> dict:
    invoice = _store_orders().filter(Invoice.id == int(order_id)).first()
    if invoice is None:
        raise StoreControlError("الطلب غير موجود في المتجر", 404, "not_found")
    if "status" in data:
        status = str(data.get("status") or "").strip()
        if status not in ORDER_STATUSES:
            raise StoreControlError("حالة الطلب غير معروفة")
        invoice.status = status
    if "payment_status" in data:
        payment = str(data.get("payment_status") or "").strip()
        if payment not in PAYMENT_STATUSES:
            raise StoreControlError("حالة الدفع غير معروفة")
        invoice.payment_status = payment
    if "note" in data:
        extra = str(data.get("note") or "").strip()
        invoice.note = f"{STORE_NOTE_PREFIX} | {extra}" if extra else STORE_NOTE_PREFIX
    db.session.commit()
    return {"order": _order_payload(invoice)}


def _flag_snapshot(flags: dict) -> dict:
    design = StorefrontSettingsService().design_settings()
    shipping, default_fee = StorefrontSettingsService().shipping_config()
    coupon = StorefrontSettingsService().coupon_config()
    return {
        "store_name": design.get("store_name"),
        "logo_url": design.get("logo_url"),
        "whatsapp": design.get("whatsapp"),
        "primary_color": design.get("primary_color"),
        "shipping_color": design.get("shipping_color"),
        "card_style": design.get("card_style"),
        "theme_preset": design.get("preset"),
        "theme_mode": design.get("theme_mode"),
        "hero_title": design.get("hero_title"),
        "hero_subtitle": design.get("hero_subtitle"),
        "hero_mode": design.get("hero_mode"),
        "hero_slides": flags.get("storefront_hero_slides") or [],
        "product_sections": flags.get("storefront_product_sections")
        if isinstance(flags.get("storefront_product_sections"), list)
        else (design.get("product_sections") or []),
        "shipping_default_fee": default_fee,
        "shipping_by_city": shipping,
        "coupon": coupon,
        "ai_assistant_enabled": design.get("ai_assistant_enabled"),
        "ai_assistant_name": design.get("ai_assistant_name"),
        "ai_assistant_greeting": design.get("ai_assistant_greeting"),
    }


def read_settings() -> dict:
    return _flag_snapshot(_settings().get_ui_flags())


def update_settings(data: dict) -> dict:
    row = _settings()
    flags = row.get_ui_flags()
    if "store_name" in data:
        flags["storefront_store_name"] = str(data.get("store_name") or "").strip()[:150] or "متجر المنتجات"
    if "logo_url" in data:
        flags["storefront_logo_url"] = str(data.get("logo_url") or "").strip()[:512]
    if "whatsapp" in data:
        flags["storefront_whatsapp"] = str(data.get("whatsapp") or "").strip()[:40]
    if "primary_color" in data:
        flags["storefront_primary_color"] = safe_hex_color(data.get("primary_color"), "#4f8cff")
    if "shipping_color" in data:
        flags["storefront_shipping_color"] = safe_hex_color(data.get("shipping_color"), "#10b981")
    if "card_style" in data:
        style = str(data.get("card_style") or "").strip()
        if style not in CARD_STYLES:
            raise StoreControlError("شكل البطاقة غير معروف")
        flags["storefront_product_card_style"] = style
    if "theme_preset" in data:
        preset = str(data.get("theme_preset") or "").strip()
        if preset not in THEME_PRESETS:
            raise StoreControlError("قالب المتجر غير معروف")
        flags["storefront_theme_preset"] = preset
    if "theme_mode" in data:
        mode = str(data.get("theme_mode") or "").strip().lower()
        if mode not in THEME_MODES:
            raise StoreControlError("وضع الألوان غير معروف")
        flags["storefront_theme_mode"] = mode
    if "hero_title" in data:
        flags["storefront_hero_title"] = str(data.get("hero_title") or "").strip()[:180]
    if "hero_subtitle" in data:
        flags["storefront_hero_subtitle"] = str(data.get("hero_subtitle") or "").strip()[:400]
    if "hero_mode" in data:
        mode = str(data.get("hero_mode") or "").strip().lower()
        if mode not in HERO_MODES:
            raise StoreControlError("وضع الواجهة غير معروف")
        flags["storefront_hero_mode"] = mode
    if "product_sections" in data:
        sections = data.get("product_sections")
        if not isinstance(sections, list):
            raise StoreControlError("أقسام الصفحة يجب أن تكون قائمة")
        from modules.storefront.services.store_layout_service import normalize_section

        flags["storefront_product_sections"] = [
            normalize_section(row, sort_order=index)
            for index, row in enumerate(sections[:20])
            if isinstance(row, dict)
        ]
    if "hero_slides" in data:
        slides = data.get("hero_slides")
        if not isinstance(slides, list):
            raise StoreControlError("شرائح الواجهة يجب أن تكون قائمة")
        flags["storefront_hero_slides"] = [row for row in slides if isinstance(row, dict)][:12]
    if "shipping_default_fee" in data:
        flags["storefront_shipping_default_fee"] = max(0, safe_int(data.get("shipping_default_fee"), 0))
    if "shipping_by_city" in data:
        cities = data.get("shipping_by_city")
        if not isinstance(cities, dict):
            raise StoreControlError("أسعار الشحن يجب أن تكون كائناً")
        flags["storefront_shipping_by_city"] = {
            str(city).strip(): max(0, safe_int(fee, 0))
            for city, fee in cities.items()
            if str(city).strip()
        }
    if "coupon_code" in data:
        flags["storefront_coupon_code"] = str(data.get("coupon_code") or "").strip().upper()[:40]
    if "coupon_type" in data:
        ctype = str(data.get("coupon_type") or "").strip().lower()
        if ctype not in {"percent", "fixed"}:
            raise StoreControlError("نوع الكوبون غير معروف")
        flags["storefront_coupon_type"] = ctype
    if "coupon_value" in data:
        flags["storefront_coupon_value"] = max(0, safe_int(data.get("coupon_value"), 0))
    if "ai_assistant_enabled" in data:
        flags["storefront_ai_assistant_enabled"] = bool(data.get("ai_assistant_enabled"))
    if "ai_assistant_name" in data:
        flags["storefront_ai_assistant_name"] = str(data.get("ai_assistant_name") or "").strip()[:80] or "مساعد المتجر"
    if "ai_assistant_greeting" in data:
        flags["storefront_ai_assistant_greeting"] = str(data.get("ai_assistant_greeting") or "").strip()[:400]
    row.set_ui_flags(flags)
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return {"settings": _flag_snapshot(row.get_ui_flags())}


def public_or_managed(tenant_slug: str, product_id: int, *, include_hidden: bool):
    if include_hidden:
        return get_managed_product(tenant_slug, product_id)
    return get_public_product(tenant_slug, product_id)
