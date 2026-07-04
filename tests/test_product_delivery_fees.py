"""Unit tests for per-product delivery fee calculation."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.product_delivery_fees import (
    apply_delivery_fees_to_meta,
    delivery_fees_from_form,
    fee_for_cart_items,
    fee_for_product,
    product_delivery_config,
)


class _FakeForm:
    def __init__(self, data: dict):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def getlist(self, key):
        value = self._data.get(key, [])
        if isinstance(value, list):
            return value
        return [value]


def _product(meta: dict | None = None, shipping_cost: int = 0):
    return SimpleNamespace(
        meta_json=json.dumps(meta or {}, ensure_ascii=False) if meta else None,
        shipping_cost=shipping_cost,
        name="منتج تجريبي",
        id=1,
    )


def test_fee_for_product_uses_province_specific_fee():
    product = _product(
        {
            "delivery_by_province": {"بغداد": 3000, "البصرة": 5000},
            "delivery_default_fee": 4000,
        }
    )
    assert fee_for_product(product, "بغداد") == 3000
    assert fee_for_product(product, "البصرة") == 5000


def test_fee_for_product_uses_default_when_province_missing():
    product = _product({"delivery_by_province": {"بغداد": 3000}, "delivery_default_fee": 4500})
    assert fee_for_product(product, "أربيل") == 4500


def test_fee_for_product_uses_shipping_cost_when_no_meta_default():
    product = _product({"delivery_by_province": {"بغداد": 3000}}, shipping_cost=2500)
    assert fee_for_product(product, "أربيل") == 2500


def test_fee_for_cart_items_sums_qty_times_fee():
    products = {
        1: _product({"delivery_by_province": {"بغداد": 2000}}, shipping_cost=0),
        2: _product({"delivery_by_province": {"بغداد": 5000}}, shipping_cost=0),
    }
    products[1].id = 1
    products[2].id = 2

    class _Query:
        @staticmethod
        def get(product_id):
            return products.get(product_id)

    original = __import__("utils.product_delivery_fees", fromlist=["Product"]).Product
    import utils.product_delivery_fees as module

    module.Product = _Query
    try:
        total, breakdown = fee_for_cart_items(
            [{"product_id": 1, "qty": 2}, {"product_id": 2, "qty": 1}],
            "بغداد",
            products,
        )
    finally:
        module.Product = original

    assert total == 9000
    assert len(breakdown) == 2
    assert breakdown[0]["line_fee"] == 4000
    assert breakdown[1]["line_fee"] == 5000


def test_delivery_fees_from_form_uses_default_for_empty_province():
    form = _FakeForm(
        {
            "delivery_province_name": ["بغداد", "البصرة"],
            "delivery_province_fee": ["", "5000"],
            "delivery_default_fee": "6000",
        }
    )
    by_province, default_fee = delivery_fees_from_form(form)
    assert by_province["بغداد"] == 6000
    assert by_province["البصرة"] == 5000
    assert default_fee == 6000


def test_delivery_fees_from_form_saves_all_provinces():
    form = _FakeForm(
        {
            "delivery_province_name": ["بغداد"],
            "delivery_province_fee": ["3000"],
            "delivery_default_fee": "6000",
        }
    )
    by_province, _ = delivery_fees_from_form(form, ["بغداد", "البصرة", "نينوى"])
    assert by_province["بغداد"] == 3000
    assert by_province["البصرة"] == 6000
    assert by_province["نينوى"] == 6000


def test_delivery_fees_from_form_pairs_names_and_values():
    form = _FakeForm(
        {
            "delivery_province_name": ["بغداد", "البصرة"],
            "delivery_province_fee": ["3000", "5000"],
            "delivery_default_fee": "4000",
        }
    )
    by_province, default_fee = delivery_fees_from_form(form)
    assert by_province == {"بغداد": 3000, "البصرة": 5000}
    assert default_fee == 4000


def test_apply_delivery_fees_to_meta_clears_empty_values():
    meta = apply_delivery_fees_to_meta({"brand": "X"}, {}, 0)
    assert "delivery_by_province" not in meta
    assert "delivery_default_fee" not in meta
    assert meta["brand"] == "X"


def test_product_delivery_config_reads_meta():
    product = _product({"delivery_by_province": {"بغداد": 1000}, "delivery_default_fee": 2000})
    cfg = product_delivery_config(product)
    assert cfg["delivery_by_province"]["بغداد"] == 1000
    assert cfg["delivery_default_fee"] == 2000


def test_get_shipping_fee_from_invoice_reads_line_item():
    from utils.order_shipping import SHIPPING_BARCODE, SHIPPING_PRODUCT_NAME, get_shipping_fee_from_invoice

    invoice = SimpleNamespace(
        order_items=[
            SimpleNamespace(
                product_name=SHIPPING_PRODUCT_NAME,
                product=SimpleNamespace(barcode=SHIPPING_BARCODE),
                total=7500,
                cost=0,
            )
        ]
    )
    assert get_shipping_fee_from_invoice(invoice) == 7500


def test_get_shipping_fee_from_invoice_reads_cost_when_total_zero():
    from utils.order_shipping import SHIPPING_BARCODE, SHIPPING_PRODUCT_NAME, get_shipping_fee_from_invoice

    invoice = SimpleNamespace(
        order_items=[
            SimpleNamespace(
                product_name=SHIPPING_PRODUCT_NAME,
                product=SimpleNamespace(barcode=SHIPPING_BARCODE),
                total=0,
                cost=15000,
            )
        ]
    )
    assert get_shipping_fee_from_invoice(invoice) == 15000


def test_prepare_invoice_items_hides_shipping_and_deducts_legacy():
    from utils.order_shipping import SHIPPING_PRODUCT_NAME, prepare_invoice_items_for_print

    items = [
        SimpleNamespace(product_name="غسالة", quantity=1, price=195000, total=195000, product=None),
        SimpleNamespace(product_name=SHIPPING_PRODUCT_NAME, quantity=1, price=15000, total=15000, cost=0, product=None),
    ]
    printable, total = prepare_invoice_items_for_print(items)
    assert len(printable) == 1
    assert printable[0].total == 180000
    assert printable[0].price == 180000
    assert total == 180000


if __name__ == "__main__":
    test_fee_for_product_uses_province_specific_fee()
    test_fee_for_product_uses_default_when_province_missing()
    test_fee_for_product_uses_shipping_cost_when_no_meta_default()
    test_fee_for_cart_items_sums_qty_times_fee()
    test_delivery_fees_from_form_pairs_names_and_values()
    test_apply_delivery_fees_to_meta_clears_empty_values()
    test_product_delivery_config_reads_meta()
    test_get_shipping_fee_from_invoice_reads_line_item()
    print("all product delivery fee tests ok")
