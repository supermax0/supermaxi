"""Shared helpers for the storefront tests: a seeded tenant with N published products and a query counter."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager

CATEGORIES = ["شاشات", "غسالات", "ثلاجات", "سبالت", "طباخات"]
BRANDS = ["LG", "Samsung", "TCL", "Gree", "Hisense"]


def seed_products(app, tenant: str, count: int, *, prefix: str = "ST") -> list[int]:
    """`count` published, in-stock products spread over five categories; returns their ids."""
    from flask import g

    from extensions import db
    from models.product import Product

    ids: list[int] = []
    with app.test_request_context():
        g.tenant = tenant
        from utils.branch_migration import get_default_branch

        branch_id = get_default_branch().id
        rows = []
        for i in range(count):
            category = CATEGORIES[i % len(CATEGORIES)]
            brand = BRANDS[i % len(BRANDS)]
            meta = {"category": category, "store_badge": category, "brand": brand, "model": f"{prefix}{i:05d}"}
            rows.append(Product(
                name=f"{category} {brand} {prefix}{i:05d}", sku=f"{prefix}-{i:05d}", buy_price=200_000 + i,
                sale_price=300_000 + (i % 50) * 5_000, quantity=3 + i % 5, active=True, store_visible=True, branch_id=branch_id,
                image_url=f"/static/img/placeholder-{i % 3}.png" if i % 4 else None,
                meta_json=json.dumps(meta, ensure_ascii=False)))
        db.session.add_all(rows)
        db.session.commit()
        ids = [r.id for r in rows]
    return ids


@contextmanager
def count_queries():
    """Counts SQL statements issued inside the block (all engines of the app)."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    box = {"n": 0}

    def before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        box["n"] += 1

    event.listen(Engine, "before_cursor_execute", before)
    try:
        yield box
    finally:
        event.remove(Engine, "before_cursor_execute", before)


def timed_get(client, url: str) -> dict:
    started = time.perf_counter()
    with count_queries() as q:
        res = client.get(url)
    elapsed = (time.perf_counter() - started) * 1000
    body = res.get_data()
    return {"status": res.status_code, "bytes": len(body), "ms": round(elapsed), "queries": q["n"], "html": body}
