from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from routes.purchases import (
    _shared_purchase_products,
    _supplier_allowed_for_purchase_branch,
)


def _product(product_id, branch_id, group_id, *, sku="", barcode="", name="TV"):
    return SimpleNamespace(
        id=product_id,
        branch_id=branch_id,
        catalog_group_id=group_id,
        sku=sku,
        barcode=barcode,
        name=name,
    )


def test_shared_purchase_picker_merges_legacy_branch_copies_by_sku():
    products = [
        _product(31, 3, "legacy-group-c", sku="V6D55", name="شاشة تي سي ال 55 موديل V6D"),
        _product(11, 1, "legacy-group-a", sku="v6d55", name="شاشة تي سي ال 55 موديل V6D"),
        _product(21, 2, "legacy-group-b", sku=" V6D55 ", name="شاشة تي سي ال 55 موديل V6D"),
    ]

    result = _shared_purchase_products(products)

    assert [product.id for product in result] == [11]


def test_shared_purchase_picker_keeps_distinct_products_without_shared_identity():
    products = [
        _product(1, 1, "group-a", name="منتج أ"),
        _product(2, 2, "group-b", name="منتج ب"),
    ]

    assert [product.id for product in _shared_purchase_products(products)] == [1, 2]


def test_shared_purchase_picker_keeps_edited_branch_copy_in_one_family():
    products = [_product(24, 1, "washer-family", barcode="NEW"), _product(147, 2, "washer-family")]
    assert [product.id for product in _shared_purchase_products(products)] == [24]


def test_purchase_form_always_offers_real_inventory_branches():
    template = (
        Path(__file__).resolve().parents[1] / "templates" / "purchases_form.html"
    ).read_text(encoding="utf-8")
    select_start = template.index('<select id="branchId"')
    select_end = template.index("</select>", select_start)
    branch_select = template[select_start:select_end]

    assert "{% for b in branches %}" in branch_select
    assert "مشترك — الفروع كلها تستخدم نفس البيانات" not in branch_select
    assert 'id="branchId" required' in branch_select


def test_shared_supplier_can_be_used_for_stock_received_at_another_branch():
    supplier = SimpleNamespace(id=7, branch_id=1, name="مورد مشترك")

    with patch("routes.purchases.independent_branches_enabled", return_value=False):
        assert _supplier_allowed_for_purchase_branch(supplier, branch_id=2) is True


def test_independent_supplier_cannot_be_used_at_another_branch():
    supplier = SimpleNamespace(id=7, branch_id=1, name="مورد فرع")

    with patch("routes.purchases.independent_branches_enabled", return_value=True):
        assert _supplier_allowed_for_purchase_branch(supplier, branch_id=2) is False
