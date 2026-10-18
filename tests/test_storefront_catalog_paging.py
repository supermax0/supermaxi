"""Storefront Sprint 1: the catalogue is paged on the server — no page ever carries or builds all products."""
from __future__ import annotations

import json
import re

import pytest

from tests.storefront_harness import CATEGORIES, seed_products, timed_get
from tests.test_branch_management_api import _make_ctx, app  # noqa: F401


@pytest.fixture()
def shop(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from routes.storefront import reset_schema_ready

    reset_schema_ready()
    invalidate_catalog_cache()
    ids = _make_ctx(app)
    product_ids = seed_products(app, ids["tenant"], 120, prefix="PG")
    invalidate_catalog_cache()
    from flask import g

    from models.product import Product

    with app.test_request_context():
        g.tenant = ids["tenant"]
        total = Product.query.execution_options(skip_branch_scope=True).filter_by(active=True, store_visible=True).count()
    # the company fixture already owns one visible product besides the 120 seeded here
    return {"client": app.test_client(), "tenant": ids["tenant"], "app": app, "ids": product_ids, "total": total}


def _api(shop, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    res = shop["client"].get(f"/shop/{shop['tenant']}/api/products?{query}")
    assert res.status_code == 200, res.get_data(as_text=True)[:300]
    return res.get_json(), res


def test_home_page_renders_one_page_and_the_true_total_not_the_catalogue(shop):
    r = timed_get(shop["client"], f"/shop/{shop['tenant']}/")
    html = r["html"].decode("utf-8")
    assert r["status"] == 200
    assert r["bytes"] < 250_000  # was ~2 MB per 1000 products
    assert re.search(rf"<b>{shop['total']}</b>", html)  # the real total comes from COUNT, not from len(all cards)
    assert "PG00119" not in html and "PG00000" not in html or html.count("PG00000") <= 3  # oldest/newest tail not dumped
    # the embedded product payload is only what the page shows, never the catalogue
    embedded = re.search(r'id="sfSaleProductsData">(.*?)</script>', html, re.S)
    assert embedded and len(json.loads(embedded.group(1))) <= 80


def test_pages_are_distinct_clamped_and_complete(shop):
    seen: set[int] = set()
    first, _ = _api(shop, page=1, per_page=15, sort="name_asc")
    total, pages = shop["total"], -(-shop["total"] // 15)
    assert first["total"] == total and first["pages"] == pages and len(first["products"]) == 15
    for page in range(1, pages + 1):
        data, _ = _api(shop, page=page, per_page=15, sort="name_asc")
        ids = {p["id"] for p in data["products"]}
        assert not ids & seen  # no product appears on two pages
        seen |= ids
    assert len(seen) == total  # …and together they are the whole catalogue
    beyond, _ = _api(shop, page=999, per_page=15)
    assert beyond["page"] == pages and len(beyond["products"]) == total - 15 * (pages - 1)  # clamped to the last page
    assert len(_api(shop, per_page=500)[0]["products"]) == 48  # the page size is capped


def test_search_price_category_and_sort_are_applied_by_the_server(shop):
    hit, _ = _api(shop, q="PG00007")
    assert hit["total"] == 1 and hit["products"][0]["model"] == "PG00007"
    for category in CATEGORIES:
        data, _ = _api(shop, badge=category, per_page=48)
        assert data["total"] == 24 and all(p["category"] == category for p in data["products"])
    cheap, _ = _api(shop, max_price=310000, per_page=48)
    assert cheap["total"] > 0 and all(p["price"] <= 310000 for p in cheap["products"])
    asc, _ = _api(shop, sort="price_asc", per_page=48)
    prices = [p["price"] for p in asc["products"]]
    assert prices == sorted(prices)
    none, _ = _api(shop, q="nothing-matches-this")
    assert none["total"] == 0 and none["products"] == [] and none["pages"] == 1


def test_work_per_page_does_not_grow_with_the_catalogue(shop):
    small = timed_get(shop["client"], f"/shop/{shop['tenant']}/")["queries"]
    seed_products(shop["app"], shop["tenant"], 400, prefix="BIG")
    from modules.storefront.services.catalog_service import invalidate_catalog_cache

    invalidate_catalog_cache()
    big = timed_get(shop["client"], f"/shop/{shop['tenant']}/")
    assert big["bytes"] < 250_000
    assert big["queries"] <= small + 15, (small, big["queries"])  # 120 → 520 products: same work
    cart = timed_get(shop["client"], f"/shop/{shop['tenant']}/cart")
    assert cart["queries"] < 40 and cart["bytes"] < 80_000  # the cart page used to load the whole catalogue


def test_hidden_or_inactive_products_are_never_listed_or_served(shop):
    from flask import g

    from extensions import db
    from models.product import Product

    hidden_id, inactive_id = shop["ids"][0], shop["ids"][1]
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        Product.query.execution_options(skip_branch_scope=True).get(hidden_id).store_visible = False
        Product.query.execution_options(skip_branch_scope=True).get(inactive_id).active = False
        db.session.commit()
    from modules.storefront.services.catalog_service import invalidate_catalog_cache

    invalidate_catalog_cache()
    data, _ = _api(shop, per_page=48, sort="name_asc")
    assert data["total"] == shop["total"] - 2
    listed = {p["id"] for page in range(1, 4) for p in _api(shop, page=page, per_page=48)[0]["products"]}
    assert hidden_id not in listed and inactive_id not in listed
    for pid in (hidden_id, inactive_id):
        assert shop["client"].get(f"/shop/{shop['tenant']}/api/product/{pid}/options").status_code == 404
    assert shop["client"].get(f"/shop/{shop['tenant']}/api/product/{shop['ids'][2]}/options").status_code == 200


def test_related_products_prefer_the_same_category_not_just_the_newest(shop):
    from modules.storefront.services import catalog_service

    anchor = shop["ids"][0]  # first seeded = the category at index 0 ("شاشات")
    with shop["app"].test_request_context():
        from flask import g

        g.tenant = shop["tenant"]
        g.public_branch_id = None
        from utils.branch_migration import get_default_branch

        g.public_branch_id = get_default_branch().id
        g.branch_scope_ready = True
        related = catalog_service.related_page(anchor, shop["tenant"], limit=4)
    assert len(related) == 4 and all(card["category"] == CATEGORIES[0] for card in related)
    assert anchor not in {card["id"] for card in related}


def test_categories_page_counts_and_previews(shop):
    res = shop["client"].get(f"/shop/{shop['tenant']}/categories")
    html = res.get_data(as_text=True)
    assert res.status_code == 200
    for category in CATEGORIES:
        assert category in html
    assert len(res.get_data()) < 150_000
