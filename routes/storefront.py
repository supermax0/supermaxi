from __future__ import annotations

import json

from flask import Blueprint, abort, render_template, url_for

from models.product import Product


storefront_bp = Blueprint("storefront", __name__, url_prefix="/shop")


def _product_meta(product: Product) -> dict:
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


def _product_gallery(product: Product, meta: dict) -> list[str]:
    gallery: list[str] = []
    if product.image_url:
        gallery.append(str(product.image_url))
    for key in ("gallery", "images", "photos"):
        value = meta.get(key)
        if isinstance(value, list):
            gallery.extend(str(item or "").strip() for item in value)
    return _unique_strings(gallery)


def _product_specs(meta: dict) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
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

    if specs:
        return specs

    for key, label in (
        ("brand", "العلامة"),
        ("category", "الصنف"),
        ("subcategory", "التصنيف الفرعي"),
        ("unit", "الوحدة"),
        ("warranty", "الضمان"),
        ("weight", "الوزن"),
        ("color", "اللون"),
        ("size", "القياس"),
        ("model", "الموديل"),
    ):
        value = str(meta.get(key) or "").strip()
        if value:
            specs.append({"label": label, "value": value})
    return specs


def _product_card(product: Product) -> dict:
    meta = _product_meta(product)
    gallery = _product_gallery(product, meta)
    return {
        "id": product.id,
        "name": product.name,
        "price": int(product.sale_price or 0),
        "description": str(product.description or "").strip(),
        "image_url": gallery[0] if gallery else "",
        "gallery": gallery,
        "video_url": str(meta.get("video_url") or "").strip(),
        "specs": _product_specs(meta),
        "short_specs": " | ".join(
            f"{item['label']}: {item['value']}" for item in _product_specs(meta)[:3]
        ),
        "badge": str(meta.get("store_badge") or meta.get("category") or "").strip(),
        "stock": int(product.quantity or 0),
        "is_available": bool(product.active and int(product.quantity or 0) > 0),
        "url": url_for("storefront.product_detail", product_id=product.id),
    }


@storefront_bp.route("/")
def store_index():
    products = (
        Product.query.filter(Product.active == True)  # noqa: E712
        .order_by(Product.id.desc())
        .all()
    )
    cards = [_product_card(product) for product in products]
    return render_template("storefront/index.html", products=cards)


@storefront_bp.route("/product/<int:product_id>")
def product_detail(product_id: int):
    product = Product.query.get_or_404(product_id)
    if not product.active:
        abort(404)
    card = _product_card(product)
    related = (
        Product.query.filter(Product.active == True, Product.id != product.id)  # noqa: E712
        .order_by(Product.id.desc())
        .limit(4)
        .all()
    )
    related_cards = [_product_card(item) for item in related]
    return render_template(
        "storefront/product_detail.html",
        product=card,
        related_products=related_cards,
    )
