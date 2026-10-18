from modules.workspace.services.courier_settlement.courier_price_adjustment_policy import (
    CourierPriceAdjustmentPolicy,
)


def _snapshot(**overrides):
    data = {
        "id": 10,
        "total": 195000,
        "paid_amount": 0,
        "remaining_amount": 195000,
        "note": "",
        "agent_note": "",
        "shipping_barcodes": ["210618"],
    }
    data.update(overrides)
    return data


def test_replacement_note_allows_larger_price_change():
    plan = CourierPriceAdjustmentPolicy.build_plan(
        _snapshot(note="تبدل ميتاشي موديل 43 بسعر مختلف"),
        185000,
        "210618",
    )
    assert plan["kind"] == "replacement"
    assert plan["target_total"] == 185000
    assert plan["target_status"] == "استبدال"


def test_fuzzy_replacement_word_is_recognized():
    assert CourierPriceAdjustmentPolicy.note_indicates_replacement(
        "تم الاستبدالل حسب طلب الزبون"
    )


def test_small_difference_is_planned_without_replacement_note():
    plan = CourierPriceAdjustmentPolicy.build_plan(
        _snapshot(total=289000),
        285000,
        "210621",
    )
    assert plan["kind"] == "small_price_change"
    assert plan["absolute_difference"] == 4000


def test_large_difference_without_replacement_note_is_rejected():
    assert (
        CourierPriceAdjustmentPolicy.build_plan(
            _snapshot(total=195000),
            185000,
            "210618",
        )
        is None
    )


def test_multi_piece_order_never_gets_automatic_price_change():
    assert (
        CourierPriceAdjustmentPolicy.build_plan(
            _snapshot(shipping_barcodes=["508", "210605"]),
            169000,
            "210605",
        )
        is None
    )


def test_partial_payment_targets_paid_plus_statement_amount():
    plan = CourierPriceAdjustmentPolicy.build_plan(
        _snapshot(total=314000, paid_amount=145000, remaining_amount=169000),
        165000,
        "508",
    )
    assert plan["target_total"] == 310000
    assert plan["difference"] == -4000
