"""Public catalog payloads for the store API."""

from __future__ import annotations

from flask import request, url_for

from modules.storefront.services import catalog_service as _catalog_paged

from models.product import Product
from models.system_settings import SystemSettings
from modules.storefront.services.catalog_service import (
    StorefrontCatalogService,
    cash_store_product_is_visible,
    has_shared_installment_catalog,
    published_installment_item,
)
from modules.storefront.services.product_presenter import product_card
from modules.storefront.services.settings_service import StorefrontSettingsService

_catalog = StorefrontCatalogService()
_settings = StorefrontSettingsService()

_PUBLIC_FIELDS = (
    "id",
    "name",
    "price",
    "old_price",
    "price_currency",
    "discount_percent",
    "category",
    "brand",
    "model",
    "sku",
    "description",
    "features",
    "image_url",
    "gallery",
    "video_url",
    "specs",
    "badge",
    "stock",
    "is_available",
    "url",
)


def absolute_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("//"):
        return request.scheme + ":" + raw
    base = request.host_url.rstrip("/")
    if not raw.startswith("/"):
        raw = "/" + raw
    return base + raw


def store_profile(tenant_slug: str) -> dict:
    design = _settings.design_settings()
    currency = "د.ع"
    try:
        settings = SystemSettings.get_settings()
        if settings and settings.default_currency:
            currency = str(settings.default_currency).strip() or currency
    except Exception:
        pass
    from modules.storefront.services.product_presenter import iqd_per_usd

    rate = float(iqd_per_usd())
    store_url = url_for("storefront.store_index", tenant_slug=tenant_slug, _external=True)
    api_base = request.host_url.rstrip("/") + "/api/v1/store"
    return {
        "name": design.get("store_name") or "متجر المنتجات",
        "url": store_url,
        "api_base_url": api_base,
        "currency": currency,
        "currencies": ["IQD", "USD"],
        "exchange_rate": rate,
        "logo_url": absolute_url(design.get("logo_url") or ""),
    }


def public_product(card: dict, *, currency: str) -> dict:
    item = {key: card.get(key) for key in _PUBLIC_FIELDS}
    code = "USD" if str(item.get("price_currency") or "").upper() == "USD" else "IQD"
    item["price_currency"] = code
    item["currency"] = "USD" if code == "USD" else currency
    item["image_url"] = absolute_url(item.get("image_url") or "")
    item["url"] = absolute_url(item.get("url") or "")
    item["video_url"] = absolute_url(item.get("video_url") or "") if str(item.get("video_url") or "").startswith("/") else (item.get("video_url") or "")
    gallery = item.get("gallery") or []
    item["gallery"] = [absolute_url(url) for url in gallery if str(url or "").strip()]
    item["price"] = int(item.get("price") or 0)
    item["stock"] = int(item.get("stock") or 0)
    item["is_available"] = bool(item.get("is_available"))
    item["has_options"] = bool(card.get("has_colors"))
    item["option_axes"] = card.get("option_axes") or ([] if not item["has_options"] else ["اللون"])
    item["variants"] = [{
        "id": row.get("id"), "name": row["name"], "attributes": row.get("attributes", {}),
        "price": int(row.get("sale_price", item["price"]) or 0),
        "stock": int(row.get("available_qty", row.get("qty", 0)) or 0),
        "is_available": int(row.get("available_qty", row.get("qty", 0)) or 0) > 0,
        "image_url": absolute_url(row.get("image_url") or card.get("image_url") or ""),
    } for row in card.get("colors", []) if row.get("active", True)]
    return item


def list_public_products(
    tenant_slug: str,
    *,
    q: str = "",
    category: str = "",
    sort: str = "latest",
    availability: str = "all",
    page: int = 1,
    per_page: int = 24,
) -> dict:
    profile = store_profile(tenant_slug)
    per_page = min(100, max(1, int(per_page or 24)))
    # one page from the database — the public API never builds cards for the whole catalogue
    result = _catalog_paged.list_page(
        tenant_slug,
        q=q,
        badge=category,
        sort=sort or "latest",
        availability=availability or "all",
        page=max(1, int(page or 1)),
        per_page=per_page,
        max_per_page=100,
    )
    window = result["cards"]
    currency = profile["currency"]
    return {
        "store": profile,
        "products": [public_product(card, currency=currency) for card in window],
        "categories": _catalog_paged.badges(tenant_slug),
        "page": result["page"],
        "per_page": per_page,
        "total": result["total"],
        "has_more": result["page"] < result["pages"],
    }


def get_public_product(tenant_slug: str, product_id: int) -> dict | None:
    product = db_get_product(product_id)
    if not cash_store_product_is_visible(product):
        return None
    catalog_item = published_installment_item(product_id) if has_shared_installment_catalog() else None
    profile = store_profile(tenant_slug)
    return public_product(
        product_card(product, tenant_slug, catalog_item=catalog_item),
        currency=profile["currency"],
    )


def list_categories(tenant_slug: str) -> list[str]:
    return _catalog_paged.badges(tenant_slug)


def db_get_product(product_id: int) -> Product | None:
    from extensions import db

    return db.session.get(Product, int(product_id))
