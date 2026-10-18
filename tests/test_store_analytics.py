"""Smart Commerce Sprint 10: store dashboard (funnel from events, sales from real invoices), refresh-proof events,
recommendation attribution (a click is not a sale) and the holdout experiment, Core Web Vitals, server timings, SEO."""
from __future__ import annotations

import json
import re

from tests.test_branch_management_api import _client, _json, app  # noqa: F401
from tests.test_recommendations import API as REC_API
from tests.test_recommendations import shop  # noqa: F401

API = "/api/v1/desktop/store-analytics"
AJAX = {"X-Requested-With": "XMLHttpRequest"}


def _base(shop):
    return f"/shop/{shop['tenant']}"


def _order(client, shop, *product_ids):
    base = _base(shop)
    for pid in product_ids:
        client.post(f"{base}/api/cart/add", json={"product_id": pid, "quantity": 1}, headers=AJAX)
    client.get(f"{base}/checkout")
    res = client.post(f"{base}/checkout", data={"customer_name": "زبون تحليلات", "phone": "07701234000",
                                                "city": "بغداد", "address": "المنصور"})
    assert res.status_code == 302, res.get_data(as_text=True)[:300]
    return int(re.search(r"order-success/(\d+)", res.headers["Location"]).group(1))


def _dash(shop, days=30):
    return _json(_client(shop).get(f"{API}?days={days}"))


def test_funnel_counts_each_event_once_and_sales_come_from_real_invoices(shop):
    c = shop["client"]
    base = _base(shop)
    c.get(f"{base}/product/{shop['tv55']}")
    c.get(f"{base}/product/{shop['tv55']}")  # refresh: still one view
    c.get(f"{base}/?q=" + "زززز غير موجود")
    c.get(f"{base}/?q=" + "زززز غير موجود")  # retry: still one search
    _order(c, shop, shop["tv55"])
    d = _dash(shop)
    b, s = d["behaviour"], d["sales"]
    assert b["sessions"] == 1 and b["product_views"] == 1 and b["searches"] == 1 and b["searches_no_results"] == 1
    assert b["top_no_results"][0]["query"] == "زززز غير موجود"
    assert b["add_to_cart"] == 1 and b["checkout_started"] == 1 and b["orders"] == 1 and b["conversion_rate"] == 100.0
    assert [f["count"] for f in b["funnel"]] == [1, 1, 1, 1, 1]
    # the seeded non-store invoices are not store sales
    assert s["orders"] == 1 and s["units_per_order"] == 1 and s["top_products"][0]["product_id"] == shop["tv55"]
    assert s["estimated_margin"] == 1_000_000 - 1  # price − recorded cost: an estimate, not accounting profit
    assert s["revenue"] >= 1_000_000 and s["average_order_value"] == s["revenue"]


def test_cancelled_store_orders_leave_revenue_and_raise_the_cancel_rate(shop):
    from flask import g

    from extensions import db
    from models.invoice import Invoice

    c = shop["client"]
    first = _order(c, shop, shop["tv55"])
    _order(shop["app"].test_client(), shop, shop["tv50"])
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        db.session.get(Invoice, first).status = "ملغي"
        db.session.commit()
    s = _dash(shop)["sales"]
    assert s["orders_all"] == 2 and s["orders"] == 1 and s["cancel_rate"] == 50.0
    assert [p["product_id"] for p in s["top_products"]] == [shop["tv50"]]


def test_a_recommendation_sale_needs_a_click_and_a_real_order(shop):
    admin = _client(shop)
    _json(admin.post(f"{REC_API}/relations", json={"source_product_id": shop["tv55"], "target_product_id": shop["stand"],
                                                    "relation_type": "accessory", "verified": True}))
    c = shop["client"]
    base = _base(shop)
    c.get(f"{base}/product/{shop['tv55']}")
    c.post(f"{base}/api/events", json={"type": "rec_click", "section": "accessories", "product_id": shop["stand"]})
    other = shop["app"].test_client()  # clicked nothing, bought the same accessory: not attributed
    _order(other, shop, shop["stand"])
    _order(c, shop, shop["tv55"], shop["stand"])
    r = _dash(shop)["recommendations"]
    acc = next(x for x in r["sections"] if x["section"] == "accessories")
    assert acc["views"] >= 1 and acc["clicks"] == 1 and acc["attributed_sales"] == 1 and acc["attributed_value"] == 50_000
    assert r["attributed_value"] == 50_000 and r["experiment"] is None


def test_holdout_experiment_hides_recommendations_for_a_stable_share(shop):
    admin = _client(shop)
    assert _client(shop, "clerk").post(f"{API}/experiment", json={"holdout_pct": 50}).status_code == 403
    assert admin.post(f"{API}/experiment", json={"holdout_pct": 80}).status_code == 400
    _json(admin.post(f"{API}/experiment", json={"holdout_pct": 50}))
    _json(admin.post(f"{REC_API}/relations", json={"source_product_id": shop["tv55"], "target_product_id": shop["stand"],
                                                    "relation_type": "accessory", "verified": True}))
    seen = {"holdout": 0, "exposed": 0}
    for _ in range(24):
        page = shop["app"].test_client().get(f"{_base(shop)}/product/{shop['tv55']}").get_data(as_text=True)
        seen["exposed" if "ملحقات متوافقة" in page else "holdout"] += 1
    assert seen["holdout"] and seen["exposed"]  # both groups exist
    client = shop["app"].test_client()
    first = "ملحقات متوافقة" in client.get(f"{_base(shop)}/product/{shop['tv55']}").get_data(as_text=True)
    again = "ملحقات متوافقة" in client.get(f"{_base(shop)}/product/{shop['tv55']}").get_data(as_text=True)
    assert first == again  # the same visitor always stays in the same group
    exp = _dash(shop)["recommendations"]["experiment"]
    assert exp["holdout_pct"] == 50 and exp["enough_data"] is False
    assert exp["holdout"]["sessions"] + exp["exposed"]["sessions"] >= 25


def test_core_web_vitals_and_server_timings(shop):
    c = shop["client"]
    base = _base(shop)
    res = c.get(f"{base}/product/{shop['tv55']}")
    assert re.match(r"app;dur=\d+(\.\d)?$", res.headers["Server-Timing"])
    for lcp, cls, inp in ((1800, 0.02, 90), (2200, 0.05, 120), (2400, 0.08, 150), (4000, 0.3, 400)):
        assert c.post(f"{base}/api/vitals", json={"page": "product", "lcp": lcp, "cls": cls, "inp": inp}).status_code == 200
    assert c.post(f"{base}/api/vitals", json={"page": "product"}).status_code == 400
    assert c.post(f"{base}/api/vitals", json={"page": "evil", "lcp": 99_999_999}).status_code == 400  # out of range
    d = _dash(shop)
    product = next(v for v in d["vitals"] if v["page"] == "product")
    assert product["samples"] == 4 and product["lcp_p75_ms"] == 2400 and product["cls_p75"] == 0.08
    assert product["inp_p75_ms"] == 150 and product["passes"] == {"lcp": True, "cls": True, "inp": True}
    assert any(r["endpoint"] == "storefront.product_detail" for r in d["server"]["rows"])


def test_dashboard_permissions(shop):
    assert shop["app"].test_client().get(API).status_code == 401
    assert _client(shop, "clerk").get(API).status_code == 403
    assert _dash(shop, days=7)["days"] == 7


def test_sitemaps_are_split_and_list_only_store_pages(shop):
    c = shop["client"]
    base = _base(shop)
    index = c.get(f"{base}/sitemap.xml")
    assert index.status_code == 200 and index.mimetype == "application/xml"
    body = index.get_data(as_text=True)
    assert "<sitemapindex" in body and "sitemap-pages.xml" in body and "sitemap-products-1.xml" in body
    products = c.get(f"{base}/sitemap-products-1.xml").get_data(as_text=True)
    assert f"/product/{shop['tv55']}</loc>" in products and products.count("<url>") >= 9
    assert c.get(f"{base}/sitemap-products-2.xml").status_code == 404
    pages = c.get(f"{base}/sitemap-pages.xml").get_data(as_text=True)
    assert "badge=" in pages and "/faq" in pages and "/cart" not in pages
    robots = c.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /shop/*/cart" in robots and "Disallow: /shop/*/api/" in robots


def test_seo_tags_match_what_the_page_shows(shop):
    c = shop["client"]
    base = _base(shop)
    home = c.get(f"{base}/").get_data(as_text=True)
    assert 'rel="canonical"' in home and '"SearchAction"' in home and 'og:title' in home and "noindex" not in home
    search = c.get(f"{base}/?q=" + "شاشة").get_data(as_text=True)
    assert '<meta name="robots" content="noindex, follow">' in search and 'rel="canonical"' not in search
    category = c.get(f"{base}/?badge=" + "شاشات").get_data(as_text=True)
    assert "noindex" not in category and re.search(r'rel="canonical" href="[^"]*badge=', category)
    page = c.get(f"{base}/product/{shop['tv55']}").get_data(as_text=True)
    assert '<meta property="og:type" content="product">' in page
    assert '<meta property="product:price:amount" content="1000000">' in page
    blocks = [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)]
    product = next(b for b in blocks if b["@type"] == "Product")
    crumbs = next(b for b in blocks if b["@type"] == "BreadcrumbList")
    assert product["offers"]["price"] == 1_000_000 and product["offers"]["availability"].endswith("InStock")
    assert "aggregateRating" not in product and "review" not in product  # never invented
    assert [i["name"] for i in crumbs["itemListElement"]][-1] == "شاشة سامسونج 55 بوصة"


def test_first_time_visitors_share_a_short_page_cache_others_never_do(shop):
    from routes import storefront as sf

    sf._PAGE_CACHE.clear()
    base = _base(shop)
    first = shop["app"].test_client().get(f"{base}/?badge=" + "شاشات")
    assert first.status_code == 200 and len(sf._PAGE_CACHE) == 1  # an empty session: cached
    hit = shop["app"].test_client().get(f"{base}/?badge=" + "شاشات")
    assert hit.get_data() == first.get_data()
    shop["app"].test_client().get(f"{base}/?q=" + "شاشة")
    assert len(sf._PAGE_CACHE) == 1  # searches are never cached (they record analytics)
    buyer = shop["app"].test_client()
    buyer.post(f"{base}/api/cart/add", json={"product_id": shop["tv55"], "quantity": 1}, headers=AJAX)
    page = buyer.get(f"{base}/?badge=" + "شاشات").get_data(as_text=True)
    assert len(sf._PAGE_CACHE) == 1 and page != first.get_data(as_text=True)  # own cart: rendered for them
    sf._PAGE_CACHE.clear()


def test_admin_switches_the_new_design_and_writes_store_texts(shop):
    admin = _client(shop)
    assert _client(shop, "clerk").post(f"{API}/settings", json={"design_v2": False}).status_code == 403
    off = _json(admin.post(f"{API}/settings", json={"design_v2": False}))
    assert off["design_v2"] is False
    c = shop["app"].test_client()
    assert "sm-body" not in c.get(f"/shop/{shop['tenant']}/terms").get_data(as_text=True)  # the old design
    saved = _json(admin.post(f"{API}/settings", json={"design_v2": True, "returns_policy": "الإرجاع خلال 3 أيام.",
                                                       "about_text": "متجر عائلي منذ 2010."}))
    assert saved["design_v2"] and saved["returns_policy"] == "الإرجاع خلال 3 أيام."
    assert "الإرجاع خلال 3 أيام." in c.get(f"/shop/{shop['tenant']}/terms").get_data(as_text=True)
    assert "متجر عائلي منذ 2010." in c.get(f"/shop/{shop['tenant']}/about").get_data(as_text=True)
    assert _json(admin.get(f"{API}/settings"))["about_text"] == "متجر عائلي منذ 2010."
    assert admin.post(f"{API}/settings", json={"about_text": "x" * 1600}).status_code == 400
