"""Deferred inventory policy for orders in ``تم الطلب``.

This module is the single source of truth for whether an invoice currently owns
deducted physical inventory.  All operations are deliberately flush-only; the
calling route controls the surrounding transaction and its accounting effects.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from sqlalchemy.orm import load_only
from utils.order_status import is_canceled, is_returned, normalize_status


POLICY_FLAG = "defer_pending_order_stock"
PACKED_DEDUCTION_FLAG = "deduct_order_stock_on_packed"
POLICY_INITIALIZED_FLAG = "defer_pending_order_stock_initialized_v2"
DUPLICATE_RESTORE_REPAIR_FLAG = "duplicate_order_restore_repaired_v1"
PACKED_STOCK_STATUSES = {"معباة", "معبأة"}
STOCK_STATUSES = {"جاري الشحن", "قيد الشحن", "تم التوصيل", "مسدد"}
STOCK_PAYMENT_STATUSES = {"جزئي", "مسدد", "مسدد جزئي"}


class OrderStockError(Exception):
    def __init__(
        self,
        message: str,
        shortages: list[str] | None = None,
        *,
        order_id: int | None = None,
        product_name: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.shortages = shortages or []
        self.order_id = order_id
        self.product_name = product_name


def deferred_stock_enabled() -> bool:
    try:
        from models.system_settings import SystemSettings

        settings = SystemSettings.get_settings()
        return bool(settings.get_ui_flags().get(POLICY_FLAG, True))
    except Exception:
        return True


def packed_stock_deduction_enabled() -> bool:
    """Return whether moving an order to packed should deduct inventory."""
    try:
        from models.system_settings import SystemSettings

        settings = SystemSettings.get_settings()
        return bool(settings.get_ui_flags().get(PACKED_DEDUCTION_FLAG, True))
    except Exception:
        return True


def order_needs_stock(*, status: str | None = None, payment_status: str | None = None) -> bool:
    normalized_status = normalize_status(status)
    packed_requires_stock = (
        normalized_status in PACKED_STOCK_STATUSES
        and packed_stock_deduction_enabled()
    )
    return (
        packed_requires_stock
        or normalized_status in STOCK_STATUSES
        or normalize_status(payment_status) in STOCK_PAYMENT_STATUSES
    )


def is_physical_order_item(item: OrderItem) -> bool:
    from utils.order_shipping import SHIPPING_BARCODE, SHIPPING_PRODUCT_NAME

    name = normalize_status(getattr(item, "product_name", None))
    if name == SHIPPING_PRODUCT_NAME:
        return False
    if int(getattr(item, "total", 0) or 0) < 0:
        return False
    if name in {"خصم كوبون", "خصم", "أجور توصيل", "اجور توصيل"}:
        return False
    product_id = int(getattr(item, "product_id", 0) or 0)
    if product_id:
        barcode = db.session.query(Product.barcode).filter(Product.id == product_id).scalar()
        if barcode == SHIPPING_BARCODE:
            return False
    return True


def _physical_items(invoice_id: int) -> list[OrderItem]:
    items = (
        OrderItem.query.options(
            load_only(
                OrderItem.id,
                OrderItem.invoice_id,
                OrderItem.product_id,
                OrderItem.fulfillment_branch_id,
                OrderItem.product_name,
                OrderItem.quantity,
                OrderItem.total,
                OrderItem.variant_color,
            )
        )
        .filter_by(invoice_id=invoice_id)
        .all()
    )
    return [item for item in items if is_physical_order_item(item)]


def stock_is_deducted(order: Invoice | None) -> bool:
    return bool(order and getattr(order, "stock_is_deducted", False))


def select_order_stock_branch(order: Invoice, branch_id: int | str | None) -> int | None:
    """Assign one active fulfillment branch to every physical order line.

    This is intentionally flush-only so callers can select the branch and
    deduct stock in the same transaction as payment.
    """
    items = _physical_items(order.id)
    if branch_id in (None, "", 0, "0") and stock_is_deducted(order):
        used_branch_id = next(
            (
                int(item.fulfillment_branch_id)
                for item in items
                if getattr(item, "fulfillment_branch_id", None)
            ),
            None,
        )
        return used_branch_id or getattr(order, "branch_id", None)

    if branch_id in (None, "", 0, "0"):
        from utils.shipping_branch_schedule import resolve_shipping_branch_for_now

        branch_id = resolve_shipping_branch_for_now()
        if not branch_id:
            return None
    try:
        branch_id = int(branch_id)
    except (TypeError, ValueError) as exc:
        raise OrderStockError("فرع خصم المخزون غير صالح", order_id=order.id) from exc

    if stock_is_deducted(order):
        used_branch_ids = {
            int(item.fulfillment_branch_id)
            for item in items
            if getattr(item, "fulfillment_branch_id", None)
        }
        if used_branch_ids and used_branch_ids != {branch_id}:
            raise OrderStockError(
                "تم خصم مخزون هذا الطلب سابقاً ولا يمكن تغيير الفرع عند التسديد",
                order_id=order.id,
            )
        return branch_id

    from models.branch import Branch

    branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
    if not branch:
        raise OrderStockError("فرع خصم المخزون غير موجود أو غير نشط", order_id=order.id)

    order.branch_id = branch_id
    for item in items:
        item.fulfillment_branch_id = branch_id
    db.session.flush()
    return branch_id


def deduct_order_stock(order: Invoice) -> bool:
    """Deduct every physical line atomically in the caller's transaction."""
    if stock_is_deducted(order):
        return False

    # Keep the scalar id before any flush.  A failed SQL flush expires ORM
    # attributes, and reading ``order.id`` while the session awaits rollback
    # would hide the real stock error behind PendingRollbackError.
    order_id = int(order.id)

    from utils.order_stock_lock import apply_stock_actions, check_invoice_stock, clear_order_stock_lock

    now = datetime.utcnow()
    claimed = (
        db.session.query(Invoice)
        .filter(Invoice.id == order_id, Invoice.stock_is_deducted.is_(False))
        .update(
            {
                Invoice.stock_is_deducted: True,
                Invoice.stock_deducted_at: now,
                Invoice.stock_restored_at: None,
            },
            synchronize_session=False,
        )
    )
    if claimed != 1:
        db.session.expire(order)
        return False
    db.session.expire(order)

    result = check_invoice_stock(order)
    if not result.can_fulfill:
        detail = result.reason_text or "المخزون غير كافٍ لتنفيذ الطلب"
        raise OrderStockError(
            f"المخزون غير كافٍ لتنفيذ الطلب #{order_id}: {detail}",
            result.reasons,
            order_id=order_id,
        )
    try:
        apply_stock_actions(result.actions, invoice=order)
    except Exception as exc:
        raise OrderStockError(str(exc), [str(exc)], order_id=order_id) from exc

    clear_order_stock_lock(order)
    db.session.flush()
    return True


def restore_order_stock(
    order: Invoice,
    *,
    release_fulfillment: bool = False,
    return_branch_id: int | str | None = None,
    return_location_id: int | None = None,
) -> bool:
    """Restore physical lines only when they are currently deducted."""
    if not stock_is_deducted(order):
        return False

    # Food invoices own their quantities in variant/base-unit stock.  Routing
    # them through the legacy Product/Branch stock path would restore a
    # different inventory ledger.
    if str(getattr(order, "source_module", "") or "").strip().lower() == "food":
        try:
            from modules.food.service import FoodError, restore_sale_stock

            return restore_sale_stock(order)
        except FoodError as exc:
            raise OrderStockError(str(exc), order_id=order.id) from exc

    selected_return_branch_id = None
    if return_branch_id not in (None, "", 0, "0"):
        try:
            selected_return_branch_id = int(return_branch_id)
        except (TypeError, ValueError) as exc:
            raise OrderStockError("فرع إرجاع المخزون غير صالح", order_id=order.id) from exc

        from models.branch import Branch

        return_branch = Branch.query.filter_by(id=selected_return_branch_id, is_active=True).first()
        if not return_branch:
            raise OrderStockError("فرع إرجاع المخزون غير موجود أو غير نشط", order_id=order.id)
        from flask import has_request_context
        if has_request_context():
            from utils.branch_scope import current_employee,is_general_admin,allowed_branch_ids
            employee=current_employee()
            if employee and not is_general_admin(employee) and selected_return_branch_id not in allowed_branch_ids():
                raise OrderStockError('فرع استلام المرتجع خارج صلاحياتك',order_id=order.id)
    from modules.inventory_locations.lots import validate_location
    if return_location_id is not None and selected_return_branch_id is None:
        raise OrderStockError('اختر فرع مخزن استلام المرتجع',order_id=order.id)
    validate_location(selected_return_branch_id,return_location_id)

    now = datetime.utcnow()
    claimed = (
        db.session.query(Invoice)
        .filter(Invoice.id == order.id, Invoice.stock_is_deducted.is_(True))
        .update(
            {
                Invoice.stock_is_deducted: False,
                Invoice.stock_restored_at: now,
            },
            synchronize_session=False,
        )
    )
    if claimed != 1:
        db.session.expire(order)
        return False
    db.session.expire(order)

    restored_any = False
    for item in _physical_items(order.id):
        product = Product.query.get(item.product_id)
        if not product:
            continue
        qty = int(item.quantity or 0)
        branch_id = selected_return_branch_id or item.fulfillment_branch_id or getattr(order, "branch_id", None)

        from utils.stock_movement_guard import (
            claim_stock_movement,
            latest_order_item_movement_key,
            next_order_item_movement_key,
        )
        from models.stock_movement import StockMovement

        # The invoice flag is a fast guard, but old/manual workflows could set
        # it back to true without recording a new dispatch.  The immutable line
        # history is authoritative: an inbound restore cannot be followed by a
        # second restore until a newer outbound deduction exists.
        latest_lifecycle_movement = (
            StockMovement.query.filter(
                StockMovement.source_type == "invoice",
                StockMovement.source_id == int(order.id),
                StockMovement.source_line_id == int(item.id),
                StockMovement.movement_type.in_({"order_deduct", "order_restore"}),
            )
            .order_by(StockMovement.id.desc())
            .first()
        )
        if latest_lifecycle_movement and latest_lifecycle_movement.direction == "in":
            if release_fulfillment:
                item.fulfillment_branch_id = None
            continue

        return_product=product
        if selected_return_branch_id:
            from utils.branch_mode import independent_branches_enabled
            from utils.branch_product_service import product_for_branch
            from models.branch import BranchStock
            has_legacy_owner=not product.branch_id and BranchStock.query.filter_by(
                branch_id=selected_return_branch_id,product_id=product.id).first()
            if independent_branches_enabled() and not has_legacy_owner:
                return_product=product_for_branch(product,selected_return_branch_id)
        from models.inventory_lot import OrderItemCostLayer
        cost_layers=OrderItemCostLayer.query.filter_by(order_item_id=item.id).all()
        return_cost=sum(layer.quantity*layer.unit_cost for layer in cost_layers) if cost_layers else int(item.cost or 0)*qty


        deduct_key = latest_order_item_movement_key(order.id, item.id, "deduct")
        restore_key = next_order_item_movement_key(order.id, item.id, "restore")
        claim = claim_stock_movement(
            restore_key,
            movement_type="order_restore",
            direction="in",
            product_id=return_product.id,
            branch_id=int(branch_id) if branch_id else None,
            quantity=qty,
            unit_cost=int(getattr(item, "cost", 0) or 0),
            source_type="invoice",
            source_id=order.id,
            source_line_id=item.id,
            reversal_of_key=deduct_key,
            details={
                "return_branch_id": selected_return_branch_id,
                "return_location_id":return_location_id,
                "variant_color": (getattr(item, "variant_color", None) or "").strip() or None,
            },
        )
        if not claim.applied:
            if release_fulfillment:
                item.fulfillment_branch_id = None
            continue
        restored_any = True
        claim.movement.total_cost=return_cost

        from utils.inventory_lots import restore_order_item_lots

        restore_order_item_lots(item, return_branch_id=selected_return_branch_id,return_location_id=return_location_id)
        if branch_id:
            from utils.branch_stock_service import receive_stock

            receive_stock(int(branch_id), return_product.id, qty,audit_context={
                'movement_id':claim.movement.id,'operation':'order_restore','source_type':'invoice',
                'source_id':order.id,'source_line_id':item.id,'metadata':{'return_location_id':return_location_id}})
        else:
            product.quantity = int(product.quantity or 0) + qty
        color = (getattr(item, "variant_color", None) or "").strip()
        if color:
            from utils.product_color_service import restore_color_stock

            restore_color_stock(return_product.id, color, qty, branch_id=int(branch_id) if branch_id else None)
        if release_fulfillment:
            item.fulfillment_branch_id = None

    if selected_return_branch_id:
        order.return_branch_id = selected_return_branch_id

    db.session.flush()
    return restored_any


def repair_duplicate_order_restores(order_id: int | None = None) -> dict:
    """Reverse historical inbound restores that have no unmatched dispatch.

    Audit rows stay immutable.  Each excess inbound movement receives one
    explicit outbound correction, so branch quantities, colors and the stock
    trace remain explainable and the repair itself is idempotent.
    """
    import json

    from models.stock_movement import StockMovement
    from utils.stock_movement_guard import claim_stock_movement, ensure_stock_movement_schema

    ensure_stock_movement_schema()
    query = StockMovement.query.filter(
        StockMovement.source_type == "invoice",
        StockMovement.source_line_id.isnot(None),
        StockMovement.movement_type.in_({"order_deduct", "order_restore"}),
    )
    if order_id is not None:
        query = query.filter(StockMovement.source_id == int(order_id))
    movements = query.order_by(
        StockMovement.source_id.asc(),
        StockMovement.source_line_id.asc(),
        StockMovement.id.asc(),
    ).all()

    grouped: dict[tuple[int, int], list[StockMovement]] = {}
    for movement in movements:
        key = (int(movement.source_id), int(movement.source_line_id))
        grouped.setdefault(key, []).append(movement)

    duplicates: list[tuple[StockMovement, int]] = []
    for line_movements in grouped.values():
        cycles: list[dict[str, list[StockMovement]]] = []
        current_cycle: dict[str, list[StockMovement]] | None = None
        for movement in line_movements:
            if movement.movement_type == "order_deduct" and movement.direction == "out":
                if current_cycle is None or current_cycle["restores"]:
                    if current_cycle is not None:
                        cycles.append(current_cycle)
                    current_cycle = {"deducts": [], "restores": []}
                current_cycle["deducts"].append(movement)
            elif (
                current_cycle is not None
                and movement.movement_type == "order_restore"
                and movement.direction == "in"
            ):
                current_cycle["restores"].append(movement)
        if current_cycle is not None:
            cycles.append(current_cycle)

        for cycle in cycles:
            deducts = cycle["deducts"]
            restores = cycle["restores"]
            if not deducts or not restores:
                continue
            remaining = sum(int(row.quantity or 0) for row in deducts)
            source_branch_ids = {
                int(row.branch_id) if row.branch_id else None
                for row in deducts
            }
            # If the same dispatch was restored twice to different branches,
            # keep the restore matching its source branch. This repairs the old
            # AGT bug (wrong branch first, correct original branch on retry).
            prioritized = sorted(
                enumerate(restores),
                key=lambda pair: (
                    0
                    if (int(pair[1].branch_id) if pair[1].branch_id else None) in source_branch_ids
                    else 1,
                    pair[0],
                ),
            )
            for _index, restore in prioritized:
                qty = int(restore.quantity or 0)
                covered = min(remaining, qty)
                remaining -= covered
                excess = qty - covered
                if excess > 0:
                    duplicates.append((restore, excess))

    repaired = 0
    repaired_units = 0
    skipped = 0
    errors: list[str] = []
    for duplicate, excess in duplicates:
        correction_key = f"{duplicate.movement_key}:duplicate-correction:v1"
        existing = StockMovement.query.filter_by(movement_key=correction_key).first()
        if existing:
            skipped += 1
            continue

        item = OrderItem.query.get(int(duplicate.source_line_id))
        product = Product.query.get(int(duplicate.product_id))
        if not item or not product:
            errors.append(f"تعذر تصحيح الحركة {duplicate.movement_key}: الصنف غير موجود")
            continue

        try:
            with db.session.begin_nested():
                try:
                    details = json.loads(duplicate.details_json or "{}")
                except (TypeError, ValueError):
                    details = {}
                variant_color = (details.get("variant_color") or getattr(item, "variant_color", None) or "").strip() or None
                claim = claim_stock_movement(
                    correction_key,
                    movement_type="order_restore_correction",
                    direction="out",
                    product_id=int(duplicate.product_id),
                    branch_id=int(duplicate.branch_id) if duplicate.branch_id else None,
                    quantity=int(excess),
                    unit_cost=int(duplicate.unit_cost or 0),
                    source_type="invoice",
                    source_id=int(duplicate.source_id),
                    source_line_id=int(duplicate.source_line_id),
                    reversal_of_key=duplicate.movement_key,
                    details={
                        "reason": "duplicate_order_restore",
                        "variant_color": variant_color,
                    },
                )
                if not claim.applied:
                    skipped += 1
                    continue

                if duplicate.branch_id:
                    from utils.branch_stock_service import deduct_stock

                    deduct_stock(int(duplicate.branch_id), int(duplicate.product_id), int(excess))
                else:
                    updated = (
                        db.session.query(Product)
                        .filter(Product.id == int(product.id), Product.quantity >= int(excess))
                        .update(
                            {Product.quantity: Product.quantity - int(excess)},
                            synchronize_session=False,
                        )
                    )
                    if updated != 1:
                        raise OrderStockError(
                            f"المخزون العام غير كافٍ لتصحيح الإرجاع المكرر للمنتج «{product.name}»",
                            order_id=int(duplicate.source_id),
                        )

                if variant_color:
                    from utils.product_color_service import deduct_color_stock

                    deduct_color_stock(
                        int(duplicate.product_id),
                        variant_color,
                        int(excess),
                        branch_id=int(duplicate.branch_id),
                    )

                # Normal order restores are full-line quantities. Rebuild the
                # consumed cost layers only when the excess is the complete line.
                if int(excess) == int(item.quantity or 0):
                    from utils.inventory_lots import consume_lots_for_order_item

                    consume_lots_for_order_item(
                        item,
                        branch_id=int(duplicate.branch_id) if duplicate.branch_id else None,
                        variant_color=variant_color,
                    )
                db.session.flush()
            repaired += 1
            repaired_units += int(excess)
        except Exception as exc:
            errors.append(f"تعذر تصحيح الحركة {duplicate.movement_key}: {exc}")

    db.session.flush()
    return {
        "duplicates": len(duplicates),
        "repaired": repaired,
        "repaired_units": repaired_units,
        "skipped": skipped,
        "errors": errors,
    }


def ensure_stock_for_transition(
    order: Invoice,
    *,
    target_status: str | None = None,
    target_payment_status: str | None = None,
) -> bool:
    status = target_status if target_status is not None else order.status
    payment = target_payment_status if target_payment_status is not None else order.payment_status
    deducted = False
    if not stock_is_deducted(order) and order_needs_stock(status=status, payment_status=payment):
        deducted = deduct_order_stock(order)
    if (payment or "").strip() == "مسدد":
        from utils.trade_in_service import sync_trade_in_receipts

        sync_trade_in_receipts(order, paid_override=True)
    return deducted


def prepare_order_for_dispatch(order: Invoice) -> bool:
    """Start one physical dispatch cycle and own its inventory atomically.

    A delayed order no longer owns stock because the previous report restored
    it.  Creating the next courier/agent report is therefore the point where a
    new immutable deduction movement must be recorded before the parcel leaves
    the branch again.
    """
    if order is None:
        raise OrderStockError("الطلب غير موجود")
    if is_canceled(order.status, order.payment_status):
        raise OrderStockError("لا يمكن إخراج طلب ملغى", order_id=order.id)
    if is_returned(order.status, order.payment_status):
        raise OrderStockError("لا يمكن إخراج طلب راجع", order_id=order.id)
    if normalize_status(order.status) in {"تم التوصيل", "مسدد"}:
        raise OrderStockError("الطلب واصل مسبقاً ولا يمكن إخراجه بكشف جديد", order_id=order.id)

    deducted = ensure_stock_for_transition(order, target_status="جاري الشحن")
    order.status = "جاري الشحن"
    order.shipping_status = "جاري الشحن"
    db.session.flush()
    return deducted


def migrate_pending_orders_to_deferred() -> dict:
    """Release legacy pending/unpaid inventory and unlock shortage orders."""
    from utils.order_stock_lock import clear_order_stock_lock, is_stock_locked

    restored_orders = 0
    restored_units = 0
    unlocked_orders = 0
    orders = (
        Invoice.query.options(
            load_only(
                Invoice.id,
                Invoice.branch_id,
                Invoice.status,
                Invoice.payment_status,
                Invoice.is_stock_locked,
                Invoice.stock_is_deducted,
                Invoice.stock_deducted_at,
                Invoice.stock_restored_at,
            )
        )
        .filter(Invoice.status == "تم الطلب")
        .order_by(Invoice.id.asc())
        .all()
    )
    for order in orders:
        if order_needs_stock(payment_status=order.payment_status):
            continue
        if stock_is_deducted(order):
            restored_units += sum(int(item.quantity or 0) for item in _physical_items(order.id))
            if restore_order_stock(order, release_fulfillment=True):
                restored_orders += 1
        if is_stock_locked(order):
            clear_order_stock_lock(order)
            unlocked_orders += 1
    db.session.flush()
    return {
        "restored_orders": restored_orders,
        "restored_units": restored_units,
        "unlocked_orders": unlocked_orders,
    }


def ensure_policy_initialized() -> dict:
    """Apply the default-enabled policy once for an existing tenant."""
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    policy_initialized = bool(flags.get(POLICY_INITIALIZED_FLAG))
    repair_initialized = bool(flags.get(DUPLICATE_RESTORE_REPAIR_FLAG))
    if policy_initialized and repair_initialized:
        return {"migrated": False, "restored_orders": 0, "restored_units": 0, "unlocked_orders": 0}

    result = migrate_pending_orders_to_deferred() if (
        not policy_initialized and bool(flags.get(POLICY_FLAG, True))
    ) else {
        "restored_orders": 0,
        "restored_units": 0,
        "unlocked_orders": 0,
    }
    repair_result = (
        repair_duplicate_order_restores()
        if not repair_initialized
        else {"duplicates": 0, "repaired": 0, "repaired_units": 0, "skipped": 0, "errors": []}
    )
    flags[POLICY_FLAG] = bool(flags.get(POLICY_FLAG, True))
    flags[POLICY_INITIALIZED_FLAG] = True
    if not repair_result["errors"]:
        flags[DUPLICATE_RESTORE_REPAIR_FLAG] = True
    settings.set_ui_flags(flags)
    settings.updated_at = datetime.utcnow()
    db.session.add(settings)
    db.session.commit()
    result["migrated"] = not policy_initialized
    result["duplicate_restore_repair"] = repair_result
    return result


def initialize_registered_tenant_policies() -> dict:
    """Initialize the default policy for every company registered in Core.

    Request hooks still initialize lazily as a safety net. Running this during
    startup also releases legacy pending/unpaid inventory immediately. The
    scoped session must be removed between tenants because invoice ids repeat
    across the separate tenant databases.
    """
    from flask import g
    from models.core.tenant import Tenant

    previous_tenant = getattr(g, "tenant", None)
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    try:
        g.tenant = None
        db.session.remove()
        tenant_slugs = [
            str(slug).strip()
            for (slug,) in db.session.query(Tenant.slug).filter(Tenant.slug.isnot(None)).all()
            if str(slug or "").strip()
        ]
        db.session.remove()

        for tenant_slug in tenant_slugs:
            g.tenant = tenant_slug
            try:
                results[tenant_slug] = ensure_policy_initialized()
            except Exception as exc:
                db.session.rollback()
                errors[tenant_slug] = str(exc)
            finally:
                db.session.remove()
    finally:
        g.tenant = previous_tenant

    return {"tenants": results, "errors": errors}


def set_deferred_stock_policy(enabled: bool) -> dict:
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    was_enabled = bool(flags.get(POLICY_FLAG, True))
    result = {"restored_orders": 0, "restored_units": 0, "unlocked_orders": 0}
    if enabled and not was_enabled:
        result = migrate_pending_orders_to_deferred()
    flags[POLICY_FLAG] = bool(enabled)
    flags[POLICY_INITIALIZED_FLAG] = True
    settings.set_ui_flags(flags)
    settings.updated_at = datetime.utcnow()
    db.session.add(settings)
    db.session.commit()
    return {"enabled": bool(enabled), **result}


def set_packed_stock_deduction_policy(enabled: bool) -> dict:
    """Choose whether the packed status itself starts inventory deduction."""
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags[PACKED_DEDUCTION_FLAG] = bool(enabled)
    settings.set_ui_flags(flags)
    settings.updated_at = datetime.utcnow()
    db.session.add(settings)
    db.session.commit()
    return {"deduct_on_packed": bool(enabled)}
