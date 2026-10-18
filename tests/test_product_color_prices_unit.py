"""Unit coverage for per-color buy/sale prices."""

from types import SimpleNamespace


def test_parse_color_row_supports_prices():
    from utils.product_color_service import _parse_color_row

    name, qty, buy, sale = _parse_color_row(("أبيض", 3, 140000, 175000))
    assert name == "أبيض"
    assert qty == 3
    assert buy == 140000
    assert sale == 175000

    name, qty, buy, sale = _parse_color_row({"name": "أسود", "qty": 2, "buy_price": 150000, "sale_price": 190000})
    assert name == "أسود"
    assert qty == 2
    assert buy == 150000
    assert sale == 190000


def test_effective_color_prices_fallback_to_product():
    from utils.product_color_service import effective_color_buy_price, effective_color_sale_price

    product = SimpleNamespace(buy_price=100, sale_price=200)
    variant_unset = SimpleNamespace(buy_price=None, sale_price=None)
    variant_set = SimpleNamespace(buy_price=111, sale_price=222)

    assert effective_color_buy_price(product, variant=variant_unset) == 100
    assert effective_color_sale_price(product, variant=variant_unset) == 200
    assert effective_color_buy_price(product, variant=variant_set) == 111
    assert effective_color_sale_price(product, variant=variant_set) == 222
