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
from utils.branch_stock_service import BranchStockError, deduct_stock, get_branch_stock, get_total_stock
from utils.order_shipping import is_shipping_item
from utils.product_color_service import (
    ProductColorError,
    deduct_color_stock,
    get_color_quantity,
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
        return get_branch_stock(branch_id, product_id)
    return get_total_stock(product_id)


def check_stock_rows(rows: Iterable[dict], *, preferred_branch_id: int | None = None) -> StockCheckResult:
    actions: list[StockAction] = []
    reasons: list[str] = []

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
            available_color = get_color_quantity(product.id, variant_color)
            if available_color < qty:
                reasons.append(
                    f"{product.name} / {variant_color}: المتوفر {available_color} والمطلوب {qty}"
                )
                continue

        explicit_branch_id = row.get("fulfillment_branch_id")
        try:
            explicit_branch_id = int(explicit_branch_id) if explicit_branch_id not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            explicit_branch_id = None

        branch_id = pick_fulfillment_branch(
            product.id,
            qty,
            preferred_branch_id=preferred_branch_id,
            explicit_branch_id=explicit_branch_id,
        )
        available = _available_for_reason(product.id, branch_id or preferred_branch_id)
        if not branch_id or available < qty:
            reasons.append(f"{product.name}: المتوفر {available} والمطلوب {qty}")
            continue

        actions.append(
            StockAction(
                product_id=product.id,
                quantity=qty,
                fulfillment_branch_id=branch_id,
                variant_color=variant_color,
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
        rows.append(
            {
                "product_id": item.product_id,
                "product": item.product,
                "quantity": int(item.quantity or 0),
                "variant_color": getattr(item, "variant_color", None),
                "fulfillment_branch_id": getattr(item, "fulfillment_branch_id", None),
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
    items_by_product: dict[tuple[int, str | None], list[OrderItem]] = {}
    if invoice is not None and getattr(invoice, "id", None):
        for item in OrderItem.query.filter_by(invoice_id=invoice.id).all():
            if is_shipping_item(item):
                continue
            key = (int(item.product_id), (getattr(item, "variant_color", None) or "").strip() or None)
            items_by_product.setdefault(key, []).append(item)

    for action in actions:
        try:
            deduct_stock(action.fulfillment_branch_id, action.product_id, action.quantity)
            if action.variant_color:
                deduct_color_stock(action.product_id, action.variant_color, action.quantity)
        except ProductColorError as exc:
            product = Product.query.get(action.product_id)
            product_name = (product.name if product else None) or f"#{action.product_id}"
            raise BranchStockError(
                f"مخزون اللون غير كافٍ للمنتج «{product_name} / {action.variant_color}»: {exc}"
            ) from exc

        if invoice is not None:
            key = (int(action.product_id), (action.variant_color or "").strip() or None)
            candidates = items_by_product.get(key) or []
            for item in candidates:
                if int(item.quantity or 0) == int(action.quantity or 0):
                    item.fulfillment_branch_id = action.fulfillment_branch_id
                    candidates.remove(item)
                    break


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
