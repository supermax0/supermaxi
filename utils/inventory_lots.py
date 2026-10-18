from __future__ import annotations

from extensions import db
from models.inventory_lot import InventoryLot, OrderItemCostLayer
from models.product import Product
from sqlalchemy import update

_DEFAULT_LOCATION = object()


class InventoryLotError(Exception):
    pass


def ensure_inventory_lot_schema() -> None:
    # Keep SQLite schema checks on the caller's transaction connection.
    # Opening/closing a second Engine connection can roll back uncommitted
    # branch-stock changes when the pool hands out the same DBAPI connection.
    bind = db.session.connection()
    InventoryLot.__table__.create(bind=bind, checkfirst=True)
    OrderItemCostLayer.__table__.create(bind=bind, checkfirst=True)


def create_purchase_lot(purchase_item, branch_id: int | None, *, storage_location_id: int | None = None) -> InventoryLot:
    ensure_inventory_lot_schema()
    from modules.inventory_locations.lots import attach,validate_location
    validate_location(branch_id,storage_location_id)
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
    if storage_location_id is not None:
        db.session.flush();attach(lot,storage_location_id)
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


def _create_fallback_lot(product_id: int, qty: int, branch_id: int | None, variant_color: str | None, unit_cost: int,
    *,created_at=_DEFAULT_LOCATION) -> InventoryLot:
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
    if created_at is not _DEFAULT_LOCATION:lot.created_at=created_at
    db.session.flush()
    if created_at is None:lot.created_at=None
    return lot


def consume_lots_for_order_item(order_item, *, branch_id: int | None = None, variant_color: str | None = None,
    storage_location_id=_DEFAULT_LOCATION) -> int:
    connection=db.session.connection()
    if connection.dialect.name=='sqlite' and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql('BEGIN')
    with db.session.begin_nested():
        return _consume_lots_for_order_item(order_item,branch_id=branch_id,variant_color=variant_color,
            storage_location_id=storage_location_id)


def _consume_lots_for_order_item(order_item, *, branch_id=None,variant_color=None,storage_location_id=_DEFAULT_LOCATION):
    ensure_inventory_lot_schema()
    qty_needed = int(getattr(order_item, "quantity", 0) or 0)
    if qty_needed <= 0:
        return 0

    product_id = int(order_item.product_id)
    branch_id = int(branch_id) if branch_id else None
    color = (variant_color or getattr(order_item, "variant_color", None) or "").strip() or None

    from modules.inventory_locations.lots import choose_order_item_location,order_item_location,partitioned,placement,query_lots
    from utils.branch_stock_service import _branch_product_id
    product_id=_branch_product_id(branch_id,product_id) if branch_id else product_id
    choice=order_item_location(order_item.id)
    location_id=(choice.location_id if choice else None) if storage_location_id is _DEFAULT_LOCATION else storage_location_id
    automatic=(choice.automatic if choice else True) if storage_location_id is _DEFAULT_LOCATION else False
    if choice and choice.branch_id!=branch_id:
        raise InventoryLotError('فرع مصدر السطر المحفوظ لا يطابق فرع الخصم')
    strict=location_id is not None or partitioned(branch_id,product_id)
    if strict:
        candidates=query_lots(product_id,branch_id,color,location_id,sale=True,automatic=automatic).populate_existing().all()
        reusable=sum(layer.quantity for layer in OrderItemCostLayer.query.filter_by(order_item_id=order_item.id)
            if layer.inventory_lot and layer.inventory_lot.branch_id==branch_id and layer.inventory_lot.product_id==product_id
            and (layer.inventory_lot.variant_color or None)==color and (automatic or placement(layer.inventory_lot)==location_id))
        if sum(lot.remaining_quantity for lot in candidates)+reusable<qty_needed or any(lot.unit_cost<0 for lot in candidates):
            raise InventoryLotError('رصيد مخزن المصدر أو دليل كلفة قطعه غير كافٍ؛ لم تسحب قطع من موقع آخر')
    if not choice and branch_id and (strict or storage_location_id is not _DEFAULT_LOCATION):
        choose_order_item_location(order_item,branch_id,location_id,automatic=automatic)
    elif choice and storage_location_id is not _DEFAULT_LOCATION:
        choose_order_item_location(order_item,branch_id,location_id,automatic=automatic)

    restore_order_item_lots(order_item)

    remaining = qty_needed
    total_cost = 0
    lots = list(query_lots(product_id,branch_id,color,location_id,sale=True,automatic=automatic).populate_existing().all())
    if strict and sum(lot.remaining_quantity for lot in lots)<qty_needed:
        raise InventoryLotError('دليل مخزن المصدر لا يغطي السحب؛ أعد مراجعة المصدر دون إنشاء كلفة بديلة')
    product = Product.query.get(product_id)
    fallback_cost = int(getattr(order_item, "cost", 0) or getattr(product, "buy_price", 0) or 0)

    for lot in lots:
        if remaining <= 0:
            break
        take = min(remaining, int(lot.remaining_quantity or 0))
        if take <= 0:
            continue
        before=int(lot.remaining_quantity or 0)
        changed=db.session.execute(update(InventoryLot).where(InventoryLot.id==lot.id,
            InventoryLot.remaining_quantity==before).values(remaining_quantity=before-take).execution_options(synchronize_session=False))
        if changed.rowcount!=1:raise InventoryLotError('تغيرت دفعة مخزن المصدر؛ حدّث رصيد القطع قبل البيع')
        db.session.expire(lot)
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
        if strict:raise InventoryLotError('لم تغطِ دفعات مخزن المصدر الكمية؛ لم تنشأ كلفة بديلة')
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


def restore_order_item_lots(order_item, *, return_branch_id: int | None = None,return_location_id: int | None = None) -> None:
    ensure_inventory_lot_schema()
    from modules.inventory_locations.lots import validate_location,placement,attach
    target_branch_id=int(return_branch_id) if return_branch_id else None
    if return_location_id is not None and target_branch_id is None:
        raise InventoryLotError('اختر فرع مخزن استلام المرتجع')
    validate_location(target_branch_id,return_location_id)
    layers = OrderItemCostLayer.query.filter_by(order_item_id=getattr(order_item, "id", None)).all()
    for layer in layers:
        lot = layer.inventory_lot
        lot_branch_id = int(lot.branch_id) if lot and lot.branch_id else None
        if lot and target_branch_id and (target_branch_id != lot_branch_id or placement(lot)!=return_location_id):
            from utils.branch_product_service import product_for_branch
            from utils.branch_mode import independent_branches_enabled
            from utils.branch_stock_service import _branch_product_id
            target_product_id=_branch_product_id(target_branch_id,int(layer.product_id))
            source_product=Product.query.execution_options(skip_branch_scope=True).get(int(layer.product_id))
            if independent_branches_enabled() and source_product and target_branch_id!=lot_branch_id:
                target_product_id=product_for_branch(source_product,target_branch_id).id
            received=_create_fallback_lot(
                target_product_id,
                int(layer.quantity or 0),
                target_branch_id,
                getattr(lot, "variant_color", None) or getattr(order_item, "variant_color", None),
                int(layer.unit_cost or 0),
                created_at=lot.created_at,
            )
            attach(received,return_location_id)
        elif lot:
            before=int(lot.remaining_quantity or 0)
            changed=db.session.execute(update(InventoryLot).where(InventoryLot.id==lot.id,
                InventoryLot.remaining_quantity==before).values(remaining_quantity=before+int(layer.quantity or 0)).execution_options(synchronize_session=False))
            if changed.rowcount!=1:raise InventoryLotError('تغيرت دفعة المرتجع؛ راجع سند الإرجاع')
            db.session.expire(lot)
        db.session.delete(layer)


def current_lot_inventory_value() -> int:
    ensure_inventory_lot_schema()
    from utils.inventory_transfer_valuation import in_transit_value,valuation_branch_ids
    branch_ids=valuation_branch_ids()
    value_query = db.session.query(
        db.func.coalesce(db.func.sum(InventoryLot.remaining_quantity * InventoryLot.unit_cost), 0)
    )
    quantity_query = (
        db.session.query(
            InventoryLot.product_id,
            db.func.coalesce(db.func.sum(InventoryLot.remaining_quantity), 0).label("lot_qty"),
        )
        .group_by(InventoryLot.product_id)
    )
    products=Product.query.filter(Product.active == True)
    if branch_ids is not None:
        value_query=value_query.filter(InventoryLot.branch_id.in_(branch_ids))
        quantity_query=quantity_query.filter(InventoryLot.branch_id.in_(branch_ids))
        products=products.filter(Product.branch_id.in_(branch_ids))
    lot_value=value_query.scalar()
    lot_rows=quantity_query.all()
    lot_qty_by_product = {int(row.product_id): int(row.lot_qty or 0) for row in lot_rows}
    fallback_value = 0
    for product in products.all():
        product_qty = int(product.quantity or 0)
        lot_qty = lot_qty_by_product.get(int(product.id), 0)
        uncovered_qty = max(product_qty - lot_qty, 0)
        fallback_value += uncovered_qty * int(product.buy_price or 0)
    return int(lot_value or 0) + fallback_value + in_transit_value()
