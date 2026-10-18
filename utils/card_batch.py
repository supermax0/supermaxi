"""Per-page batch facts for building many product cards at once (storefront performance, Sprint 10).

Building a card asked the database, per product, «does it have colour variants?» (a COUNT, plus a sibling lookup in
shared-branch mode) and read the company settings for the primary province — 2 queries × every card. Inside
``card_batch(products)`` those answers are computed once for the whole page; outside it nothing changes.
"""
from __future__ import annotations

from contextlib import contextmanager

from flask import g, has_app_context

_KEY = "_card_batch"


def current() -> dict | None:
    return g.get(_KEY) if has_app_context() else None


def _colored(products) -> dict[int, bool]:
    from extensions import db
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from utils.branch_mode import independent_branches_enabled

    siblings: dict[int, set[int]] = {int(p.id): {int(p.id)} for p in products}
    if not independent_branches_enabled():
        # same identity rule as product_color_service._shared_catalog_product_ids (group id, barcode or SKU)
        def keys(p):
            return [(k, v) for k, v in (("g", getattr(p, "catalog_group_id", None)), ("b", getattr(p, "barcode", None)),
                                        ("s", getattr(p, "sku", None))) if str(v or "").strip()]

        wanted = {k: {str(v).strip() for p in products for kk, v in keys(p) if kk == k} for k in ("g", "b", "s")}
        filters = []
        if wanted["g"]:
            filters.append(Product.catalog_group_id.in_(wanted["g"]))
        if wanted["b"]:
            filters.append(Product.barcode.in_(wanted["b"]))
        if wanted["s"]:
            filters.append(Product.sku.in_(wanted["s"]))
        if filters:
            index: dict[tuple[str, str], set[int]] = {}
            for pid, gid, bar, sku in (Product.query.execution_options(skip_branch_scope=True).filter(db.or_(*filters))
                                       .with_entities(Product.id, Product.catalog_group_id, Product.barcode, Product.sku)):
                for k, v in (("g", gid), ("b", bar), ("s", sku)):
                    if str(v or "").strip():
                        index.setdefault((k, str(v).strip()), set()).add(int(pid))
            for p in products:
                for k, v in keys(p):
                    siblings[int(p.id)] |= index.get((k, str(v).strip()), set())
    every = set().union(*siblings.values()) if siblings else set()
    with_variants = {int(pid) for (pid,) in ProductColorVariant.query.filter(ProductColorVariant.product_id.in_(every))
                     .with_entities(ProductColorVariant.product_id).distinct()} if every else set()
    return {pid: bool(ids & with_variants) for pid, ids in siblings.items()}


@contextmanager
def card_batch(products):
    """Precompute per-page facts for ``products``; nested use keeps the outer batch."""
    products = [p for p in products if p is not None]
    if not has_app_context() or g.get(_KEY) is not None or len(products) < 2:
        yield
        return
    batch: dict = {}
    try:
        batch["colors"] = _colored(products)
    except Exception:
        batch["colors"] = {}  # fall back to the per-card query
    try:
        from utils.product_region_pricing import primary_province_name

        batch["province"] = primary_province_name()
    except Exception:
        pass
    setattr(g, _KEY, batch)
    try:
        yield
    finally:
        g.pop(_KEY, None)
