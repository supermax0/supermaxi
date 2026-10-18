"""Search index (derived, cached per company) and ranking.

Order of operations: exact model / barcode → mandatory conditions (category, brand, budget, explicit size / ton /
kg) → text relevance → weighted ranking → if nothing matches, relax the measurements first, then the brand, and say
so. Weights are a starting point (45% relevance, 20% price fit, 15% availability, 10% delivery, 5% data quality,
5% popularity) meant to be tuned from real search → order data.

Scale (Sprint 10): the index keeps per-category lists and word postings so a query only checks the products that
can match (not the whole catalogue), the stored products are slim (slots, shared measurement objects, interned
words), and the last results per company are cached until the index is rebuilt.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from modules.search import lexicon as L
from modules.search.parser import Intent, attributes, parse

WEIGHTS = {"relevance": 0.45, "price": 0.20, "availability": 0.15, "delivery": 0.10, "quality": 0.05, "popularity": 0.05}
_TTL = 60
_RESULT_CACHE_SIZE = 256
_cache: dict[str, tuple[float, "Index"]] = {}
_locks: dict[str, threading.Lock] = {}
_gov_cache: dict[str, tuple[float, dict[int, set[str]]]] = {}


@dataclass(slots=True)
class Attrs:
    """The measurable facts of one product (what ``_passes`` and the recommendations compare)."""

    size_inch: float | None
    ton: float | None
    kg: float | None
    features: frozenset


@dataclass(slots=True)
class Doc:
    id: int
    name: str
    codes: frozenset
    category: str
    brand: str | None
    price: int
    in_stock: bool
    quality: float
    attrs: Attrs
    popularity: float = 0.0
    name_norm: str = ""
    words: frozenset = frozenset()
    cats: frozenset = frozenset()  # every category the product answers to: its own + category words in its name


@dataclass
class Index:
    """Per-company search structures, rebuilt together (every ``_TTL`` seconds or on invalidate)."""

    docs: list
    by_id: dict
    by_cat: dict  # category -> [Doc]
    postings: dict  # word -> [Doc]
    vocab: tuple  # distinct words, for prefix / substring terms
    results: OrderedDict = field(default_factory=OrderedDict)  # (query, synonyms, province) -> Result


@dataclass
class Result:
    ids: list[int]
    total: int
    intent: Intent
    exact: bool = False
    relaxed: list[str] = field(default_factory=list)

    def understood(self) -> list[str]:
        i = self.intent
        parts = []
        if i.category:
            parts.append(i.category)
        if i.brand:
            parts.append(i.brand)
        if i.size_inch:
            parts.append(f"{int(i.size_inch)} بوصة")
        if i.ton:
            parts.append("طن ونص" if i.ton == 1.5 else f"{i.ton:g} طن")
        if i.kg:
            parts.append(f"{i.kg:g} كغم")
        labels = {"inverter": "انفرتر", "smart": "سمارت", "4k": "4K", "hot_cold": "حار/بارد", "twin_tub": "حوضين",
                  "front_load": "تحميل أمامي", "no_frost": "نوفروست", "gaming": "مناسب للألعاب",
                  "efficient": "موفّر للطاقة", "large": "حجم كبير"}
        parts += [labels[f] for f in sorted(i.features) if f in labels]
        if i.min_price and i.max_price:
            parts.append(f"من {i.min_price:,} إلى {i.max_price:,} د.ع")
        elif i.max_price:
            parts.append(f"حتى {i.max_price:,} د.ع")
        return parts


def invalidate(shop_slug: str | None = None) -> None:
    if shop_slug is None:
        _cache.clear()
        _gov_cache.clear()
    else:
        _cache.pop(str(shop_slug), None)
        _gov_cache.pop(str(shop_slug), None)


def _stock_by_governorate(shop_slug: str) -> dict[int, set[str]]:
    key = str(shop_slug or "")
    cached = _gov_cache.get(key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]
    try:
        from modules.fulfillment.service import governorate_stock_index

        index = governorate_stock_index()
    except Exception:
        index = {}
    _gov_cache[key] = (now + _TTL, index)
    return index


@lru_cache(maxsize=4096)
def _known_brand(raw: str) -> str:
    n = L.normalize(raw)
    for brand, words in L.BRAND_WORDS.items():
        if n in words or n == brand.casefold():
            return brand
    return raw


def _brand_of(meta: dict, text: str) -> str | None:
    raw = str(meta.get("brand") or "").strip()
    if raw:
        return _known_brand(raw)
    for brand, words in L.BRAND_WORDS.items():
        if any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text) for w in words if len(w) > 2):
            return brand
    return None


_CAT_PROBES = tuple((cat, tuple(f" {w} " for w in words if w not in L.GENERIC_ONLY))
                    for cat, words in L.CATEGORY_WORDS.items())


def _cats_of(category: str, name_norm: str) -> frozenset:
    cats = {category} if category else set()
    for cat, probes in _CAT_PROBES:
        if cat not in cats and any(p in name_norm for p in probes):
            cats.add(cat)
    return frozenset(cats)


def _build(shop_slug: str) -> list[Doc]:
    from models.product import Product
    from modules.storefront.services import catalog_service as cs

    shared = cs.has_shared_installment_catalog()
    if shared:
        from modules.installments.models import InstallmentProduct

        rows = (InstallmentProduct.query.join(Product, Product.id == InstallmentProduct.product_id)
                .filter(InstallmentProduct.status == "published", Product.active.is_(True),
                        Product.store_visible.isnot(False))
                .with_entities(Product.id, InstallmentProduct.title, InstallmentProduct.category, Product.sku,
                               Product.barcode, Product.meta_json, InstallmentProduct.cash_price, Product.quantity,
                               Product.image_url, InstallmentProduct.short_description).all())
    else:
        rows = (cs._storefront_visible_query()
                .with_entities(Product.id, Product.name, Product.meta_json, Product.sku, Product.barcode, Product.meta_json,
                               Product.sale_price, Product.quantity, Product.image_url, Product.description).all())
    try:
        top = cs.top_selling_ids(shop_slug, limit=50)
    except Exception:
        top = []
    rank = {pid: 1 - i / max(1, len(top)) for i, pid in enumerate(top)}
    intern = sys.intern
    shared_attrs: dict[tuple, Attrs] = {}
    docs: list[Doc] = []
    for pid, name, cat_or_meta, sku, barcode, meta_json, price, qty, image, desc in rows:
        try:
            meta = json.loads(meta_json or "{}") or {}
        except ValueError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        category = cs._light_badge(None, name, cat_or_meta) if shared else cs.badge_from_meta(meta, name)
        specs = " ".join(f"{s.get('label', '')} {s.get('value', '')}" for s in (meta.get("specs_items") or [])
                         if isinstance(s, dict))
        blob = " ".join(str(x or "") for x in (name, meta.get("brand"), meta.get("model"), category, specs,
                                               meta.get("specs_text"), str(desc or "")[:300]))
        text = L.normalize(blob)
        codes = frozenset(k for k in (L.compact(c) for c in (sku, barcode, meta.get("model")) if c) if len(k) >= 3)
        quality = (0.5 if image or meta.get("gallery") else 0) + (0.5 if specs or meta.get("specs_text") else 0)
        found = attributes(text, category)
        key = (found.size_inch, found.ton, found.kg, frozenset(found.features))
        attrs = shared_attrs.get(key)
        if attrs is None:  # thousands of products share a handful of measurement combinations
            attrs = shared_attrs[key] = Attrs(*key)
        name_norm = f" {L.normalize(name)} "
        category = intern(category)
        docs.append(Doc(id=int(pid), name=str(name or ""), codes=codes, category=category,
                        brand=_brand_of(meta, text), price=int(price or 0), in_stock=int(qty or 0) > 0,
                        quality=quality, attrs=attrs, popularity=rank.get(int(pid), 0.0), name_norm=name_norm,
                        words=frozenset(intern(w) for w in text.split()), cats=_cats_of(category, name_norm)))
    return docs


def _index(shop_slug: str) -> Index:
    """The company's index. When it expires, ONE request rebuilds it while the others keep answering from the
    previous one (no pile-up of identical rebuilds under load); only the very first build is waited for."""
    key = str(shop_slug or "")
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    lock = _locks.setdefault(key, threading.Lock())
    if cached is not None:
        if not lock.acquire(blocking=False):
            return cached[1]
    else:
        lock.acquire()
    try:
        fresh = _cache.get(key)
        if fresh and fresh[0] > time.monotonic():
            return fresh[1]
        return _rebuild(shop_slug, key)
    finally:
        lock.release()


def _rebuild(shop_slug: str, key: str) -> Index:
    docs = _build(shop_slug)
    by_cat: dict[str, list[Doc]] = {}
    postings: dict[str, list[Doc]] = {}
    for d in docs:
        for c in d.cats:
            by_cat.setdefault(c, []).append(d)
        for w in d.words:
            postings.setdefault(w, []).append(d)
    index = Index(docs=docs, by_id={d.id: d for d in docs}, by_cat=by_cat, postings=postings, vocab=tuple(postings))
    _cache[key] = (time.monotonic() + _TTL, index)
    return index


def documents(shop_slug: str) -> list[Doc]:
    return _index(shop_slug).docs


def doc_map(shop_slug: str) -> dict[int, Doc]:
    """{product id: Doc}, built once per index."""
    return _index(shop_slug).by_id


def same_category(shop_slug: str, category: str) -> list[Doc]:
    """Products whose own category is ``category`` (for similar / upgrade suggestions), via the index."""
    return [d for d in _index(shop_slug).by_cat.get(category, ()) if d.category == category]


def _category_ok(doc: Doc, category: str) -> bool:
    return category in doc.cats


def _passes(doc: Doc, i: Intent, *, measures: bool, brand: bool) -> bool:
    if i.category and not _category_ok(doc, i.category):
        return False
    if brand and i.brand and (doc.brand or "").casefold() != i.brand.casefold():
        return False
    if i.max_price and (doc.price <= 0 or doc.price > i.max_price):
        return False
    if i.min_price and doc.price < i.min_price:
        return False
    if measures:
        a = doc.attrs
        if i.size_inch and (a.size_inch is None or abs(a.size_inch - i.size_inch) > 1):
            return False
        if i.ton and (a.ton is None or a.ton != i.ton):
            return False
        if i.kg and (a.kg is None or abs(a.kg - i.kg) > 1):
            return False
        if "twin_tub" in i.features and "twin_tub" not in a.features:
            return False
    return True


def _relevance(doc: Doc, i: Intent) -> float:
    if not i.terms and not i.features:
        return 0.6  # the intent was fully structured (category / brand / size …): all candidates fit equally
    hits = 0.0
    for term in i.terms:
        if term in doc.words:
            hits += 1
        elif len(term) >= 3 and any(w.startswith(term) or (len(term) >= 4 and term in w) for w in doc.words):
            hits += 0.6
    rel = hits / len(i.terms) if i.terms else 0.5
    if i.features:
        rel = 0.7 * rel + 0.3 * (len(i.features & doc.attrs.features) / len(i.features))
    return rel


def score(doc: Doc, i: Intent, province: str = "", stock_gov: dict[int, set[str]] | None = None) -> float:
    delivery = 0.5  # unknown area / no branch data: neutral, never a guess
    available = doc.in_stock
    if province and stock_gov is not None:
        held = stock_gov.get(doc.id, set())
        delivery = 1.0 if L.normalize(province) in held else (0.5 if held else 0.2)
        available = available or bool(held)  # sold from another branch's stock when the company allows it
    price = 0.5
    if i.max_price and doc.price:
        price = min(1.0, doc.price / i.max_price)  # within budget, the closer to the budget the better the match
    return (WEIGHTS["relevance"] * _relevance(doc, i) + WEIGHTS["price"] * price
            + WEIGHTS["availability"] * (1.0 if available else 0.3) + WEIGHTS["delivery"] * delivery
            + WEIGHTS["quality"] * doc.quality + WEIGHTS["popularity"] * doc.popularity)


def _with_any_term(index: Index, terms: list[str]) -> set[int]:
    """Ids of products holding a term exactly, or as a prefix / substring the way ``_relevance`` counts it."""
    ids: set[int] = set()
    for term in terms:
        words = [term] if term in index.postings else []
        if len(term) >= 3:
            words += [w for w in index.vocab if w != term and (w.startswith(term) or (len(term) >= 4 and term in w))]
        for w in words:
            ids.update(d.id for d in index.postings.get(w, ()))
    return ids


def search(shop_slug: str, query: str, *, synonyms: dict[str, str] | None = None, province: str = "") -> Result:
    index = _index(shop_slug)
    key = (str(query or ""), tuple(sorted((synonyms or {}).items())), L.normalize(province) if province else "")
    hit = index.results.get(key)
    if hit is not None:
        index.results.move_to_end(key)
        return hit
    result = _search(shop_slug, index, query, synonyms=synonyms, province=province)
    index.results[key] = result
    if len(index.results) > _RESULT_CACHE_SIZE:
        index.results.popitem(last=False)
    return result


def _search(shop_slug: str, index: Index, query: str, *, synonyms, province) -> Result:
    intent = parse(query, synonyms=synonyms)
    docs = index.docs
    if intent.codes:
        wanted = set(intent.codes)
        exact = [d for d in docs if d.codes & wanted]
        if not exact:  # partial model typed («55c7» for «55c7k»)
            exact = [d for d in docs if any(c and any(code.startswith(c) for code in d.codes) for c in intent.codes)]
        if exact:
            exact.sort(key=lambda d: (not d.in_stock, d.id))
            return Result(ids=[d.id for d in exact], total=len(exact), intent=intent, exact=True)
    if not (intent.category or intent.brand or intent.terms or intent.features or intent.size_inch or intent.ton
            or intent.kg or intent.max_price):
        return Result(ids=[], total=0, intent=intent)
    # The category is mandatory in every step below, so its list is the whole pool when one was asked for.
    pool = index.by_cat.get(intent.category, []) if intent.category else docs
    relaxed: list[str] = []
    candidates = [d for d in pool if _passes(d, intent, measures=True, brand=True)]
    if intent.terms and candidates:
        termed = _with_any_term(index, intent.terms)
        # exactly ``_relevance(d) > 0``: a term hit, or (with features asked) a shared feature
        with_terms = [d for d in candidates if d.id in termed or (intent.features and intent.features & d.attrs.features)]
        candidates = with_terms or ([] if not (intent.category or intent.brand) else candidates)
    if not candidates and (intent.size_inch or intent.ton or intent.kg):
        candidates = [d for d in pool if _passes(d, intent, measures=False, brand=True)]
        relaxed.append("المقاس أو السعة")
    if not candidates and intent.brand:
        candidates = [d for d in pool if _passes(d, intent, measures=False, brand=False)]
        relaxed.append("العلامة")
    stock_gov = _stock_by_governorate(shop_slug) if province else None
    ranked = sorted(candidates, key=lambda d: (-score(d, intent, province, stock_gov), d.price, d.id))
    return Result(ids=[d.id for d in ranked], total=len(ranked), intent=intent, relaxed=relaxed)


def company_synonyms() -> dict[str, str]:
    try:
        from models.system_settings import SystemSettings

        raw = SystemSettings.get_settings().get_ui_flags().get("search_synonyms") or {}
        return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    except Exception:
        return {}


def to_dict(result: Result) -> dict[str, Any]:
    return {"total": result.total, "exact": result.exact, "relaxed": result.relaxed, "understood": result.understood()}
