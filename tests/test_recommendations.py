"""Smart Commerce Sprint 8: similar, upgrade (with stated benefit), verified accessories only, bought-together from
real non-cancelled orders, cart suggestions, comparison, recently viewed cards and the admin API."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import pytest

from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

API = "/api/v1/desktop/recommendations"
AJAX = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture()
def shop(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    from flask import g

    from extensions import db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.system_settings import SystemSettings
    from modules.recommendations import service
    from modules.search import engine
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from routes.storefront import reset_schema_ready
    from utils.branch_migration import get_default_branch

    reset_schema_ready()
    invalidate_catalog_cache()
    engine.invalidate()
    service._PAIR_CACHE.clear()
    ids = _make_ctx(app)
    with app.test_request_context():
        g.tenant = ids["tenant"]
        main = get_default_branch()

        def product(name, price, qty, category, specs=()):
            meta = {"category": category, "brand": name.split()[1] if len(name.split()) > 1 else ""}
            if specs:
                meta["specs_items"] = [{"label": k, "value": v} for k, v in specs]
            p = Product(name=name, sku=uuid.uuid4().hex[:8], buy_price=1, sale_price=price, quantity=qty, active=True,
                        store_visible=True, branch_id=main.id, catalog_group_id=uuid.uuid4().hex, meta_json=json.dumps(meta))
            db.session.add(p)
            db.session.flush()
            return p.id

        p = {
            "tv55": product("شاشة سامسونج 55 بوصة", 1_000_000, 5, "شاشات", [("الحجم", "55 بوصة"), ("الدقة", "Full HD")]),
            "tv50": product("شاشة ال جي 50 بوصة", 950_000, 3, "شاشات", [("الحجم", "50 بوصة"), ("الدقة", "Full HD")]),
            "tv65": product("شاشة سامسونج 65 بوصة 4K", 1_300_000, 2, "شاشات", [("الحجم", "65 بوصة"), ("الدقة", "4K")]),
            "tv55_out": product("شاشة هايسنس 55 بوصة", 1_000_000, 0, "شاشات"),
            "stand": product("حامل شاشة جداري", 50_000, 10, "ملحقات"),
            "cable": product("كيبل HDMI ذهبي", 10_000, 10, "ملحقات"),
            "remote": product("ريموت شاشة عام", 15_000, 10, "ملحقات"),
            "soundbar": product("مكبر صوت ساوندبار", 200_000, 4, "صوتيات"),
            "mouse": product("ماوس لاسلكي", 12_000, 9, "ملحقات"),
        }
        customer = Customer(name="زبون", phone="07701234567", city="بغداد", branch_id=main.id)
        db.session.add(customer)
        db.session.flush()

        def order(items, status="تم التوصيل", days=5):
            inv = Invoice(customer_id=customer.id, customer_name=customer.name, branch_id=main.id, total=1, status=status,
                          payment_status="مسدد", created_at=datetime.utcnow() - timedelta(days=days))
            db.session.add(inv)
            db.session.flush()
            for pid in items:
                db.session.add(OrderItem(invoice_id=inv.id, product_id=pid, product_name="x", price=1, quantity=1, cost=1, total=1))

        order([p["tv55"], p["remote"]])
        order([p["tv55"], p["remote"], p["mouse"]])  # mouse: only once together → below the support threshold
        order([p["tv55"], p["soundbar"]], status="ملغي")
        order([p["tv55"], p["soundbar"]], status="ملغي")  # cancelled orders never count
        order([p["tv55"], p["cable"]], days=400)
        order([p["tv55"], p["cable"]], days=400)  # too old
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags()
        flags["storefront_v2"] = True
        settings.set_ui_flags(flags)
        db.session.commit()
    ids.update(p)
    invalidate_catalog_cache()
    engine.invalidate()
    return {**ids, "app": app, "client": app.test_client()}


def _svc(shop, fn, *args, **kwargs):
    from flask import g

    from modules.recommendations import service

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        from utils.branch_migration import get_default_branch

        g.public_branch_id, g.branch_scope_ready = get_default_branch().id, True
        return getattr(service, fn)(shop["tenant"], *args, **kwargs)


def _relation(shop, admin, source, target, verified=True, note="يناسب 32–70 بوصة VESA 400"):
    return _json(admin.post(f"{API}/relations", json={"source_product_id": shop[source], "target_product_id": shop[target],
                                                      "relation_type": "accessory", "compatibility_note": note,
                                                      "verified": verified}))


def test_similar_and_upgrade_follow_the_rules(shop):
    similar = _svc(shop, "similar", shop["tv55"])
    assert shop["tv50"] in similar
    assert shop["tv55_out"] not in similar  # out of stock is never recommended
    assert shop["tv65"] not in similar and shop["stand"] not in similar  # 10" bigger / other category
    ups = _svc(shop, "upgrades", shop["tv55"])
    assert [u["id"] for u in ups] == [shop["tv65"]]
    assert ups[0]["price_difference"] == 300_000
    assert any("10 بوصة" in b for b in ups[0]["benefits"]) and any("4K" in b for b in ups[0]["benefits"])
    assert _svc(shop, "upgrades", shop["tv65"]) == []  # nothing better in the 10–40% band


def test_bought_together_uses_only_real_recent_valid_orders(shop):
    together = _svc(shop, "bought_together", shop["tv55"])
    assert together == [shop["remote"]]  # not the cancelled soundbar, the once-only mouse or the year-old cable


def test_only_verified_accessories_are_shown(shop):
    admin = _client(shop)
    _relation(shop, admin, "tv55", "stand")
    _relation(shop, admin, "tv55", "cable", verified=False)
    acc = _svc(shop, "accessories", shop["tv55"])
    assert [a["id"] for a in acc] == [shop["stand"]] and "VESA" in acc[0]["note"]
    recs = _svc(shop, "for_product", shop["tv55"], in_cart={shop["remote"]})
    flat = [a["id"] for a in recs["accessories"]] + recs["bought_together"] + [u["id"] for u in recs["upgrades"]] + recs["similar"]
    assert shop["remote"] not in flat and shop["tv55"] not in flat and len(flat) == len(set(flat))


def test_product_page_and_cart_show_the_sections_without_adding_anything(shop):
    admin = _client(shop)
    _relation(shop, admin, "tv55", "stand")
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    html = c.get(f"{base}/product/{shop['tv55']}").get_data(as_text=True)
    assert "ملحقات متوافقة" in html and "VESA" in html and "يُشترى عادة معه" in html
    assert "خيار أفضل بفرق بسيط" in html and "بفرق 300,000" in html and "منتجات مشابهة" in html
    assert "أضف للمقارنة" in html and "data-sm-viewed" in html
    c.post(f"{base}/api/cart/add", json={"product_id": shop["tv55"], "quantity": 1},
           headers={"X-Requested-With": "XMLHttpRequest"})
    cart = c.get(f"{base}/cart").get_data(as_text=True)
    assert "قد تحتاج أيضاً" in cart and "حامل شاشة جداري" in cart and "ريموت شاشة عام" in cart
    # nothing was added by itself: the cart still holds exactly one line
    assert cart.count("data-lux-cart-item") == 1


def test_compare_page_and_recent_cards(shop):
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    html = c.get(f"{base}/compare?ids={shop['tv55']},{shop['tv65']}").get_data(as_text=True)
    assert "مقارنة المنتجات" in html and "4K" in html and "Full HD" in html and 'class="is-diff"' in html
    mixed = c.get(f"{base}/compare?ids={shop['tv55']},{shop['stand']}").get_data(as_text=True)
    assert "من أقسام مختلفة" in mixed
    assert "اختر منتجين على الأقل" in c.get(f"{base}/compare?ids={shop['tv55']}").get_data(as_text=True)
    rows = c.get(f"{base}/api/cards?ids={shop['tv50']},{shop['tv55']},abc,0").get_json()["rows"]
    assert [r["id"] for r in rows] == [shop["tv50"], shop["tv55"]] and set(rows[0]) >= {"name", "price", "url"}


def test_bundles_count_current_prices_only_for_what_is_available(shop):
    admin = _client(shop)
    b = _json(admin.post(f"{API}/bundles", json={"title": "جهّز صالتك", "product_ids": [shop["tv55"], shop["stand"], shop["tv55_out"]]}))
    rows = _svc(shop, "bundles")
    assert rows[0]["id"] == b["bundle"]["id"] and rows[0]["total"] == 1_050_000 and rows[0]["complete"] is False
    assert admin.post(f"{API}/bundles", json={"title": "x", "product_ids": [1]}).status_code == 400
    html = shop["client"].get(f"/shop/{shop['tenant']}/product/{shop['tv55']}").get_data(as_text=True)
    assert "جهّز صالتك" in html and "1,050,000" in html


def test_admin_api_requires_permission(shop):
    clerk = _client(shop, "clerk")
    assert clerk.get(f"{API}/relations").status_code == 403
    assert shop["app"].test_client().get(f"{API}/relations").status_code == 401
    admin = _client(shop)
    assert admin.post(f"{API}/relations", json={"source_product_id": shop["tv55"], "target_product_id": shop["tv55"]}).status_code == 400
    rel = _relation(shop, admin, "tv55", "stand")["relation"]
    listed = _json(admin.get(f"{API}/relations?product_id={shop['tv55']}"))["rows"]
    assert listed[0]["target_name"] == "حامل شاشة جداري"
    preview = _json(admin.get(f"{API}/preview/{shop['tv55']}"))
    assert preview["accessories"][0]["id"] == shop["stand"]
    _json(admin.post(f"{API}/relations/{rel['id']}/delete"))
    assert _json(admin.get(f"{API}/relations"))["rows"] == []


def test_home_shows_bundles_and_one_click_adds_what_can_be_bought(shop):
    from routes import storefront as sf

    sf._PAGE_CACHE.clear()
    admin = _client(shop)
    b = _json(admin.post(f"{API}/bundles", json={"title": "جهّز صالتك",
                                                  "product_ids": [shop["tv55"], shop["stand"], shop["tv55_out"]]}))["bundle"]
    _json(admin.post(f"{API}/bundles", json={"title": "باقة متوقفة", "product_ids": [shop["tv50"], shop["stand"]],
                                              "active": False}))
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    home = c.get(f"{base}/").get_data(as_text=True)
    section = home.split('aria-label="باقة جهّز صالتك"', 1)[1].split("</section>", 1)[0]
    assert "1,050,000" in section and "1 من منتجاتها غير متوفر حالياً ولن يُضاف" in section
    assert f'data-sm-add-bundle="{b["id"]}"' in section and "حامل شاشة جداري" in section
    assert "باقة متوقفة" not in home  # inactive bundles are not shown
    res = c.post(f"{base}/api/cart/add-bundle", json={"bundle_id": b["id"]}, headers=AJAX)
    data = res.get_json()
    assert res.status_code == 200 and sorted(data["added"]) == sorted([shop["tv55"], shop["stand"]])
    assert [s["id"] for s in data["skipped"]] == [shop["tv55_out"]] and data["skipped"][0]["reason"] == "غير متوفر حالياً"
    assert data["cart"]["count"] == 2 and data["cart"]["subtotal"] == 1_050_000
    assert c.post(f"{base}/api/cart/add-bundle", json={"bundle_id": 999}, headers=AJAX).status_code == 404
    sf._PAGE_CACHE.clear()
