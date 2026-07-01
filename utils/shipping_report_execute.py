# utils/shipping_report_execute.py
"""Shared logic for executing shipping / agent report status selections."""

from __future__ import annotations

import json

from extensions import db
from models.expense import Expense
from models.invoice import Invoice
from models.order_item import OrderItem

from utils.cash_calculations import _effective_paid_amount as _effective_paid_amount_inv
from utils.payment_ledger import append_payment_ledger_delta


def execute_shipping_report(report, expense_amount: int = 0) -> dict:
    if report.is_executed:
        return {"error": "تم تنفيذ هذا الكشف مسبقاً"}

    if not report.order_status_selections:
        return {"error": "لا توجد حالات محفوظة للتنفيذ"}

    try:
        status_selections = json.loads(report.order_status_selections)
    except Exception:
        return {"error": "خطأ في قراءة الحالات المحفوظة"}

    if not isinstance(status_selections, dict) or not status_selections:
        return {"error": "لا توجد حالات محفوظة للتنفيذ"}

    orders_data = json.loads(report.orders_data) if report.orders_data else []

    updated_count = 0
    canceled_count = 0
    delayed_count = 0

    try:
        if expense_amount and int(expense_amount) > 0:
            db.session.add(
                Expense(
                    title=f"كروة - كشف {report.report_number}",
                    category="كروة",
                    amount=int(expense_amount),
                    note=f"مصروف كروة لكشف رقم {report.report_number}",
                )
            )

        for order_data in orders_data:
            order_id = order_data.get("id") or order_data.get("order_id")
            if not order_id:
                continue

            order = Invoice.query.get(order_id)
            if not order:
                continue

            selected_status = status_selections.get(str(order_id))
            if not selected_status:
                continue

            if selected_status in ("واصل", "Delivered"):
                prev_eff = _effective_paid_amount_inv(order)
                order.status = "مسدد"
                order.payment_status = "مسدد"
                if not order.paid_amount or int(order.paid_amount or 0) < int(order.total or 0):
                    order.paid_amount = order.total
                delta_pay = _effective_paid_amount_inv(order) - prev_eff
                append_payment_ledger_delta(order.id, delta_pay)
                updated_count += 1
            elif selected_status in ("ملغي", "Canceled"):
                from utils.order_status import is_canceled, is_returned

                already_canceled = is_canceled(order.status, order.payment_status)
                already_returned = is_returned(order.status, order.payment_status)
                order.status = "ملغي"
                order.payment_status = "ملغي"
                canceled_count += 1
                if not already_canceled and not already_returned:
                    items = OrderItem.query.filter_by(invoice_id=order.id).all()
                    for item in items:
                        if item.product:
                            item.product.quantity += int(item.quantity or 0)
            elif selected_status in ("مؤجل", "Delayed"):
                order.status = "تم الطلب"
                order.payment_status = "غير مسدد"
                order.note = order.note or "مؤجل"
                delayed_count += 1

        report.is_executed = True
        db.session.commit()

        return {
            "success": True,
            "message": (
                f"تم تنفيذ الكشف بنجاح: {updated_count} واصل، "
                f"{canceled_count} ملغي، {delayed_count} مؤجل"
            ),
            "updated_count": updated_count,
            "canceled_count": canceled_count,
            "delayed_count": delayed_count,
        }
    except Exception as e:
        db.session.rollback()
        return {"error": f"حدث خطأ أثناء التنفيذ: {str(e)}"}
