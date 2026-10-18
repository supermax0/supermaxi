"""Smart Commerce Sprint 7: availability per branch, preparation plan, delivery fee and (only stated) delivery time."""
from __future__ import annotations

import json
import uuid

import pytest

from tests.test_branch_management_api import API as BRANCH_API
from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401


@pytest.fixture()
def shop(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    from flask import g

    from extensions import db
    from models.branch import BranchStock
    from models.product import Product
    from models.system_settings import SystemSettings
    from modules.search import engine
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from routes.storefront import reset_schema_ready
    from utils.branch_migration import get_default_branch

    reset_schema_ready()
    invalidate_catalog_cache()
    engine.invalidate()
    ids = _make_ctx(app)
    admin = _client(ids)
    _json(admin.post(f"{BRANCH_API}/feature", json={"enabled": True}))
    basra = _json(admin.post(BRANCH_API, json={"code": "BSR", "name": "فرع البصرة", "governorate": "البصرة"}))["branch"]
    with app.test_request_context():
        g.tenant = ids["tenant"]
        main = get_default_branch()
        from models.branch_profile import BranchProfile

        profile = BranchProfile.query.get(main.id) or BranchProfile(branch_id=main.id)
        profile.governorate = "بغداد"
        db.session.add(profile)

        def product(name, main_qty, basra_qty, price=500_000):
            group = uuid.uuid4().hex
            p = Product(name=name, sku=name[-6:], buy_price=1, sale_price=price, quantity=main_qty, active=True,
                        store_visible=True, branch_id=main.id, catalog_group_id=group,
                        meta_json=json.dumps({"category": "شاشات", "brand": "LG"}))
            clone = Product(name=name, sku=name[-6:], buy_price=1, sale_price=price, quantity=basra_qty, active=True,
                            store_visible=True, branch_id=basra["id"], catalog_group_id=group,
                            meta_json=json.dumps({"category": "شاشات", "brand": "LG"}))
            db.session.add_all([p, clone])
            db.session.flush()
            db.session.add_all([BranchStock(branch_id=main.id, product_id=p.id, quantity=main_qty),
                                BranchStock(branch_id=basra["id"], product_id=clone.id, quantity=basra_qty)])
            return p

        both = product("شاشة LG كلا الفرعين AAA111", 2, 3)
        only_basra = product("شاشة LG البصرة فقط BBB222", 0, 4)
        only_main = product("شاشة LG بغداد فقط CCC333", 5, 0)
        nowhere = product("شاشة LG نافدة DDD444", 0, 0)
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags()
        flags.update({"sell_from_all_branches": True, "storefront_v2": True,
                      "storefront_shipping_by_city": {"بغداد": 5000, "البصرة": 8000}})
        settings.set_ui_flags(flags)
        db.session.commit()
        ids.update(main_id=main.id, basra_id=basra["id"], both=both.id, only_basra=only_basra.id,
                   only_main=only_main.id, nowhere=nowhere.id)
    invalidate_catalog_cache()
    engine.invalidate()
    return {**ids, "app": app, "client": app.test_client()}


def _plan(shop, items, province):
    from flask import g

    from modules.fulfillment import service

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        return service.plan(items, province)


def test_a_branch_that_has_everything_wins_and_a_local_one_wins_among_them(shop):
    p = _plan(shop, [{"product_id": shop["both"], "quantity": 1}], "البصرة")
    assert p["mode"] == "single" and p["branch"]["id"] == shop["basra_id"] and p["branch"]["local"] and p["fee"] == 8000
    whole = _plan(shop, [{"product_id": shop["both"], "quantity": 1}, {"product_id": shop["only_main"], "quantity": 1}],
                  "البصرة")
    assert whole["mode"] == "single" and whole["branch"]["id"] == shop["main_id"]  # farther, but complete
    split = _plan(shop, [{"product_id": shop["only_main"], "quantity": 1}, {"product_id": shop["only_basra"], "quantity": 1}],
                  "بغداد")
    assert split["mode"] == "split" and split["days"] is None and len(split["parts"]) == 2
    none = _plan(shop, [{"product_id": shop["nowhere"], "quantity": 1}], "بغداد")
    assert none["mode"] == "unavailable"
    big = _plan(shop, [{"product_id": shop["both"], "quantity": 4}], "بغداد")
    assert big["mode"] == "unavailable"  # 2 + 3 in two branches is not 4 in one place


def test_only_the_shops_own_branch_counts_when_cross_branch_selling_is_off(shop):
    from flask import g

    from extensions import db
    from models.system_settings import SystemSettings

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags()
        flags["sell_from_all_branches"] = False
        settings.set_ui_flags(flags)
        db.session.commit()
    assert _plan(shop, [{"product_id": shop["only_basra"], "quantity": 1}], "البصرة")["mode"] == "unavailable"


def test_a_delivery_time_is_promised_only_when_the_company_stated_one(shop):
    assert _plan(shop, [{"product_id": shop["only_main"], "quantity": 1}], "بغداد")["days"] is None
    from flask import g

    from extensions import db
    from models.system_settings import SystemSettings

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags()
        flags["storefront_delivery_days"] = {"بغداد": "1-2"}
        settings.set_ui_flags(flags)
        db.session.commit()
    assert _plan(shop, [{"product_id": shop["only_main"], "quantity": 1}], "بغداد")["days"] == "1-2"
    assert _plan(shop, [{"product_id": shop["only_main"], "quantity": 1}], "البصرة")["days"] is None  # not stated


def test_area_api_quote_and_the_product_page(shop):
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    assert c.post(f"{base}/api/delivery-area", json={"province": "المريخ"}).status_code == 400
    assert c.post(f"{base}/api/delivery-area", json={"province": "البصرة"}).get_json()["province"] == "البصرة"
    quote = c.get(f"{base}/api/delivery-quote?product_id={shop['both']}").get_json()
    assert quote["province"] == "البصرة" and quote["plan"]["branch"]["id"] == shop["basra_id"]
    html = c.get(f"{base}/product/{shop['both']}").get_data(as_text=True)
    assert "التوصيل إلى البصرة" in html and "8,000" in html and "فرع البصرة" in html and "يصل خلال" not in html
    c.post(f"{base}/api/cart/add", json={"product_id": shop["only_main"], "quantity": 1},
           headers={"X-Requested-With": "XMLHttpRequest"})
    cart = c.get(f"{base}/api/delivery-quote?cart=1").get_json()
    assert cart["plan"]["mode"] == "single" and cart["plan"]["branch"]["id"] == shop["main_id"]


def test_search_prefers_what_can_be_prepared_in_the_shoppers_province(shop):
    from flask import g

    from modules.search import engine

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        from utils.branch_migration import get_default_branch

        g.public_branch_id, g.branch_scope_ready = get_default_branch().id, True
        basra = engine.search(shop["tenant"], "شاشة LG", province="البصرة").ids
        baghdad = engine.search(shop["tenant"], "شاشة LG", province="بغداد").ids
    assert basra.index(shop["only_basra"]) < basra.index(shop["only_main"])
    assert baghdad.index(shop["only_main"]) < baghdad.index(shop["only_basra"])
