from types import SimpleNamespace

from routes.inventory import _collapse_shared_inventory_products


def _product(product_id, branch_id, group_id, *, sku="", barcode="", name="TV"):
    return SimpleNamespace(
        id=product_id,
        branch_id=branch_id,
        catalog_group_id=group_id,
        sku=sku,
        barcode=barcode,
        name=name,
    )


def test_inventory_collapse_merges_legacy_branch_copies_by_sku():
    products = [
        _product(31, 3, "legacy-group-c", sku="V6D55", name="شاشة تي سي ال 55 موديل V6D"),
        _product(11, 1, "legacy-group-a", sku="v6d55", name="شاشة تي سي ال 55 موديل V6D"),
        _product(21, 2, "legacy-group-b", sku=" V6D55 ", name="شاشة تي سي ال 55 موديل V6D"),
    ]

    rows, members = _collapse_shared_inventory_products(products)

    assert [product.id for product in rows] == [11]
    assert members[11] == [11, 21, 31]


def test_inventory_collapse_keeps_distinct_products_without_shared_identity():
    products = [
        _product(1, 1, "group-a", name="منتج أ"),
        _product(2, 2, "group-b", name="منتج ب"),
    ]

    rows, members = _collapse_shared_inventory_products(products)

    assert [product.id for product in rows] == [1, 2]
    assert members[1] == [1]
    assert members[2] == [2]


def test_inventory_collapse_keeps_family_together_after_barcode_and_sku_edit():
    products = [
        _product(24, 1, "washer-family", barcode="2909536325824", sku="NEW", name="Washer"),
        _product(147, 2, "washer-family", name="Washer"),
    ]
    rows, members = _collapse_shared_inventory_products(products)
    assert [product.id for product in rows] == [24]
    assert members == {24: [24, 147]}


def test_catalog_groups_link_legacy_identities_and_stable_families_transitively():
    from services.pos_catalog import shared_catalog_groups
    products = [
        _product(1, 1, "family-a", barcode="new-code"),
        _product(2, 2, "family-a", sku="OLD-SKU"),
        _product(3, 3, "legacy-family", sku="old-sku"),
        _product(4, 4, "separate-family", name="TV"),
    ]
    for ordered in [products, list(reversed(products))]:
        assert sorted(sorted(p.id for p in members) for members in shared_catalog_groups(ordered)) == [[1, 2, 3], [4]]


def test_catalog_groups_do_not_merge_same_names_or_different_barcode_products():
    from services.pos_catalog import shared_catalog_groups
    products = [
        _product(1, 1, "family-a", barcode="one", sku="common", name="TV"),
        _product(2, 2, "family-b", barcode="two", sku="common", name="TV"),
        _product(3, 3, "family-c", name="TV"),
    ]
    assert len(shared_catalog_groups(products)) == 3


def test_reused_barcode_keeps_lg_and_general_stock_and_names_separate():
    products = [
        _product(3, 1, "general", barcode="260101050", sku="003", name="شاشه جنرال حجم 50"),
        _product(10, 1, "lg", barcode="260101050", sku="010", name="شاشه الجي حجم 50"),
        _product(128, 2, "general", barcode="260101050", sku="003", name="شاشه جنرال حجم 50"),
        _product(135, 2, "lg", barcode="260101050", sku="010", name="شاشه الجي حجم 50"),
    ]
    for ordered in [products, list(reversed(products))]:
        rows, members = _collapse_shared_inventory_products(ordered)
        assert sorted(p.id for p in rows) == [3, 10]
        assert members == {3: [3, 128], 10: [10, 135]}


def test_ambiguous_legacy_bucket_does_not_merge_through_a_branch_copy():
    from services.pos_catalog import shared_catalog_groups
    products = [
        _product(1, 1, "a", barcode="reused"),
        _product(2, 2, "b", barcode="reused"),
        _product(3, 1, "c", barcode="reused"),
    ]
    for ordered in [products, list(reversed(products))]:
        assert len(shared_catalog_groups(ordered)) == 3


def test_barcode_fallback_preserves_legacy_copies_but_rejects_conflicting_skus():
    from services.pos_catalog import shared_catalog_groups
    products = [
        _product(1, 1, "a", barcode="legacy", sku="LG50"),
        _product(2, 2, "b", barcode="legacy", sku="lg50"),
    ]
    assert len(shared_catalog_groups(products)) == 1
    products[1].sku = "GENERAL50"
    assert len(shared_catalog_groups(products)) == 2
