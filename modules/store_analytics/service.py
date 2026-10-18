"""Store dashboard numbers. Two sources, never mixed up:

* **behaviour** (visits, searches, views, cart, checkout) from the anonymous ``store_event`` log — it only covers
  shoppers who did not switch personalisation off, so it is a lower bound;
* **sales** from the real invoices the store created (note starts with «طلب من متجر المنتجات»). Revenue is order
  value; the margin shown is price − recorded cost per line — an estimate, NOT the accounting profit.

Recommendation effect: a click is not a sale. A sale is attributed to a recommendation only when the same session
clicked that product in a recommendation section and then ordered it within 7 days; the holdout experiment (if on)
compares conversion of sessions that never saw recommendations with the others.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from flask import g

from extensions import db
from modules.store_analytics.models import StoreVital

STORE_NOTE = "طلب من متجر المنتجات"
ATTRIBUTION_DAYS = 7
MIN_GROUP_SESSIONS = 200
_READY: set[str] = set()


def _ensure(model) -> None:
    key = f"{getattr(g, 'tenant', '')}:{model.__tablename__}"
    if key in _READY:
        return
    model.__table__.create(bind=db.session.connection(), checkfirst=True)
    _READY.add(key)


def save_vital(page: str, lcp: float | None, cls: float | None, inp: float | None, mobile: bool) -> None:
    try:
        _ensure(StoreVital)
        db.session.add(StoreVital(page=page, lcp_ms=None if lcp is None else int(lcp),
                                  cls_milli=None if cls is None else int(round(cls * 1000)),
                                  inp_ms=None if inp is None else int(inp), mobile=mobile))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _events(since: datetime) -> list:
    from modules.personalization.models import StoreEvent

    _ensure(StoreEvent)
    return (StoreEvent.query.filter(StoreEvent.created_at >= since)
            .with_entities(StoreEvent.sid, StoreEvent.event_type, StoreEvent.product_id, StoreEvent.value,
                           StoreEvent.created_at).all())


def behaviour(since: datetime) -> dict[str, Any]:
    rows = _events(since)
    by_type: dict[str, list] = defaultdict(list)
    for r in rows:
        by_type[r.event_type].append(r)
    sessions = {r.sid for r in rows}
    ordered = {r.sid for r in by_type["order"]}
    norm = lambda s: " ".join(str(s or "").split()).lower()  # noqa: E731
    return {
        "sessions": len(sessions),
        "searches": len(by_type["search"]),
        "searches_no_results": len(by_type["search_none"]),
        "no_result_rate": _pct(len(by_type["search_none"]), len(by_type["search"])),
        "top_searches": Counter(norm(r.value) for r in by_type["search"] if r.value).most_common(10),
        "top_no_results": Counter(norm(r.value) for r in by_type["search_none"] if r.value).most_common(10),
        "product_views": len(by_type["view"]),
        "add_to_cart": len(by_type["cart"]),
        "removed_from_cart": len(by_type["cart_remove"]),
        "checkout_started": len(by_type["checkout"]),
        "orders": len({r.value for r in by_type["order"]}),
        "conversion_rate": _pct(len(ordered), len(sessions)),
        "funnel": [
            {"step": "زيارات (جلسات)", "count": len(sessions)},
            {"step": "شاهدوا منتجاً", "count": len({r.sid for r in by_type["view"]})},
            {"step": "أضافوا للسلة", "count": len({r.sid for r in by_type["cart"]})},
            {"step": "بدؤوا إتمام الطلب", "count": len({r.sid for r in by_type["checkout"]})},
            {"step": "أكملوا الطلب", "count": len(ordered)},
        ],
        "_rows": by_type,
    }


def sales(since: datetime) -> dict[str, Any]:
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES

    invoices = (Invoice.query.filter(Invoice.created_at >= since, Invoice.note.like(f"{STORE_NOTE}%"))
                .with_entities(Invoice.id, Invoice.total, Invoice.status).all())
    dead = set(CANCELED_STATUSES) | set(RETURN_STATUSES)
    live_ids = [i.id for i in invoices if i.status not in dead]
    cancelled = sum(1 for i in invoices if i.status in CANCELED_STATUSES)
    returned = sum(1 for i in invoices if i.status in RETURN_STATUSES)
    items = []
    if live_ids:
        items = (OrderItem.query.filter(OrderItem.invoice_id.in_(live_ids))
                 .with_entities(OrderItem.invoice_id, OrderItem.product_id, OrderItem.product_name, OrderItem.quantity,
                                OrderItem.price, OrderItem.cost, OrderItem.total).all())
    live = set(live_ids)
    revenue = sum(int(i.total or 0) for i in invoices if i.id in live)  # order value incl. delivery, not profit
    units = sum(int(it.quantity or 0) for it in items)
    margin = sum((int(it.price or 0) - int(it.cost or 0)) * int(it.quantity or 0) for it in items)
    top: Counter = Counter()
    names: dict[int, str] = {}
    for it in items:
        if it.product_id:
            top[int(it.product_id)] += int(it.quantity or 0)
            names[int(it.product_id)] = it.product_name or ""
    if names:
        live_names = dict(Product.query.execution_options(skip_branch_scope=True)
                          .filter(Product.id.in_(list(names))).with_entities(Product.id, Product.name).all())
        names.update({k: v for k, v in live_names.items() if v})
    n = len(live_ids)
    return {
        "orders": n,
        "orders_all": len(invoices),
        "revenue": revenue,
        "average_order_value": round(revenue / n) if n else 0,
        "units_per_order": round(units / n, 2) if n else 0,
        "estimated_margin": margin,
        "estimated_margin_pct": _pct(margin, sum(int(it.total or 0) for it in items)),
        "cancel_rate": _pct(cancelled, len(invoices)),
        "return_rate": _pct(returned, len(invoices)),
        "top_products": [{"product_id": pid, "name": names.get(pid, ""), "units": q} for pid, q in top.most_common(10)],
        "_items": items,
    }


def recommendations(by_type: dict[str, list], items: list, holdout_pct: int) -> dict[str, Any]:
    from modules.personalization.service import group_of

    views: Counter = Counter()
    for r in by_type.get("rec_view", []):
        for section in str(r.value or "").split(","):
            if section:
                views[section] += 1
    clicks: Counter = Counter(str(r.value or "?") for r in by_type.get("rec_click", []))
    clicked: dict[tuple[str, int], list] = defaultdict(list)  # (sid, product) -> [(time, section)]
    for r in by_type.get("rec_click", []):
        if r.product_id:
            clicked[(r.sid, int(r.product_id))].append((r.created_at, str(r.value or "?")))
    line_value = {(int(it.invoice_id), int(it.product_id)): int(it.total or 0) for it in items if it.product_id}
    attributed: Counter = Counter()
    attributed_value: Counter = Counter()
    for r in by_type.get("purchase", []):
        if not r.product_id or not str(r.value or "").startswith("inv:"):
            continue
        earlier = [(t, s) for t, s in clicked.get((r.sid, int(r.product_id)), [])
                   if t <= r.created_at and r.created_at - t <= timedelta(days=ATTRIBUTION_DAYS)]
        if not earlier:
            continue
        section = max(earlier)[1]  # last click wins
        invoice_id = int(str(r.value)[4:])
        value = line_value.get((invoice_id, int(r.product_id)))
        if value is None:
            continue  # cancelled / returned since: not a sale
        attributed[section] += 1
        attributed_value[section] += value
    sections = sorted(set(views) | set(clicks) | set(attributed))
    out = {
        "sections": [{"section": s, "views": views[s], "clicks": clicks[s], "ctr": _pct(clicks[s], views[s]),
                      "attributed_sales": attributed[s], "attributed_value": attributed_value[s]} for s in sections],
        "attributed_value": sum(attributed_value.values()),
        "experiment": None,
    }
    if holdout_pct > 0:
        sessions: dict[str, set] = {"holdout": set(), "exposed": set()}
        converted: dict[str, set] = {"holdout": set(), "exposed": set()}
        for rows in by_type.values():
            for r in rows:
                sessions[group_of(r.sid, holdout_pct)].add(r.sid)
        for r in by_type.get("order", []):
            converted[group_of(r.sid, holdout_pct)].add(r.sid)
        groups = {k: {"sessions": len(sessions[k]), "orders": len(converted[k]),
                      "conversion_rate": _pct(len(converted[k]), len(sessions[k]))} for k in sessions}
        enough = min(len(sessions["holdout"]), len(sessions["exposed"])) >= MIN_GROUP_SESSIONS
        out["experiment"] = {"holdout_pct": holdout_pct, **groups, "enough_data": enough,
                             "min_sessions_per_group": MIN_GROUP_SESSIONS}
    return out


def unmet_demand(by_type: dict[str, list], since: datetime) -> dict[str, Any]:
    """What people looked for and could not buy: searches with no result, views of products out of stock, and
    «اطلب توفيره» requests for catalogue models the company does not stock."""
    from models.product import Product

    viewed = Counter(int(r.product_id) for r in by_type.get("view", []) if r.product_id)
    out_of_stock = []
    if viewed:
        rows = (Product.query.execution_options(skip_branch_scope=True).filter(Product.id.in_(list(viewed)))
                .with_entities(Product.id, Product.name, Product.quantity).all())
        out_of_stock = sorted(({"product_id": pid, "name": name, "views": viewed[pid]} for pid, name, qty in rows
                               if int(qty or 0) <= 0), key=lambda r: -r["views"])[:10]
    requests: list = []
    try:
        from sqlalchemy import inspect

        from modules.catalog.models import AvailabilityRequest, CatalogProduct

        if inspect(db.session.connection()).has_table(AvailabilityRequest.__tablename__):
            counts = Counter(cid for (cid,) in AvailabilityRequest.query.filter(AvailabilityRequest.created_at >= since)
                             .with_entities(AvailabilityRequest.catalog_product_id).all())
            titles = dict(CatalogProduct.query.filter(CatalogProduct.id.in_(list(counts) or [0]))
                          .with_entities(CatalogProduct.id, CatalogProduct.canonical_name).all())
            requests = [{"catalog_id": cid, "title": titles.get(cid, ""), "requests": n} for cid, n in counts.most_common(10)]
    except Exception:
        db.session.rollback()
    return {"viewed_out_of_stock": out_of_stock, "availability_requests": requests}


def vitals(since: datetime) -> list[dict[str, Any]]:
    from modules.store_analytics.perf import percentile

    _ensure(StoreVital)
    rows = (StoreVital.query.filter(StoreVital.created_at >= since)
            .with_entities(StoreVital.page, StoreVital.lcp_ms, StoreVital.cls_milli, StoreVital.inp_ms).all())
    pages: dict[str, dict[str, list]] = defaultdict(lambda: {"lcp": [], "cls": [], "inp": []})
    for page, lcp, cls, inp in rows:
        for key, v in (("lcp", lcp), ("cls", cls), ("inp", inp)):
            if v is not None:
                pages[page][key].append(v)
                pages["all"][key].append(v)
    targets = {"lcp": 2500, "cls": 100, "inp": 200}
    out = []
    for page, m in pages.items():
        p75 = {k: percentile(v, 75) if v else None for k, v in m.items()}
        out.append({"page": page, "samples": max(len(v) for v in m.values()),
                    "lcp_p75_ms": p75["lcp"], "cls_p75": None if p75["cls"] is None else round(p75["cls"] / 1000, 3),
                    "inp_p75_ms": p75["inp"],
                    "passes": {k: (None if p75[k] is None else p75[k] <= targets[k]) for k in targets}})
    out.sort(key=lambda r: (r["page"] != "all", -r["samples"]))
    return out


def dashboard(days: int = 30) -> dict[str, Any]:
    from models.system_settings import SystemSettings
    from modules.store_analytics import perf

    days = max(1, min(int(days or 30), 365))
    since = datetime.utcnow() - timedelta(days=days)
    holdout = int(SystemSettings.get_settings().get_ui_flags().get("storefront_rec_holdout_pct") or 0)
    b = behaviour(since)
    s = sales(since)
    by_type, items = b.pop("_rows"), s.pop("_items")
    b["top_searches"] = [{"query": q, "count": n} for q, n in b["top_searches"]]
    b["top_no_results"] = [{"query": q, "count": n} for q, n in b["top_no_results"]]
    return {"days": days, "behaviour": b, "sales": s, "recommendations": recommendations(by_type, items, holdout),
            "unmet_demand": unmet_demand(by_type, since), "vitals": vitals(since),
            "server": perf.snapshot(str(getattr(g, "tenant", "") or ""))}
