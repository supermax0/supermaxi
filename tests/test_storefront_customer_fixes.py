"""Customer-facing fixes: no «بيع / استبدال» online, colour / size chosen on the product page (never a prompt),
a tidy account page, real terms / about pages, long cache for versioned static files."""
from __future__ import annotations

import json
import re
from pathlib import Path

from tests.test_branch_management_api import app  # noqa: F401
from tests.test_recommendations import shop  # noqa: F401

AJAX = {"X-Requested-With": "XMLHttpRequest"}
ROOT = Path(__file__).resolve().parents[1]


def _colored_product(shop, *, exchange_price: int = 0) -> int:
    from flask import g

    from extensions import db
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from modules.search import engine
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from utils.branch_migration import get_default_branch

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        p = Product(name="ثلاجة بيكو 18 قدم", sku="BK18", buy_price=1, sale_price=700_000, quantity=3, active=True,
                    store_visible=True, branch_id=get_default_branch().id,
                    meta_json=json.dumps({"category": "ثلاجات", "has_colors": True}, ensure_ascii=False))
        if exchange_price:
            p.exchange_sale_price = exchange_price
        db.session.add(p)
        db.session.flush()
        db.session.add_all([ProductColorVariant(product_id=p.id, color_name="أبيض", quantity=2),
                            ProductColorVariant(product_id=p.id, color_name="فضي", quantity=1)])
        db.session.commit()
        pid = p.id
    invalidate_catalog_cache()
    engine.invalidate()
    return pid


def test_online_orders_are_always_a_normal_sale(shop, monkeypatch):
    import utils.trade_in_service as trade_in

    monkeypatch.setattr(trade_in, "tenant_feature_enabled", lambda *a, **k: True)  # the shop sells «استبدال» in store
    from flask import g

    from extensions import db
    from models.product import Product

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        db.session.get(Product, shop["tv50"]).exchange_sale_price = 800_000
        db.session.commit()
    c = shop["client"]
    res = c.post(f"/shop/{shop['tenant']}/api/cart/add", headers=AJAX,
                 json={"product_id": shop["tv50"], "quantity": 1, "sale_mode": "exchange"})
    item = res.get_json()["cart"]["items"][0]
    assert res.status_code == 200 and item["sale_mode"] == "normal" and item["price"] == 950_000
    js = (ROOT / "static/storefront/js/store.js").read_text(encoding="utf-8")
    assert "prompt(" not in js and "بيع أو استبدال" not in js


def test_colour_is_chosen_on_the_product_page_not_from_the_card(shop):
    pid = _colored_product(shop)
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    listing = c.get(f"{base}/?badge=" + "ثلاجات").get_data(as_text=True)
    card = listing.split(f'data-product-id="{pid}"', 1)[1].split("</article>", 1)[0]
    assert "اختر اللون" in card and f'data-sf-add-cart="{pid}"' not in card
    page = c.get(f"{base}/product/{pid}").get_data(as_text=True)
    assert "data-sf-color-picker" in page and "أبيض" in page and "فضي" in page
    # without a colour the server refuses; with one it is added
    assert c.post(f"{base}/api/cart/add", json={"product_id": pid}, headers=AJAX).status_code == 400
    ok = c.post(f"{base}/api/cart/add", json={"product_id": pid, "color": "فضي"}, headers=AJAX).get_json()
    assert ok["success"] and ok["cart"]["items"][0]["color"] == "فضي"


def test_account_page_signed_out_and_signed_in(shop):
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    html = c.get(f"{base}/account").get_data(as_text=True)
    assert "الحساب اختياري" in html and 'id="smRegister"' in html and "متجر الأقساط" not in html
    assert re.search(r'id="smRegister"[^>]*hidden', html)  # one form at a time
    from flask import g
    from werkzeug.security import generate_password_hash

    from extensions import db
    from models.customer import Customer
    from models.tenant import Tenant
    from modules.installments.models import InstallmentCustomerAccount
    from routes.storefront import _account_session_key
    from utils.branch_migration import get_default_branch

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        company = Tenant.query.first() or Tenant(name="شركة تجربة")
        db.session.add(company)
        db.session.flush()
        customer = Customer(name="علي حسن محمد كاظم", phone="07701239876", tenant_id=company.id,
                            branch_id=get_default_branch().id)
        db.session.add(customer)
        db.session.flush()
        account = InstallmentCustomerAccount(tenant_id=company.id, customer_id=customer.id, phone="07701239876",
                                             password_hash=generate_password_hash("secret-pass-1"))
        db.session.add(account)
        db.session.commit()
        account_id, company_id = account.id, company.id
        customer = db.session.get(Customer, customer.id)
    with c.session_transaction() as sess:
        sess[_account_session_key(shop["tenant"])] = account_id
        sess["tenant_id"] = company_id
    from models.invoice import Invoice
    from models.order_item import OrderItem

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        inv = Invoice(customer_id=customer.id, customer_name=customer.name, branch_id=get_default_branch().id,
                      total=1_000_000, status="تم الطلب", payment_status="غير مسدد")
        db.session.add(inv)
        db.session.flush()
        db.session.add(OrderItem(invoice_id=inv.id, product_id=shop["tv55"], product_name="شاشة سامسونج 55 بوصة",
                                 price=1_000_000, quantity=1, cost=1, total=1_000_000))
        db.session.commit()
    html = c.get(f"{base}/account").get_data(as_text=True)
    main = html.split('id="smMain"', 1)[1]
    assert "علي حسن محمد كاظم" in main, main[:1500]
    assert "طلباتي" in main and "شاشة سامسونج 55 بوصة" in main, main[:3000]
    assert "تفاصيل وتتبع" in html and "تسجيل الخروج" in html and "تم استلام الطلب" in html


def test_terms_about_and_faq_are_customer_pages(shop):
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    terms = c.get(f"{base}/terms").get_data(as_text=True)
    for heading in ("الطلب وتأكيده", "الأسعار والتوفر", "الدفع", "التوصيل", "الفحص والاستلام",
                    "الإرجاع والاستبدال والضمان", "إلغاء الطلب", "الخصوصية"):
        assert heading in terms
    assert 'href="#returns"' in terms and "يتم في المعرض فقط" in terms
    about = c.get(f"{base}/about").get_data(as_text=True)
    assert "الدفع عند الاستلام" in about and "كتالوج" not in about and "متجر الأقساط" not in about
    faq = c.get(f"{base}/faq").get_data(as_text=True)
    assert faq.count("<details") >= 6
    from flask import g

    from extensions import db
    from models.system_settings import SystemSettings

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        s = SystemSettings.get_settings()
        flags = s.get_ui_flags()
        flags["storefront_returns_policy"] = "يمكن إرجاع الجهاز خلال 3 أيام بكارتونه الأصلي."
        s.set_ui_flags(flags)
        db.session.commit()
    assert "خلال 3 أيام بكارتونه الأصلي" in c.get(f"{base}/terms").get_data(as_text=True)  # the owner's own text


def test_versioned_static_files_are_cached_for_a_year(shop):
    c = shop["app"].test_client()
    versioned = c.get("/static/storefront/js/store-v2.js?v=20261017")
    assert versioned.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    plain = c.get("/static/storefront/js/store-v2.js")
    assert "immutable" not in (plain.headers.get("Cache-Control") or "")


def test_store_switch_hides_a_product_published_for_installments(shop):
    """A shop with a shared installment catalogue: «إظهار في المتجر» off must hide the product online too."""
    from flask import g

    from extensions import db
    from models.product import Product
    from models.tenant import Tenant
    from modules.installments.models import InstallmentProduct
    from modules.search import engine
    from modules.storefront.services.catalog_service import invalidate_catalog_cache
    from routes import storefront as sf

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        company = Tenant.query.first() or Tenant(name="شركة تجربة")
        db.session.add(company)
        db.session.flush()
        for key, title in (("tv55", "شاشة سامسونج 55 بوصة"), ("tv50", "شاشة ال جي 50 بوصة")):
            db.session.add(InstallmentProduct(tenant_id=company.id, product_id=shop[key], title=title, slug=key,
                                              cash_price=1_000_000, status="published"))
        db.session.get(Product, shop["tv50"]).store_visible = False  # the owner switched it off
        db.session.commit()
    invalidate_catalog_cache()
    engine.invalidate()
    sf._PAGE_CACHE.clear()
    c = shop["app"].test_client()
    base = f"/shop/{shop['tenant']}"
    listing = c.get(f"{base}/?sort=name_asc").get_data(as_text=True)
    assert f'data-product-id="{shop["tv55"]}"' in listing and f'data-product-id="{shop["tv50"]}"' not in listing
    assert c.get(f"{base}/product/{shop['tv50']}").status_code == 404
    found = c.get(f"{base}/api/products?q=" + "ال جي").get_json()
    assert shop["tv50"] not in [p["id"] for p in found.get("products") or found.get("rows") or []]
    assert c.post(f"{base}/api/cart/add", json={"product_id": shop["tv50"]}, headers=AJAX).status_code == 400
    sf._PAGE_CACHE.clear()
