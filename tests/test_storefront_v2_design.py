"""Storefront Sprint 2: the V2 design is opt-in per company, previewable, and every shop page still renders in it."""
from __future__ import annotations

import json

import pytest

from tests.storefront_harness import CATEGORIES, seed_products
from tests.test_branch_management_api import _make_ctx, app  # noqa: F401


@pytest.fixture()
def shop(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from routes.storefront import reset_schema_ready

    reset_schema_ready()
    invalidate_catalog_cache()
    ids = _make_ctx(app)
    product_ids = seed_products(app, ids["tenant"], 40, prefix="V2")
    invalidate_catalog_cache()
    return {"client": app.test_client(), "tenant": ids["tenant"], "app": app, "ids": product_ids}


def _get(shop, path, **kw):
    res = shop["client"].get(f"/shop/{shop['tenant']}{path}", **kw)
    return res.status_code, res.get_data(as_text=True)


def _set_flag(shop, value: bool):
    from flask import g

    from extensions import db
    from models.system_settings import SystemSettings

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags()
        flags["storefront_v2"] = value
        settings.set_ui_flags(flags)
        db.session.commit()


def test_existing_shops_keep_the_current_design_by_default(shop):
    status, html = _get(shop, "/")
    assert status == 200 and "cash-store-header" in html and "sm-header" not in html


def test_owner_preview_switches_on_for_the_browser_and_off_again(shop):
    status, html = _get(shop, "/?v2=1")
    assert status == 200 and 'class="sm-body sm-native"' in html and "cash-store-header" not in html
    assert "sm-header" in _get(shop, "/cart")[1]  # the preview follows the visitor to other pages
    assert "cash-store-header" in _get(shop, "/?v2=0")[1]
    assert "cash-store-header" in _get(shop, "/")[1]


def test_company_flag_turns_v2_on_for_everyone(shop):
    _set_flag(shop, True)
    assert "sm-header" in _get(shop, "/")[1]
    other = shop["app"].test_client()  # a brand new visitor
    assert "sm-header" in other.get(f"/shop/{shop['tenant']}/").get_data(as_text=True)


@pytest.mark.parametrize("path", ["/", "/?q=V2000", "/?badge=" + CATEGORIES[1], "/categories", "/offers", "/favorites",
                                  "/cart", "/checkout", "/track", "/account", "/about", "/faq"])
def test_every_shop_page_renders_inside_the_v2_shell(shop, path):
    _set_flag(shop, True)
    status, html = _get(shop, path)
    assert status == 200, (path, html[:300])
    assert "sm-header" in html and "sm-footer" in html


def test_product_page_renders_in_v2(shop):
    _set_flag(shop, True)
    status, html = _get(shop, f"/product/{shop['ids'][3]}")
    assert status == 200 and "sm-header" in html and "data-sf-add-cart" in html


def test_v2_home_is_light_and_carries_only_shown_products(shop):
    _set_flag(shop, True)
    status, html = _get(shop, "/")
    assert status == 200
    assert len(html.encode()) < 200_000
    assert html.count('class="sm-card') >= 15  # grid page (+ rails)
    import re

    embedded = json.loads(re.search(r'id="sfSaleProductsData">(.*?)</script>', html, re.S).group(1))
    assert len(embedded) <= 90
    assert 'loading="lazy"' in html  # images below the fold are lazy
    assert "ai-chat.js" not in html.split("STOREFRONT_CONFIG")[0]  # the assistant is not on the critical path


def test_results_show_count_active_filters_and_an_empty_state(shop):
    _set_flag(shop, True)
    _, html = _get(shop, "/?badge=" + CATEGORIES[0] + "&max_price=999999")
    assert "<b>8</b>" in html  # 40 products over 5 categories
    assert "مسح الكل" in html and CATEGORIES[0] + " ✕" in html
    _, empty = _get(shop, "/?q=zz-no-such-thing")
    assert "لا توجد منتجات مطابقة" in empty and "sm-empty" in empty


def test_card_shows_an_old_price_only_for_a_real_discount(shop):
    from flask import g

    from extensions import db
    from models.product import Product

    discounted, fake = shop["ids"][0], shop["ids"][1]
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        for pid, old in ((discounted, 999_000), (fake, 1)):  # an "old price" below the price is not a discount
            p = Product.query.execution_options(skip_branch_scope=True).get(pid)
            meta = json.loads(p.meta_json)
            meta["old_price"] = old
            p.meta_json = json.dumps(meta, ensure_ascii=False)
        db.session.commit()
    from modules.storefront.services.catalog_service import invalidate_catalog_cache

    invalidate_catalog_cache()
    _set_flag(shop, True)
    _, html = _get(shop, "/?q=V200000")
    assert "<s>999,000</s>" in html or "<s>999٬000</s>" in html or "<s>999000</s>" in html
    _, html_fake = _get(shop, "/?q=V200001")
    assert "<s>" not in html_fake.split('id="smAll"')[1]


def test_v2_product_page_cart_and_checkout_keep_their_working_hooks(shop):
    _set_flag(shop, True)
    pid = shop["ids"][5]
    status, html = _get(shop, f"/product/{pid}")
    assert status == 200 and 'class="sm-shell sm-pd"' in html
    for hook in ('id="sfMainImage"', 'id="sfQuantity"', 'id="sfAddForm"', f'data-sf-add-cart="{pid}"', '"@type": "Product"'):
        assert hook in html, hook
    assert "store-luxury.css" not in html  # the redesigned page does not pull the old style sheets
    res = shop["client"].post(f"/shop/{shop['tenant']}/api/cart/add", json={"product_id": pid, "quantity": 2},
                              headers={"X-Requested-With": "XMLHttpRequest"})
    assert res.status_code == 200 and res.get_json()["success"], res.get_data(as_text=True)[:200]
    status, cart = _get(shop, "/cart")
    assert status == 200 and 'id="luxCartPage"' in cart
    for hook in ("data-lux-cart-item", "data-lux-cart-qty-plus", "data-lux-cart-remove", 'id="luxCartNet"', "store-luxury.js"):
        assert hook in cart, hook
    status, checkout = _get(shop, "/checkout")
    assert status == 200 and "data-sm-checkout" in checkout and 'name="city"' in checkout
    assert "<option value=" in checkout.split('id="sfCheckoutCity"')[1].split("</select>")[0]


def test_an_order_placed_through_the_v2_checkout_reaches_finora_with_server_prices(shop):
    from flask import g

    from models.invoice import Invoice

    _set_flag(shop, True)
    pid = shop["ids"][6]
    shop["client"].post(f"/shop/{shop['tenant']}/api/cart/add", json={"product_id": pid, "quantity": 1},
                        headers={"X-Requested-With": "XMLHttpRequest"})
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        before = Invoice.query.execution_options(skip_branch_scope=True).count()
    res = shop["client"].post(f"/shop/{shop['tenant']}/checkout", data={
        "customer_name": "زبون تجربة", "phone": "07701234567", "city": "بغداد", "address": "الكرادة قرب الساحة",
        "notes": "", "price": "1"})  # a price sent by the browser must be ignored
    assert res.status_code in (302, 303), res.get_data(as_text=True)[:300]
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        invoices = Invoice.query.execution_options(skip_branch_scope=True).order_by(Invoice.id.desc()).all()
        assert len(invoices) == before + 1
        from models.product import Product

        product = Product.query.execution_options(skip_branch_scope=True).get(pid)
        assert invoices[0].total >= int(product.sale_price)  # the product price from the database, not "1"
