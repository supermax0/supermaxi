"""Fast purchase movement tests without tenant database startup."""

from types import SimpleNamespace


def _purchase_fixture():
    product = SimpleNamespace(id=7, name="Protected", quantity=0)
    purchase = SimpleNamespace(id=10, stock_revision=2)
    item = SimpleNamespace(
        id=11,
        product_id=product.id,
        product=product,
        quantity=51,
        final_unit_cost=100,
        variant_color=None,
    )
    return purchase, item


def test_allocate_purchase_stock_revision_skips_orphaned_keys(monkeypatch):
    import routes.purchases as purchases

    monkeypatch.setattr(
        purchases,
        "_max_recorded_purchase_stock_revision",
        lambda _purchase_id: 1,
    )
    assert purchases._allocate_purchase_stock_revision(83) == 2
    assert purchases._allocate_purchase_stock_revision(83, at_least=5) == 5


def test_allocate_purchase_stock_revision_starts_at_one(monkeypatch):
    import routes.purchases as purchases

    monkeypatch.setattr(
        purchases,
        "_max_recorded_purchase_stock_revision",
        lambda _purchase_id: 0,
    )
    assert purchases._allocate_purchase_stock_revision(83) == 1

    import routes.purchases as purchases

    purchase, item = _purchase_fixture()
    received = []
    captured_keys = []
    monkeypatch.setattr(
        purchases,
        "claim_stock_movement",
        lambda key, **_kwargs: (
            captured_keys.append(key) or SimpleNamespace(applied=False)
        ),
    )
    monkeypatch.setattr(
        purchases,
        "receive_stock",
        lambda *args: received.append(args),
    )

    applied = purchases._apply_purchase_item_stock(
        purchase,
        item,
        branch_id=3,
        apply_stock=True,
    )

    assert applied is False
    assert received == []
    assert captured_keys == ["purchase:10:revision:2:item:11:receive"]


def test_new_purchase_receive_changes_stock_once(monkeypatch):
    import routes.purchases as purchases

    purchase, item = _purchase_fixture()
    received = []
    monkeypatch.setattr(
        purchases,
        "claim_stock_movement",
        lambda *_args, **_kwargs: SimpleNamespace(applied=True),
    )
    monkeypatch.setattr(
        purchases,
        "receive_stock",
        lambda *args: received.append(args),
    )

    applied = purchases._apply_purchase_item_stock(
        purchase,
        item,
        branch_id=3,
        apply_stock=True,
    )

    assert applied is True
    assert received == [(3, 7, 51)]


def test_duplicate_purchase_reverse_skips_every_side_effect(monkeypatch):
    import routes.purchases as purchases

    purchase, item = _purchase_fixture()
    reversed_lots = []
    deducted = []
    monkeypatch.setattr(
        purchases,
        "claim_stock_movement",
        lambda *_args, **_kwargs: SimpleNamespace(applied=False),
    )
    monkeypatch.setattr(
        purchases,
        "reverse_purchase_lot",
        lambda row: reversed_lots.append(row.id),
    )
    monkeypatch.setattr(
        purchases,
        "deduct_stock",
        lambda *args: deducted.append(args),
    )

    applied = purchases._reverse_purchase_item_stock(
        purchase,
        item,
        branch_id=3,
    )

    assert applied is False
    assert reversed_lots == []
    assert deducted == []
