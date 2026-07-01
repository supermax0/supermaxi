"""
Unified order return/cancel lifecycle: barcode verification, stock restore, barcode clearing.
"""

from __future__ import annotations

from typing import Optional, Tuple

from models.order_item import OrderItem
from models.product import Product
from utils.order_status import is_canceled, is_returned, normalize_status


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
    return False


def clear_order_barcodes(order) -> None:
    order.barcode = None
    order.shipping_barcode = None


def restore_order_stock_once(order) -> bool:
    """
    Restore line quantities to inventory once.
    Returns True if stock was restored, False if already returned/canceled.
    """
    if is_returned(order.status, order.payment_status) or is_canceled(
        order.status, order.payment_status
    ):
        return False

    items = OrderItem.query.filter_by(invoice_id=order.id).all()
    for item in items:
        product = Product.query.get(item.product_id)
        if product:
            product.quantity += int(item.quantity or 0)
    return True


def process_order_return(order, scanned_barcode: Optional[str]) -> Tuple[bool, str]:
    """
    Validate barcode, restore stock once, mark returned, clear barcodes.
    Returns (already_returned, message).
    """
    if is_canceled(order.status, order.payment_status):
        raise OrderLifecycleError("لا يمكن ترجيع طلب ملغي")

    if is_returned(order.status, order.payment_status):
        return True, "الطلب مرتجع مسبقاً"

    if not verify_order_barcode(order, scanned_barcode):
        raise OrderLifecycleError("الباركود لا يطابق الطلب")

    restore_order_stock_once(order)
    order.status = "مرتجع"
    order.payment_status = "مرتجع"
    order.paid_amount = 0
    clear_order_barcodes(order)
    return False, "تم ترجيع الطلب وإرجاع الكمية للمخزون"


def process_order_cancel(order) -> None:
    """Cancel order only when status is تم الطلب; restore stock and clear barcodes."""
    status = normalize_status(order.status)
    if status != "تم الطلب":
        raise OrderLifecycleError("يمكن إلغاء الطلب فقط عندما تكون حالته «تم الطلب»")

    if is_canceled(order.status, order.payment_status):
        return

    restore_order_stock_once(order)
    order.status = "ملغي"
    order.payment_status = "ملغي"
    order.paid_amount = 0
    clear_order_barcodes(order)
