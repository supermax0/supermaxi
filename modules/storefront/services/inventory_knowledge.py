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


def _normalize_search_text(text: str) -> str:
    normalized = _normalize_ar_digits(str(text or "")).translate(
        str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
    )
    return re.sub(r"\s+", " ", normalized.lower()).strip()


def extract_foot_size(text: str) -> int | None:
    normalized = _normalize_search_text(text)
    match = re.search(r"(?<!\d)(\d{1,2})\s*(?:قدم|قدام|ft)\b", normalized, re.I)
    if not match:
        return None
    size = int(match.group(1))
    return size if 3 <= size <= 40 else None


def _product_match_blob(p: Product) -> str:
    from utils.tenant_feature_flags import tenant_feature_enabled

    parts: list[str] = [
        p.name or "",
        p.sku or "",
        p.barcode or "",
        str(p.sale_price or ""),
        (
            str(getattr(p, "exchange_sale_price", None) or "")
            if tenant_feature_enabled("trade_in_sales", default=False)
            else ""
        ),
        str(p.quantity or ""),
        str(p.description or ""),
    ]
    meta = product_meta(p)
    for key in ("brand", "category", "size", "color", "unit", "model"):
        value = meta.get(key)
        if value is not None and str(value).strip():
            parts.append(str(value))
    return _normalize_search_text(" ".join(parts))


def _product_identity_text(product: Product) -> str:
    return " ".join(
        str(getattr(product, field, "") or "")
        for field in ("name", "catalog_category", "description")
    )


def product_foot_size(product: Product) -> int | None:
    return extract_foot_size(_product_identity_text(product))


def _requested_product_family(text: str) -> str:
    normalized = _normalize_search_text(text)
    if re.search(r"(?:براد|مبرد|كولر)\s*(?:ال)?ماء|water\s*cooler", normalized):
        return "water_cooler"
    if re.search(r"مجمد|فريزر|freezer", normalized):
        return "freezer"
    if re.search(r"ثلاج|refrigerator|fridge", normalized):
        return "refrigerator"
    if re.search(r"شاش|تلفزيون|تلفاز|\btv\b", normalized):
        return "television"
    return ""


def _product_family(product: Product) -> str:
    normalized = _normalize_search_text(_product_identity_text(product))
    if re.search(r"(?:براد|مبرد|كولر)\s*(?:ال)?ماء|water\s*cooler", normalized):
        return "water_cooler"
    if re.search(r"مجمد|فريزر|freezer", normalized):
        return "freezer"
    if re.search(r"ثلاج|refrigerator|fridge", normalized):
        return "refrigerator"
    if re.search(r"شاش|تلفزيون|تلفاز|\btv\b", normalized):
        return "television"
    return ""


def _nearest_foot_products(products: list[Product], message: str) -> list[Product]:
    requested_size = extract_foot_size(message)
    if requested_size is None:
        return []

    requested_family = _requested_product_family(message)
    candidates: list[tuple[Product, int]] = []
    for product in products:
        if requested_family and _product_family(product) != requested_family:
            continue
        size = product_foot_size(product)
        if size is not None:
            candidates.append((product, size))
    if not candidates:
        return []

    # Prefer products actually in stock. If none are stocked, keep the closest
    # published option so reservation-enabled products can still be shown.
    stocked = [row for row in candidates if int(getattr(row[0], "quantity", 0) or 0) > 0]
    ranked_pool = stocked or candidates
    nearest_size = min(
        {size for _, size in ranked_pool},
        key=lambda size: (abs(size - requested_size), 0 if size >= requested_size else 1, size),
    )
    return sorted(
        [product for product, size in ranked_pool if size == nearest_size],
        key=lambda product: str(getattr(product, "name", "") or ""),
    )


def _score_product_match(p: Product, query_blob: str) -> int:
    if not query_blob.strip():
        return 0
    hay = _product_match_blob(p)
    query_blob = _normalize_search_text(query_blob)
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
    return _normalize_search_text("\n".join(parts))


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
    from utils.tenant_feature_flags import tenant_feature_enabled

    meta = product_meta(p)
    extra_parts: list[str] = []
    for key in ("brand", "unit", "category", "shelf", "color", "size"):
        value = meta.get(key)
        if value is not None and str(value).strip():
            extra_parts.append(f"{key}: {value}")
    extra = f" | {' | '.join(extra_parts)}" if extra_parts else ""
    specs = product_specs(meta)
    specs_preview = " | ".join(f"{item['label']}: {item['value']}" for item in specs[:4])
    exchange_text = (
        f" | سعر الاستبدال: {getattr(p, 'exchange_sale_price', None) or '-'}"
        if tenant_feature_enabled("trade_in_sales", default=False)
        else ""
    )

    lines = [
        (
            f"- المنتج: {p.name}"
            f" | SKU: {p.sku or '-'}"
            f" | سعر البيع: {p.sale_price} د.ع"
            f"{exchange_text}"
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
    if not include_inactive and str(message or "").strip():
        # The whole catalogue through the intelligent search — the old candidate pool below only ever saw the first
        # products in alphabetical order, so anything after them could never be recommended.
        try:
            from flask import g

            from modules.search import engine

            result = engine.search(str(getattr(g, "tenant", "") or ""), str(message), synonyms=engine.company_synonyms())
            if result.ids:
                wanted = result.ids[:match_limit]
                rows = {p.id: p for p in Product.query.filter(Product.id.in_(wanted)).all()}
                found = [rows[i] for i in wanted if i in rows]
                if found:
                    return found
        except Exception:
            pass
    q = Product.query.order_by(Product.name.asc(), Product.id.asc())
    if not include_inactive:
        q = q.filter(Product.active == True, Product.store_visible == True)  # noqa: E712
    products = q.limit(max(50, min(pool_limit, 5000))).all()

    if not query_blob.strip():
        return products[:match_limit]

    if extract_foot_size(message) is not None:
        nearest = _nearest_foot_products(products, message)
        return nearest[:match_limit]

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
