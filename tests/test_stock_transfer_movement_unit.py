"""Exactly-once guards for inter-branch transfer phases."""

from types import SimpleNamespace


def _transfer():
    line = SimpleNamespace(id=8, product_id=7, quantity=4, variant_color=None)
    return SimpleNamespace(
        id=20,
        from_branch_id=1,
        to_branch_id=2,
        lines=[line],
    )


def _fake_product_model():
    product = SimpleNamespace(id=7, buy_price=100, meta_json=None)
    return SimpleNamespace(
        query=SimpleNamespace(get=lambda _product_id: product)
    )


def test_duplicate_transfer_send_does_not_deduct(monkeypatch):
    import routes.stock_transfers as transfers

    deducted = []
    monkeypatch.setattr(transfers, "Product", _fake_product_model())
    monkeypatch.setattr(transfers, "_validate_transfer_line", lambda *_a, **_k: "")
    monkeypatch.setattr(
        transfers,
        "claim_stock_movement",
        lambda *_args, **_kwargs: SimpleNamespace(applied=False),
    )
    monkeypatch.setattr(
        transfers,
        "deduct_stock",
        lambda *args: deducted.append(args),
    )

    transfers._apply_transfer_movements(_transfer(), "send")
    assert deducted == []


def test_transfer_send_and_receive_use_distinct_keys(monkeypatch):
    import routes.stock_transfers as transfers

    keys = []
    deducted = []
    received = []
    monkeypatch.setattr(transfers, "Product", _fake_product_model())
    monkeypatch.setattr(transfers, "_validate_transfer_line", lambda *_a, **_k: "")
    monkeypatch.setattr(
        transfers,
        "claim_stock_movement",
        lambda key, **_kwargs: (
            keys.append(key) or SimpleNamespace(applied=True)
        ),
    )
    monkeypatch.setattr(
        transfers,
        "deduct_stock",
        lambda *args: deducted.append(args),
    )
    monkeypatch.setattr(
        transfers,
        "receive_stock",
        lambda *args: received.append(args),
    )

    transfer = _transfer()
    transfers._apply_transfer_movements(transfer, "send")
    transfers._apply_transfer_movements(transfer, "receive")

    assert keys == [
        "transfer:20:line:8:send",
        "transfer:20:line:8:receive",
    ]
    assert deducted == [(1, 7, 4)]
    assert received == [(2, 7, 4)]


def test_transfer_send_records_variant_color_in_movement_details(monkeypatch):
    import routes.stock_transfers as transfers

    details_seen = []
    monkeypatch.setattr(transfers, "Product", _fake_product_model())
    monkeypatch.setattr(transfers, "_validate_transfer_line", lambda *_a, **_k: "")
    monkeypatch.setattr(
        transfers,
        "claim_stock_movement",
        lambda key, **kwargs: (
            details_seen.append(kwargs.get("details") or {}) or SimpleNamespace(applied=True)
        ),
    )
    monkeypatch.setattr(transfers, "deduct_stock", lambda *_a: None)

    transfer = _transfer()
    transfer.lines[0].variant_color = "أبيض"
    transfers._apply_transfer_movements(transfer, "send")

    assert details_seen[0].get("variant_color") == "أبيض"