"""Database-backed exactly-once guard for physical stock mutations."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from extensions import db
from models.stock_movement import StockMovement


class StockMovementConflict(Exception):
    """The same idempotency key was reused for different inventory data."""


@dataclass(frozen=True)
class StockMovementClaim:
    movement: StockMovement
    applied: bool


def _order_item_movement_prefix(order_id: int, item_id: int, action: str) -> str:
    action = str(action or "").strip().lower()
    if action not in {"deduct", "restore"}:
        raise ValueError("نوع حركة الطلب غير صالح")
    return f"order:{int(order_id)}:item:{int(item_id)}:{action}:v"


def _order_item_movement_versions(order_id: int, item_id: int, action: str) -> list[tuple[int, str]]:
    """Return persisted lifecycle versions for one order line and action.

    Old tenants started with fixed ``v1`` keys.  Reading the version from the
    key keeps those records valid while allowing a later deduct/restore cycle
    to claim ``v2`` instead of colliding with immutable history.
    """
    ensure_stock_movement_schema()
    prefix = _order_item_movement_prefix(order_id, item_id, action)
    rows = (
        db.session.query(StockMovement.movement_key)
        .filter(StockMovement.movement_key.like(f"{prefix}%"))
        .all()
    )
    versions: list[tuple[int, str]] = []
    for (movement_key,) in rows:
        suffix = str(movement_key or "")[len(prefix):]
        try:
            versions.append((int(suffix), str(movement_key)))
        except (TypeError, ValueError):
            continue
    return sorted(versions, key=lambda value: value[0])


def next_order_item_movement_key(order_id: int, item_id: int, action: str) -> str:
    """Allocate the next immutable key for a new stock lifecycle action."""
    versions = _order_item_movement_versions(order_id, item_id, action)
    next_version = (versions[-1][0] + 1) if versions else 1
    return f"{_order_item_movement_prefix(order_id, item_id, action)}{next_version}"


def latest_order_item_movement_key(order_id: int, item_id: int, action: str) -> str | None:
    versions = _order_item_movement_versions(order_id, item_id, action)
    return versions[-1][1] if versions else None


def ensure_stock_movement_schema() -> None:
    # Use the session's current connection. SQLite cannot execute DDL through
    # a second connection while the caller has an open stock transaction.
    StockMovement.__table__.create(bind=db.session.connection(), checkfirst=True)


def _normalized_payload(
    *,
    movement_type: str,
    direction: str,
    product_id: int,
    branch_id: int | None,
    quantity: int,
    unit_cost: int,
    source_type: str,
    source_id: int,
    source_line_id: int | None,
    reversal_of_key: str | None,
) -> dict:
    direction = str(direction or "").strip().lower()
    quantity = int(quantity or 0)
    if direction not in {"in", "out"}:
        raise ValueError("اتجاه حركة المخزون غير صالح")
    if quantity <= 0:
        raise ValueError("كمية حركة المخزون يجب أن تكون أكبر من صفر")
    if not str(movement_type or "").strip() or not str(source_type or "").strip():
        raise ValueError("نوع ومصدر حركة المخزون مطلوبان")
    return {
        "movement_type": str(movement_type or "").strip(),
        "direction": direction,
        "product_id": int(product_id),
        "branch_id": int(branch_id) if branch_id else None,
        "quantity": quantity,
        "unit_cost": int(unit_cost or 0),
        "source_type": str(source_type or "").strip(),
        "source_id": int(source_id),
        "source_line_id": int(source_line_id) if source_line_id else None,
        "reversal_of_key": str(reversal_of_key or "").strip() or None,
    }


def _movement_payload(movement: StockMovement) -> dict:
    return {
        "movement_type": movement.movement_type,
        "direction": movement.direction,
        "product_id": int(movement.product_id),
        "branch_id": int(movement.branch_id) if movement.branch_id else None,
        "quantity": int(movement.quantity),
        "unit_cost": int(movement.unit_cost or 0),
        "source_type": movement.source_type,
        "source_id": int(movement.source_id),
        "source_line_id": int(movement.source_line_id) if movement.source_line_id else None,
        "reversal_of_key": movement.reversal_of_key or None,
    }


def claim_stock_movement(
    movement_key: str,
    *,
    movement_type: str,
    direction: str,
    product_id: int,
    branch_id: int | None,
    quantity: int,
    unit_cost: int = 0,
    source_type: str,
    source_id: int,
    source_line_id: int | None = None,
    reversal_of_key: str | None = None,
    details: dict | None = None,
) -> StockMovementClaim:
    """Claim a unique stock mutation inside the caller's transaction.

    The first caller inserts the immutable movement and may mutate inventory.
    Retries receive ``applied=False`` and must skip every physical side effect.
    Reusing a key with different data is treated as corruption and rejected.
    """
    ensure_stock_movement_schema()
    movement_key = str(movement_key or "").strip()
    if not movement_key:
        raise ValueError("مفتاح حركة المخزون مطلوب")

    payload = _normalized_payload(
        movement_type=movement_type,
        direction=direction,
        product_id=product_id,
        branch_id=branch_id,
        quantity=quantity,
        unit_cost=unit_cost,
        source_type=source_type,
        source_id=source_id,
        source_line_id=source_line_id,
        reversal_of_key=reversal_of_key,
    )
    details_json = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)
    movement = StockMovement(
        movement_key=movement_key,
        total_cost=payload["quantity"] * payload["unit_cost"],
        details_json=details_json,
        **payload,
    )

    try:
        with db.session.begin_nested():
            db.session.add(movement)
            db.session.flush()
        return StockMovementClaim(movement=movement, applied=True)
    except IntegrityError:
        existing = StockMovement.query.filter_by(movement_key=movement_key).first()
        if existing is None:
            raise
        if (
            _movement_payload(existing) != payload
            or (existing.details_json or "{}") != details_json
        ):
            raise StockMovementConflict(
                f"مفتاح حركة المخزون «{movement_key}» مستخدم ببيانات مختلفة"
            )
        return StockMovementClaim(movement=existing, applied=False)
