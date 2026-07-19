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
POLICY_INITIALIZED_FLAG = "defer_pending_order_stock_initialized_v2"
STOCK_STATUSES = {"معباة", "معبأة", "جاري الشحن", "قيد الشحن", "تم التوصيل", "مسدد"}
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


def order_needs_stock(*, status: str | None = None, payment_status: str | None = None) -> bool:
    return normalize_status(status) in STOCK_STATUSES or normalize_status(payment_status) in STOCK_PAYMENT_STATUSES


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


def deduct_order_stock(order: Invoice) -> bool:
    """Deduct every physical line atomically in the caller's transaction."""
    if stock_is_deducted(order):
        return False

    from utils.order_stock_lock import apply_stock_actions, check_invoice_stock, clear_order_stock_lock

    now = datetime.utcnow()
    claimed = (
        db.session.query(Invoice)
        .filter(Invoice.id == order.id, Invoice.stock_is_deducted.is_(False))
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
            f"المخزون غير كافٍ لتنفيذ الطلب #{order.id}: {detail}",
            result.reasons,
            order_id=order.id,
        )
    try:
        apply_stock_actions(result.actions, invoice=order)
    except Exception as exc:
        raise OrderStockError(str(exc), [str(exc)], order_id=order.id) from exc

    clear_order_stock_lock(order)
    db.session.flush()
    return True


def restore_order_stock(order: Invoice, *, release_fulfillment: bool = False) -> bool:
    """Restore physical lines only when they are currently deducted."""
    if not stock_is_deducted(order):
        return False

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

    for item in _physical_items(order.id):
        product = Product.query.get(item.product_id)
        if not product:
            continue
        qty = int(item.quantity or 0)
        branch_id = item.fulfillment_branch_id or getattr(order, "branch_id", None)
        if branch_id:
            from utils.branch_stock_service import receive_stock

            receive_stock(int(branch_id), product.id, qty)
        else:
            product.quantity = int(product.quantity or 0) + qty
        color = (getattr(item, "variant_color", None) or "").strip()
        if color:
            from utils.product_color_service import restore_color_stock

            restore_color_stock(product.id, color, qty)
        if release_fulfillment:
            item.fulfillment_branch_id = None

    db.session.flush()
    return True


def ensure_stock_for_transition(
    order: Invoice,
    *,
    target_status: str | None = None,
    target_payment_status: str | None = None,
) -> bool:
    if stock_is_deducted(order):
        return False
    status = target_status if target_status is not None else order.status
    payment = target_payment_status if target_payment_status is not None else order.payment_status
    if not order_needs_stock(status=status, payment_status=payment):
        return False
    return deduct_order_stock(order)


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
    if flags.get(POLICY_INITIALIZED_FLAG):
        return {"migrated": False, "restored_orders": 0, "restored_units": 0, "unlocked_orders": 0}

    result = migrate_pending_orders_to_deferred() if bool(flags.get(POLICY_FLAG, True)) else {
        "restored_orders": 0,
        "restored_units": 0,
        "unlocked_orders": 0,
    }
    flags[POLICY_FLAG] = bool(flags.get(POLICY_FLAG, True))
    flags[POLICY_INITIALIZED_FLAG] = True
    settings.set_ui_flags(flags)
    settings.updated_at = datetime.utcnow()
    db.session.add(settings)
    db.session.commit()
    result["migrated"] = True
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
