from __future__ import annotations

from extensions import db
from models.inventory_lot import InventoryLot, OrderItemCostLayer
from models.product import Product


class InventoryLotError(Exception):
    pass


def ensure_inventory_lot_schema() -> None:
    bind = db.session.get_bind()
    InventoryLot.__table__.create(bind=bind, checkfirst=True)
    OrderItemCostLayer.__table__.create(bind=bind, checkfirst=True)


def create_purchase_lot(purchase_item, branch_id: int | None) -> InventoryLot:
    ensure_inventory_lot_schema()
    qty = int(getattr(purchase_item, "quantity", 0) or 0)
    lot = InventoryLot(
        product_id=int(purchase_item.product_id),
        purchase_item_id=getattr(purchase_item, "id", None),
        branch_id=int(branch_id) if branch_id else None,
        variant_color=(getattr(purchase_item, "variant_color", None) or "").strip() or None,
        quantity=qty,
        remaining_quantity=qty,
        unit_cost=int(getattr(purchase_item, "final_unit_cost", 0) or 0),
    )
    db.session.add(lot)
    return lot


def reverse_purchase_lot(purchase_item) -> None:
    ensure_inventory_lot_schema()
    lot = InventoryLot.query.filter_by(purchase_item_id=getattr(purchase_item, "id", None)).first()
    if not lot:
        return
    consumed = int(lot.quantity or 0) - int(lot.remaining_quantity or 0)
    if consumed > 0:
        product_name = getattr(getattr(purchase_item, "product", None), "name", None) or f"#{lot.product_id}"
        raise InventoryLotError(
            f"لا يمكن تعديل/عكس دفعة شراء المنتج «{product_name}» لأن {consumed} قطعة منها مباعة مسبقاً."
        )
    db.session.delete(lot)


def _lot_query(product_id: int, branch_id: int | None, variant_color: str | None):
    query = InventoryLot.query.filter(
        InventoryLot.product_id == int(product_id),
        InventoryLot.remaining_quantity > 0,
    )
    if branch_id:
        query = query.filter(InventoryLot.branch_id == int(branch_id))
    else:
        query = query.filter(InventoryLot.branch_id.is_(None))
    color = (variant_color or "").strip() or None
    if color:
        query = query.filter(InventoryLot.variant_color == color)
    else:
        query = query.filter(InventoryLot.variant_color.is_(None))
    return query.order_by(InventoryLot.created_at.asc(), InventoryLot.id.asc())


def _create_fallback_lot(product_id: int, qty: int, branch_id: int | None, variant_color: str | None, unit_cost: int) -> InventoryLot:
    lot = InventoryLot(
        product_id=int(product_id),
        purchase_item_id=None,
        branch_id=int(branch_id) if branch_id else None,
        variant_color=(variant_color or "").strip() or None,
        quantity=int(qty),
        remaining_quantity=int(qty),
        unit_cost=int(unit_cost or 0),
    )
    db.session.add(lot)
    db.session.flush()
    return lot


def consume_lots_for_order_item(order_item, *, branch_id: int | None = None, variant_color: str | None = None) -> int:
    ensure_inventory_lot_schema()
    qty_needed = int(getattr(order_item, "quantity", 0) or 0)
    if qty_needed <= 0:
        return 0

    product_id = int(order_item.product_id)
    branch_id = int(branch_id) if branch_id else None
    color = (variant_color or getattr(order_item, "variant_color", None) or "").strip() or None

    restore_order_item_lots(order_item)

    remaining = qty_needed
    total_cost = 0
    lots = list(_lot_query(product_id, branch_id, color).all())
    product = Product.query.get(product_id)
    fallback_cost = int(getattr(order_item, "cost", 0) or getattr(product, "buy_price", 0) or 0)

    for lot in lots:
        if remaining <= 0:
            break
        take = min(remaining, int(lot.remaining_quantity or 0))
        if take <= 0:
            continue
        lot.remaining_quantity = int(lot.remaining_quantity or 0) - take
        db.session.add(
            OrderItemCostLayer(
                order_item_id=order_item.id,
                inventory_lot_id=lot.id,
                product_id=product_id,
                quantity=take,
                unit_cost=int(lot.unit_cost or 0),
            )
        )
        total_cost += take * int(lot.unit_cost or 0)
        remaining -= take

    if remaining > 0:
        fallback = _create_fallback_lot(product_id, remaining, branch_id, color, fallback_cost)
        fallback.remaining_quantity = 0
        db.session.add(
            OrderItemCostLayer(
                order_item_id=order_item.id,
                inventory_lot_id=fallback.id,
                product_id=product_id,
                quantity=remaining,
                unit_cost=fallback_cost,
            )
        )
        total_cost += remaining * fallback_cost
        remaining = 0

    order_item.cost = int(round(total_cost / qty_needed)) if qty_needed else 0
    return total_cost


def restore_order_item_lots(order_item, *, return_branch_id: int | None = None) -> None:
    ensure_inventory_lot_schema()
    layers = OrderItemCostLayer.query.filter_by(order_item_id=getattr(order_item, "id", None)).all()
    for layer in layers:
        lot = layer.inventory_lot
        target_branch_id = int(return_branch_id) if return_branch_id else None
        lot_branch_id = int(lot.branch_id) if lot and lot.branch_id else None
        if lot and target_branch_id and target_branch_id != lot_branch_id:
            _create_fallback_lot(
                int(layer.product_id),
                int(layer.quantity or 0),
                target_branch_id,
                getattr(lot, "variant_color", None) or getattr(order_item, "variant_color", None),
                int(layer.unit_cost or 0),
            )
        elif lot:
            layer.inventory_lot.remaining_quantity = int(layer.inventory_lot.remaining_quantity or 0) + int(layer.quantity or 0)
        db.session.delete(layer)


def current_lot_inventory_value() -> int:
    ensure_inventory_lot_schema()
    lot_value = db.session.query(
        db.func.coalesce(db.func.sum(InventoryLot.remaining_quantity * InventoryLot.unit_cost), 0)
    ).scalar()
    lot_rows = (
        db.session.query(
            InventoryLot.product_id,
            db.func.coalesce(db.func.sum(InventoryLot.remaining_quantity), 0).label("lot_qty"),
        )
        .group_by(InventoryLot.product_id)
        .all()
    )
    lot_qty_by_product = {int(row.product_id): int(row.lot_qty or 0) for row in lot_rows}
    fallback_value = 0
    for product in Product.query.filter(Product.active == True).all():
        product_qty = int(product.quantity or 0)
        lot_qty = lot_qty_by_product.get(int(product.id), 0)
        uncovered_qty = max(product_qty - lot_qty, 0)
        fallback_value += uncovered_qty * int(product.buy_price or 0)
    return int(lot_value or 0) + fallback_value
