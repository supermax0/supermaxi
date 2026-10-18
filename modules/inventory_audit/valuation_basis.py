"""Explicit FIFO subledger repair to authoritative on-hand, before count settlement.

Old sales/transfers/manual changes can leave uncovered or stale cost layers.
Repairing their remaining quantities must not book those historical sales twice.
Only the physical count delta creates the count journal. Every basis change is
saved in the same immutable post event, with the original layer IDs and values.
"""
from collections import defaultdict

from models.inventory_lot import InventoryLot
from utils.inventory_lots import _create_fallback_lot, ensure_inventory_lot_schema
from .common import AuditError, fingerprint, require, text
from .stock import product_data


METHOD = "fifo_on_hand_basis_v1"


def plan(counted, *, lock=False):
    require("inventory.audit.cost")
    require("inventory.audit.system")
    if not counted or any(line.warehouse_id for line in counted):
        raise AuditError("مطابقة طبقات FIFO تخص مخزون الفروع فقط")
    ensure_inventory_lot_schema()
    keys = {(line.branch_id, line.product_id, line.variant_name) for line in counted}
    query = InventoryLot.query.filter(
        InventoryLot.branch_id.in_({key[0] for key in keys}),
        InventoryLot.product_id.in_({key[1] for key in keys})).order_by(
            InventoryLot.created_at.asc(), InventoryLot.id.asc()).populate_existing()
    groups = defaultdict(list)
    for lot in (query.with_for_update() if lock else query).all():
        key = (lot.branch_id, lot.product_id, lot.variant_color or "")
        if key in keys:
            if int(lot.remaining_quantity) < 0 or int(lot.unit_cost) < 0:
                raise AuditError("طبقة تكلفة سالبة؛ راجع مصدرها قبل مطابقة التقييم", "valuation_conflict", 409)
            groups[key].append(lot)
    identity, items, operations = [], [], []
    for line in counted:
        lots = groups[(line.branch_id, line.product_id, line.variant_name)]
        cost = product_data(line, show_cost=True)["unit_cost"]
        if line.expected_quantity is None or line.expected_quantity < 0 or cost < 0:
            raise AuditError("رصيد أو تكلفة أساس الجرد غير صالح", "valuation_conflict", 409)
        quantity = sum(int(lot.remaining_quantity) for lot in lots)
        value = sum(int(lot.remaining_quantity) * int(lot.unit_cost) for lot in lots)
        identity.append({"line": line.id, "version": line.version,
            "expected": line.expected_quantity, "counted": line.counted_quantity, "unit_cost": cost,
            "lots": [[lot.id, lot.quantity, lot.remaining_quantity, lot.unit_cost,
                       lot.purchase_item_id, str(lot.created_at)] for lot in lots]})
        if quantity == line.expected_quantity:
            continue
        remove = max(0, quantity - line.expected_quantity)
        changes, removed_value = [], 0
        for lot in lots:
            take = min(remove, int(lot.remaining_quantity))
            if take:
                changes.append({"lot_id": lot.id, "before": int(lot.remaining_quantity),
                    "after": int(lot.remaining_quantity) - take, "unit_cost": int(lot.unit_cost),
                    "purchase_item_id": lot.purchase_item_id})
                operations.append((lot, int(lot.remaining_quantity) - take))
                removed_value += take * int(lot.unit_cost)
                remove -= take
        missing = max(0, line.expected_quantity - quantity)
        item = {"line_id": line.id, "location_key": line.location_key,
            "product_name": product_data(line, show_cost=True)["name"], "variant_name": line.variant_name,
            "system_quantity": line.expected_quantity, "counted_quantity": line.counted_quantity,
            "layer_quantity_before": quantity, "layer_value_before": value,
            "layer_value_after": value - removed_value + missing * cost,
            "removed_quantity": max(0, quantity - line.expected_quantity), "removed_value": removed_value,
            "added_quantity": missing, "added_value": missing * cost, "changes": changes}
        items.append(item)
        if missing:
            operations.append((line, missing, cost, item))
    result = {"method": METHOD, "fingerprint": fingerprint({"method": METHOD, "lines": identity}),
        "affected_lines": len(items), "removed_units": sum(x["removed_quantity"] for x in items),
        "added_units": sum(x["added_quantity"] for x in items), "items": items,
        "note": "مطابقة أساس طبقات التكلفة لرصيد الفرع قبل تسوية العد، بالأقدم أولاً FIFO والتكلفة المحفوظة للرصيد غير المغطى. لا تعيد تسجيل مبيعات سابقة أو قبض أو صرف؛ قيد الجرد يخص فرق العدد الفعلي فقط."}
    return result, operations


def apply(counted, payload):
    reason = text(payload.get("valuation_reason"), required=True)
    result, operations = plan(counted, lock=True)
    if payload.get("valuation_fingerprint") != result["fingerprint"]:
        raise AuditError("تغيّرت طبقات التكلفة؛ افحص المطابقة مرة أخرى قبل الترحيل", "valuation_conflict", 409)
    for operation in operations:
        if len(operation) == 2:
            lot, quantity = operation
            lot.remaining_quantity = quantity
        else:
            line, quantity, cost, item = operation
            lot = _create_fallback_lot(line.product_id, quantity, line.branch_id,
                                       line.variant_name or None, cost)
            item["changes"].append({"lot_id": lot.id, "before": 0, "after": quantity,
                                    "unit_cost": cost, "legacy_fallback": True})
    result["reason"] = reason
    return result
