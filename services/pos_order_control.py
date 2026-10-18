"""POS order lookup and lifecycle actions used by the machine API (preview then execute)."""
from __future__ import annotations

import threading

from sqlalchemy import or_

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from models.order_item import OrderItem
from utils.activity_logger import INVOICE_SNAPSHOT_FIELDS, log_mutation, snapshot_attrs
from utils.cash_calculations import _effective_paid_amount
from utils.delivery_expense_service import sync_delivery_expense_for_invoice
from utils.order_lifecycle import OrderLifecycleError, process_order_cancel, process_order_return
from utils.order_stock_lock import LOCKED_ORDER_MESSAGE, is_stock_locked
from utils.order_stock_policy import OrderStockError, ensure_stock_for_transition, stock_is_deducted
from utils.payment_ledger import append_payment_ledger_delta
from utils.permission_checks import employee_can
from utils.shipping_settlement_service import ensure_paid_shipping_order_settled

from services.pos_catalog import serialize_pos_order
from services.pos_checkout import PosCheckoutError

_PAYMENT_LOCK = threading.RLock()


def _visible_order_query(employee):
    query = Invoice.query
    if employee and employee.role == "admin":
        query = query.execution_options(skip_branch_scope=True)
    return query


def get_pos_order(employee, order_id: int) -> Invoice:
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        raise PosCheckoutError("طلب غير صالح", 400, code="VALIDATION_ERROR")
    order = _visible_order_query(employee).filter(Invoice.id == order_id).first()
    if not order:
        raise PosCheckoutError("الطلب غير موجود", 404, code="NOT_FOUND")
    return order


def search_pos_orders(
    employee,
    *,
    customer: str | None = None,
    product: str | None = None,
    province: str | None = None,
    limit: int = 20,
) -> list[dict]:
    query = _visible_order_query(employee)
    customer_q = (customer or "").strip()
    product_q = (product or "").strip()
    province_q = (province or "").strip()
    if customer_q:
        phone_matches = Customer.query.filter(
            or_(
                Customer.name.contains(customer_q),
                Customer.phone.contains(customer_q),
                Customer.phone2.contains(customer_q),
            )
        )
        if employee and employee.role == "admin":
            phone_matches = phone_matches.execution_options(skip_branch_scope=True)
        customer_ids = [row.id for row in phone_matches.limit(200).all()]
        filters = [Invoice.customer_name.contains(customer_q)]
        if customer_ids:
            filters.append(Invoice.customer_id.in_(customer_ids))
        query = query.filter(or_(*filters))
    if province_q:
        province_customers = Customer.query.filter(Customer.city.contains(province_q))
        if employee and employee.role == "admin":
            province_customers = province_customers.execution_options(skip_branch_scope=True)
        province_ids = [row.id for row in province_customers.limit(400).all()]
        query = query.filter(Invoice.customer_id.in_(province_ids or [-1]))
    if product_q:
        item_invoice_ids = [
            row[0]
            for row in db.session.query(OrderItem.invoice_id)
            .filter(OrderItem.product_name.contains(product_q))
            .distinct()
            .limit(400)
            .all()
        ]
        query = query.filter(Invoice.id.in_(item_invoice_ids or [-1]))
    rows = query.order_by(Invoice.created_at.desc()).limit(max(1, min(int(limit or 20), 50))).all()
    return [serialize_pos_order(row) for row in rows]


def _remaining(order: Invoice) -> int:
    return max(0, int(order.total or 0) - int(_effective_paid_amount(order) or 0))


def _require_permission(employee, permission: str):
    if not employee_can(employee, permission):
        raise PosCheckoutError("ليست لديك صلاحية تنفيذ هذا الإجراء", 403, code="FORBIDDEN")


def _reject_locked(order: Invoice):
    if is_stock_locked(order):
        raise PosCheckoutError(LOCKED_ORDER_MESSAGE, 409, code="STOCK_LOCKED")


def preview_pos_payment(employee, order_id: int, *, mode: str = "full", amount=None) -> dict:
    _require_permission(employee, "pay_orders")
    order = get_pos_order(employee, order_id)
    _reject_locked(order)
    remaining_before = _remaining(order)
    mode = (mode or "full").strip().lower()
    if mode not in ("full", "partial"):
        raise PosCheckoutError("وضع التسديد غير صالح", 400, code="VALIDATION_ERROR")
    if remaining_before <= 0:
        raise PosCheckoutError("لا يوجد مبلغ متبقٍ على هذا الطلب", 400, code="ALREADY_PAID")
    if mode == "full":
        pay_amount = remaining_before
    else:
        try:
            pay_amount = int(amount or 0)
        except (TypeError, ValueError):
            raise PosCheckoutError("مبلغ التسديد الجزئي غير صحيح", 400, code="VALIDATION_ERROR")
        if pay_amount <= 0:
            raise PosCheckoutError("مبلغ التسديد الجزئي يجب أن يكون أكبر من صفر", 400, code="VALIDATION_ERROR")
        if pay_amount > remaining_before:
            raise PosCheckoutError(
                f"مبلغ التسديد الجزئي يتجاوز المستحق ({remaining_before:,} د.ع)",
                400,
                code="AMOUNT_EXCEEDS_DUE",
            )
    remaining_after = max(0, remaining_before - pay_amount)
    return {
        "order_id": order.id,
        "amount": pay_amount,
        "mode": "full" if remaining_after == 0 else "partial",
        "remaining_before": remaining_before,
        "remaining_after": remaining_after,
        "total": int(order.total or 0),
        "paid": int(_effective_paid_amount(order) or 0),
    }


def execute_pos_payment(
    employee,
    order_id: int,
    *,
    mode: str = "full",
    amount=None,
    method: str | None = "cash",
) -> dict:
    preview = preview_pos_payment(employee, order_id, mode=mode, amount=amount)
    with _PAYMENT_LOCK:
        order = get_pos_order(employee, order_id)
        _reject_locked(order)
        before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
        prev_effective_paid = _effective_paid_amount(order)
        pay_amount = int(preview["amount"])
        remaining_before = _remaining(order)
        if remaining_before <= 0:
            raise PosCheckoutError("لا يوجد مبلغ متبقٍ على هذا الطلب", 400, code="ALREADY_PAID")
        if pay_amount > remaining_before:
            pay_amount = remaining_before

        payment_status = "مسدد" if pay_amount >= remaining_before else "جزئي"
        try:
            if not stock_is_deducted(order):
                from utils.order_stock_policy import select_order_stock_branch

                select_order_stock_branch(order, order.branch_id)
            ensure_stock_for_transition(order, target_payment_status=payment_status)
        except OrderStockError as exc:
            db.session.rollback()
            raise PosCheckoutError(exc.message, 409, code="INSUFFICIENT_STOCK", payload={"shortages": exc.shortages}) from exc

        treasury_account_id = None
        try:
            from utils.treasury_helpers import get_default_cash_account

            cash = get_default_cash_account(order.branch_id)
            treasury_account_id = cash.id if cash else None
        except Exception:
            treasury_account_id = None

        if payment_status == "مسدد":
            order.payment_status = "مسدد"
            order.paid_amount = order.total
            if order.status not in ("تم التوصيل", "مرتجع", "راجع", "راجعة"):
                order.status = "تم التوصيل"
        else:
            order.paid_amount = min(int(order.paid_amount or 0) + pay_amount, int(order.total or 0))
            if int(order.paid_amount or 0) >= int(order.total or 0):
                order.payment_status = "مسدد"
                order.paid_amount = order.total
                payment_status = "مسدد"
                if order.status not in ("تم التوصيل", "مرتجع", "راجع", "راجعة"):
                    order.status = "تم التوصيل"
            else:
                order.payment_status = "جزئي"

        if payment_status == "مسدد":
            ensure_paid_shipping_order_settled(order)
        delta_pay = _effective_paid_amount(order) - prev_effective_paid
        append_payment_ledger_delta(order.id, delta_pay, treasury_account_id)
        delivery_expense_account_id = None
        if payment_status == "مسدد":
            from utils.treasury_helpers import get_default_cash_account

            try:
                delivery_expense_account_id = get_default_cash_account(order.branch_id).id
            except Exception:
                delivery_expense_account_id = None
        sync_delivery_expense_for_invoice(order, treasury_account_id=delivery_expense_account_id)
        try:
            from utils.payroll_service import sync_commission_line_for_invoice

            sync_commission_line_for_invoice(order)
        except Exception:
            pass
        try:
            from modules.order_installment_lifecycle.service import on_manual_payment

            on_manual_payment(order, employee_id=employee.id)
        except Exception:
            pass
        db.session.commit()
        try:
            log_mutation(
                "update",
                "pos_api",
                "invoice",
                order.id,
                before,
                snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
                f"تسديد الطلب #{order.id} عبر API — {order.payment_status}",
            )
        except Exception:
            pass
        return {
            "order_id": order.id,
            "amount": pay_amount,
            "method": method or "cash",
            "payment_status": order.payment_status,
            "paid": int(_effective_paid_amount(order) or 0),
            "remaining": _remaining(order),
            "status": order.status,
        }


def preview_pos_cancel(employee, order_id: int) -> dict:
    _require_permission(employee, "delete_orders")
    order = get_pos_order(employee, order_id)
    _reject_locked(order)
    return {
        "order_id": order.id,
        "status": order.status,
        "payment_status": order.payment_status,
        "total": int(order.total or 0),
        "can_cancel": True,
        "message": "سيتم إلغاء الطلب وإرجاع المخزون إن كان مخصوماً.",
    }


def execute_pos_cancel(employee, order_id: int, *, reason: str | None = None) -> dict:
    preview_pos_cancel(employee, order_id)
    order = get_pos_order(employee, order_id)
    _reject_locked(order)
    before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
    prev_effective_paid = _effective_paid_amount(order)
    try:
        process_order_cancel(order, actor_id=employee.id, reason=reason)
        append_payment_ledger_delta(order.id, _effective_paid_amount(order) - prev_effective_paid)
        sync_delivery_expense_for_invoice(order)
        try:
            from utils.payroll_service import sync_commission_line_for_invoice

            sync_commission_line_for_invoice(order)
        except Exception:
            pass
        db.session.commit()
    except OrderLifecycleError as exc:
        db.session.rollback()
        raise PosCheckoutError(exc.message, exc.status_code, code="CANCEL_DENIED") from exc
    except Exception as exc:
        db.session.rollback()
        raise PosCheckoutError(str(exc), 500, code="SERVER_ERROR") from exc
    try:
        log_mutation(
            "update",
            "pos_api",
            "invoice",
            order.id,
            before,
            snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
            f"إلغاء الطلب #{order.id} عبر API",
        )
    except Exception:
        pass
    return {"order_id": order.id, "status": order.status, "payment_status": order.payment_status}


def preview_pos_return(employee, order_id: int) -> dict:
    _require_permission(employee, "return_orders")
    order = get_pos_order(employee, order_id)
    _reject_locked(order)
    return {
        "order_id": order.id,
        "status": order.status,
        "payment_status": order.payment_status,
        "total": int(order.total or 0),
        "paid": int(_effective_paid_amount(order) or 0),
        "message": "سيتم تسجيل الطلب راجعاً وإرجاع الكميات للمخزون.",
    }


def execute_pos_return(employee, order_id: int, *, reason: str | None = None, barcode: str | None = None) -> dict:
    preview_pos_return(employee, order_id)
    order = get_pos_order(employee, order_id)
    _reject_locked(order)
    before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
    prev_effective_paid = _effective_paid_amount(order)
    scanned = (barcode or "").strip() or str(order.id)
    try:
        already_returned, message = process_order_return(order, scanned)
        if already_returned:
            db.session.commit()
            return {"order_id": order.id, "already_returned": True, "message": message}
        delta_pay = _effective_paid_amount(order) - prev_effective_paid
        append_payment_ledger_delta(order.id, delta_pay)
        sync_delivery_expense_for_invoice(order)
        try:
            from utils.payroll_service import sync_commission_line_for_invoice

            sync_commission_line_for_invoice(order)
        except Exception:
            pass
        db.session.commit()
    except OrderLifecycleError as exc:
        db.session.rollback()
        raise PosCheckoutError(exc.message, exc.status_code, code="RETURN_DENIED") from exc
    except Exception as exc:
        db.session.rollback()
        raise PosCheckoutError(str(exc), 500, code="SERVER_ERROR") from exc
    try:
        from utils.customer_blacklist import maybe_auto_blacklist_after_return

        maybe_auto_blacklist_after_return(order.id)
    except Exception:
        pass
    try:
        log_mutation(
            "update",
            "pos_api",
            "invoice",
            order.id,
            before,
            snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
            f"ترجيع الطلب #{order.id} عبر API" + (f" — {reason}" if reason else ""),
        )
    except Exception:
        pass
    return {
        "order_id": order.id,
        "status": order.status,
        "payment_status": order.payment_status,
        "reason": reason or "",
    }
