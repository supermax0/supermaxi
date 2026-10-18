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


def restore_order_stock_once(order, return_branch_id: int | str | None = None,return_location_id: int | None = None) -> bool:
    """
    Restore line quantities to inventory once.
    Returns True if stock was restored, False if already returned/canceled.
    """
    from utils.order_stock_policy import restore_order_stock

    return restore_order_stock(order, return_branch_id=return_branch_id,return_location_id=return_location_id)


def process_order_return(
    order,
    scanned_barcode: Optional[str],
    return_branch_id: int | str | None = None,
    return_location_id: int | None = None,
) -> Tuple[bool, str]:
    """
    Validate barcode, restore stock once, mark returned, clear barcodes.
    Returns (already_returned, message).
    """
    # Only a fully canceled order (status=ملغي) is blocked. Payment-only ملغي with
    # an active fulfillment status (e.g. جاري الشحن) is an inconsistent state that
    # staff must be able to correct into راجع.
    if normalize_status(order.status) == "ملغي":
        raise OrderLifecycleError("لا يمكن ترجيع طلب ملغي")

    if is_returned(order.status, order.payment_status):
        return True, "الطلب راجع مسبقاً"

    if normalize_status(order.status) == "تم الطلب":
        raise OrderLifecycleError("طلب «تم الطلب» يُلغى ولا يُسجل راجعاً")

    if not verify_order_barcode(order, scanned_barcode):
        raise OrderLifecycleError("الباركود لا يطابق الطلب")

    from modules.sales_returns.facts import documents
    saved_returns = documents(order.id)
    if saved_returns is not None and saved_returns.first() is not None:
        from modules.sales_returns.service import return_remaining
        from modules.finance.common import FinanceError
        from modules.sales_returns.preview import ReturnPreviewError

        try:
            return_remaining(order, branch_id=return_branch_id, location_id=return_location_id)
        except (FinanceError, ReturnPreviewError) as exc:
            raise OrderLifecycleError(str(exc), getattr(exc, "status", 409)) from exc
        clear_order_barcodes(order)
        return False, "تم ترجيع الكمية المتبقية وإرجاعها للمخزون"

    try:
        restore_order_stock_once(order, return_branch_id=return_branch_id,return_location_id=return_location_id)
    except Exception as exc:
        from utils.order_stock_policy import OrderStockError

        if isinstance(exc, OrderStockError):
            raise OrderLifecycleError(exc.message) from exc
        raise
    order.status = RETURN_STATUS
    order.payment_status = RETURN_STATUS
    order.paid_amount = 0
    if hasattr(order, "shipping_status"):
        order.shipping_status = RETURN_STATUS
    from utils.shipping_settlement_service import reverse_returned_shipping_settlement

    reverse_returned_shipping_settlement(order)
    clear_order_barcodes(order)
    from utils.customer_credit_service import remove_invoice_credit_plans

    remove_invoice_credit_plans(order.id, reason="ترجيع")
    try:
        from modules.order_installment_lifecycle.service import on_order_returned

        on_order_returned(order)
    except Exception:
        pass
    return False, "تم ترجيع الطلب وإرجاع الكمية للمخزون"


def _sync_installment_cancellation(order, actor_id: int | None, reason: str | None) -> None:
    if str(getattr(order, "source_module", "") or "").strip().lower() != "installments":
        return
    from modules.installments.services import CancellationService, InstallmentError

    try:
        CancellationService.cancel_from_invoice(order, employee_id=actor_id, reason=reason)
    except InstallmentError as exc:
        raise OrderLifecycleError(str(exc)) from exc


def process_order_cancel(order, *, actor_id: int | None = None, reason: str | None = None) -> None:
    """Cancel a pending order and synchronize any linked installment records."""
    status = normalize_status(order.status)
    already_canceled = is_canceled(order.status, order.payment_status)
    if status != "تم الطلب" and not already_canceled:
        raise OrderLifecycleError("يمكن إلغاء الطلب فقط عندما تكون حالته «تم الطلب»")

    from utils.customer_credit_service import remove_invoice_credit_plans

    if already_canceled:
        # Repair partially cancelled legacy orders without returning stock twice.
        order.status = "ملغي"
        order.payment_status = "ملغي"
        order.paid_amount = 0
        clear_order_barcodes(order)
        remove_invoice_credit_plans(order.id, reason="إلغاء")
        _sync_installment_cancellation(order, actor_id, reason)
        try:
            from modules.order_installment_lifecycle.service import on_order_cancelled

            on_order_cancelled(order, employee_id=actor_id)
        except Exception:
            pass
        return

    restore_order_stock_once(order)
    order.status = "ملغي"
    order.payment_status = "ملغي"
    order.paid_amount = 0
    clear_order_barcodes(order)
    remove_invoice_credit_plans(order.id, reason="إلغاء")
    _sync_installment_cancellation(order, actor_id, reason)
    try:
        from modules.order_installment_lifecycle.service import on_order_cancelled

        on_order_cancelled(order, employee_id=actor_id)
    except Exception:
        pass
