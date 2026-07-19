from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

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


def product_gallery(product: Product, meta: dict, *, max_images: int = 5) -> list[str]:
    """Main image + up to 4 extras (5 total) for the product page."""
    gallery: list[str] = []
    if product.image_url:
        gallery.append(str(product.image_url))
    for key in ("gallery", "images", "photos"):
        value = meta.get(key)
        if isinstance(value, list):
            gallery.extend(str(item or "").strip() for item in value)
    return _unique_strings(gallery)[: max(1, int(max_images or 5))]


def product_specs(meta: dict) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    raw_items = meta.get("specs_items")
    if isinstance(raw_items, list):
        for row in raw_items:
            if not isinstance(row, dict):
                continue
            key = str(row.get("label") or "").strip() or "مواصفة"
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
                key, value = "مواصفة", row
            key = key.strip()
            value = value.strip()
            if value:
                specs.append({"label": key or "مواصفة", "value": value})
    return specs


def product_badge(meta: dict) -> str:
    return str(meta.get("store_badge") or meta.get("category") or "").strip()


def product_category(meta: dict) -> str:
    return str(meta.get("category") or meta.get("store_badge") or "").strip()


def product_brand(meta: dict) -> str:
    return str(meta.get("brand") or "").strip()


def product_old_price(meta: dict) -> int:
    for key in ("compare_at_price", "original_price", "old_price"):
        if key not in meta:
            continue
        raw = meta.get(key)
        if raw is None or raw == "":
            continue
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            continue
    return 0


def product_discount_percent(price: int, old_price: int) -> int:
    if old_price <= 0 or old_price <= price:
        return 0
    return int(round((old_price - price) / old_price * 100))


def product_is_new(product: Product, badge: str) -> bool:
    if "جديد" in str(badge or ""):
        return True
    created = getattr(product, "created_at", None)
    if not created:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (now - created) <= timedelta(days=30)


def product_card(product: Product, shop_slug: str) -> dict:
    meta = product_meta(product)
    gallery = product_gallery(product, meta)
    specs = product_specs(meta)
    badge = product_badge(meta)
    price = int(product.sale_price or 0)
    old_price = product_old_price(meta)
    discount_percent = product_discount_percent(price, old_price)
    category = product_category(meta)
    brand = product_brand(meta)
    model = str(meta.get("model") or "").strip()
    sku = str(product.sku or "").strip()
    is_new = product_is_new(product, badge)
    if shop_slug:
        detail = url_for("storefront.product_detail", tenant_slug=shop_slug, product_id=product.id)
    else:
        detail = url_for("storefront.product_detail_legacy", product_id=product.id)
    return {
        "id": product.id,
        "name": product.name,
        "price": price,
        "old_price": old_price,
        "discount_percent": discount_percent,
        "category": category,
        "brand": brand,
        "model": model,
        "sku": sku,
        "is_new": is_new,
        "description": str(product.description or "").strip(),
        "image_url": gallery[0] if gallery else "",
        "gallery": gallery,
        "video_url": str(meta.get("video_url") or "").strip(),
        "specs": specs,
        "short_specs": " | ".join(f"{item['label']}: {item['value']}" for item in specs[:3]),
        "badge": badge,
        "stock": int(product.quantity or 0),
        "is_available": bool(product.active and product.store_visible and int(product.quantity or 0) > 0),
        "url": detail,
    }


def build_hero_slides(cards: list[dict], store_design: dict, *, limit: int = 4) -> list[dict]:
    """Build hero carousel slides from real catalog data — no mock content."""
    hero_mode = str(store_design.get("hero_mode") or "auto").strip().lower()
    if hero_mode not in {"auto", "manual", "both"}:
        hero_mode = "auto"
    manual_raw = store_design.get("hero_slides")
    manual_slides = manual_raw if isinstance(manual_raw, list) else []

    available = [c for c in cards if c.get("image_url") and c.get("is_available") is not False]
    spotlight_ids: set[int] = set()
    slides: list[dict] = []

    def _safe_str(v) -> str:
        return str(v or "").strip()

    def _safe_href(v) -> str:
        href = _safe_str(v)
        if not href:
            return "#luxProducts"
        if href.startswith("#"):
            return href
        # allow internal shop links or absolute URLs
        return href

    def _manual_to_slide(row: dict) -> dict | None:
        if not isinstance(row, dict):
            return None
        title = _safe_str(row.get("title")) or _safe_str(store_design.get("store_name")) or "متجر"
        kicker = _safe_str(row.get("kicker")) or _safe_str(store_design.get("store_tagline")) or "عروض مميزة"
        subtitle = _safe_str(row.get("subtitle"))
        cta_text = _safe_str(row.get("cta_text")) or "تسوق الآن"
        cta_href = _safe_href(row.get("cta_href"))
        image_url = _safe_str(row.get("image_url"))
        if not image_url:
            return None
        return {
            "layout": "spotlight",
            "kicker": kicker,
            "title": title,
            "subtitle": subtitle,
            "features": [s.strip() for s in _safe_str(row.get("features")).split("|") if s.strip()] if row.get("features") else [],
            "cta_text": cta_text,
            "cta_href": cta_href,
            "spotlight": {
                "image_url": image_url,
                "name": title,
                "price": 0,
                "old_price": 0,
                "discount_percent": 0,
                "is_new": False,
            },
            "products": [],
        }

    if hero_mode in {"manual", "both"}:
        for row in manual_slides:
            if len(slides) >= limit:
                break
            slide = _manual_to_slide(row)
            if slide:
                slides.append(slide)

    if hero_mode == "manual":
        if not slides:
            # fallback to brand slide if no manual configured
            hero_mode = "auto"
        else:
            return slides[:limit]

    brand_products = available[:4]
    slides.append(
        {
            "layout": "mosaic",
            "kicker": str(store_design.get("store_tagline") or "ابتكار اليوم ... رفاهية تدوم").strip(),
            "title": str(store_design.get("hero_title") or store_design.get("store_name") or "ارتقِ بمنزلك").strip(),
            "subtitle": str(store_design.get("hero_subtitle") or "مع أحدث الأجهزة الذكية").strip(),
            "features": ["ضمان شامل", "توصيل آمن", "أصالة مضمونة"],
            "cta_text": "تسوق الآن",
            "cta_href": "#luxProducts",
            "products": brand_products,
            "logo_url": str(store_design.get("logo_url") or "").strip(),
            "store_name": str(store_design.get("store_name") or "").strip(),
        }
    )

    promos = sorted(
        [c for c in available if int(c.get("discount_percent") or 0) > 0],
        key=lambda c: int(c.get("discount_percent") or 0),
        reverse=True,
    )
    for product in promos:
        if len(slides) >= limit:
            break
        pid = int(product.get("id") or 0)
        if pid in spotlight_ids:
            continue
        spotlight_ids.add(pid)
        specs = [s.strip() for s in str(product.get("short_specs") or "").split(" | ") if s.strip()]
        slides.append(
            {
                "layout": "spotlight",
                "kicker": f"خصم {product['discount_percent']}%",
                "title": str(product.get("name") or "").strip(),
                "subtitle": str(product.get("category") or product.get("badge") or "").strip(),
                "features": specs[:3] or ["دفع عند الاستلام", "ضمان أصلي", "توصيل سريع"],
                "cta_text": "اطلب الآن",
                "cta_href": str(product.get("url") or "#luxProducts"),
                "spotlight": product,
                "products": [product],
            }
        )

    if len(slides) < limit:
        for product in [c for c in available if c.get("is_new")]:
            if len(slides) >= limit:
                break
            pid = int(product.get("id") or 0)
            if pid in spotlight_ids:
                continue
            spotlight_ids.add(pid)
            specs = [s.strip() for s in str(product.get("short_specs") or "").split(" | ") if s.strip()]
            slides.append(
                {
                    "layout": "spotlight",
                    "kicker": "وصل حديثاً",
                    "title": str(product.get("name") or "").strip(),
                    "subtitle": str(product.get("brand") or product.get("category") or "").strip(),
                    "features": specs[:3] or ["جديد في المتجر", "أصالة مضمونة", "دفع عند الاستلام"],
                    "cta_text": "عرض التفاصيل",
                    "cta_href": str(product.get("url") or "#luxProducts"),
                    "spotlight": product,
                    "products": [product],
                }
            )

    if len(slides) < 2 and len(available) > 1:
        extras = available[1:4]
        if extras:
            slides.append(
                {
                    "layout": "mosaic",
                    "kicker": "تشكيلة مختارة",
                    "title": str(store_design.get("store_name") or "أجهزة منزلية أصلية").strip(),
                    "subtitle": "تبريد، غسيل، وترفيه في مكان واحد",
                    "features": ["دفع عند الاستلام", "دعم عملاء متميز", "إرجاع سهل"],
                    "cta_text": "استكشف الأجهزة",
                    "cta_href": "#luxProducts",
                    "products": extras,
                    "logo_url": "",
                    "store_name": "",
                }
            )

    if not brand_products and slides:
        first = slides[0]
        if not first.get("products") and not first.get("logo_url"):
            first["logo_url"] = str(store_design.get("logo_url") or "").strip()
            first["store_name"] = str(store_design.get("store_name") or "").strip()

    return slides[:limit]
