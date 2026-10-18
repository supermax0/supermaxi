"""Recommendations built from the shop's own data, with the safety rules of the spec:

* only products that can be bought now (in stock, or on reservation) are recommended;
* accessories / compatible items come ONLY from verified relations — compatibility is never guessed;
* «bought together» comes from real, non-cancelled orders with at least ``MIN_SUPPORT`` co-occurrences;
* an upgrade states its concrete benefit and price difference; nothing is added to a cart automatically;
* the product itself and what is already in the cart are never recommended again.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

from extensions import db
from modules.recommendations.models import ALL_TABLES, Bundle, ProductRelation

MIN_SUPPORT = 2
_PAIR_CACHE: dict[str, tuple[float, dict[int, list[tuple[int, int]]]]] = {}


def ensure_tables() -> None:
    conn = db.session.connection()
    for model in ALL_TABLES:
        model.__table__.create(bind=conn, checkfirst=True)


def _tables() -> bool:
    from sqlalchemy import inspect

    try:
        return inspect(db.session.connection()).has_table(ProductRelation.__tablename__)
    except Exception:
        return False


def _docs(shop_slug: str):
    from modules.search import engine

    return engine.doc_map(shop_slug)


def _same_category(shop_slug: str, category: str):
    from modules.search import engine

    return engine.same_category(shop_slug, category)


def _buyable(doc) -> bool:
    return doc.in_stock


def similar(shop_slug: str, product_id: int, *, limit: int = 8, exclude: set[int] = frozenset()) -> list[int]:
    """Same category, close size / capacity, price within ±30% — available first, closest first."""
    docs = _docs(shop_slug)
    me = docs.get(int(product_id))
    if me is None:
        return []
    out = []
    for d in _same_category(shop_slug, me.category):
        if d.id == me.id or d.id in exclude or d.category != me.category or not _buyable(d):
            continue
        if me.price and d.price and not (0.7 * me.price <= d.price <= 1.3 * me.price):
            continue
        a, b = me.attrs, d.attrs
        if a.size_inch and b.size_inch and abs(a.size_inch - b.size_inch) > 5:
            continue
        if a.ton and b.ton and a.ton != b.ton:
            continue
        if a.kg and b.kg and abs(a.kg - b.kg) > 2:
            continue
        distance = abs((d.price or 0) - (me.price or 0)) / max(1, me.price or 1)
        out.append((distance - (0.1 if d.brand == me.brand else 0), d.id))
    return [i for _, i in sorted(out)[:limit]]


def upgrades(shop_slug: str, product_id: int, *, limit: int = 3, exclude: set[int] = frozenset()) -> list[dict[str, Any]]:
    """A better model in the same category for 10–40% more — with the concrete benefit spelled out."""
    docs = _docs(shop_slug)
    me = docs.get(int(product_id))
    if me is None or not me.price:
        return []
    out = []
    for d in _same_category(shop_slug, me.category):
        if d.id == me.id or d.id in exclude or d.category != me.category or not _buyable(d) or not d.price:
            continue
        if not (1.1 * me.price <= d.price <= 1.4 * me.price):
            continue
        benefits = []
        if me.attrs.size_inch and d.attrs.size_inch and d.attrs.size_inch > me.attrs.size_inch:
            benefits.append(f"أكبر بـ {int(d.attrs.size_inch - me.attrs.size_inch)} بوصة")
        if me.attrs.kg and d.attrs.kg and d.attrs.kg > me.attrs.kg:
            benefits.append(f"سعة أكبر ({d.attrs.kg:g} كغم)")
        if me.attrs.ton and d.attrs.ton and d.attrs.ton > me.attrs.ton:
            benefits.append(f"قدرة أعلى ({d.attrs.ton:g} طن)")
        labels = {"inverter": "انفرتر موفّر", "4k": "دقة 4K", "smart": "سمارت", "no_frost": "نوفروست",
                  "hot_cold": "حار/بارد", "gaming": "مناسب للألعاب"}
        benefits += [labels[f] for f in sorted(d.attrs.features - me.attrs.features) if f in labels]
        if not benefits:
            continue  # an upgrade without a stated, real benefit is just a more expensive product
        out.append({"id": d.id, "price_difference": d.price - me.price, "benefits": benefits[:3]})
    out.sort(key=lambda r: r["price_difference"])
    return out[:limit]


def _pairs(shop_slug: str, days: int = 180) -> dict[int, list[tuple[int, int]]]:
    """{product: [(other product, times bought together)]} from real orders — cached ten minutes."""
    key = f"{shop_slug}:{days}"
    cached = _PAIR_CACHE.get(key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES

    since = datetime.utcnow() - timedelta(days=days)
    dead = list(CANCELED_STATUSES | RETURN_STATUSES)
    rows = (OrderItem.query.join(Invoice, Invoice.id == OrderItem.invoice_id)
            .filter(Invoice.created_at >= since, Invoice.status.notin_(dead), OrderItem.product_id.isnot(None))
            .with_entities(OrderItem.invoice_id, OrderItem.product_id).all())
    baskets: dict[int, set[int]] = {}
    for invoice_id, product_id in rows:
        baskets.setdefault(int(invoice_id), set()).add(int(product_id))
    counts: dict[tuple[int, int], int] = {}
    for items in baskets.values():
        if len(items) < 2 or len(items) > 20:
            continue
        for a in items:
            for b in items:
                if a != b:
                    counts[(a, b)] = counts.get((a, b), 0) + 1
    out: dict[int, list[tuple[int, int]]] = {}
    for (a, b), n in counts.items():
        if n >= MIN_SUPPORT:
            out.setdefault(a, []).append((b, n))
    for a in out:
        out[a].sort(key=lambda r: -r[1])
    _PAIR_CACHE[key] = (now + 600, out)
    return out


def bought_together(shop_slug: str, product_id: int, *, limit: int = 4, exclude: set[int] = frozenset()) -> list[int]:
    docs = _docs(shop_slug)
    return [b for b, _ in _pairs(shop_slug).get(int(product_id), [])
            if b in docs and _buyable(docs[b]) and b not in exclude and b != int(product_id)][:limit]


def accessories(shop_slug: str, product_id: int, *, limit: int = 4, exclude: set[int] = frozenset()) -> list[dict[str, Any]]:
    if not _tables():
        return []
    docs = _docs(shop_slug)
    rows = (ProductRelation.query.filter_by(source_product_id=int(product_id), verified=True)
            .filter(ProductRelation.relation_type.in_(("accessory", "compatible", "service")))
            .order_by(ProductRelation.priority.asc(), ProductRelation.id.asc()).all())
    return [{"id": r.target_product_id, "note": r.compatibility_note or "", "type": r.relation_type} for r in rows
            if r.target_product_id in docs and _buyable(docs[r.target_product_id]) and r.target_product_id not in exclude][:limit]


def for_product(shop_slug: str, product_id: int, *, in_cart: set[int] = frozenset()) -> dict[str, Any]:
    """Everything the product page shows, each list de-duplicated against the others and against the cart."""
    seen = {int(product_id), *in_cart}
    acc = accessories(shop_slug, product_id, exclude=seen)
    seen |= {a["id"] for a in acc}
    together = bought_together(shop_slug, product_id, exclude=seen)
    seen |= set(together)
    ups = upgrades(shop_slug, product_id, exclude=seen)
    seen |= {u["id"] for u in ups}
    sim = similar(shop_slug, product_id, exclude=seen)
    return {"accessories": acc, "bought_together": together, "upgrades": ups, "similar": sim}


def for_cart(shop_slug: str, product_ids: list[int], *, limit: int = 4) -> list[dict[str, Any]]:
    """A few verified accessories / bought-together items for what is in the cart — never the cart's own items."""
    in_cart = {int(i) for i in product_ids}
    out: list[dict[str, Any]] = []
    for pid in product_ids:
        for a in accessories(shop_slug, pid, exclude=in_cart | {o["id"] for o in out}):
            out.append({"id": a["id"], "why": a["note"] or "ملحق متوافق"})
        for b in bought_together(shop_slug, pid, exclude=in_cart | {o["id"] for o in out}):
            out.append({"id": b, "why": "يُشترى عادة معه"})
    return out[:limit]


# ───────────────────────────── administration ─────────────────────────────


def save_relation(data: dict, *, by: int | None) -> ProductRelation:
    from models.product import Product

    ensure_tables()
    src, dst = int(data.get("source_product_id") or 0), int(data.get("target_product_id") or 0)
    kind = str(data.get("relation_type") or "accessory")
    if kind not in ("accessory", "compatible", "upgrade", "service"):
        raise ValueError("نوع العلاقة غير معروف")
    if src == dst or not src or not dst:
        raise ValueError("اختر منتجين مختلفين")
    q = Product.query.execution_options(skip_branch_scope=True)
    if q.get(src) is None or q.get(dst) is None:
        raise LookupError("المنتج غير موجود")
    row = (ProductRelation.query.filter_by(source_product_id=src, target_product_id=dst, relation_type=kind).first()
           or ProductRelation(source_product_id=src, target_product_id=dst, relation_type=kind, created_by_id=by))
    row.compatibility_note = str(data.get("compatibility_note") or "").strip()[:255] or None
    row.priority = int(data.get("priority") or 50)
    row.verified = bool(data.get("verified"))
    db.session.add(row)
    db.session.flush()
    return row


def save_bundle(data: dict, *, bundle_id: int | None = None) -> Bundle:
    ensure_tables()
    title = str(data.get("title") or "").strip()
    ids = [int(i) for i in (data.get("product_ids") or [])]
    if len(title) < 3:
        raise ValueError("اكتب عنوان الباقة")
    if not 2 <= len(set(ids)) <= 12:
        raise ValueError("الباقة من 2 إلى 12 منتجاً")
    bundle = db.session.get(Bundle, int(bundle_id)) if bundle_id else Bundle()
    if bundle is None:
        raise LookupError("الباقة غير موجودة")
    bundle.title, bundle.description = title[:120], str(data.get("description") or "").strip()[:255] or None
    bundle.product_ids_json = json.dumps(list(dict.fromkeys(ids)))
    bundle.active = bool(data.get("active", True))
    db.session.add(bundle)
    db.session.flush()
    return bundle


def bundles(shop_slug: str, *, only_active: bool = True) -> list[dict[str, Any]]:
    """Bundles with their CURRENT total. A bundle with an unavailable product is shown as incomplete, not hidden
    silently, and its total counts only what can be bought."""
    if not _tables():
        return []
    docs = _docs(shop_slug)
    q = Bundle.query.order_by(Bundle.sort_order, Bundle.id)
    if only_active:
        q = q.filter_by(active=True)
    out = []
    for b in q.all():
        ids = json.loads(b.product_ids_json or "[]")
        available = [i for i in ids if i in docs and _buyable(docs[i])]
        out.append({"id": b.id, "title": b.title, "description": b.description or "", "product_ids": ids,
                    "available_ids": available, "total": sum(docs[i].price for i in available),
                    "complete": len(available) == len(ids), "active": b.active})
    return out


def compare(shop_slug: str, product_ids: list[int]) -> dict[str, Any]:
    """2–4 products side by side; the rows where they differ are flagged. Facts only (from their own data)."""
    from modules.storefront.services.catalog_service import cards_for_ids

    ids = list(dict.fromkeys(int(i) for i in product_ids))[:4]
    cards = cards_for_ids(shop_slug, ids)
    if len(cards) < 2:
        raise ValueError("اختر منتجين على الأقل للمقارنة")
    categories = {c.get("category") for c in cards}
    labels: list[str] = []
    for c in cards:
        for s in c.get("specs") or []:
            if s.get("label") and s["label"] not in labels:
                labels.append(s["label"])
    rows = []
    for label in labels:
        values = [next((s.get("value", "") for s in (c.get("specs") or []) if s.get("label") == label), "") for c in cards]
        rows.append({"label": label, "values": values, "differs": len({v for v in values}) > 1})
    return {"products": cards, "rows": rows, "same_category": len(categories) == 1}
