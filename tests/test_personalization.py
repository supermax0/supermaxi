"""Smart Commerce Sprint 9: interests from shopping signals, personalised home sections, privacy controls.

Acceptance: the shop works with and without data, a single glance does not reshape the page, and switching off /
Global Privacy Control / clearing are respected."""
from __future__ import annotations

from tests.test_branch_management_api import _client, _json, app  # noqa: F401
from tests.test_recommendations import API as REC_API
from tests.test_recommendations import shop  # noqa: F401

AJAX = {"X-Requested-With": "XMLHttpRequest"}


def _events(shop, **filters):
    from flask import g

    from modules.personalization.models import StoreEvent

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        try:
            return StoreEvent.query.filter_by(**filters).count()
        except Exception:
            return 0


def _home(client, shop):
    return client.get(f"/shop/{shop['tenant']}/").get_data(as_text=True)


def test_without_data_the_home_page_shows_the_general_sections(shop):
    html = _home(shop["client"], shop)
    assert "مقترح لك" not in html and "مكمّلات لمشترياتك" not in html
    assert "منتجات ضمن ميزانيتك" in html and "الخصوصية والتخصيص" in html


def test_one_glance_is_weak_repeated_interest_is_strong(shop):
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    c.get(f"{base}/product/{shop['tv55']}")
    assert "مقترح لك" not in _home(c, shop)  # one view = 1 point, not enough
    c.post(f"{base}/favorites/{shop['tv55']}/toggle", headers=AJAX)
    html = _home(c, shop)
    assert "مقترح لك في شاشات" in html and "لماذا أرى هذا؟" in html
    section = html.split("مقترح لك في شاشات", 1)[1].split("</section>", 1)[0]
    assert "شاشة ال جي 50 بوصة" in section  # an available screen the shopper has not opened yet
    assert "شاشة سامسونج 55 بوصة" not in section  # just viewed: not suggested again
    assert "شاشة هايسنس" not in section  # out of stock is never suggested
    assert _events(shop, event_type="view") == 1 and _events(shop, event_type="favorite") == 1


def test_a_typed_budget_becomes_a_section(shop):
    c = shop["client"]
    c.get(f"/shop/{shop['tenant']}/?q=" + "شاشة بأقل من مليون")
    html = _home(c, shop)
    assert "ضمن ميزانيتك (حتى 1,000,000 د.ع)" in html and "تسوّق بميزانية أخرى" in html
    section = html.split("ضمن ميزانيتك (حتى", 1)[1].split("</section>", 1)[0]
    assert "شاشة سامسونج 65" not in section  # 1.3M is over the budget
    info = c.get(f"/shop/{shop['tenant']}/personalization").get_data(as_text=True)
    assert "شاشة بأقل من مليون" in info and "1,000,000" in info


def test_after_buying_a_screen_its_accessories_replace_more_screens(shop):
    admin = _client(shop)
    _json(admin.post(f"{REC_API}/relations", json={"source_product_id": shop["tv55"], "target_product_id": shop["stand"],
                                                    "relation_type": "accessory", "verified": True}))
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    c.post(f"{base}/favorites/{shop['tv50']}/toggle", headers=AJAX)
    c.post(f"{base}/api/cart/add", json={"product_id": shop["tv55"], "quantity": 1}, headers=AJAX)
    res = c.post(f"{base}/checkout", data={"customer_name": "زبون تجربة", "phone": "07701112233", "city": "بغداد",
                                          "address": "الكرادة"})
    assert res.status_code == 302 and "order-success" in res.headers["Location"]
    html = _home(c, shop)
    assert "مكمّلات لمشترياتك" in html and "حامل شاشة جداري" in html
    assert "مقترح لك في شاشات" not in html  # just bought a screen: no wall of screens
    assert _events(shop, event_type="purchase") == 1


def test_switching_off_forgets_and_stops_recording(shop):
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    c.get(f"{base}/product/{shop['tv55']}")
    c.post(f"{base}/favorites/{shop['tv55']}/toggle", headers=AJAX)
    assert "مقترح لك" in _home(c, shop)
    res = c.post(f"{base}/personalization", data={"action": "off"})
    assert res.status_code == 302
    before = _events(shop)
    c.get(f"{base}/product/{shop['tv50']}")
    c.post(f"{base}/api/cart/add", json={"product_id": shop["tv50"], "quantity": 1}, headers=AJAX)
    assert _events(shop) == before  # nothing recorded while off
    html = _home(c, shop)
    assert "مقترح لك" not in html and "data-sm-recent" not in html and '"personalize": false' not in html
    assert "personalize: false" in html  # the browser script also forgets its local history
    assert "التخصيص: متوقف" in c.get(f"{base}/personalization").get_data(as_text=True)
    on = c.post(f"{base}/personalization", json={"action": "on"}).get_json()
    assert on["enabled"] is True and on["interests"] == []  # switching back on starts from nothing


def test_clear_history_and_global_privacy_control(shop):
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    c.get(f"{base}/?q=" + "غسالة")
    c.post(f"{base}/favorites/{shop['tv55']}/toggle", headers=AJAX)
    info = c.post(f"{base}/personalization", json={"action": "clear"}).get_json()
    assert info["enabled"] is True and info["interests"] == [] and info["searches"] == []
    gpc = shop["app"].test_client()
    before = _events(shop)
    gpc.get(f"{base}/product/{shop['tv55']}", headers={"Sec-GPC": "1"})
    assert _events(shop) == before
    assert "التخصيص: متوقف" in gpc.get(f"{base}/personalization", headers={"Sec-GPC": "1"}).get_data(as_text=True)
    assert c.post(f"{base}/personalization", data={"action": "hack"}).status_code == 400


def test_events_api_and_anonymous_rows(shop):
    c = shop["client"]
    base = f"/shop/{shop['tenant']}"
    assert c.post(f"{base}/api/events", json={"type": "rec_click", "product_id": shop["stand"], "section": "accessories"}).status_code == 200
    assert c.post(f"{base}/api/events", json={"type": "compare", "product_id": shop["tv55"]}).status_code == 200
    assert c.post(f"{base}/api/events", json={"type": "purchase", "product_id": shop["tv55"]}).status_code == 400
    assert _events(shop, event_type="rec_click", value="accessories") == 1
    from modules.personalization.models import StoreEvent

    assert set(StoreEvent.__table__.columns.keys()) == {"id", "sid", "event_type", "product_id", "category", "value", "created_at"}


def test_store_script_never_shadows_its_own_functions():
    """Regression: a top-level ``var recent`` once replaced ``function recent()`` and broke recent searches."""
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "static/storefront/js/store-v2.js").read_text(encoding="utf-8")
    functions = set(re.findall(r"^  function (\w+)\(", js, re.M))
    top_vars = set(re.findall(r"^  var (\w+)\s*=", js, re.M))
    assert functions and not (functions & top_vars)


def test_stores_on_the_old_design_record_nothing(shop):
    from flask import g

    from extensions import db
    from models.system_settings import SystemSettings

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags()
        flags["storefront_v2"] = False
        settings.set_ui_flags(flags)
        db.session.commit()
    c = shop["client"]
    c.get(f"/shop/{shop['tenant']}/product/{shop['tv55']}")
    c.post(f"/shop/{shop['tenant']}/favorites/{shop['tv55']}/toggle", headers=AJAX)
    assert _events(shop) == 0
