from __future__ import annotations

import time

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from models.product import Product
from modules.installments.models import InstallmentProduct
from modules.storefront.services.category_normalize import merge_washer_category
from modules.storefront.services.product_presenter import (
    product_badge,
    product_card,
    product_category,
    product_meta,
)


PREFERRED_CATEGORY_ORDER = ("شاشات", "ثلاجات", "سبالت", "براد", "تبريد")


def _storefront_visible_query():
    return Product.query.filter(Product.active == True, Product.store_visible == True)  # noqa: E712


def _shared_installment_query():
    """Published installment items are the canonical catalog for both shops."""
    return (
        InstallmentProduct.query.options(
            selectinload(InstallmentProduct.product),
            selectinload(InstallmentProduct.media),
        )
        .join(Product, Product.id == InstallmentProduct.product_id)
        .filter(
            InstallmentProduct.status == "published",
            Product.active == True,  # noqa: E712
            Product.store_visible.isnot(False),  # «إظهار في المتجر» off hides it here even if published for installments
        )
    )


def published_installment_item(product_id: int):
    return (
        _shared_installment_query()
        .filter(InstallmentProduct.product_id == int(product_id))
        .first()
    )


def has_shared_installment_catalog() -> bool:
    return InstallmentProduct.query.with_entities(InstallmentProduct.id).first() is not None


def cash_store_product_is_visible(product: Product | None) -> bool:
    if not product or not product.active:
        return False
    linked = InstallmentProduct.query.filter_by(product_id=product.id).first()
    if linked is not None:
        # published in the installment catalogue AND not hidden with «إظهار في المتجر»
        return linked.status == "published" and product.store_visible is not False
    if has_shared_installment_catalog():
        return False
    return bool(product.store_visible)


def _category_sort_key(value: str) -> tuple[int, str]:
    clean = str(value or "").strip()
    try:
        return (PREFERRED_CATEGORY_ORDER.index(clean), clean)
    except ValueError:
        return (len(PREFERRED_CATEGORY_ORDER), clean)


class StorefrontCatalogService:
    def list_products(
        self,
        shop_slug: str,
        *,
        q: str = "",
        min_price: int = 0,
        max_price: int = 0,
        availability: str = "all",
        badge_filter: str = "",
        sort: str = "latest",
    ) -> tuple[list[dict], list[str]]:
        shared_query = _shared_installment_query()
        uses_shared_catalog = has_shared_installment_catalog()
        if uses_shared_catalog:
            query = shared_query

            if min_price > 0:
                query = query.filter(InstallmentProduct.cash_price >= min_price)
            if max_price > 0:
                query = query.filter(InstallmentProduct.cash_price <= max_price)
            if availability == "in_stock":
                query = query.filter(Product.quantity > 0)
            elif availability == "out_stock":
                query = query.filter(Product.quantity <= 0)

            q_norm = str(q or "").strip().lower()
            if q_norm:
                like = f"%{q_norm}%"
                query = query.filter(
                    or_(
                        InstallmentProduct.title.ilike(like),
                        InstallmentProduct.category.ilike(like),
                        InstallmentProduct.short_description.ilike(like),
                        Product.name.ilike(like),
                        Product.sku.ilike(like),
                    )
                )

            if sort == "price_asc":
                query = query.order_by(InstallmentProduct.cash_price.asc(), InstallmentProduct.id.desc())
            elif sort == "price_desc":
                query = query.order_by(InstallmentProduct.cash_price.desc(), InstallmentProduct.id.desc())
            elif sort == "name_asc":
                query = query.order_by(InstallmentProduct.title.asc(), InstallmentProduct.id.desc())
            else:
                query = query.order_by(
                    InstallmentProduct.featured.desc(),
                    InstallmentProduct.sort_order.asc(),
                    InstallmentProduct.id.desc(),
                )

            items = query.all()
            cards = [product_card(item.product, shop_slug, catalog_item=item) for item in items]
            badges = sorted(
                {str(card.get("category") or "").strip() for card in cards if str(card.get("category") or "").strip()},
                key=_category_sort_key,
            )
            if badge_filter:
                cards = [card for card in cards if card["badge"] == badge_filter]
            return cards, badges

        query = _storefront_visible_query()

        if min_price > 0:
            query = query.filter(Product.sale_price >= min_price)
        if max_price > 0:
            query = query.filter(Product.sale_price <= max_price)
        if availability == "in_stock":
            query = query.filter(Product.quantity > 0)
        elif availability == "out_stock":
            query = query.filter(Product.quantity <= 0)

        q_norm = str(q or "").strip().lower()
        if q_norm:
            like = f"%{q_norm}%"
            query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))

        if sort == "price_asc":
            query = query.order_by(Product.sale_price.asc(), Product.id.desc())
        elif sort == "price_desc":
            query = query.order_by(Product.sale_price.desc(), Product.id.desc())
        elif sort == "name_asc":
            query = query.order_by(Product.name.asc(), Product.id.desc())
        else:
            query = query.order_by(Product.id.desc())

        products = query.all()
        cards = [product_card(p, shop_slug) for p in products]
        badges = sorted(
            {str(card.get("category") or "").strip() for card in cards if str(card.get("category") or "").strip()},
            key=_category_sort_key,
        )
        if badge_filter:
            cards = [c for c in cards if c["badge"] == badge_filter]
        return cards, badges

    def featured_products(self, cards: list[dict], limit: int = 6) -> list[dict]:
        return cards[:limit]

    def related_products(self, product_id: int, shop_slug: str, limit: int = 4) -> list[dict]:
        shared = (
            _shared_installment_query()
            .filter(InstallmentProduct.product_id != product_id)
            .order_by(InstallmentProduct.featured.desc(), InstallmentProduct.id.desc())
            .limit(limit)
            .all()
        )
        if has_shared_installment_catalog():
            return [product_card(item.product, shop_slug, catalog_item=item) for item in shared]
        related = (
            _storefront_visible_query()
            .filter(Product.id != product_id)
            .order_by(Product.id.desc())
            .limit(limit)
            .all()
        )
        return [product_card(item, shop_slug) for item in related]


# ─────────────────────────────── paged catalogue (Sprint 1) ───────────────────────────────
#
# The storefront used to build a full presentation card for EVERY visible product on EVERY page (2 MB of HTML,
# ~2300 queries at 1 000 products). Pages now ask for one page of cards. Everything that needs "all products"
# (category list, previews, filters) works from a *light* projection — a few columns, no relationships, no gallery
# or spec parsing — and the heavy card is built only for the ids that are actually shown.

DEFAULT_PAGE_SIZE = 15
MAX_PAGE_SIZE = 48
POOL_SIZE = 60  # hero / curated sections draw from the first POOL_SIZE products of the default order
_LIGHT_CACHE_SECONDS = 45
_light_cache: dict[str, tuple[float, list[tuple]]] = {}


def invalidate_catalog_cache(shop_slug: str | None = None) -> None:
    """Drop the derived category index (tests and write paths call this; otherwise it expires in seconds)."""
    if shop_slug is None:
        _light_cache.clear()
    else:
        _light_cache.pop(str(shop_slug), None)


class _Meta:
    """Minimal stand-in so the presenter's own meta parser can read a bare meta_json column."""

    def __init__(self, meta_json):
        self.meta_json = meta_json


def _light_badge(meta_json, name, category_override=None) -> str:
    """The same badge a full card shows, computed from the light columns only."""
    if category_override is not None:
        return merge_washer_category(str(category_override or "").strip(), name)
    return badge_from_meta(product_meta(_Meta(meta_json)), name)


def badge_from_meta(meta: dict, name) -> str:
    """``_light_badge`` for an already parsed meta (the search index parses it once for several fields)."""
    category = merge_washer_category(product_category(meta), name)
    return merge_washer_category(product_badge(meta), name) or category


def _row_badge(shared: bool, name, extra) -> str:
    return _light_badge(None, name, extra) if shared else _light_badge(extra, name)


_badge_maps: dict[str, tuple[list, dict[int, str]]] = {}


def _badge_map(shop_slug: str) -> dict[int, str]:
    """{product id: badge} for the current category index (rebuilt only when the index itself is)."""
    key = str(shop_slug or "")
    rows = _category_index(shop_slug)
    cached = _badge_maps.get(key)
    if cached and cached[0] is rows:
        return cached[1]
    mapping = dict(rows)
    _badge_maps[key] = (rows, mapping)
    return mapping


def _visible_among(ids: list[int]) -> set[int]:
    """Which of these product ids the store shows (same visibility rule as the listing)."""
    if not ids:
        return set()
    shared = has_shared_installment_catalog()
    query = _filtered_query(shared, q="", min_price=0, max_price=0, availability="all", sort="id_desc")
    return {int(pid) for pid, _name, _extra in query.filter(Product.id.in_(ids)).all()}


def _category_index(shop_slug: str) -> list[tuple]:
    """[(product_id, badge)] over every visible product (newest first), cached for a few seconds."""
    key = str(shop_slug or "")
    cached = _light_cache.get(key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]
    try:
        # The search index already holds every visible product with this very badge (same query, same
        # ``_light_badge`` rule): reuse it instead of a second pass over the whole catalogue.
        from modules.search import engine

        rows = sorted(((d.id, d.category) for d in engine.documents(shop_slug)), key=lambda r: -r[0])
    except Exception:
        shared = has_shared_installment_catalog()
        query = _filtered_query(shared, q="", min_price=0, max_price=0, availability="all", sort="id_desc")
        rows = [(int(pid), _row_badge(shared, name, extra)) for pid, name, extra in query.all()]
    _light_cache[key] = (now + _LIGHT_CACHE_SECONDS, rows)
    return rows


def _filtered_query(shared: bool, *, q, min_price, max_price, availability, sort):
    """Light query (id, display name, badge source) with every SQL-expressible filter, ordered like the old listing."""
    if shared:
        query = (
            InstallmentProduct.query.join(Product, Product.id == InstallmentProduct.product_id)
            .filter(InstallmentProduct.status == "published", Product.active == True,  # noqa: E712
                    Product.store_visible.isnot(False))
            .with_entities(Product.id, InstallmentProduct.title, InstallmentProduct.category)
        )
        price = InstallmentProduct.cash_price
    else:
        query = _storefront_visible_query().with_entities(Product.id, Product.name, Product.meta_json)
        price = Product.sale_price
    if min_price > 0:
        query = query.filter(price >= min_price)
    if max_price > 0:
        query = query.filter(price <= max_price)
    if availability == "in_stock":
        query = query.filter(Product.quantity > 0)
    elif availability == "out_stock":
        query = query.filter(Product.quantity <= 0)
    q_norm = str(q or "").strip().lower()
    if q_norm:
        like = f"%{q_norm}%"
        if shared:
            query = query.filter(or_(
                InstallmentProduct.title.ilike(like), InstallmentProduct.category.ilike(like),
                InstallmentProduct.short_description.ilike(like), Product.name.ilike(like), Product.sku.ilike(like)))
        else:
            query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))
    name_column = InstallmentProduct.title if shared else Product.name
    if sort == "price_asc":
        query = query.order_by(price.asc(), Product.id.desc())
    elif sort == "price_desc":
        query = query.order_by(price.desc(), Product.id.desc())
    elif sort == "name_asc":
        query = query.order_by(name_column.asc(), Product.id.desc())
    elif sort == "id_desc":
        query = query.order_by(Product.id.desc())
    elif shared:
        query = query.order_by(InstallmentProduct.featured.desc(), InstallmentProduct.sort_order.asc(),
                               InstallmentProduct.id.desc())
    else:
        query = query.order_by(Product.id.desc())
    return query


def cards_for_ids(shop_slug: str, ids: list[int]) -> list[dict]:
    """Full presentation cards for exactly these product ids, in the given order."""
    ids = [int(i) for i in ids]
    if not ids:
        return []
    from utils.card_batch import card_batch

    if has_shared_installment_catalog():
        rows = _shared_installment_query().filter(InstallmentProduct.product_id.in_(ids)).all()
        with card_batch([item.product for item in rows]):
            by_id = {int(item.product_id): product_card(item.product, shop_slug, catalog_item=item) for item in rows}
    else:
        rows = _storefront_visible_query().filter(Product.id.in_(ids)).all()
        with card_batch(rows):
            by_id = {int(p.id): product_card(p, shop_slug) for p in rows}
    return [by_id[i] for i in ids if i in by_id]


def list_page(shop_slug: str, *, q: str = "", min_price: int = 0, max_price: int = 0, availability: str = "all",
              badge: str = "", sort: str = "latest", page: int = 1, per_page: int = DEFAULT_PAGE_SIZE,
              max_per_page: int = MAX_PAGE_SIZE, include_catalog: bool = False, smart: bool = False,
              province: str = "") -> dict:
    """One page of cards + totals — never the whole catalogue.

    ``badge`` is the display category, computed with the same rules a full card uses, on light columns.
    ``include_catalog`` appends published master-catalogue models the company does not stock ("on request") AFTER
    every stocked product; they never match a price or an in-stock filter because they have neither.
    """
    per_page = max(1, min(int(per_page or DEFAULT_PAGE_SIZE), int(max_per_page)))
    search_info = None
    if smart and str(q or "").strip():
        ranked = _smart_ids(shop_slug, q, min_price=min_price, max_price=max_price, availability=availability,
                            badge=badge, sort=sort, province=province)
        if ranked is not None:
            ids_ranked, search_info = ranked
            return _page_from_ids(shop_slug, ids_ranked, page=page, per_page=per_page, q=q, badge=badge,
                                  include_catalog=include_catalog and not min_price and not max_price
                                  and availability != "in_stock", search_info=search_info)
    shared = has_shared_installment_catalog()
    query = _filtered_query(shared, q=q, min_price=min_price, max_price=max_price, availability=availability,
                            sort=sort)
    badge = str(badge or "").strip()
    ids: list[int] | None = None
    if badge:
        # badges come from the cached category index; only products newer than it are computed here
        known = _badge_map(shop_slug)
        ordered = [int(pid) for (pid,) in query.with_entities(Product.id).all()]
        missing = [pid for pid in ordered if pid not in known]
        if missing:
            fresh = _filtered_query(shared, q="", min_price=0, max_price=0, availability="all", sort="id_desc")
            known = {**known, **{int(pid): _row_badge(shared, name, extra)
                                 for pid, name, extra in fresh.filter(Product.id.in_(missing)).all()}}
        ids = [pid for pid in ordered if known.get(pid) == badge]
        total = len(ids)
    else:
        total = int(query.order_by(None).with_entities(func.count(Product.id)).scalar() or 0)
    extra_rows = []
    if include_catalog and not min_price and not max_price and availability != "in_stock":
        from modules.catalog import service as catalog

        extra_rows = catalog.published_catalog_only(q, badge)
    grand = total + len(extra_rows)
    pages = max(1, -(-grand // per_page))
    page = max(1, min(int(page or 1), pages))
    start, end = (page - 1) * per_page, page * per_page
    if start < total:
        if ids is not None:
            page_ids = ids[start:min(end, total)]
        else:
            page_ids = [int(r[0]) for r in query.limit(min(end, total) - start).offset(start).all()]
    else:
        page_ids = []
    cards = cards_for_ids(shop_slug, page_ids)
    if extra_rows and end > total:
        from modules.catalog import service as catalog

        cards += [catalog.card(entry, shop_slug) for entry in extra_rows[max(0, start - total):end - total]]
    return {"cards": cards, "total": grand, "page": page, "pages": pages, "per_page": per_page,
            "on_request": len(extra_rows)}


def _smart_ids(shop_slug: str, q: str, *, min_price: int, max_price: int, availability: str, badge: str,
               sort: str, province: str = "") -> tuple[list[int], dict] | None:
    """Intelligent search ids (ranked), with the page's explicit filters applied on top. None → use plain search
    (the engine failed, or understood nothing and found nothing)."""
    try:
        from modules.search import engine

        result = engine.search(shop_slug, q, synonyms=engine.company_synonyms(), province=province)
        docs = engine.doc_map(shop_slug)
    except Exception:
        return None
    if not result.ids:
        return None  # nothing matched the understood conditions: the plain text search gets its chance
    rows = [docs[i] for i in result.ids if i in docs]
    if min_price:
        rows = [d for d in rows if d.price >= min_price]
    if max_price:
        rows = [d for d in rows if 0 < d.price <= max_price]
    if availability == "in_stock":
        rows = [d for d in rows if d.in_stock]
    elif availability == "out_stock":
        rows = [d for d in rows if not d.in_stock]
    if badge:
        rows = [d for d in rows if d.category == badge]
    if sort == "price_asc":
        rows.sort(key=lambda d: (d.price, -d.id))
    elif sort == "price_desc":
        rows.sort(key=lambda d: (-d.price, -d.id))
    elif sort == "name_asc":
        rows.sort(key=lambda d: (d.name, -d.id))
    return [d.id for d in rows], engine.to_dict(result)


def _page_from_ids(shop_slug: str, ids: list[int], *, page: int, per_page: int, q: str, badge: str,
                   include_catalog: bool, search_info: dict | None) -> dict:
    extra_rows = []
    if include_catalog:
        from modules.catalog import service as catalog

        extra_rows = catalog.published_catalog_only(q, badge)
    total = len(ids)
    grand = total + len(extra_rows)
    pages = max(1, -(-grand // per_page))
    page = max(1, min(int(page or 1), pages))
    start, end = (page - 1) * per_page, page * per_page
    cards = cards_for_ids(shop_slug, ids[start:min(end, total)]) if start < total else []
    if extra_rows and end > total:
        from modules.catalog import service as catalog

        cards += [catalog.card(entry, shop_slug) for entry in extra_rows[max(0, start - total):end - total]]
    return {"cards": cards, "total": grand, "page": page, "pages": pages, "per_page": per_page,
            "on_request": len(extra_rows), "search": search_info}


def badges(shop_slug: str, *, include_catalog: bool = False) -> list[str]:
    names = {b for _, b in _category_index(shop_slug) if b}
    if include_catalog:
        from modules.catalog import service as catalog

        names |= {e.category for e in catalog.published_catalog_only() if e.category}
    return sorted(names, key=_category_sort_key)


def category_overview(shop_slug: str) -> list[dict]:
    """[{name, count, preview}] — one preview card per category, built for those few ids only."""
    counts: dict[str, int] = {}
    first: dict[str, int] = {}
    for pid, badge in _category_index(shop_slug):
        key = badge or "منتجات متنوعة"
        counts[key] = counts.get(key, 0) + 1
        first.setdefault(key, pid)
    previews = {int(c["id"]): c for c in cards_for_ids(shop_slug, list(first.values()))}
    return [{"name": name, "count": counts[name], "preview": previews.get(first[name])} for name in sorted(counts)]


def related_page(product_id: int, shop_slug: str, limit: int = 4) -> list[dict]:
    """Same category first (newest), then the rest of the catalogue to fill the row — not just 'the latest added'."""
    index = _category_index(shop_slug)
    product_id = int(product_id)
    mine = next((badge for pid, badge in index if pid == product_id), "")
    same = [pid for pid, badge in index if mine and badge == mine and pid != product_id]
    taken = set(same)
    others = [pid for pid, _ in index if pid != product_id and pid not in taken]
    return cards_for_ids(shop_slug, (same + others)[:limit])


_TOP_CACHE: dict[str, tuple[float, list[int]]] = {}


def top_selling_ids(shop_slug: str, *, limit: int = 12, days: int = 60) -> list[int]:
    """Products actually sold most in the last ``days`` (cancelled / returned orders excluded). Real data only —
    an empty list when the shop has no sales yet. Cached for ten minutes per company."""
    from datetime import datetime, timedelta

    from models.invoice import Invoice
    from models.order_item import OrderItem
    from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES

    key = f"{shop_slug}:{limit}:{days}"
    cached = _TOP_CACHE.get(key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]
    dead = list(CANCELED_STATUSES | RETURN_STATUSES)
    since = datetime.utcnow() - timedelta(days=days)
    try:
        rows = (OrderItem.query.join(Invoice, Invoice.id == OrderItem.invoice_id)
                .filter(Invoice.created_at >= since, Invoice.status.notin_(dead), OrderItem.product_id.isnot(None))
                .with_entities(OrderItem.product_id, func.sum(OrderItem.quantity).label("qty"))
                .group_by(OrderItem.product_id).order_by(func.sum(OrderItem.quantity).desc())
                .limit(limit * 3).all())
        wanted = [int(pid) for pid, _ in rows]
        visible = _visible_among(wanted)  # only the few sold ids, not the whole catalogue
        ids = [pid for pid in wanted if pid in visible][:limit]
    except Exception:
        ids = []
    _TOP_CACHE[key] = (now + 600, ids)
    return ids
