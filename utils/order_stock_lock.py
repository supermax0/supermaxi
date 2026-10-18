from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy import or_

from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from utils.branch_context import current_branch_id
from utils.branch_migration import get_default_branch
from utils.branch_sales import pick_fulfillment_branch
from utils.branch_stock_service import BranchStockError, deduct_stock, get_available_branch_stock, get_total_stock
from utils.inventory_lots import consume_lots_for_order_item, ensure_inventory_lot_schema
from utils.order_shipping import is_shipping_item
from utils.product_color_service import (
    ProductColorError,
    deduct_color_stock,
    product_has_colors,
)


LOCKED_ORDER_MESSAGE = "الطلب مقفل بانتظار توفر المخزون"
LOCKED_ORDER_STATUS_LABEL = "مقفل - بانتظار المخزون"


@dataclass
class StockAction:
    product_id: int
    quantity: int
    fulfillment_branch_id: int | None
    variant_color: str | None = None
    storage_location_id: int | None = None
    order_item_id: int | None = None
    storage_automatic: bool = True


@dataclass
class StockCheckResult:
    can_fulfill: bool
    actions: list[StockAction]
    reasons: list[str]

    @property
    def reason_text(self) -> str:
        return "؛ ".join(self.reasons) if self.reasons else ""


def is_stock_locked(order: Invoice | None) -> bool:
    return bool(getattr(order, "is_stock_locked", False))


def stock_unlocked_filter(invoice_model=Invoice):
    return or_(invoice_model.is_stock_locked.is_(False), invoice_model.is_stock_locked.is_(None))


def _preferred_branch_id(order: Invoice | None = None, explicit: int | None = None) -> int | None:
    if explicit:
        return int(explicit)
    if order is not None and getattr(order, "branch_id", None):
        return int(order.branch_id)
    branch_id = current_branch_id()
    if branch_id:
        return int(branch_id)
    default = get_default_branch()
    return int(default.id) if default else None


def _available_for_reason(product_id: int, branch_id: int | None) -> int:
    if branch_id:
        from utils.branch_sales import available_fulfillment_qty
        return available_fulfillment_qty(branch_id,product_id)
    return get_total_stock(product_id)


def check_stock_rows(rows: Iterable[dict], *, preferred_branch_id: int | None = None) -> StockCheckResult:
    actions: list[StockAction] = []
    reasons: list[str] = []
    parsed: list[dict] = []
    product_groups: dict[tuple[int, int | None,int | None,bool], dict] = {}

    for row in rows:
        product = row.get("product")
        product_id = int(row.get("product_id") or getattr(product, "id", 0) or 0)
        product = product or Product.query.get(product_id)
        qty = int(row.get("quantity") or row.get("qty") or 0)
        if not product or product_id <= 0:
            reasons.append("منتج غير موجود")
            continue
        if qty <= 0:
            reasons.append(f"كمية غير صالحة للمنتج {product.name}")
            continue

        variant_color = (row.get("variant_color") or row.get("color") or "").strip() or None
        if product_has_colors(product):
            if not variant_color:
                reasons.append(f"يجب اختيار لون للمنتج {product.name}")
                continue

        explicit_branch_id = row.get("fulfillment_branch_id")
        location_id=row.get('storage_location_id')
        if location_id is not None and (type(location_id) is not int or location_id<1):
            reasons.append(f'مخزن مصدر غير صالح للمنتج {product.name}');continue
        automatic=bool(row.get('storage_automatic',location_id is None)) and location_id is None
        try:
            explicit_branch_id = int(explicit_branch_id) if explicit_branch_id not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            explicit_branch_id = None

        parsed.append(
            {
                "product": product,
                "quantity": qty,
                "variant_color": variant_color,
                "explicit_branch_id": explicit_branch_id,
                "storage_location_id":location_id,
                "order_item_id":row.get('order_item_id'),
                "source_selected":bool(row.get('storage_source_selected')),
                "automatic_source":automatic,
            }
        )
        group_key = (product.id, explicit_branch_id,location_id,automatic)
        group = product_groups.setdefault(
            group_key,
            {"product": product, "quantity": 0, "explicit_branch_id": explicit_branch_id},
        )
        group["quantity"] += qty

    selected_branches: dict[tuple[int, int | None,int | None,bool], int] = {}
    for group_key, group in product_groups.items():
        product = group["product"]
        qty = int(group["quantity"])
        branch_id = pick_fulfillment_branch(
            product.id,
            qty,
            preferred_branch_id=preferred_branch_id,
            explicit_branch_id=group["explicit_branch_id"],
        )
        available = _available_for_reason(product.id, branch_id or preferred_branch_id)
        if not branch_id or available < qty:
            reasons.append(f"{product.name}: المتوفر {available} والمطلوب {qty}")
            continue
        selected_branches[group_key] = branch_id

    from utils.branch_stock_service import _branch_product_id
    from utils.branch_sales import available_fulfillment_qty
    branch_totals={}
    for row in parsed:
        selected=selected_branches.get((row['product'].id,row['explicit_branch_id'],row['storage_location_id'],row['automatic_source']))
        if selected:
            physical=(_branch_product_id(selected,row['product'].id),selected)
            row['source_key']=physical
            branch_totals[physical]=branch_totals.get(physical,0)+row['quantity']
    for (product_id,branch_id),required in branch_totals.items():
        if available_fulfillment_qty(branch_id,product_id)<required:
            reasons.append(f'رصيد الفرع لا يغطي مجموع أسطر المنتج #{product_id}')

    for row in parsed:
        product = row["product"]
        group_key = (product.id, row["explicit_branch_id"],row['storage_location_id'],row['automatic_source'])
        branch_id = selected_branches.get(group_key)
        if not branch_id:
            continue
        if row['variant_color']:
            from utils.branch_sales import available_fulfillment_qty
            color_required=sum(other['quantity'] for other in parsed if other.get('source_key')==row.get('source_key')
                and other['variant_color']==row['variant_color'])
            color_available=available_fulfillment_qty(branch_id,product.id,row['variant_color'])
            if color_available<color_required:
                reasons.append(f"{product.name} / {row['variant_color']}: المتوفر {color_available} والمطلوب {color_required}");continue
        from modules.inventory_locations.lots import available,partitioned
        from utils.inventory_lots import InventoryLotError
        if row['storage_location_id'] is not None or partitioned(branch_id,_branch_product_id(branch_id,product.id)):
            required=sum(other['quantity'] for other in parsed if other.get('source_key')==row.get('source_key')
                and other['storage_location_id']==row['storage_location_id'] and other['variant_color']==row['variant_color']
                and other['automatic_source']==row['automatic_source'])
            try:site_available=available(product.id,branch_id,row['variant_color'],row['storage_location_id'],automatic=row['automatic_source'])
            except InventoryLotError as exc:reasons.append(str(exc));continue
            if site_available<required:
                reasons.append(f'{product.name}: المتاح في مخزن المصدر {site_available} والمطلوب {required}');continue
        actions.append(
            StockAction(
                product_id=product.id,
                quantity=row["quantity"],
                fulfillment_branch_id=branch_id,
                variant_color=row["variant_color"],
                storage_location_id=row['storage_location_id'],
                order_item_id=row['order_item_id'],
                storage_automatic=row['automatic_source'],
            )
        )

    return StockCheckResult(can_fulfill=not reasons, actions=actions, reasons=reasons)


def check_invoice_stock(order: Invoice) -> StockCheckResult:
    from utils.order_stock_policy import is_physical_order_item

    rows = []
    preferred = _preferred_branch_id(order)
    for item in OrderItem.query.filter_by(invoice_id=order.id).all():
        if not is_physical_order_item(item):
            continue
        from modules.inventory_locations.lots import order_item_location
        choice=order_item_location(item.id)
        rows.append(
            {
                "product_id": item.product_id,
                "product": item.product,
                "quantity": int(item.quantity or 0),
                "variant_color": getattr(item, "variant_color", None),
                "fulfillment_branch_id": choice.branch_id if choice else getattr(item, "fulfillment_branch_id", None),
                "storage_location_id":choice.location_id if choice else None,
                "storage_source_selected":choice is not None,
                "storage_automatic":choice.automatic if choice else True,
                "order_item_id":item.id,
            }
        )
    return check_stock_rows(rows, preferred_branch_id=preferred)


def mark_order_stock_locked(order: Invoice, reason: str | None = None) -> None:
    order.is_stock_locked = True
    order.stock_lock_reason = reason or LOCKED_ORDER_MESSAGE
    order.stock_locked_at = order.stock_locked_at or datetime.utcnow()
    order.stock_unlocked_at = None
    order.status = "تم الطلب"
    order.payment_status = "غير مسدد"
    order.paid_amount = 0
    if hasattr(order, "stock_is_deducted"):
        order.stock_is_deducted = False


def clear_order_stock_lock(order: Invoice) -> None:
    order.is_stock_locked = False
    order.stock_lock_reason = None
    order.stock_unlocked_at = datetime.utcnow()


def apply_stock_actions(actions: Iterable[StockAction], *, invoice: Invoice | None = None) -> None:
    if invoice is None or not getattr(invoice, "id", None):
        raise BranchStockError("لا يمكن خصم مخزون طلب بدون رقم فاتورة للحركة")

    ensure_inventory_lot_schema()
    items_by_product: dict[tuple[int, str | None], list[OrderItem]] = {}
    for item in OrderItem.query.filter_by(invoice_id=invoice.id).order_by(OrderItem.id.asc()).all():
        if is_shipping_item(item):
            continue
        key = (int(item.product_id), (getattr(item, "variant_color", None) or "").strip() or None)
        items_by_product.setdefault(key, []).append(item)

    # Protect explicitly selected sites first; automatic rows then use what remains.
    for action in sorted(actions,key=lambda row: row.storage_automatic and row.storage_location_id is None):
        key = (int(action.product_id), (action.variant_color or "").strip() or None)
        candidates = items_by_product.get(key) or []
        selected_item = None
        for item in candidates:
            if int(item.quantity or 0) == int(action.quantity or 0) and (action.order_item_id is None or item.id==action.order_item_id):
                selected_item = item
                candidates.remove(item)
                break
        if selected_item is None:
            raise BranchStockError(
                f"تعذر ربط خصم المنتج #{action.product_id} بسطر الطلب #{invoice.id}"
            )

        from utils.stock_movement_guard import claim_stock_movement, next_order_item_movement_key

        movement_key = next_order_item_movement_key(
            invoice.id,
            selected_item.id,
            "deduct",
        )
        from utils.branch_stock_service import _branch_product_id
        source_product_id=_branch_product_id(action.fulfillment_branch_id,action.product_id) if action.fulfillment_branch_id else action.product_id
        claim = claim_stock_movement(
            movement_key,
            movement_type="order_deduct",
            direction="out",
            product_id=source_product_id,
            branch_id=action.fulfillment_branch_id,
            quantity=action.quantity,
            unit_cost=int(getattr(selected_item, "cost", 0) or 0),
            source_type="invoice",
            source_id=invoice.id,
            source_line_id=selected_item.id,
            details={"variant_color": action.variant_color,"storage_location_id":action.storage_location_id},
        )
        selected_item.fulfillment_branch_id = action.fulfillment_branch_id
        if not claim.applied:
            continue

        try:
            deduct_stock(action.fulfillment_branch_id, action.product_id, action.quantity)
            if action.variant_color:
                deduct_color_stock(
                    action.product_id,
                    action.variant_color,
                    action.quantity,
                    branch_id=action.fulfillment_branch_id,
                )
        except ProductColorError as exc:
            product = Product.query.get(action.product_id)
            product_name = (product.name if product else None) or f"#{action.product_id}"
            raise BranchStockError(
                f"مخزون اللون غير كافٍ للمنتج «{product_name} / {action.variant_color}»: {exc}"
            ) from exc

        total_cost=consume_lots_for_order_item(
            selected_item,
            branch_id=action.fulfillment_branch_id,
            variant_color=action.variant_color,
            **({'storage_location_id':action.storage_location_id} if action.storage_location_id is not None or not action.storage_automatic else {}),
        )
        claim.movement.unit_cost=int(selected_item.cost or 0)
        claim.movement.total_cost=total_cost
        import json
        from models.inventory_lot import OrderItemCostLayer
        details=json.loads(claim.movement.details_json or '{}')
        from modules.inventory_locations.lots import order_item_location
        source_choice=order_item_location(selected_item.id)
        details['storage_location_id']=source_choice.location_id if source_choice else action.storage_location_id
        details['storage_automatic']=source_choice.automatic if source_choice else action.storage_location_id is None
        details['catalog_product_id']=action.product_id
        details['valuation_layers']=[(layer.inventory_lot_id,layer.quantity,layer.unit_cost)
            for layer in OrderItemCostLayer.query.filter_by(order_item_id=selected_item.id).order_by(OrderItemCostLayer.id)]
        claim.movement.details_json=json.dumps(details,ensure_ascii=False)


def unlock_order_if_possible(order: Invoice) -> bool:
    if not is_stock_locked(order):
        return False

    result = check_invoice_stock(order)
    if not result.can_fulfill:
        order.stock_lock_reason = result.reason_text or LOCKED_ORDER_MESSAGE
        return False

    apply_stock_actions(result.actions, invoice=order)
    order.stock_is_deducted = True
    order.stock_deducted_at = datetime.utcnow()
    order.stock_restored_at = None
    clear_order_stock_lock(order)
    return True


def auto_unlock_locked_orders(limit: int = 100) -> int:
    from utils.order_stock_policy import deferred_stock_enabled

    if deferred_stock_enabled():
        return 0
    orders = (
        Invoice.query.filter(Invoice.is_stock_locked.is_(True))
        .order_by(Invoice.created_at.asc(), Invoice.id.asc())
        .limit(int(limit))
        .all()
    )
    unlocked = 0
    for order in orders:
        try:
            if unlock_order_if_possible(order):
                unlocked += 1
            db.session.flush()
        except (BranchStockError, ProductColorError):
            db.session.rollback()
        except Exception:
            db.session.rollback()
    if unlocked:
        db.session.commit()
    else:
        db.session.flush()
    return unlocked


def locked_order_response():
    return {"success": False, "error": LOCKED_ORDER_MESSAGE}
