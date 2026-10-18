"""Original discount/FIFO evidence survives arbitrary consecutive partials."""
from itertools import permutations
import pytest
from modules.sales_returns.allocation import (
    AllocationError, OriginalCostLayer, SaleLine, credit_breakdown,
    discounted_line_values, original_fifo_return, partial_line_credit,
)


def test_discount_rounding_is_stable_for_reordered_lines_and_gifts():
    lines = [SaleLine(7, 2, 7), SaleLine(3, 1, 7), SaleLine(9, 1, 0)]
    for ordered in permutations(lines):
        assert discounted_line_values(13, ordered) == {3: 7, 7: 6, 9: 0}


@pytest.mark.parametrize("quantity", [1, 2, 3, 7, 100])
@pytest.mark.parametrize("value", [0, 1, 2, 99, 1001, 9_000_000_000_000_000])
def test_partial_then_full_remainder_preserves_every_dinar(quantity, value):
    credits = [partial_line_credit(value, quantity, previous, 1) for previous in range(quantity)]
    assert sum(credits) == value
    assert max(credits) - min(credits) <= 1
    for previous in range(quantity):
        assert sum(credits[:previous]) + partial_line_credit(value, quantity, previous, quantity-previous) == value


def test_partial_return_crosses_original_fifo_layers_without_repricing():
    layers = [OriginalCostLayer(2, 55, 3, 250), OriginalCostLayer(1, 44, 2, 100)]
    first = original_fifo_return(layers, 0, 1)
    middle = original_fifo_return(layers, 1, 2)
    last = original_fifo_return(layers, 3, 2)
    assert [(row.lot_id, row.quantity, row.unit_cost) for row in middle] == [(44, 1, 100), (55, 1, 250)]
    assert sum(row.amount for row in first + middle + last) == 950
    assert sum(row.quantity for row in first + middle + last) == 5
    assert layers == [OriginalCostLayer(2, 55, 3, 250), OriginalCostLayer(1, 44, 2, 100)]


def test_saved_consumption_cost_keeps_unknown_lot_identity_unknown():
    returned = original_fifo_return([OriginalCostLayer(4, None, 2, 100)], 1, 1)
    assert returned[0].layer_id == 4 and returned[0].lot_id is None and returned[0].amount == 100


@pytest.mark.parametrize("paid,credit,debt,excess", [(0,400,400,0), (300,400,400,0),
    (300,700,500,200), (800,400,0,400), (800,800,0,800), (0,0,0,0)])
def test_credit_relieves_debt_before_creating_excess_collection(paid, credit, debt, excess):
    result = credit_breakdown(800, paid, credit)
    assert result == {"debt_relief": debt, "excess_collection": excess,
        "sale_remaining": 800-credit, "collection_remaining": paid-excess}
    assert result["sale_remaining"] - result["collection_remaining"] == 800-paid-debt


@pytest.mark.parametrize("operation", [
    lambda: discounted_line_values(11, [SaleLine(1, 1, 10)]),
    lambda: discounted_line_values(1, [SaleLine(1, 1, 1), SaleLine(1, 1, 2)]),
    lambda: partial_line_credit(100, 3, 2, 2),
    lambda: partial_line_credit(100, 3, 0, True),
    lambda: original_fifo_return([OriginalCostLayer(1, 1, 1, 10)], 0, 2),
    lambda: original_fifo_return([OriginalCostLayer(1, 1, 1, 10), OriginalCostLayer(1, 1, 1, 10)], 0, 1),
    lambda: credit_breakdown(100, 101, 1),
    lambda: credit_breakdown(100, 0, 101),
])
def test_invalid_original_evidence_and_over_returns_are_rejected(operation):
    with pytest.raises(AllocationError):
        operation()
