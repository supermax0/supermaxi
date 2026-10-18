# utils/shipping_report_execute.py
"""Shared logic for executing shipping / agent report status selections."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from extensions import db
from models.expense import Expense
from models.invoice import Invoice

from utils.cash_calculations import _effective_paid_amount as _effective_paid_amount_inv
from utils.delivery_expense_service import sync_delivery_expense_for_invoice
from utils.order_lifecycle import clear_order_barcodes, restore_order_stock_once
from utils.payment_ledger import append_payment_ledger_delta
from utils.shipping_settlement_service import ensure_paid_shipping_order_settled
from utils.order_stock_policy import (
    OrderStockError,
    ensure_stock_for_transition,
    select_order_stock_branch,
)


def execute_shipping_report(
    report,
    expense_amount: int = 0,
    return_branch_id: int | str | None = None,
    treasury_account_id: int | None = None,
) -> dict:
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
    # Agent reports already persist the selected fulfillment branch on every
    # physical order line.  A report-level return branch would overwrite that
    # source and can send all returned items to an unrelated branch.  Let the
    # stock policy restore each item to the exact branch it was deducted from.
    effective_return_branch_id = (
        None if report_number.startswith("AGT-") else return_branch_id
    )

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
    replacement_count = 0
    reclassified_count = 0
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

            # Workspace courier statements may route every collection row to a
            # different account. Other reports continue using the report-level
            # account passed by their existing screens.
            order_treasury_account_id = treasury_account_id
            try:
                selected_account_id = int(order_data.get("treasury_account_id") or 0)
                if selected_account_id > 0:
                    order_treasury_account_id = selected_account_id
            except (AttributeError, TypeError, ValueError):
                pass

            if selected_status in ("واصل", "Delivered", "استبدال", "Replacement"):
                is_replacement = selected_status in ("استبدال", "Replacement")
                prev_eff = _effective_paid_amount_inv(order)
                is_piece_settlement = bool(order_data.get("partial_settlement"))
                if is_piece_settlement:
                    order_total = max(int(order.total or 0), 0)
                    requested = max(int(order_data.get("total") or 0), 0)
                    remaining = max(order_total - prev_eff, 0)
                    piece_payment = min(requested, remaining)
                    order.paid_amount = min(prev_eff + piece_payment, order_total)
                    if order.paid_amount >= order_total:
                        ensure_stock_for_transition(
                            order,
                            target_status="تم التوصيل",
                            target_payment_status="مسدد",
                        )
                        order.status = "استبدال" if is_replacement else "تم التوصيل"
                        order.shipping_status = "استبدال" if is_replacement else "تم التوصيل"
                        order.payment_status = "مسدد"
                    else:
                        order.payment_status = "جزئي"
                else:
                    ensure_stock_for_transition(
                        order,
                        target_status="تم التوصيل",
                        target_payment_status="مسدد",
                    )
                    order.status = "استبدال" if is_replacement else "تم التوصيل"
                    order.shipping_status = "استبدال" if is_replacement else "تم التوصيل"
                    order.payment_status = "مسدد"
                    if not order.paid_amount or int(order.paid_amount or 0) < int(order.total or 0):
                        order.paid_amount = order.total
                delta_pay = _effective_paid_amount_inv(order) - prev_eff
                append_payment_ledger_delta(
                    order.id,
                    delta_pay,
                    treasury_account_id=order_treasury_account_id,
                )
                reclassified_amount = _reclassify_invoice_payment_account(
                    order.id,
                    order_data.get("payment_reclassification"),
                )
                allocations = _invoice_payment_allocations(
                    order.id,
                    pending_delta=delta_pay,
                    pending_treasury_account_id=order_treasury_account_id,
                )
                # A workspace row with zero collection is a courier-fee-only row
                # for an order whose collection was posted previously.  Creating a
                # ShippingPayment here would move the old collection to today and
                # make the cash report count it for a second time.
                is_workspace_fee_only = bool(order_data.get("workspace_row_id")) and int(
                    order_data.get("total") or 0
                ) <= 0
                if order.payment_status == "مسدد" and not is_workspace_fee_only:
                    ensure_paid_shipping_order_settled(
                        order,
                        treasury_account_id=order_treasury_account_id,
                        allocations=allocations,
                    )
                sync_delivery_expense_for_invoice(
                    order,
                    treasury_account_id=order_treasury_account_id,
                    allow_partial=is_piece_settlement,
                )
                if is_replacement:
                    order.status = "استبدال"
                    order.shipping_status = "استبدال"
                updated_count += 1
                if reclassified_amount > 0:
                    reclassified_count += 1
                if is_replacement:
                    replacement_count += 1
            elif selected_status in ("ملغي", "Canceled"):
                from utils.order_status import is_canceled, is_returned

                prev_eff = _effective_paid_amount_inv(order)
                already_canceled = is_canceled(order.status, order.payment_status)
                already_returned = is_returned(order.status, order.payment_status)
                if not already_canceled and not already_returned:
                    restore_order_stock_once(order, return_branch_id=effective_return_branch_id)
                order.status = "ملغي"
                order.payment_status = "ملغي"
                order.shipping_status = "ملغي"
                order.paid_amount = 0
                clear_order_barcodes(order)
                from utils.customer_credit_service import remove_invoice_credit_plans

                remove_invoice_credit_plans(order.id, reason="إلغاء")
                delta_pay = _effective_paid_amount_inv(order) - prev_eff
                append_payment_ledger_delta(order.id, delta_pay)
                canceled_count += 1
                sync_delivery_expense_for_invoice(order)
            elif selected_status in ("مؤجل", "Delayed"):
                prev_eff = _effective_paid_amount_inv(order)
                restore_order_stock_once(order, return_branch_id=effective_return_branch_id)
                # If a company report explicitly returned the parcel to another
                # branch, the next dispatch must deduct from that actual branch.
                if effective_return_branch_id not in (None, "", 0, "0"):
                    select_order_stock_branch(order, effective_return_branch_id)
                order.status = "تم الطلب"
                order.shipping_status = "تم الطلب"
                order.payment_status = "غير مسدد"
                order.paid_amount = 0
                order.note = order.note or "مؤجل"
                delta_pay = _effective_paid_amount_inv(order) - prev_eff
                append_payment_ledger_delta(order.id, delta_pay)
                sync_delivery_expense_for_invoice(order)
                delayed_count += 1

        # Record actual execution independently of creation in the report snapshot.
        executed_at = datetime.now(timezone.utc).isoformat()
        for row in orders_data:
            row["executed_at"] = executed_at
        report.orders_data = json.dumps(orders_data, ensure_ascii=False)
        report.is_executed = True
        db.session.commit()

        return {
            "success": True,
            "message": (
                f"تم تنفيذ الكشف بنجاح: {updated_count} واصل، "
                f"منها {replacement_count} استبدال، "
                f"{canceled_count} ملغي، {delayed_count} مؤجل"
            ),
            "updated_count": updated_count,
            "replacement_count": replacement_count,
            "reclassified_payment_count": reclassified_count,
            "canceled_count": canceled_count,
            "delayed_count": delayed_count,
        }
    except OrderStockError as e:
        db.session.rollback()
        return {"error": e.message, "code": "INSUFFICIENT_STOCK", "shortages": e.shortages}
    except Exception as e:
        db.session.rollback()
        return {"error": f"حدث خطأ أثناء التنفيذ: {str(e)}"}


def _invoice_payment_allocations(
    invoice_id: int,
    pending_delta: int = 0,
    pending_treasury_account_id: int | None = None,
) -> list[dict]:
    """Return positive ledger installments with their original dates/accounts.

    Treasury reporting replaces invoice-ledger rows with ShippingPayment rows
    after courier settlement.  The dates therefore must be preserved; grouping
    historical and current installments into one row would make old cash look
    like a new collection on the execution day.
    """
    try:
        from models.invoice_payment_ledger import InvoicePaymentLedger
        from utils.payment_ledger import ensure_invoice_payment_ledger_table
        from utils.treasury_helpers import get_default_cash_account

        ensure_invoice_payment_ledger_table()
        db.session.flush()
        rows = (
            InvoicePaymentLedger.query
            .filter(InvoicePaymentLedger.invoice_id == int(invoice_id))
            .order_by(
                InvoicePaymentLedger.recorded_at.asc(),
                InvoicePaymentLedger.id.asc(),
            )
            .all()
        )
        default_cash_id = int(get_default_cash_account().id)
        lots: list[dict] = []
        for row in rows:
            amount = int(row.amount_delta or 0)
            account_id = int(row.treasury_account_id or default_cash_id)
            if amount > 0:
                lots.append(
                    {
                        "treasury_account_id": account_id,
                        "amount": amount,
                        "created_at": row.recorded_at,
                    }
                )
                continue
            if amount >= 0:
                continue

            # A reversal cancels the newest matching installments first.
            remaining = abs(amount)
            for lot in reversed(lots):
                if remaining <= 0:
                    break
                if row.treasury_account_id is not None and (
                    int(lot["treasury_account_id"]) != account_id
                ):
                    continue
                reduction = min(int(lot["amount"]), remaining)
                lot["amount"] = int(lot["amount"]) - reduction
                remaining -= reduction

        lots = [lot for lot in lots if int(lot["amount"]) > 0]

        from models.invoice import Invoice

        invoice = Invoice.query.get(int(invoice_id))
        paid_total = _effective_paid_amount_inv(invoice) if invoice else sum(
            int(lot["amount"]) for lot in lots
        )
        allocated_total = sum(int(lot["amount"]) for lot in lots)

        # Legacy paid invoices may predate the ledger. Preserve their total and
        # place only the untracked balance on the invoice's original date.
        if invoice is not None and allocated_total < paid_total:
            fallback_account_id = int(
                pending_treasury_account_id or default_cash_id
            )
            lots.insert(
                0,
                {
                    "treasury_account_id": fallback_account_id,
                    "amount": int(paid_total) - allocated_total,
                    "created_at": getattr(invoice, "created_at", None),
                },
            )
        elif allocated_total > paid_total:
            excess = allocated_total - int(paid_total)
            for lot in reversed(lots):
                if excess <= 0:
                    break
                reduction = min(int(lot["amount"]), excess)
                lot["amount"] = int(lot["amount"]) - reduction
                excess -= reduction

        return [lot for lot in lots if int(lot["amount"]) > 0]
    except Exception:
        return []


def _reclassify_invoice_payment_account(
    invoice_id: int,
    plan: dict | None,
) -> int:
    """Reassign existing paid lots without changing the invoice paid total."""
    if not isinstance(plan, dict):
        return 0
    try:
        target_account_id = int(plan.get("target_account_id") or 0)
        expected_amount = int(plan.get("amount") or 0)
    except (TypeError, ValueError):
        return 0
    if target_account_id <= 0 or expected_amount <= 0:
        return 0

    from datetime import datetime

    from models.invoice_payment_ledger import InvoicePaymentLedger

    lots = _invoice_payment_allocations(invoice_id)
    movable = [
        lot
        for lot in lots
        if int(lot.get("treasury_account_id") or 0) != target_account_id
        and int(lot.get("amount") or 0) > 0
    ]
    movable_amount = sum(int(lot["amount"]) for lot in movable)
    if movable_amount != expected_amount:
        raise ValueError(
            "Payment allocation changed after approval; reopen the preview and try again."
        )

    for lot in movable:
        source_account_id = int(lot["treasury_account_id"])
        amount = int(lot["amount"])
        recorded_at = lot.get("created_at")
        if not isinstance(recorded_at, datetime):
            recorded_at = datetime.utcnow()
        db.session.add(
            InvoicePaymentLedger(
                invoice_id=int(invoice_id),
                amount_delta=-amount,
                treasury_account_id=source_account_id,
                source_module="courier_settlement_reclassification",
                note=f"Reclassified to treasury account #{target_account_id}",
                recorded_at=recorded_at,
            )
        )
        db.session.add(
            InvoicePaymentLedger(
                invoice_id=int(invoice_id),
                amount_delta=amount,
                treasury_account_id=target_account_id,
                source_module="courier_settlement_reclassification",
                note=f"Reclassified from treasury account #{source_account_id}",
                recorded_at=recorded_at,
            )
        )
    db.session.flush()
    return movable_amount
