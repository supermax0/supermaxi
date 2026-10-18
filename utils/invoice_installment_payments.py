"""Allocate invoice payment edits without posting cash a second time."""
from datetime import datetime

from flask import has_request_context, session
from sqlalchemy import inspect

from extensions import db
from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment, CustomerInstallment
from modules.finance.common import FinanceError
from utils.customer_credit_service import compute_installment_status
from utils.payment_ledger import business_today


def sync_invoice_installments(invoice, *, recorded_at=None, note=None):
    """The invoice/treasury caller owns the payment; this only records its slices.

    Allocating the final invoice balance also makes split treasury payments safe:
    the second ledger slice sees an already synchronized plan and does nothing.
    Finance and customer FIFO callers already allocate their own slices.
    """
    with db.session.no_autoflush:
        plans = CustomerCreditPlan.query.filter_by(invoice_id=invoice.id).with_for_update().all()
        if not plans:
            return
        if len(plans) != 1:
            raise FinanceError("الفاتورة مرتبطة بأكثر من خطة أقساط؛ راجع الخطط قبل تعديل التحصيل", "conflict", 409)
        plan = plans[0]
        installments = CustomerInstallment.query.filter_by(plan_id=plan.id).order_by(
            CustomerInstallment.due_date, CustomerInstallment.sequence, CustomerInstallment.id
        ).with_for_update().all()
        before = int(plan.paid_amount or 0)
        target = int(invoice.paid_amount or 0)
        if (plan.customer_id != invoice.customer_id or plan.total_amount != invoice.total
                or not 0 <= before <= plan.total_amount or not 0 <= target <= plan.total_amount
                or sum(i.amount for i in installments) != plan.total_amount
                or sum(int(i.paid_amount or 0) for i in installments) != before
                or any(i.amount < 0 or not 0 <= int(i.paid_amount or 0) <= i.amount for i in installments)):
            raise FinanceError("رصيد الفاتورة وجدول الأقساط غير متطابق؛ راجع التسديدات قبل التعديل", "conflict", 409)
        if target == before:
            return
        previous = inspect(invoice).attrs.paid_amount.history.deleted
        if previous and before != int(previous[0] or 0):
            raise FinanceError("رصيد الفاتورة وخطة الأقساط مختلف قبل التعديل؛ راجع التسديدات", "conflict", 409)
        payments = CustomerCreditPayment.query.filter_by(plan_id=plan.id).with_for_update().all()
        if payments and (sum(p.amount for p in payments) != before
                or any(p.installment_id not in {i.id for i in installments} for p in payments)
                or any(sum(p.amount for p in payments if p.installment_id == i.id)
                       != int(i.paid_amount or 0) for i in installments)):
            raise FinanceError("سجل دفعات الأقساط لا يطابق الرصيد؛ راجع مصدر التسديدات", "conflict", 409)
        protected = {i.id: sum(p.amount for p in payments
            if p.installment_id == i.id and "[FV:" in (p.note or "")) for i in installments}
        if any(not 0 <= protected[i.id] <= int(i.paid_amount or 0) for i in installments):
            raise FinanceError("توزيع سندات الحسابات لا يطابق الأقساط؛ راجع السندات الأصلية", "conflict", 409)
        delta = target - before
        if delta < 0 and -delta > sum(int(i.paid_amount or 0) - protected[i.id] for i in installments):
            raise FinanceError("التسديد مرتبط بسند حسابات؛ اعكس السند الأصلي من الحسابات قبل إنقاص التحصيل", "immutable_source", 409)

    employee_id = session.get("user_id") if has_request_context() else None
    # Preserve an old, unitemized balance explicitly; do not invent another cash entry.
    if before and not payments:
        for installment in installments:
            if installment.paid_amount:
                db.session.add(CustomerCreditPayment(customer_id=plan.customer_id, plan_id=plan.id,
                    installment_id=installment.id, amount=installment.paid_amount,
                    created_at=plan.created_at, note=f"[IP:{invoice.id}] رصيد أقساط سابق قبل سجل التعديل"))
    remaining = abs(delta)
    for installment in installments if delta > 0 else reversed(installments):
        paid = int(installment.paid_amount or 0)
        available = installment.amount - paid if delta > 0 else paid - protected[installment.id]
        applied = min(remaining, available)
        if not applied:
            continue
        signed = applied if delta > 0 else -applied
        installment.paid_amount = paid + signed
        installment.status = compute_installment_status(installment, business_today())
        db.session.add(CustomerCreditPayment(customer_id=plan.customer_id, plan_id=plan.id,
            installment_id=installment.id, amount=signed, employee_id=employee_id,
            created_at=recorded_at or datetime.utcnow(),
            note=f"[IP:{invoice.id}] {note or 'تعديل تحصيل الفاتورة'}"[:255]))
        remaining -= applied
        if not remaining:
            break
    plan.paid_amount = target
    return before
