"""
Unified order return/cancel lifecycle: barcode verification, stock restore, barcode clearing.
"""

from __future__ import annotations

from typing import Optional, Tuple

from models.order_item import OrderItem
from models.product import Product
from utils.order_status import is_canceled, is_returned, normalize_status, RETURN_STATUS


class OrderLifecycleError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def verify_order_barcode(order, scanned: Optional[str]) -> bool:
    """Return True if scanned value matches order id, invoice barcode, or shipping barcode."""
    code = normalize_status(scanned)
    if not code:
        return False
    if code == str(order.id):
        return True
    invoice_barcode = normalize_status(getattr(order, "barcode", None))
    if invoice_barcode and invoice_barcode == code:
        return True
    shipping_barcode = normalize_status(getattr(order, "shipping_barcode", None))
    if shipping_barcode and shipping_barcode == code:
        return True
    try:
        from utils.shipping_barcodes import shipping_barcodes_match_code
        if shipping_barcodes_match_code(order, code):
            return True
    except Exception:
        pass
    return False


def clear_order_barcodes(order) -> None:
    order.barcode = None
    order.shipping_barcode = None
    if hasattr(order, "shipping_barcodes_json"):
        order.shipping_barcodes_json = None


def restore_order_stock_once(order, return_branch_id: int | str | None = None) -> bool:
    """
    Restore line quantities to inventory once.
    Returns True if stock was restored, False if already returned/canceled.
    """
    from utils.order_stock_policy import restore_order_stock

    return restore_order_stock(order, return_branch_id=return_branch_id)


def process_order_return(
    order,
    scanned_barcode: Optional[str],
    return_branch_id: int | str | None = None,
) -> Tuple[bool, str]:
    """
    Validate barcode, restore stock once, mark returned, clear barcodes.
    Returns (already_returned, message).
    """
    if is_canceled(order.status, order.payment_status):
        raise OrderLifecycleError("لا يمكن ترجيع طلب ملغي")

    if is_returned(order.status, order.payment_status):
        return True, "الطلب راجع مسبقاً"

    if normalize_status(order.status) == "تم الطلب":
        raise OrderLifecycleError("طلب «تم الطلب» يُلغى ولا يُسجل راجعاً")

    if not verify_order_barcode(order, scanned_barcode):
        raise OrderLifecycleError("الباركود لا يطابق الطلب")

    try:
        restore_order_stock_once(order, return_branch_id=return_branch_id)
    except Exception as exc:
        from utils.order_stock_policy import OrderStockError

        if isinstance(exc, OrderStockError):
            raise OrderLifecycleError(exc.message) from exc
        raise
    order.status = RETURN_STATUS
    order.payment_status = RETURN_STATUS
    order.paid_amount = 0
    clear_order_barcodes(order)
    return False, "تم ترجيع الطلب وإرجاع الكمية للمخزون"


def process_order_cancel(order) -> None:
    """Cancel a pending order; restore only if it was actually deducted."""
    status = normalize_status(order.status)
    if status != "تم الطلب":
        raise OrderLifecycleError("يمكن إلغاء الطلب فقط عندما تكون حالته «تم الطلب»")

    if is_canceled(order.status, order.payment_status):
        if status != "ملغي":
            order.status = "ملغي"
            order.payment_status = "ملغي"
            order.paid_amount = 0
            clear_order_barcodes(order)
        return

    restore_order_stock_once(order)
    order.status = "ملغي"
    order.payment_status = "ملغي"
    order.paid_amount = 0
    clear_order_barcodes(order)
