from types import SimpleNamespace

from modules.storefront.services.ai_assistant_service import (
    _compact_reply,
    _fallback_reply,
    _foot_size_reply,
    _should_show_product_cards,
)
from modules.storefront.services.inventory_knowledge import _nearest_foot_products


def test_compact_reply_removes_raw_links_and_limits_long_answers():
    long_reply = (
        "أكيد، هذا هو المنتج المناسب إلك https://example.com/product/1 "
        + "تفاصيل إضافية كثيرة " * 30
    )

    reply = _compact_reply(long_reply, has_products=True)

    assert "http" not in reply
    assert len(reply) <= 191
    assert reply.endswith("…")


def test_product_cards_only_appear_after_explicit_visual_request():
    products = [SimpleNamespace(name="ثلاجة هاير أربعة أبواب 536 لتر")]

    assert _should_show_product_cards("عندكم ثلاجة هاير؟", products) is False
    assert _should_show_product_cards("شكد سعر ثلاجة هاير؟", products) is False
    assert _should_show_product_cards("أريد شاشة 32", products) is False
    assert _should_show_product_cards("دزلي صورتها", products) is True
    assert _should_show_product_cards("أريد أشوف ثلاجة هاير", products) is True
    assert _should_show_product_cards("ممكن أشوفها؟", products) is True
    assert _should_show_product_cards("اعرضلي تفاصيل المنتج", products) is True
    assert _should_show_product_cards("شنو رسوم التوصيل؟", products) is False
    assert _should_show_product_cards("أريد أتتبع طلبي", products) is False


def test_fallback_product_reply_does_not_repeat_catalog_names():
    products = [
        {"name": "ثلاجة هاير 536 لتر"},
        {"name": "مجمدة 12 قدم"},
    ]

    reply = _fallback_reply("المنتجات المتوفرة", products, {}, None)

    assert "ثلاجة هاير" not in reply
    assert "مجمدة" not in reply
    assert len(reply) < 130


def _product(name, quantity=1):
    return SimpleNamespace(
        name=name,
        quantity=quantity,
        catalog_category="",
        description="",
    )


def test_nearest_foot_size_keeps_the_requested_product_family():
    products = [
        _product("ثلاجة هاير 12 قدم"),
        _product("ثلاجة سامسونج 18 قدم"),
        _product("مجمدة أفقية 20 قدم"),
        _product("براد ماء 22 قدم"),
    ]

    matched = _nearest_foot_products(products, "شعندك ثلاجه 22 قدم")

    assert [product.name for product in matched] == ["ثلاجة سامسونج 18 قدم"]


def test_nearest_foot_size_prefers_larger_size_when_distance_is_equal():
    products = [
        _product("ثلاجة 12 قدم"),
        _product("ثلاجة 18 قدم"),
    ]

    matched = _nearest_foot_products(products, "ثلاجة 15 قدم")

    assert [product.name for product in matched] == ["ثلاجة 18 قدم"]
    assert _foot_size_reply("ثلاجة 15 قدم", matched) == (
        "قياس 15 قدم مو متوفر حالياً، أقرب حجم موجود هو 18 قدم 👇"
    )
