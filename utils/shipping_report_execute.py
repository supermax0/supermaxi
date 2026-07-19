# utils/shipping_report_execute.py
"""Shared logic for executing shipping / agent report status selections."""

from __future__ import annotations

import json

from extensions import db
from models.expense import Expense
from models.invoice import Invoice

from utils.cash_calculations import _effective_paid_amount as _effective_paid_amount_inv
from utils.delivery_expense_service import sync_delivery_expense_for_invoice
from utils.order_lifecycle import clear_order_barcodes, restore_order_stock_once
from utils.payment_ledger import append_payment_ledger_delta
from utils.shipping_settlement_service import ensure_paid_shipping_order_settled
from utils.order_stock_policy import OrderStockError, ensure_stock_for_transition


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
    report_number = str(getattr(report, "report_number", "") or "")

    if report_number.startswith("AGT-"):
        try:
            from utils.agent_report_helpers import (
                extract_agent_id_from_report,
                find_blocking_executed_agent_reports_for_order,
            )

            agent_id = extract_agent_id_from_report(report_number)
            blocked = []
            for order_data in orders_data:
                order_id = order_data.get("id") or order_data.get("order_id")
                if not order_id or not status_selections.get(str(order_id)):
                    continue
                previous_reports = [
                    r.report_number
                    for r in find_blocking_executed_agent_reports_for_order(int(order_id), agent_id)
                    if int(r.id) != int(report.id)
                ]
                if previous_reports:
                    blocked.append(f"#{order_id} منفذ في {', '.join(previous_reports)}")
            if blocked:
                return {"error": "لا يمكن تنفيذ كشف يحتوي طلبات منفذة سابقاً: " + "، ".join(blocked)}
        except Exception as exc:
            return {"error": f"تعذر التحقق من تكرار كشوف المندوب قبل التنفيذ: {exc}"}

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
                ensure_stock_for_transition(order, target_status="تم التوصيل", target_payment_status="مسدد")
                prev_eff = _effective_paid_amount_inv(order)
                order.status = "تم التوصيل"
                order.payment_status = "مسدد"
                if not order.paid_amount or int(order.paid_amount or 0) < int(order.total or 0):
                    order.paid_amount = order.total
                ensure_paid_shipping_order_settled(order)
                delta_pay = _effective_paid_amount_inv(order) - prev_eff
                append_payment_ledger_delta(order.id, delta_pay)
                sync_delivery_expense_for_invoice(order)
                updated_count += 1
            elif selected_status in ("ملغي", "Canceled"):
                from utils.order_status import is_canceled, is_returned

                prev_eff = _effective_paid_amount_inv(order)
                already_canceled = is_canceled(order.status, order.payment_status)
                already_returned = is_returned(order.status, order.payment_status)
                if not already_canceled and not already_returned:
                    restore_order_stock_once(order)
                order.status = "ملغي"
                order.payment_status = "ملغي"
                order.paid_amount = 0
                clear_order_barcodes(order)
                delta_pay = _effective_paid_amount_inv(order) - prev_eff
                append_payment_ledger_delta(order.id, delta_pay)
                canceled_count += 1
                sync_delivery_expense_for_invoice(order)
            elif selected_status in ("مؤجل", "Delayed"):
                prev_eff = _effective_paid_amount_inv(order)
                restore_order_stock_once(order)
                order.status = "تم الطلب"
                order.shipping_status = "تم الطلب"
                order.payment_status = "غير مسدد"
                order.paid_amount = 0
                order.note = order.note or "مؤجل"
                delta_pay = _effective_paid_amount_inv(order) - prev_eff
                append_payment_ledger_delta(order.id, delta_pay)
                sync_delivery_expense_for_invoice(order)
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
    except OrderStockError as e:
        db.session.rollback()
        return {"error": e.message, "code": "INSUFFICIENT_STOCK", "shortages": e.shortages}
    except Exception as e:
        db.session.rollback()
        return {"error": f"حدث خطأ أثناء التنفيذ: {str(e)}"}
