from __future__ import annotations

import json
import re
from typing import Any

from flask import current_app, has_request_context, request, url_for

from models.product import Product
from modules.storefront.services.product_presenter import product_card, product_meta, product_specs

_AR_STOP = frozenset(
    {
        "هل",
        "ما",
        "في",
        "من",
        "على",
        "عن",
        "هذا",
        "هذه",
        "ذلك",
        "الي",
        "الى",
        "إلى",
        "مع",
        "قد",
        "تم",
        "كل",
        "أي",
        "اي",
        "كم",
    }
)


def _normalize_ar_digits(text: str) -> str:
    if not text:
        return ""
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return text.translate(trans)


def _product_match_blob(p: Product) -> str:
    parts: list[str] = [
        p.name or "",
        p.sku or "",
        p.barcode or "",
        str(p.sale_price or ""),
        str(p.quantity or ""),
        str(p.description or ""),
    ]
    meta = product_meta(p)
    for key in ("brand", "category", "size", "color", "unit", "model"):
        value = meta.get(key)
        if value is not None and str(value).strip():
            parts.append(str(value))
    return _normalize_ar_digits(" ".join(parts)).lower()


def _score_product_match(p: Product, query_blob: str) -> int:
    if not query_blob.strip():
        return 0
    hay = _product_match_blob(p)
    score = 0
    for word in re.findall(r"[\u0600-\u06ffa-z0-9]{2,}", query_blob):
        if word in _AR_STOP and len(word) <= 3:
            continue
        if len(word) >= 2 and word in hay:
            score += 2
    for number in re.findall(r"\d+", query_blob):
        if number in hay:
            score += 4
    return score


def _query_blob_from_message(message: str, history: list[dict[str, str]] | None = None) -> str:
    parts = [str(message or "")]
    for item in history or []:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            parts.append(content)
    return _normalize_ar_digits("\n".join(parts)).lower()


def _product_public_url(p: Product, shop_slug: str) -> str:
    if shop_slug:
        path = url_for("storefront.product_detail", tenant_slug=shop_slug, product_id=int(p.id))
    else:
        path = url_for("storefront.product_detail_legacy", product_id=int(p.id))
    if has_request_context():
        base = str(request.host_url or "").strip().rstrip("/")
        if base:
            return f"{base}{path}"
    base = str(current_app.config.get("BASE_URL") or "").strip().rstrip("/")
    return f"{base}{path}" if base else path


def _product_catalog_lines(p: Product, shop_slug: str) -> list[str]:
    meta = product_meta(p)
    extra_parts: list[str] = []
    for key in ("brand", "unit", "category", "shelf", "color", "size"):
        value = meta.get(key)
        if value is not None and str(value).strip():
            extra_parts.append(f"{key}: {value}")
    extra = f" | {' | '.join(extra_parts)}" if extra_parts else ""
    specs = product_specs(meta)
    specs_preview = " | ".join(f"{item['label']}: {item['value']}" for item in specs[:4])

    lines = [
        (
            f"- المنتج: {p.name}"
            f" | SKU: {p.sku or '-'}"
            f" | سعر البيع: {p.sale_price} د.ع"
            f" | المخزون: {p.quantity}"
            f" | متوفر: {'نعم' if p.active and int(p.quantity or 0) > 0 else 'لا'}"
            f"{extra}"
        )
    ]
    if p.description:
        desc = str(p.description).strip()
        if len(desc) > 220:
            desc = desc[:220] + "..."
        if desc:
            lines.append(f"  الوصف: {desc}")
    if specs_preview:
        lines.append(f"  المواصفات: {specs_preview}")
    lines.append(f"  رابط التفاصيل: {_product_public_url(p, shop_slug)}")
    video_url = str(meta.get("video_url") or "").strip()
    if video_url:
        lines.append(f"  رابط الفيديو: {video_url}")
    return lines


def match_products(
    message: str,
    history: list[dict[str, str]] | None = None,
    *,
    pool_limit: int = 800,
    match_limit: int = 8,
    include_inactive: bool = False,
) -> list[Product]:
    query_blob = _query_blob_from_message(message, history)
    q = Product.query.order_by(Product.name.asc(), Product.id.asc())
    if not include_inactive:
        q = q.filter(Product.active == True, Product.store_visible == True)  # noqa: E712
    products = q.limit(max(50, min(pool_limit, 5000))).all()

    if not query_blob.strip():
        return products[:match_limit]

    scored: list[tuple[int, Product]] = []
    for product in products:
        score = _score_product_match(product, query_blob)
        if score > 0:
            scored.append((score, product))
    scored.sort(key=lambda item: (-item[0], item[1].name or ""))
    matched = [product for _, product in scored[:match_limit]]
    if matched:
        return matched
    return products[: min(5, match_limit)]


def build_catalog_text(products: list[Product], shop_slug: str) -> str:
    if not products:
        return "(لا توجد منتجات نشطة في المخزون حالياً.)"
    lines = ["كتالوج المنتجات من المخزون:"]
    for product in products:
        lines.extend(_product_catalog_lines(product, shop_slug))
    return "\n".join(lines)


def product_cards_for_chat(products: list[Product], shop_slug: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for product in products:
        card = product_card(product, shop_slug)
        cards.append(card)
    return cards
