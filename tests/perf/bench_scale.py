"""Storefront scale benchmark (Smart Commerce V2, Sprint 10) — NOT part of the pytest run.

Seeds a throw-away tenant with N realistic products (default 100,000), then measures inside one process:
search-index build time and memory, smart search latency (engine and full HTTP page), suggestions API, home /
category / product pages, sitemap, response sizes and SQL statements per request. The tenant is deleted at the end.

    python tests/perf/bench_scale.py --count 100000 --out docs/perf/scale-100k.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FINORA_LOCAL_WORKSPACE", "0")

CATEGORIES = {
    "شاشات": ("شاشة", ["سامسونج", "ال جي", "TCL", "هايسنس", "سوني"], "{size} بوصة {feat}", ["سمارت 4K", "سمارت", "4K", "QLED سمارت"]),
    "غسالات": ("غسالة", ["ال جي", "سامسونج", "بيكو", "اريستون", "دنكا"], "{kg} كغم {feat}", ["اوتوماتيك", "حوضين", "انفرتر"]),
    "ثلاجات": ("ثلاجة", ["ال جي", "سامسونج", "بيكو", "شارب", "هاير"], "{ft} قدم {feat}", ["نوفروست", "انفرتر", "بابين"]),
    "سبالت": ("سبلت", ["كري", "ال جي", "TCL", "ميديا", "هاير"], "{ton} طن {feat}", ["انفرتر", "حار بارد", "انفرتر حار بارد"]),
    "طباخات": ("طباخ", ["بيكو", "اريستون", "تكنو", "الحافظ", "يونيون"], "{burners} عين {feat}", ["غاز", "كهربائي", "مختلط"]),
}
QUERIES = ["شاشة 55 سمارت بأقل من 600 ألف", "سبلت طن ونص انفرتر", "غسالة حوضين 12 كيلو", "ثلاجة نوفروست 18 قدم",
           "الجي خمسين", "شاشة سامسونج 65", "طباخ غاز 5 عين", "سبلت كري 2 طن", "M-012345", "غسالة اوتوماتيك بيكو"]


def seed(app, tenant: str, count: int) -> float:
    from flask import g
    from sqlalchemy import insert

    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.product import Product
    from utils.branch_migration import get_default_branch

    started = time.perf_counter()
    rnd = random.Random(7)
    with app.test_request_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        branch_id = get_default_branch().id
        rows = []
        cats = list(CATEGORIES)
        for i in range(count):
            cat = cats[i % len(cats)]
            noun, brands, pattern, feats = CATEGORIES[cat]
            brand = brands[rnd.randrange(len(brands))]
            spec = pattern.format(size=rnd.choice([32, 43, 50, 55, 65, 75]), kg=rnd.choice([7, 8, 10, 12, 14]),
                                  ft=rnd.choice([12, 14, 16, 18, 22]), ton=rnd.choice(["1", "1.5", "2"]),
                                  burners=rnd.choice([4, 5]), feat=rnd.choice(feats))
            model = f"M-{i:06d}"
            meta = {"category": cat, "store_badge": cat, "brand": brand, "model": model,
                    "specs_items": [{"label": "المواصفة", "value": spec}]}
            rows.append({"name": f"{noun} {brand} {spec} {model}", "sku": model, "barcode": f"62{i:011d}",
                         "buy_price": 100_000 + rnd.randrange(900_000), "sale_price": 150_000 + rnd.randrange(30) * 50_000,
                         "quantity": rnd.choice([0, 1, 2, 3, 5, 8, 12]), "active": True, "store_visible": True,
                         "branch_id": branch_id, "meta_json": json.dumps(meta, ensure_ascii=False),
                         "image_url": f"/static/img/placeholder-{i % 3}.png" if i % 4 else None})
            if len(rows) == 5000:
                db.session.execute(insert(Product.__table__), rows)
                rows = []
        if rows:
            db.session.execute(insert(Product.__table__), rows)
        db.session.commit()
    return time.perf_counter() - started


def pct(values, p):
    from modules.store_analytics.perf import percentile

    return round(percentile(values, p), 1)


def run(count: int) -> dict:
    import psutil

    from app import app
    from modules.search import engine
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from tests.storefront_harness import timed_get

    app.config["TESTING"] = True
    tenant = f"perf_scale_{count}_{os.getpid()}"
    proc = psutil.Process()
    out: dict = {"products": count, "machine": {"cpu": os.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 2**30, 1)}}
    out["seed_seconds"] = round(seed(app, tenant, count), 1)
    try:
        from flask import g

        with app.test_request_context():
            g.tenant = tenant
            from models.system_settings import SystemSettings
            from extensions import db

            s = SystemSettings.get_settings()
            flags = s.get_ui_flags()
            flags["storefront_v2"] = True
            s.set_ui_flags(flags)
            db.session.commit()
            invalidate_catalog_cache()
            engine.invalidate()
            rss0 = proc.memory_info().rss
            t = time.perf_counter()
            docs = engine.documents(tenant)
            out["index"] = {"docs": len(docs), "build_seconds": round(time.perf_counter() - t, 2),
                            "memory_mb": round((proc.memory_info().rss - rss0) / 2**20, 1)}
            cold, warm = [], []
            for q in QUERIES + [f"{q} {n}" for q in QUERIES[:5] for n in ("سعر", "جديد")]:  # first time: no result cache
                t = time.perf_counter()
                engine.search(tenant, q)
                cold.append((time.perf_counter() - t) * 1000)
            for q in QUERIES:  # asked again: answered from the result cache
                t = time.perf_counter()
                engine.search(tenant, q)
                warm.append((time.perf_counter() - t) * 1000)
            out["engine_search_ms"] = {"uncached_p50": pct(cold, 50), "uncached_p95": pct(cold, 95),
                                       "uncached_max": round(max(cold), 1), "cached_p95": pct(warm, 95)}
        client = app.test_client()
        base = f"/shop/{tenant}"
        timed_get(client, f"{base}/")  # warm caches (schema guard, catalogue index)
        pages = {}
        for label, url in [("home", f"{base}/"), ("category", f"{base}/?badge=شاشات"), ("category_page_50", f"{base}/?badge=شاشات&page=50"),
                           ("product", f"{base}/product/{docs[len(docs) // 2].id}"), ("sitemap_index", f"{base}/sitemap.xml"),
                           ("sitemap_products_1", f"{base}/sitemap-products-1.xml")]:
            runs = [timed_get(client, url) for _ in range(3)]
            pages[label] = {"status": runs[-1]["status"], "kb": round(runs[-1]["bytes"] / 1024, 1),
                            "ms_warm": min(r["ms"] for r in runs), "queries": min(r["queries"] for r in runs)}
        out["pages"] = pages
        http_search, suggest = [], []
        for q in QUERIES + [f"{q} {n}" for q in QUERIES for n in ("ابيض", "اصلي")]:  # distinct: no result cache
            http_search.append(timed_get(client, f"{base}/?q={q}")["ms"])
            suggest.append(timed_get(client, f"{base}/api/products?per_page=6&q={q[:-1]}")["ms"])
        out["http_search_page_ms"] = {"p50": pct(http_search, 50), "p95": pct(http_search, 95)}
        out["suggestions_api_ms"] = {"p50": pct(suggest, 50), "p95": pct(suggest, 95)}
        out["process_rss_mb"] = round(proc.memory_info().rss / 2**20)
    finally:
        try:
            from extensions_tenant import clear_tenant_engine
            from extensions import db

            with app.app_context():
                db.session.remove()
                clear_tenant_engine(tenant)
        except Exception as exc:
            print("cleanup:", exc, file=sys.stderr)
        for suffix in ("", "-wal", "-shm"):
            try:
                (ROOT / "tenants" / f"{tenant}.db{suffix}").unlink(missing_ok=True)
            except OSError:
                pass
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    result = run(args.count)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
