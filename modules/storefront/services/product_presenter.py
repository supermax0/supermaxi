from __future__ import annotations

import json

from flask import url_for

from models.product import Product


def product_meta(product: Product) -> dict:
    raw = (product.meta_json or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _unique_strings(values: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        s = str(value or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        items.append(s)
    return items


def product_gallery(product: Product, meta: dict) -> list[str]:
    gallery: list[str] = []
    if product.image_url:
        gallery.append(str(product.image_url))
    for key in ("gallery", "images", "photos"):
        value = meta.get(key)
        if isinstance(value, list):
            gallery.extend(str(item or "").strip() for item in value)
    return _unique_strings(gallery)


def product_specs(meta: dict) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    raw_items = meta.get("specs_items")
    if isinstance(raw_items, list):
        for row in raw_items:
            if not isinstance(row, dict):
                continue
            key = str(row.get("label") or "").strip() or "تفصيل"
            value = str(row.get("value") or "").strip()
            if value:
                specs.append({"label": key, "value": value})
    if specs:
        return specs

    specs_text = str(meta.get("specs_text") or "").strip()
    if specs_text:
        for line in specs_text.splitlines():
            row = line.strip(" -\t\r\n")
            if not row:
                continue
            if ":" in row:
                key, value = row.split(":", 1)
            elif " - " in row:
                key, value = row.split(" - ", 1)
            else:
                key, value = "تفصيل", row
            key = key.strip()
            value = value.strip()
            if value:
                specs.append({"label": key or "تفصيل", "value": value})
    return specs


def product_badge(meta: dict) -> str:
    return str(meta.get("store_badge") or meta.get("category") or "").strip()


def product_card(product: Product, shop_slug: str) -> dict:
    meta = product_meta(product)
    gallery = product_gallery(product, meta)
    specs = product_specs(meta)
    if shop_slug:
        detail = url_for("storefront.product_detail", tenant_slug=shop_slug, product_id=product.id)
    else:
        detail = url_for("storefront.product_detail_legacy", product_id=product.id)
    return {
        "id": product.id,
        "name": product.name,
        "price": int(product.sale_price or 0),
        "description": str(product.description or "").strip(),
        "image_url": gallery[0] if gallery else "",
        "gallery": gallery,
        "video_url": str(meta.get("video_url") or "").strip(),
        "specs": specs,
        "short_specs": " | ".join(f"{item['label']}: {item['value']}" for item in specs[:3]),
        "badge": product_badge(meta),
        "stock": int(product.quantity or 0),
        "is_available": bool(product.active and int(product.quantity or 0) > 0),
        "url": detail,
    }
