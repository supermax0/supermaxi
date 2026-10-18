"""Integer allocations from immutable original-sale evidence; no posting here."""
from dataclasses import dataclass
from typing import Sequence


class AllocationError(ValueError):
    pass


def _integer(value, name, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise AllocationError(f"{name} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True)
class SaleLine:
    id: int
    quantity: int
    # Saved value after this line's own discount, before the invoice discount.
    value: int


@dataclass(frozen=True)
class OriginalCostLayer:
    id: int
    lot_id: int | None
    quantity: int
    unit_cost: int


@dataclass(frozen=True)
class ReturnedCost:
    layer_id: int
    lot_id: int | None
    quantity: int
    unit_cost: int

    @property
    def amount(self):
        return self.quantity * self.unit_cost


def discounted_line_values(goods_total: int, lines: Sequence[SaleLine]) -> dict[int, int]:
    """Allocate the saved final goods value; ties resolve by immutable line ID.

    The caller excludes delivery/service charges and financed interest before
    calling this function. It never invents how an unsupported charge works.
    """
    _integer(goods_total, "goods_total")
    values = {}
    for line in lines:
        _integer(line.id, "line.id", minimum=1)
        _integer(line.quantity, "line.quantity", minimum=1)
        _integer(line.value, "line.value")
        if line.id in values:
            raise AllocationError("Original line IDs must be unique")
        values[line.id] = line.value
    total = sum(values.values())
    if goods_total > total:
        raise AllocationError("Goods total exceeds original line values")
    if total == 0:
        return {line_id: 0 for line_id in values}
    allocated = {line_id: goods_total * value // total for line_id, value in values.items()}
    remainder = goods_total - sum(allocated.values())
    order = sorted(values, key=lambda line_id: (-(goods_total * values[line_id] % total), line_id))
    for line_id in order[:remainder]:
        allocated[line_id] += 1
    return allocated


def partial_line_credit(original_value: int, original_quantity: int, returned_before: int, quantity: int) -> int:
    """Consecutive partial returns sum exactly to the original discounted value."""
    _integer(original_value, "original_value")
    _integer(original_quantity, "original_quantity", minimum=1)
    _integer(returned_before, "returned_before")
    _integer(quantity, "quantity", minimum=1)
    if returned_before + quantity > original_quantity:
        raise AllocationError("Returned quantity exceeds the original sale")
    return (original_value * (returned_before + quantity) // original_quantity
        - original_value * returned_before // original_quantity)


def original_fifo_return(layers: Sequence[OriginalCostLayer], returned_before: int, quantity: int) -> list[ReturnedCost]:
    """Slice saved FIFO consumption, preserving lot identity and original cost.

    No fallback layer is created. The workflow must preserve these original
    layer snapshots before any restoration changes live consumption rows.
    """
    _integer(returned_before, "returned_before")
    _integer(quantity, "quantity", minimum=1)
    ids = set()
    for layer in layers:
        _integer(layer.id, "layer.id", minimum=1)
        if layer.lot_id is not None:
            _integer(layer.lot_id, "layer.lot_id", minimum=1)
        _integer(layer.quantity, "layer.quantity", minimum=1)
        _integer(layer.unit_cost, "layer.unit_cost")
        if layer.id in ids:
            raise AllocationError("Original cost layer IDs must be unique")
        ids.add(layer.id)
    if returned_before + quantity > sum(layer.quantity for layer in layers):
        raise AllocationError("Saved cost layers do not cover the return")
    skip, remaining, result = returned_before, quantity, []
    for layer in sorted(layers, key=lambda value: value.id):
        skipped = min(skip, layer.quantity)
        skip -= skipped
        available = layer.quantity - skipped
        take = min(remaining, available)
        if take:
            result.append(ReturnedCost(layer.id, layer.lot_id, take, layer.unit_cost))
            remaining -= take
        if not remaining:
            break
    return result


def credit_breakdown(total_remaining: int, collected_remaining: int, credit: int) -> dict[str, int]:
    """Separate debt relief from excess collection; this does not refund money.

    The workflow separately validates each actual collection source, including
    bank/cash, carrier custody and offsets, before refunding or crediting it.
    """
    _integer(total_remaining, "total_remaining")
    _integer(collected_remaining, "collected_remaining")
    _integer(credit, "credit")
    if collected_remaining > total_remaining:
        raise AllocationError("Overpaid source needs a separate reconciliation")
    if credit > total_remaining:
        raise AllocationError("Credit exceeds the remaining sale value")
    debt_relief = min(credit, total_remaining - collected_remaining)
    excess_collection = credit - debt_relief
    return {"debt_relief": debt_relief, "excess_collection": excess_collection,
        "sale_remaining": total_remaining - credit,
        "collection_remaining": collected_remaining - excess_collection}
