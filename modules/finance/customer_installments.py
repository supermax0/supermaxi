"""Keep invoice collections and their installment allocations in one transaction."""
from datetime import datetime
import json
import re
from sqlalchemy import inspect

from extensions import db
from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment, CustomerInstallment
from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
from models.invoice import Invoice
from utils.customer_credit_service import compute_installment_status
from .common import FinanceError, get_row, today, tenant_key
from .models import FinanceAllocation, FinanceVoucher


def is_reversed_invoice_archive(session, payment):
    """Only detach immutable payments from a removed, fully reversed invoice plan."""
    state = inspect(payment)
    changed = {attr.key for attr in state.attrs if attr.history.has_changes()}
    previous = state.attrs.plan_id.history.deleted
    if (payment in session.deleted or not changed or not changed <= {"plan_id", "installment_id"}
            or payment.plan_id is not None or payment.installment_id is not None or not previous):
        return False
    with session.no_autoflush:
        plan = session.get(CustomerCreditPlan, previous[0])
        invoice = session.get(Invoice, plan.invoice_id) if plan and plan.invoice_id else None
        from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
        if (not plan or plan not in session.deleted or not invoice
                or invoice.status not in CANCELED_STATUSES | RETURN_STATUSES
                or invoice.paid_amount or plan.paid_amount
                or payment.customer_id != plan.customer_id or invoice.customer_id != plan.customer_id
                or any(i.paid_amount for i in plan.installments)):
            return False
        history = CustomerCreditPayment.query.filter_by(plan_id=plan.id).all()
        if sum(p.amount for p in history) != 0:
            return False
        for item in history:
            marker = re.match(r"^\[FV:(\d+)\]", item.note or "")
            if not marker:
                continue
            source = session.get(FinanceVoucher, int(marker[1]))
            if (not source or source.tenant_key != tenant_key() or source.party_type != "customer"
                    or source.party_id != invoice.customer_id):
                return False
            if item.amount > 0:
                if source.status != "reversed":
                    return False
            else:
                try:
                    original = session.get(FinanceVoucher, json.loads(source.payload)["original_id"])
                except (ValueError, TypeError, KeyError):
                    return False
                if (source.category != "reversal" or source.status != "posted" or not original
                        or original.status != "reversed" or original.reversal_id != source.id):
                    return False
        return True


def invoice_schedule(invoice):
    plans = CustomerCreditPlan.query.filter_by(invoice_id=invoice.id).with_for_update().all()
    if not plans:
        return None, []
    if len(plans) != 1:
        raise FinanceError("الفاتورة مرتبطة بأكثر من خطة أقساط؛ راجع الخطط قبل التحصيل", "conflict", 409)
    plan = plans[0]
    installments = CustomerInstallment.query.filter_by(plan_id=plan.id).order_by(
        CustomerInstallment.due_date, CustomerInstallment.sequence, CustomerInstallment.id
    ).with_for_update().all()
    paid = int(plan.paid_amount or 0)
    if (plan.customer_id != invoice.customer_id or plan.total_amount != invoice.total
            or paid != int(invoice.paid_amount or 0)
            or sum(i.amount for i in installments) != plan.total_amount
            or sum(int(i.paid_amount or 0) for i in installments) != paid
            or any(int(i.paid_amount or 0) < 0 or int(i.paid_amount or 0) > i.amount for i in installments)):
        raise FinanceError("رصيد الفاتورة وخطة الأقساط غير متطابق؛ راجع التسديدات قبل المتابعة", "conflict", 409)
    return plan, installments


def standalone_schedule(plan):
    installments = CustomerInstallment.query.filter_by(plan_id=plan.id).order_by(
        CustomerInstallment.due_date, CustomerInstallment.sequence, CustomerInstallment.id
    ).with_for_update().all()
    paid = int(plan.paid_amount or 0)
    if (plan.invoice_id is not None or paid < 0 or paid > plan.total_amount
            or sum(i.amount for i in installments) != plan.total_amount
            or sum(int(i.paid_amount or 0) for i in installments) != paid
            or any(i.amount < 0 or not 0 <= int(i.paid_amount or 0) <= i.amount for i in installments)):
        raise FinanceError("رصيد الدين وجدول الأقساط غير متطابق؛ راجع التسديدات قبل المتابعة", "conflict", 409)
    return installments


def collect(row, invoice, amount):
    plan, installments = invoice_schedule(invoice)
    if plan is None:
        return
    collect_schedule(row, plan, installments, amount)


def collect_standalone(row, plan, amount):
    from .standalone_debts import assert_reviewed
    assert_reviewed(plan)
    collect_schedule(row, plan, standalone_schedule(plan), amount)


def collect_schedule(row, plan, installments, amount):
    remaining = amount
    for installment in installments:
        before = int(installment.paid_amount or 0)
        applied = min(remaining, installment.amount - before)
        if applied <= 0:
            continue
        installment.paid_amount = before + applied
        installment.status = compute_installment_status(installment, today())
        payment = CustomerCreditPayment(customer_id=plan.customer_id, plan_id=plan.id,
            installment_id=installment.id, amount=applied, employee_id=row.approved_by,
            note=f"[FV:{row.id}] {row.number}",
            created_at=datetime.combine(row.transaction_date, datetime.min.time().replace(hour=12)))
        db.session.add(payment)
        db.session.flush()
        db.session.add(FinanceAllocation(voucher_id=row.id, reference_type="credit_plan_payment",
            reference_id=payment.id, amount=applied, before_amount=before,
            after_amount=installment.paid_amount))
        remaining -= applied
        if remaining == 0:
            break
    if remaining:
        raise FinanceError("تغير رصيد الأقساط؛ أعد مراجعة توزيع الدفعة", "conflict", 409)
    plan.paid_amount = int(plan.paid_amount or 0) + amount


def prepare_reversal(row, allocations):
    """Validate every original slice before changing the invoice or creating a reversal."""
    schedules = {}
    for allocation in allocations:
        if allocation.reference_type == "invoice":
            invoice = get_row(Invoice, allocation.reference_id)
            plan, installments = invoice_schedule(invoice)
            if plan:
                schedules[plan.id] = (plan, {i.id: i for i in installments}, allocation.amount)
        elif allocation.reference_type == "customer_debt":
            plan = CustomerCreditPlan.query.filter_by(id=allocation.reference_id).with_for_update().first()
            if not plan or plan.customer_id != row.party_id:
                raise FinanceError("تغير مصدر الدين؛ راجع السند قبل العكس", "dependency", 409)
            from .standalone_debts import assert_reviewed
            assert_reviewed(plan)
            schedules[plan.id] = (plan, {i.id: i for i in standalone_schedule(plan)}, allocation.amount)
    totals = {plan_id: 0 for plan_id in schedules}
    result = []
    references = [(a.reference_id, a.amount, None) for a in allocations if a.reference_type == "credit_plan_payment"]
    if inspect(db.session.connection()).has_table(CustomerSchedulePaymentLink.__tablename__):
        for allocation in allocations:
            if allocation.reference_type != "invoice":
                continue
            link = CustomerSchedulePaymentLink.query.filter_by(invoice_allocation_id=allocation.id).with_for_update().first()
            if not link:
                continue
            schedule = next((s for s in schedules.values() if s[0].invoice_id == allocation.reference_id), None)
            if not schedule or link.reversal_payment_id:
                raise FinanceError("تغير ربط التحصيل السابق؛ راجع السند والجدول الأصلي", "dependency", 409)
            references.append((link.payment_id, allocation.amount, schedule[0].id))
    for payment_id, amount, expected_plan_id in references:
        payment = CustomerCreditPayment.query.filter_by(id=payment_id).with_for_update().first()
        schedule = next((s for s in schedules.values() if payment and s[0].id == payment.plan_id), None)
        if not payment or not schedule:
            raise FinanceError("تغيرت خطة أقساط السند؛ راجع المستند الأصلي قبل العكس", "dependency", 409)
        plan, installments, _ = schedule
        installment = installments.get(payment.installment_id)
        if (payment.customer_id != row.party_id or payment.amount != amount
                or not installment or int(installment.paid_amount or 0) < amount
                or expected_plan_id is not None and (plan.id != expected_plan_id or not (payment.note or "").startswith(f"[FV:{row.id}]"))):
            raise FinanceError("تغير تخصيص دفعة الأقساط؛ راجعه قبل عكس السند", "dependency", 409)
        totals[plan.id] += amount
        result.append((payment, plan, installment))
    if any(totals[invoice_id] != schedule[2] for invoice_id, schedule in schedules.items()):
        raise FinanceError("توزيع السند على الأقساط غير مكتمل؛ راجع التسديدات القديمة قبل العكس", "dependency", 409)
    return result


def reverse(row, slices):
    for original, plan, installment in slices:
        before = int(installment.paid_amount or 0)
        installment.paid_amount = before - original.amount
        installment.status = compute_installment_status(installment, today())
        plan.paid_amount = int(plan.paid_amount or 0) - original.amount
        db.session.add(CustomerCreditPayment(customer_id=plan.customer_id, plan_id=plan.id,
            installment_id=installment.id, amount=-original.amount, employee_id=row.approved_by,
            note=f"[FV:{row.id}] {row.number} — عكس دفعة #{original.id}",
            created_at=datetime.combine(row.transaction_date, datetime.min.time().replace(hour=12))))
        db.session.add(FinanceAllocation(voucher_id=row.id, reference_type="credit_plan_reversal",
            reference_id=original.id, amount=original.amount, before_amount=before,
            after_amount=installment.paid_amount))
