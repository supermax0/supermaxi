"""Interest profile in the session + anonymous event log + personalised home sections.

Signal weights (strong intent counts more than a glance): search 1, view 1, compare 2, favourite 3, add to cart 3,
purchase 5. Scores halve every 14 days. A category is a *strong* interest from 4 points — one view (1 point) is
never enough to reshape the page. With no data, or with personalisation off, the shop shows its general sections.
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta
from typing import Any

from flask import request, session

from extensions import db
from modules.personalization.models import StoreEvent

WEIGHTS = {"search": 1.0, "view": 1.0, "compare": 2.0, "favorite": 3.0, "cart": 3.0, "purchase": 5.0}
STRONG = 4.0
HALF_LIFE_DAYS = 14
MAX_CATEGORIES = 8
# Analytics-only events (spec §23 names): search_none = store_search_no_results, cart_remove = store_remove_from_cart,
# checkout = store_checkout_started, order = store_order_completed, rec_view / rec_click = store_recommendation_*.
EVENT_TYPES = set(WEIGHTS) | {"rec_click", "rec_view", "search_none", "cart_remove", "checkout", "order"}
# A refresh / retry must not count twice: the same (session, event, product, value) within this window is one event;
# an order / purchase (value = invoice) is unique for ever.
DEDUPE_MINUTES = {"view": 30, "search": 30, "search_none": 30, "rec_view": 30, "checkout": 30, "compare": 30,
                  "rec_click": 5, "favorite": 30, "cart_remove": 1}
DEDUPE_FOREVER = {"order", "purchase"}
RETENTION_DAYS = 180
_PURGED: dict[str, float] = {}


def _key(slug: str, part: str) -> str:
    return f"sm_{part}:{slug}"


# ───────────────────────────── consent ─────────────────────────────


def enabled(slug: str) -> bool:
    """On by default; off when the shopper switched it off, or when the browser asks for privacy (GPC) and the
    shopper has not explicitly switched it on."""
    choice = session.get(_key(slug, "personalize"))
    if choice is not None:
        return bool(choice)
    return request.headers.get("Sec-GPC") != "1"


def set_enabled(slug: str, on: bool) -> None:
    session[_key(slug, "personalize")] = bool(on)
    if not on:
        clear(slug)
    session.modified = True


def clear(slug: str) -> None:
    """Forget the interest profile and stop linking this browser's past events to it (new random id)."""
    session.pop(_key(slug, "profile"), None)
    session.pop(_key(slug, "sid"), None)
    session.modified = True


# ───────────────────────────── profile ─────────────────────────────


def _profile(slug: str) -> dict:
    p = session.get(_key(slug, "profile"))
    if not isinstance(p, dict):
        p = {}
    p.setdefault("c", {})   # category -> [score, last_ts]
    p.setdefault("q", [])   # last searches (text)
    p.setdefault("v", [])   # last viewed product ids
    p.setdefault("p", [])   # purchased product ids
    return p


def _decayed(score: float, ts: float, now: float) -> float:
    return score * 0.5 ** (max(0.0, now - ts) / 86400 / HALF_LIFE_DAYS)


def _sid(slug: str) -> str:
    sid = session.get(_key(slug, "sid"))
    if not sid:
        sid = secrets.token_hex(8)
        session[_key(slug, "sid")] = sid
    return sid


def _category_of(slug: str, product_id: int) -> str:
    try:
        from modules.search import engine

        d = engine.doc_map(slug).get(int(product_id))
        if d is not None:
            return d.category or ""
    except Exception:
        pass
    return ""


def _duplicate(sid: str, event_type: str, product_id: int | None, value: str | None) -> bool:
    q = StoreEvent.query.filter_by(event_type=event_type, product_id=product_id, value=value)
    if event_type in DEDUPE_FOREVER:
        return db.session.query(q.exists()).scalar()
    minutes = DEDUPE_MINUTES.get(event_type)
    if not minutes:
        return False
    since = datetime.utcnow() - timedelta(minutes=minutes)
    return db.session.query(q.filter(StoreEvent.sid == sid, StoreEvent.created_at >= since).exists()).scalar()


def in_holdout(slug: str) -> bool:
    """Recommendation experiment: a stable share of sessions (``storefront_rec_holdout_pct``, default 0 = off) sees
    no recommendation sections, so their conversion can be compared with the others on real orders."""
    try:
        from models.system_settings import SystemSettings

        pct = int(SystemSettings.get_settings().get_ui_flags().get("storefront_rec_holdout_pct") or 0)
    except Exception:
        return False
    if pct <= 0 or not enabled(slug):
        return False
    return group_of(_sid(slug), pct) == "holdout"


def group_of(sid: str, pct: int) -> str:
    try:
        return "holdout" if int(str(sid)[:8], 16) % 100 < int(pct) else "exposed"
    except ValueError:
        return "exposed"


def record(slug: str, event_type: str, *, product_id: int | None = None, query: str = "", category: str = "",
           section: str = "", value: str = "") -> bool:
    """Update the session profile and log one anonymous event. Does nothing when personalisation is off."""
    if event_type not in EVENT_TYPES or not enabled(slug):
        return False
    pid = int(product_id) if product_id else None
    text = (value or query or section or "")[:120] or None
    try:  # a refresh / retry: neither the profile nor the log counts it again
        _ensure_table()
        if _duplicate(_sid(slug), event_type, pid, text):
            return False
    except Exception:
        db.session.rollback()
    now = time.time()
    p = _profile(slug)
    if product_id and not category:
        category = _category_of(slug, product_id)
    if event_type == "search" and query:
        from modules.search.parser import parse

        intent = parse(query)
        category = category or (intent.category or "")
        if intent.max_price:
            p["b"] = int(intent.max_price)
        q = query.strip()[:80]
        p["q"] = [q] + [x for x in p["q"] if x != q][:4]
    if event_type == "view" and product_id:
        p["v"] = [int(product_id)] + [x for x in p["v"] if x != int(product_id)][:19]
    if event_type == "purchase" and product_id:
        p["p"] = [int(product_id)] + [x for x in p["p"] if x != int(product_id)][:9]
    if category and event_type in WEIGHTS:
        score, ts = p["c"].get(category, [0.0, now])
        p["c"][category] = [round(_decayed(score, ts, now) + WEIGHTS[event_type], 3), now]
        if len(p["c"]) > MAX_CATEGORIES:  # keep the strongest only (cookie size)
            ranked = sorted(p["c"].items(), key=lambda kv: -_decayed(kv[1][0], kv[1][1], now))
            p["c"] = dict(ranked[:MAX_CATEGORIES])
    session[_key(slug, "profile")] = p
    session.modified = True
    try:
        db.session.add(StoreEvent(sid=_sid(slug), event_type=event_type, product_id=pid,
                                  category=(category or None) and category[:60], value=text))
        db.session.commit()
        _purge_old(slug)
    except Exception:
        db.session.rollback()
    return True


_READY: set[str] = set()


def _ensure_table() -> None:
    from flask import g

    tenant = str(getattr(g, "tenant", "") or "")
    if tenant in _READY:
        return
    StoreEvent.__table__.create(bind=db.session.connection(), checkfirst=True)
    _READY.add(tenant)


def _purge_old(slug: str) -> None:
    now = time.monotonic()
    if _PURGED.get(slug, 0) > now:
        return
    _PURGED[slug] = now + 3600
    StoreEvent.query.filter(StoreEvent.created_at < datetime.utcnow() - timedelta(days=RETENTION_DAYS)).delete()
    db.session.commit()


def interests(slug: str) -> list[dict[str, Any]]:
    """[{category, score, strong}] strongest first — what the shopper can see under «لماذا أرى هذا؟»."""
    if not enabled(slug):
        return []
    now = time.time()
    rows = [{"category": c, "score": round(_decayed(s, ts, now), 2)} for c, (s, ts) in _profile(slug)["c"].items()]
    rows = [r for r in rows if r["score"] >= 0.5]
    for r in rows:
        r["strong"] = r["score"] >= STRONG
    return sorted(rows, key=lambda r: -r["score"])


def summary(slug: str) -> dict[str, Any]:
    p = _profile(slug)
    on = enabled(slug)
    return {"enabled": on, "interests": interests(slug), "searches": p["q"] if on else [],
            "budget": p.get("b") if on else None}


# ───────────────────────────── home sections ─────────────────────────────


def home_sections(slug: str) -> dict[str, Any]:
    """Ids for the personalised home sections. Empty when there is no (strong enough) data or it is switched off.

    * ``for_you``: available products of the strongest category, never the ones just viewed (no endless repeats);
    * ``after_purchase``: verified accessories of what was bought — rather than more of the same product;
    * ``budget``: available products under the budget the shopper typed, in their strongest category if any;
    * ``continue``: the last search, to pick up where they left off."""
    out: dict[str, Any] = {"for_you": [], "for_you_category": "", "after_purchase": [], "budget": [], "budget_limit": None,
                           "continue": ""}
    if not enabled(slug):
        return out
    from modules.search import engine

    p = _profile(slug)
    strong = [r for r in interests(slug) if r["strong"]]
    viewed = set(p["v"])
    bought = set(p["p"])
    by_id = engine.doc_map(slug)
    purchased_cats = {by_id[i].category for i in bought if i in by_id}
    if p["p"]:
        from modules.recommendations import service as recommendations

        acc: list[int] = []
        for pid in p["p"][:3]:
            acc += [a["id"] for a in recommendations.accessories(slug, pid, exclude=bought | set(acc))]
        out["after_purchase"] = acc[:8]
    for row in strong:
        if row["category"] in purchased_cats:
            continue  # just bought one: do not push dozens of similar ones
        picks = sorted((d for d in engine.same_category(slug, row["category"])
                        if d.in_stock and d.id not in viewed and d.id not in bought),
                       key=lambda d: (-d.popularity, -d.quality, d.price))
        if picks:
            out["for_you"], out["for_you_category"] = [d.id for d in picks[:8]], row["category"]
            break
    budget = p.get("b")
    if budget:
        top_cat = strong[0]["category"] if strong else None
        pool = engine.same_category(slug, top_cat) if top_cat else engine.documents(slug)
        under = [d for d in pool if d.in_stock and 0 < d.price <= budget]
        under.sort(key=lambda d: -d.price)  # the best the budget can buy first
        out["budget"], out["budget_limit"] = [d.id for d in under[:8]], budget
    out["continue"] = p["q"][0] if p["q"] else ""
    return out
