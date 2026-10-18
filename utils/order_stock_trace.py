"""Read-only stock journey summaries for orders and shipping reports."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import inspect
from sqlalchemy.orm import joinedload

from extensions import db
from models.branch import Branch
from models.invoice import Invoice
from models.order_item import OrderItem
from models.stock_movement import StockMovement
from utils.order_shipping import is_shipping_item, order_item_display_name


def _iso(value) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return None


def _branch_name(branch_id, branch_names: dict[int, str]) -> str:
    try:
        branch_id = int(branch_id) if branch_id else None
    except (TypeError, ValueError):
        branch_id = None
    if not branch_id:
        return "المخزون العام"
    return branch_names.get(branch_id, f"فرع #{branch_id}")


def _destination_label(order) -> str:
    destinations: list[str] = []
    company = getattr(order, "shipping_company", None)
    agent = getattr(order, "delivery_agent", None)
    if company and getattr(company, "name", None):
        destinations.append(f"شركة النقل: {company.name}")
    if agent and getattr(agent, "name", None):
        destinations.append(f"المندوب: {agent.name}")
    if not destinations:
        customer = getattr(order, "customer", None)
        customer_name = getattr(customer, "name", None) or getattr(order, "customer_name", None)
        destinations.append(f"الزبون: {customer_name}" if customer_name else f"الطلب #{order.id}")
    return " / ".join(destinations)


def _movement_details(movement) -> dict:
    raw = getattr(movement, "details_json", None)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def compose_order_stock_trace(
    order,
    items: Iterable,
    movements: Iterable,
    branch_names: dict[int, str],
) -> dict:
    """Compose one serializable trace. Kept pure so routing rules are testable."""
    items = [item for item in items if not is_shipping_item(item)]
    movements = sorted(
        list(movements),
        key=lambda row: (getattr(row, "created_at", None) or datetime.min, getattr(row, "id", 0) or 0),
    )
    movements_by_line: dict[int, list] = defaultdict(list)
    for movement in movements:
        line_id = getattr(movement, "source_line_id", None)
        if line_id:
            movements_by_line[int(line_id)].append(movement)

    destination = _destination_label(order)
    source_totals: dict[str, int] = defaultdict(int)
    return_totals: dict[str, int] = defaultdict(int)
    line_rows: list[dict] = []

    for item in items:
        item_events: list[dict] = []
        item_movements = movements_by_line.get(int(item.id), [])
        for movement in item_movements:
            qty = int(getattr(movement, "quantity", 0) or 0)
            branch = _branch_name(getattr(movement, "branch_id", None), branch_names)
            details = _movement_details(movement)
            direction = getattr(movement, "direction", None)
            movement_type = getattr(movement, "movement_type", None) or (
                "order_deduct" if direction == "out" else "order_restore"
            )
            is_branch_release = movement_type in {"order_branch_release", "shipping_branch_release"}
            is_branch_reserve = movement_type in {"order_branch_reserve", "shipping_branch_reserve"}
            is_restore_correction = movement_type == "order_restore_correction"
            if is_restore_correction:
                return_totals[branch] -= qty
                event = {
                    "kind": "correction",
                    "label": "تصحيح إرجاع مكرر",
                    "quantity": qty,
                    "from": branch,
                    "to": "تسوية المخزون",
                }
            elif is_branch_release:
                event = {
                    "kind": "transfer",
                    "label": "تحرير تخصيص الفرع",
                    "quantity": qty,
                    "from": "حجز الطلب",
                    "to": branch,
                }
            elif is_branch_reserve:
                source_totals[branch] += qty
                event = {
                    "kind": "transfer",
                    "label": "تغيير فرع الخصم",
                    "quantity": qty,
                    "from": branch,
                    "to": destination,
                }
            elif direction == "out":
                source_totals[branch] += qty
                event = {
                    "kind": "out",
                    "label": "خروج من المخزون",
                    "quantity": qty,
                    "from": branch,
                    "to": destination,
                }
            else:
                return_totals[branch] += qty
                event = {
                    "kind": "return",
                    "label": "إرجاع إلى المخزون",
                    "quantity": qty,
                    "from": destination,
                    "to": branch,
                }
            event.update(
                {
                    "branch_id": getattr(movement, "branch_id", None),
                    "direction": direction,
                    "movement_type": movement_type,
                    "movement_key": getattr(movement, "movement_key", None),
                    "recorded": True,
                    "at": _iso(getattr(movement, "created_at", None)),
                    "variant_color": details.get("variant_color"),
                }
            )
            item_events.append(event)

        # Legacy orders may predate StockMovement. Preserve the useful branch
        # columns while clearly marking the inferred events in the UI.
        if not item_events:
            fulfillment_branch_id = getattr(item, "fulfillment_branch_id", None) or getattr(order, "branch_id", None)
            was_ever_deducted = bool(
                getattr(order, "stock_deducted_at", None)
                or getattr(order, "stock_restored_at", None)
                or getattr(order, "stock_is_deducted", False)
            )
            if fulfillment_branch_id and was_ever_deducted:
                qty = int(getattr(item, "quantity", 0) or 0)
                branch = _branch_name(fulfillment_branch_id, branch_names)
                source_totals[branch] += qty
                item_events.append(
                    {
                        "kind": "out",
                        "label": "خروج من المخزون (سجل قديم)",
                        "quantity": qty,
                        "from": branch,
                        "to": destination,
                        "branch_id": fulfillment_branch_id,
                        "direction": "out",
                        "movement_type": "legacy_order_deduct",
                        "movement_key": None,
                        "recorded": False,
                        "at": _iso(getattr(order, "stock_deducted_at", None)),
                        "variant_color": getattr(item, "variant_color", None),
                    }
                )
                return_branch_id = getattr(order, "return_branch_id", None)
                if return_branch_id and getattr(order, "stock_restored_at", None):
                    return_branch = _branch_name(return_branch_id, branch_names)
                    return_totals[return_branch] += qty
                    item_events.append(
                        {
                            "kind": "return",
                            "label": "إرجاع إلى المخزون (سجل قديم)",
                            "quantity": qty,
                            "from": destination,
                            "to": return_branch,
                            "branch_id": return_branch_id,
                            "direction": "in",
                            "movement_type": "legacy_order_restore",
                            "movement_key": None,
                            "recorded": False,
                            "at": _iso(getattr(order, "stock_restored_at", None)),
                            "variant_color": getattr(item, "variant_color", None),
                        }
                    )

        last_event = next(
            (
                event
                for event in reversed(item_events)
                if event.get("kind") not in {"correction", "transfer"}
            ),
            None,
        )
        line_rows.append(
            {
                "item_id": int(item.id),
                "product_id": int(getattr(item, "product_id", 0) or 0),
                "product_name": order_item_display_name(item),
                "variant_color": (getattr(item, "variant_color", None) or "").strip() or None,
                "ordered_quantity": int(getattr(item, "quantity", 0) or 0),
                "current_state": (
                    "عاد إلى المخزون"
                    if last_event and last_event.get("direction") == "in"
                    else "خرج من المخزون"
                    if last_event
                    else "لم يُخصم بعد"
                ),
                "events": item_events,
            }
        )

    source_names = list(source_totals)
    return_totals = defaultdict(
        int,
        {name: quantity for name, quantity in return_totals.items() if quantity > 0},
    )
    return_names = list(return_totals)
    if source_names:
        summary_label = "، ".join(source_names)
        if return_names:
            summary_label += " ↩ " + "، ".join(return_names)
    else:
        summary_label = "لم يُخصم بعد" if line_rows else "بدون منتجات مخزنية"

    return {
        "order_id": int(order.id),
        "summary_label": summary_label,
        "destination": destination,
        "ordered_units": sum(row["ordered_quantity"] for row in line_rows),
        "source_branches": [
            {"name": name, "quantity": quantity}
            for name, quantity in source_totals.items()
        ],
        "return_branches": [
            {"name": name, "quantity": quantity}
            for name, quantity in return_totals.items()
        ],
        "lines": line_rows,
        "has_movements": any(row["events"] for row in line_rows),
    }


def build_order_stock_trace_map(order_refs: Iterable) -> dict[int, dict]:
    """Bulk-load traces to avoid a query per order or per table row."""
    refs = list(order_refs or [])
    order_ids: list[int] = []
    provided: dict[int, object] = {}
    for ref in refs:
        raw_id = getattr(ref, "id", ref)
        try:
            order_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        order_ids.append(order_id)
        if hasattr(ref, "id"):
            provided[order_id] = ref
    order_ids = list(dict.fromkeys(order_ids))
    if not order_ids:
        return {}

    missing_ids = [order_id for order_id in order_ids if order_id not in provided]
    if missing_ids:
        loaded = (
            Invoice.query.options(
                joinedload(Invoice.customer),
                joinedload(Invoice.shipping_company),
                joinedload(Invoice.delivery_agent),
            )
            .filter(Invoice.id.in_(missing_ids))
            .all()
        )
        provided.update({order.id: order for order in loaded})

    items = (
        OrderItem.query.options(joinedload(OrderItem.product))
        .filter(OrderItem.invoice_id.in_(order_ids))
        .order_by(OrderItem.invoice_id.asc(), OrderItem.id.asc())
        .all()
    )
    items_by_order: dict[int, list] = defaultdict(list)
    for item in items:
        items_by_order[int(item.invoice_id)].append(item)

    movements: list = []
    bind = db.session.get_bind()
    if inspect(bind).has_table(StockMovement.__tablename__):
        movements = (
            StockMovement.query.filter(
                StockMovement.source_type == "invoice",
                StockMovement.source_id.in_(order_ids),
            )
            .order_by(StockMovement.source_id.asc(), StockMovement.created_at.asc(), StockMovement.id.asc())
            .all()
        )
    movements_by_order: dict[int, list] = defaultdict(list)
    for movement in movements:
        movements_by_order[int(movement.source_id)].append(movement)

    branch_ids: set[int] = set()
    for order in provided.values():
        for raw_id in (getattr(order, "branch_id", None), getattr(order, "return_branch_id", None)):
            if raw_id:
                branch_ids.add(int(raw_id))
    for item in items:
        if getattr(item, "fulfillment_branch_id", None):
            branch_ids.add(int(item.fulfillment_branch_id))
    for movement in movements:
        if getattr(movement, "branch_id", None):
            branch_ids.add(int(movement.branch_id))
    branch_names = {
        int(branch.id): branch.name
        for branch in Branch.query.filter(Branch.id.in_(branch_ids)).all()
    } if branch_ids else {}

    return {
        order_id: compose_order_stock_trace(
            order,
            items_by_order.get(order_id, []),
            movements_by_order.get(order_id, []),
            branch_names,
        )
        for order_id, order in provided.items()
    }


def attach_order_stock_traces_to_rows(rows: list[dict]) -> dict[int, dict]:
    ids = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        raw_id = row.get("id") or row.get("order_id")
        try:
            ids.append(int(raw_id))
        except (TypeError, ValueError):
            pass
    traces = build_order_stock_trace_map(ids)
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            order_id = int(row.get("id") or row.get("order_id"))
        except (TypeError, ValueError):
            continue
        row["stock_trace"] = traces.get(order_id)
    return traces
