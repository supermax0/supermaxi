import json
from datetime import datetime
from types import SimpleNamespace

from utils.order_stock_trace import compose_order_stock_trace


def _order(**overrides):
    values = {
        "id": 56,
        "branch_id": 1,
        "return_branch_id": None,
        "stock_is_deducted": True,
        "stock_deducted_at": datetime(2026, 8, 1, 10, 0),
        "stock_restored_at": None,
        "customer_name": "زبون",
        "customer": None,
        "shipping_company": SimpleNamespace(name="شركة البرق"),
        "delivery_agent": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _item(item_id=1200, quantity=2, branch_id=1, name="عطر"):
    return SimpleNamespace(
        id=item_id,
        invoice_id=56,
        product_id=9,
        product_name=name,
        product=None,
        quantity=quantity,
        total=100_000,
        fulfillment_branch_id=branch_id,
        variant_color=None,
        sale_mode="normal",
    )


def _movement(*, movement_id, direction, branch_id, quantity, key, at, line_id=1200, movement_type=None, details=None):
    return SimpleNamespace(
        id=movement_id,
        direction=direction,
        movement_type=movement_type or ("order_deduct" if direction == "out" else "order_restore"),
        branch_id=branch_id,
        quantity=quantity,
        movement_key=key,
        source_line_id=line_id,
        details_json=json.dumps(details or {"variant_color": None}),
        created_at=at,
    )


def test_trace_shows_exact_source_destination_and_return_branch():
    movements = [
        _movement(
            movement_id=1,
            direction="out",
            branch_id=1,
            quantity=2,
            key="order:56:item:1200:deduct:v1",
            at=datetime(2026, 8, 1, 10, 0),
        ),
        _movement(
            movement_id=2,
            direction="in",
            branch_id=2,
            quantity=2,
            key="order:56:item:1200:restore:v1",
            at=datetime(2026, 8, 3, 12, 0),
        ),
    ]

    trace = compose_order_stock_trace(
        _order(return_branch_id=2, stock_is_deducted=False, stock_restored_at=datetime(2026, 8, 3, 12, 0)),
        [_item()],
        movements,
        {1: "الفرع الرئيسي", 2: "فرع الكرادة"},
    )

    assert trace["summary_label"] == "الفرع الرئيسي ↩ فرع الكرادة"
    assert trace["source_branches"] == [{"name": "الفرع الرئيسي", "quantity": 2}]
    assert trace["return_branches"] == [{"name": "فرع الكرادة", "quantity": 2}]
    assert trace["lines"][0]["events"][0]["from"] == "الفرع الرئيسي"
    assert trace["lines"][0]["events"][0]["to"] == "شركة النقل: شركة البرق"
    assert trace["lines"][0]["events"][1]["to"] == "فرع الكرادة"
    assert trace["lines"][0]["current_state"] == "عاد إلى المخزون"


def test_trace_keeps_each_product_line_and_quantity_separate():
    first = _item(item_id=1200, quantity=2, branch_id=1, name="عطر A")
    second = _item(item_id=1201, quantity=1, branch_id=3, name="عطر B")
    movements = [
        _movement(
            movement_id=1,
            direction="out",
            branch_id=1,
            quantity=2,
            key="order:56:item:1200:deduct:v1",
            at=datetime(2026, 8, 1, 10, 0),
            line_id=1200,
        ),
        _movement(
            movement_id=2,
            direction="out",
            branch_id=3,
            quantity=1,
            key="order:56:item:1201:deduct:v1",
            at=datetime(2026, 8, 1, 10, 1),
            line_id=1201,
        ),
    ]

    trace = compose_order_stock_trace(_order(), [first, second], movements, {1: "الرئيسي", 3: "المنصور"})

    assert trace["ordered_units"] == 3
    assert len(trace["lines"]) == 2
    assert trace["lines"][0]["ordered_quantity"] == 2
    assert trace["lines"][1]["ordered_quantity"] == 1
    assert trace["source_branches"] == [
        {"name": "الرئيسي", "quantity": 2},
        {"name": "المنصور", "quantity": 1},
    ]


def test_legacy_order_uses_saved_fulfillment_and_return_branches():
    order = _order(
        return_branch_id=2,
        stock_is_deducted=False,
        stock_restored_at=datetime(2026, 8, 3, 12, 0),
    )

    trace = compose_order_stock_trace(order, [_item()], [], {1: "الرئيسي", 2: "الكرادة"})

    events = trace["lines"][0]["events"]
    assert [event["kind"] for event in events] == ["out", "return"]
    assert all(event["recorded"] is False for event in events)
    assert trace["summary_label"] == "الرئيسي ↩ الكرادة"


def test_branch_reassignment_is_not_mislabeled_as_customer_return():
    movements = [
        _movement(
            movement_id=1,
            direction="out",
            branch_id=1,
            quantity=2,
            key="order:56:item:1200:deduct:v1",
            at=datetime(2026, 8, 1, 10, 0),
        ),
        _movement(
            movement_id=2,
            direction="in",
            branch_id=1,
            quantity=2,
            key="order:56:item:1200:move:x:release",
            at=datetime(2026, 8, 1, 11, 0),
            movement_type="order_branch_release",
            details={"to_branch_id": 2},
        ),
        _movement(
            movement_id=3,
            direction="out",
            branch_id=2,
            quantity=2,
            key="order:56:item:1200:move:x:reserve",
            at=datetime(2026, 8, 1, 11, 0),
            movement_type="order_branch_reserve",
            details={"from_branch_id": 1},
        ),
    ]

    trace = compose_order_stock_trace(_order(), [_item(branch_id=2)], movements, {1: "الرئيسي", 2: "الكرادة"})

    assert trace["return_branches"] == []
    assert [event["kind"] for event in trace["lines"][0]["events"]] == ["out", "transfer", "transfer"]
    assert trace["lines"][0]["current_state"] == "خرج من المخزون"


def test_duplicate_restore_correction_is_shown_without_inflating_return_summary():
    movements = [
        _movement(
            movement_id=1,
            direction="out",
            branch_id=1,
            quantity=2,
            key="order:56:item:1200:deduct:v1",
            at=datetime(2026, 8, 1, 10, 0),
        ),
        _movement(
            movement_id=2,
            direction="in",
            branch_id=2,
            quantity=2,
            key="order:56:item:1200:restore:v1",
            at=datetime(2026, 8, 2, 9, 0),
        ),
        _movement(
            movement_id=3,
            direction="in",
            branch_id=1,
            quantity=2,
            key="order:56:item:1200:restore:v2",
            at=datetime(2026, 8, 3, 16, 0),
        ),
        _movement(
            movement_id=4,
            direction="out",
            branch_id=2,
            quantity=2,
            key="order:56:item:1200:restore:v1:duplicate-correction:v1",
            at=datetime(2026, 8, 3, 16, 1),
            movement_type="order_restore_correction",
            details={"reason": "duplicate_order_restore"},
        ),
    ]

    trace = compose_order_stock_trace(
        _order(stock_is_deducted=False),
        [_item()],
        movements,
        {1: "الفرع الرئيسي", 2: "فرع الكرادة"},
    )

    assert trace["return_branches"] == [{"name": "الفرع الرئيسي", "quantity": 2}]
    assert trace["summary_label"] == "الفرع الرئيسي ↩ الفرع الرئيسي"
    assert [event["kind"] for event in trace["lines"][0]["events"]] == [
        "out",
        "return",
        "return",
        "correction",
    ]
    assert trace["lines"][0]["events"][-1]["label"] == "تصحيح إرجاع مكرر"
    assert trace["lines"][0]["current_state"] == "عاد إلى المخزون"
