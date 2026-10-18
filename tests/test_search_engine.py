"""Smart Commerce Sprint 6: realistic Iraqi queries against a real shop, ranking rules, fallbacks and speed."""
from __future__ import annotations

import json
import time

import pytest

from tests.storefront_harness import seed_products
from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

PRODUCTS = [
    # name, category, brand, model, price, qty, specs
    ("شاشة TCL 55 بوصة 4K سمارت", "شاشات", "TCL", "55C7K", 385_000, 4, [("الدقة", "4K UHD"), ("التردد", "144Hz")]),
    ("شاشة LG 55 بوصة UHD", "شاشات", "LG", "55UR80", 520_000, 2, [("النظام", "webOS")]),
    ("شاشة LG 50 بوصة سمارت", "شاشات", "LG", "50UR78", 410_000, 3, []),
    ("شاشة سامسونج 65 انج", "شاشات", "Samsung", "UA65CU7000", 890_000, 0, []),
    ("سبلت جري 1.5 طن انفرتر حار بارد", "سبالت", "Gree", "GWH18-INV", 750_000, 5, [("التبريد", "18000 BTU")]),
    ("سبلت جري 1 طن عادي", "سبالت", "Gree", "GWH12", 480_000, 6, []),
    ("سبلت ميديا 2 طن انفرتر", "سبالت", "Midea", "MSM24", 990_000, 1, []),
    ("غسالة حوضين اريستون 12 كغم", "غسالات", "Ariston", "AR12TT", 310_000, 2, []),
    ("غسالة سامسونج اوتوماتيك 9 كغم", "غسالات", "Samsung", "WW90", 650_000, 3, []),
    ("ثلاجة هاير 18 قدم نوفروست موفرة للطاقة", "ثلاجات", "Haier", "HRF18", 700_000, 2, [("الطاقة", "A+++")]),
]


@pytest.fixture()
def shop(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    from flask import g

    from extensions import db
    from models.product import Product
    from modules.search import engine
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from routes.storefront import reset_schema_ready
    from utils.branch_migration import get_default_branch

    reset_schema_ready()
    invalidate_catalog_cache()
    engine.invalidate()
    ids = _make_ctx(app)
    with app.test_request_context():
        g.tenant = ids["tenant"]
        branch = get_default_branch().id
        rows = {}
        for name, cat, brand, model, price, qty, specs in PRODUCTS:
            meta = {"category": cat, "brand": brand, "model": model,
                    "specs_items": [{"label": k, "value": v} for k, v in specs]}
            p = Product(name=name, sku=model, buy_price=1, sale_price=price, quantity=qty, active=True, store_visible=True,
                        branch_id=branch, meta_json=json.dumps(meta, ensure_ascii=False))
            db.session.add(p)
            rows[model] = p
        db.session.commit()
        ids["by_model"] = {m: p.id for m, p in rows.items()}
    invalidate_catalog_cache()
    engine.invalidate()
    return {**ids, "app": app, "client": app.test_client()}


def _search(shop, q):
    from flask import g

    from modules.search import engine

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        from utils.branch_migration import get_default_branch

        g.public_branch_id, g.branch_scope_ready = get_default_branch().id, True
        return engine.search(shop["tenant"], q)


def _models(shop, result):
    inverse = {v: k for k, v in shop["by_model"].items()}
    return [inverse.get(i) for i in result.ids]


@pytest.mark.parametrize("q,first,must_not", [
    ("TCL 55C7K", "55C7K", []),
    ("55c7k", "55C7K", []),
    ("شاشة 55 سمارت بأقل من 400 ألف", "55C7K", ["55UR80", "UA65CU7000"]),  # 55" + budget: only the TCL fits
    ("الجي خمسين", "50UR78", ["55C7K"]),  # an LG request never answers with TCL
    ("سبلت طن ونص انفرتر", "GWH18-INV", ["GWH12", "MSM24"]),
    ("مكيف طنين", "MSM24", ["GWH12"]),
    ("غسالة حوضين 12 كيلو", "AR12TT", ["WW90"]),
    ("ثلاجة كبيرة وما تصرف كهرباء هواي", "HRF18", []),
    ("شاشة للـ PS5", "55C7K", []),  # 144Hz screen ranked first for gaming
    ("تلفزيون سامسونك", "UA65CU7000", ["55C7K"]),
])
def test_realistic_queries(shop, q, first, must_not):
    result = _search(shop, q)
    got = _models(shop, result)
    assert got and got[0] == first, (q, got, result.understood())
    for bad in must_not:
        assert bad not in got, (q, got)


def test_exact_model_beats_everything_and_in_stock_comes_first(shop):
    result = _search(shop, "UA65CU7000")
    assert result.exact and _models(shop, result) == ["UA65CU7000"]


def test_relaxation_is_reported_when_the_exact_measure_does_not_exist(shop):
    result = _search(shop, "شاشة LG 43 بوصة")
    assert result.ids and "المقاس أو السعة" in result.relaxed
    assert set(_models(shop, result)) <= {"55UR80", "50UR78"}  # still LG screens, never another brand


def test_storefront_v2_uses_the_engine_and_tells_the_shopper_what_it_understood(shop):
    c = shop["client"]
    html = c.get(f"/shop/{shop['tenant']}/?v2=1&q=" + "سبلت طن ونص انفرتر").get_data(as_text=True)
    assert "فهمنا طلبك" in html and "طن ونص" in html and "انفرتر" in html
    api = c.get(f"/shop/{shop['tenant']}/api/products?q=" + "الجي خمسين").get_json()
    assert api["products"][0]["model"] == "50UR78" and "LG" in api["search"]["understood"]
    # an old-design shop keeps its plain search
    old = shop["app"].test_client().get(f"/shop/{shop['tenant']}/?q=" + "الجي خمسين").get_data(as_text=True)
    assert "فهمنا طلبك" not in old


def test_plain_search_takes_over_when_the_engine_finds_nothing(shop):
    c = shop["client"]
    api = c.get(f"/shop/{shop['tenant']}/api/products?v2=1&q=اوتوماتيك").get_json()
    assert api["total"] >= 1


def test_company_synonyms(shop):
    admin = _client(shop)
    assert _json(admin.post("/api/v1/desktop/search/synonyms", json={"synonyms": {"كاونتر": "ثلاجة"}}))["synonyms"]
    out = _json(admin.get("/api/v1/desktop/search/explain?q=كاونتر"))
    assert "ثلاجات" in out["understood"] and out["top"][0]["name"].startswith("ثلاجة")
    assert _client(shop, "clerk").post("/api/v1/desktop/search/synonyms", json={"synonyms": {}}).status_code == 403


def test_assistant_candidates_cover_the_whole_catalogue(shop):
    """The old assistant pool only saw the first 800 products alphabetically."""
    from flask import g

    seed_products(shop["app"], shop["tenant"], 900, prefix="AAA")  # 900 products sorted before every real one
    from modules.search import engine
    from modules.storefront.services.inventory_knowledge import match_products

    engine.invalidate()
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        found = match_products("سبلت جري طن ونص")
    assert found and found[0].sku == "GWH18-INV"


def test_search_stays_fast_on_a_few_thousand_products(shop):
    from flask import g

    from modules.search import engine

    seed_products(shop["app"], shop["tenant"], 3000, prefix="PERF")
    engine.invalidate()
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        from utils.branch_migration import get_default_branch

        g.public_branch_id, g.branch_scope_ready = get_default_branch().id, True
        built = time.perf_counter()
        engine.search(shop["tenant"], "شاشة")  # builds the index once (then cached for a minute)
        print(f"INDEX_BUILD_MS {(time.perf_counter() - built) * 1000:.0f}")
        timings = []
        for q in ("شاشة 55 سمارت بأقل من 400 ألف", "سبلت طن ونص انفرتر", "LG 55UR80", "غسالة 12 كيلو", "ابيض"):
            started = time.perf_counter()
            engine.search(shop["tenant"], q)
            timings.append((time.perf_counter() - started) * 1000)
    print("QUERY_MS", [round(t) for t in timings])
    assert max(timings) < 300, timings  # per query, on ~3000 products, in this test machine
