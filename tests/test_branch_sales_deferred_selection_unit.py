"""Fast unit guard for deferred fulfillment-branch selection."""

from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def unpartitioned_stock(monkeypatch):
    """These pure units exercise legacy branch/color stock, with no database."""
    monkeypatch.setattr("modules.inventory_locations.lots.partitioned", lambda *_args: False)


def test_deferred_branch_selection_never_moves_physical_stock(monkeypatch):
    import utils.branch_sales as branch_sales

    active_branch = SimpleNamespace(id=22, name="Selected")
    fake_query = SimpleNamespace(
        filter_by=lambda **_kwargs: SimpleNamespace(first=lambda: active_branch)
    )
    monkeypatch.setattr(branch_sales, "Branch", SimpleNamespace(query=fake_query))
    monkeypatch.setattr("utils.branch_stock_service.get_available_branch_stock", lambda _branch, _product: 20)

    physical_calls = []
    monkeypatch.setattr(
        branch_sales,
        "receive_stock",
        lambda *args, **kwargs: physical_calls.append(("receive", args, kwargs)),
    )
    monkeypatch.setattr(
        branch_sales,
        "deduct_stock",
        lambda *args, **kwargs: physical_calls.append(("deduct", args, kwargs)),
    )

    item = SimpleNamespace(
        quantity=2,
        product_id=7,
        product_name="Protected item",
        product=None,
        fulfillment_branch_id=None,
        variant_color=None,
    )

    branch_sales.reassign_item_fulfillment_branch(
        item,
        active_branch.id,
        inventory_is_deducted=False,
    )

    assert item.fulfillment_branch_id == active_branch.id
    assert physical_calls == []


def test_branches_stock_for_product_caps_by_variant_color(monkeypatch):
    import utils.branch_sales as branch_sales

    branches = [
        SimpleNamespace(id=1, name="Main", code="M"),
        SimpleNamespace(id=2, name="Karrada", code="K"),
    ]
    monkeypatch.setattr(branch_sales, "active_branches_for_sales", lambda: branches)
    monkeypatch.setattr(
        "utils.branch_stock_service.get_available_branch_stock",
        lambda branch_id, _product_id: {1: 3, 2: 0}[int(branch_id)],
    )

    import utils.product_color_service as color_service
    import utils.branch_stock_service as stock_service

    monkeypatch.setattr(stock_service, "_branch_product_id", lambda branch_id, product_id: int(product_id))
    monkeypatch.setattr(color_service, "get_available_color_quantity", lambda _product_id, color: 1 if color == "ابيض" else 2)

    class _EmptyColorQuery:
        def filter_by(self, **_kwargs):
            return self

        def first(self):
            return None

    monkeypatch.setattr(
        "models.product_color_variant.ProductColorVariant",
        SimpleNamespace(query=_EmptyColorQuery()),
    )

    rows = branch_sales.branches_stock_for_product(99, "ابيض")
    assert [(row["id"], row["quantity"]) for row in rows] == [(1, 1), (2, 0)]

    rows_all = branch_sales.branches_stock_for_product(99)
    assert [(row["id"], row["quantity"]) for row in rows_all] == [(1, 3), (2, 0)]


def test_available_fulfillment_qty_prefers_local_color_row(monkeypatch):
    import utils.branch_sales as branch_sales
    import utils.branch_stock_service as stock_service
    import utils.product_color_service as color_service

    monkeypatch.setattr(stock_service, "get_available_branch_stock", lambda *_a: 5)
    monkeypatch.setattr(stock_service, "_branch_product_id", lambda branch_id, product_id: 20)
    monkeypatch.setattr(color_service, "get_available_color_quantity", lambda *_a, **_k: 99)
    monkeypatch.setattr("utils.desktop_stock_reservations.reserved_for_stock", lambda *_a: 0)

    class _LocalQuery:
        def filter_by(self, **kwargs):
            self.kwargs = kwargs
            return self

        def first(self):
            return SimpleNamespace(id=1, quantity=2)

    monkeypatch.setattr(
        "models.product_color_variant.ProductColorVariant",
        SimpleNamespace(query=_LocalQuery()),
    )

    assert branch_sales.available_fulfillment_qty(3, 10, "ابيض") == 2


def test_deferred_color_branch_selection_rejects_mixed_total(monkeypatch):
    import utils.branch_sales as branch_sales
    import utils.branch_stock_service as stock_service

    active_branch = SimpleNamespace(id=22, name="Main")
    fake_query = SimpleNamespace(
        filter_by=lambda **_kwargs: SimpleNamespace(first=lambda: active_branch)
    )
    monkeypatch.setattr(branch_sales, "Branch", SimpleNamespace(query=fake_query))
    monkeypatch.setattr(stock_service, "get_available_branch_stock", lambda _branch, _product: 3)
    monkeypatch.setattr(stock_service, "_branch_product_id", lambda branch_id, product_id: int(product_id))

    import utils.product_color_service as color_service

    monkeypatch.setattr(color_service, "get_available_color_quantity", lambda *_args, **_kwargs: 1)

    class _EmptyColorQuery:
        def filter_by(self, **_kwargs):
            return self

        def first(self):
            return None

    monkeypatch.setattr(
        "models.product_color_variant.ProductColorVariant",
        SimpleNamespace(query=_EmptyColorQuery()),
    )

    item = SimpleNamespace(
        quantity=2,
        product_id=7,
        product_name="Fridge",
        product=None,
        fulfillment_branch_id=None,
        variant_color="ابيض",
    )

    with pytest.raises(branch_sales.BranchStockError) as exc:
        branch_sales.reassign_item_fulfillment_branch(
            item,
            active_branch.id,
            inventory_is_deducted=False,
        )
    assert "المتاح: 1" in str(exc.value)


def test_deducted_order_branch_change_moves_one_reservation(monkeypatch):
    import utils.branch_sales as branch_sales
    import utils.stock_movement_guard as movement_guard

    active_branch = SimpleNamespace(id=22, name="Selected")
    fake_query = SimpleNamespace(
        filter_by=lambda **_kwargs: SimpleNamespace(first=lambda: active_branch)
    )
    monkeypatch.setattr(branch_sales, "Branch", SimpleNamespace(query=fake_query))
    monkeypatch.setattr(branch_sales, "get_branch_stock", lambda _branch, _product: 20)
    monkeypatch.setattr(
        movement_guard,
        "claim_stock_movement",
        lambda *args, **kwargs: SimpleNamespace(applied=True),
    )

    physical_calls = []
    monkeypatch.setattr(
        branch_sales,
        "receive_stock",
        lambda *args, **kwargs: physical_calls.append(("receive", args, kwargs)),
    )
    monkeypatch.setattr(
        branch_sales,
        "deduct_stock",
        lambda *args, **kwargs: physical_calls.append(("deduct", args, kwargs)),
    )

    item = SimpleNamespace(
        id=9,
        invoice_id=55,
        quantity=2,
        product_id=7,
        cost=100,
        product_name="Protected item",
        product=None,
        fulfillment_branch_id=11,
    )

    branch_sales.reassign_item_fulfillment_branch(
        item,
        active_branch.id,
        inventory_is_deducted=True,
    )

    assert item.fulfillment_branch_id == active_branch.id
    assert [(kind, args) for kind, args, _kwargs in physical_calls] == [
        ("receive", (11, 7, 2)),
        ("deduct", (22, 7, 2)),
    ]


def test_shipping_branch_movement_rejects_untracked_inventory():
    from utils.branch_stock_service import BranchStockError
    from utils.shipping_branch_schedule import apply_shipping_branch_schedule

    deferred_order = SimpleNamespace(
        id=99,
        status="تم الطلب",
        stock_is_deducted=False,
    )

    with pytest.raises(BranchStockError, match="قبل تسجيل خصمه"):
        apply_shipping_branch_schedule(
            deferred_order,
            previous_status="تم الطلب",
        )


def test_branch_stock_reads_legacy_product_quantity_for_its_own_branch(monkeypatch):
    """A legacy product without a BranchStock row must not appear as zero."""
    import utils.branch_stock_service as stock_service

    product = SimpleNamespace(
        id=7,
        branch_id=3,
        catalog_group_id="",
        quantity=5,
        opening_stock=0,
    )

    class EmptyQuery:
        def execution_options(self, **_kwargs):
            return self

        def get(self, _product_id):
            return product

        def filter_by(self, **_kwargs):
            return self

        def first(self):
            return None

    monkeypatch.setattr(stock_service, "Product", SimpleNamespace(query=EmptyQuery()))
    monkeypatch.setattr(stock_service, "BranchStock", SimpleNamespace(query=EmptyQuery()))
    monkeypatch.setattr(
        stock_service,
        "Branch",
        SimpleNamespace(query=SimpleNamespace(filter_by=lambda **_kwargs: SimpleNamespace(first=lambda: None))),
    )

    assert stock_service.get_branch_stock(3, product.id) == 5
    assert stock_service.get_branch_stock(4, product.id) == 0
