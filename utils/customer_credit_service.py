# utils/customer_credit_service.py
from __future__ import annotations

from datetime import date, datetime, timedelta

from extensions import db
from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment, CustomerInstallment
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.customer import Customer
from models.employee import Employee
from utils.cash_calculations import _effective_paid_amount as _effective_paid_amount_inv
from utils.payment_ledger import append_payment_ledger_delta
from utils.inventory_movements import validate_sale_quantity


ENTRY_TYPES = ("opening", "products", "manual")
INTERVALS = ("monthly", "weekly")


def parse_amount(raw_value):
    if raw_value is None:
        return 0
    cleaned = str(raw_value).strip().replace(",", "").replace(" ", "")
    if not cleaned:
        return 0
    try:
        return max(0, int(float(cleaned)))
    except (TypeError, ValueError):
        return 0


def parse_date(raw_value):
    if not raw_value:
        return None
    if isinstance(raw_value, date):
        return raw_value
    try:
        return datetime.strptime(str(raw_value).strip()[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def split_installment_amounts(total_amount: int, count: int) -> list[int]:
    count = max(1, int(count or 1))
    total_amount = max(0, int(total_amount or 0))
    if total_amount == 0:
        return [0] * count
    base = total_amount // count
    remainder = total_amount - (base * count)
    amounts = [base] * count
    if amounts:
        amounts[-1] += remainder
    return amounts


def add_interval(d: date, interval: str, steps: int = 1) -> date:
    if interval == "weekly":
        return d + timedelta(weeks=steps)
    return d + timedelta(days=30 * steps)


def generate_installment_rows(plan_id: int, total_amount: int, count: int, first_due_date: date, interval: str):
    amounts = split_installment_amounts(total_amount, count)
    rows = []
    due = first_due_date
    for seq, amount in enumerate(amounts, start=1):
        rows.append(
            CustomerInstallment(
                plan_id=plan_id,
                sequence=seq,
                due_date=due,
                amount=amount,
                paid_amount=0,
                status="paid" if amount == 0 else "pending",
            )
        )
        due = add_interval(due, interval if interval in INTERVALS else "monthly")
    return rows


def compute_installment_status(inst: CustomerInstallment, today: date | None = None) -> str:
    today = today or date.today()
    paid = int(inst.paid_amount or 0)
    amount = int(inst.amount or 0)
    if amount <= 0 or paid >= amount:
        return "paid"
    if paid > 0:
        return "partial"
    if inst.due_date and inst.due_date < today:
        return "overdue"
    return "pending"


def refresh_installment_statuses(plan: CustomerCreditPlan, today: date | None = None):
    for inst in plan.installments:
        inst.status = compute_installment_status(inst, today)


def remove_invoice_credit_plans(invoice_id: int, reason: str = "ترجيع أو إلغاء") -> int:
    """Remove installment debt for a returned/canceled invoice while preserving payment history."""
    plans = CustomerCreditPlan.query.filter_by(invoice_id=invoice_id).all()
    with db.session.no_autoflush:
        for plan in plans:
            for payment in list(plan.payments):
                payment.plan_id = None
                payment.installment_id = None
                # Financial history keeps its original source marker and text.
                # The finance guard permits only detachment after full reversal.
                if not (payment.note or "").startswith("[FV:"):
                    return_note = f"خطة أقساط ملغاة بسبب {reason} الطلب #{invoice_id}"
                    payment.note = f"{payment.note} — {return_note}" if payment.note else return_note
            db.session.delete(plan)
    return len(plans)


def cleanup_voided_invoice_credit_plans(customer_id: int | None = None) -> int:
    """Remove orphan credit plans linked to canceled or returned invoices."""
    from utils.order_status import is_canceled, is_returned

    query = CustomerCreditPlan.query.filter(CustomerCreditPlan.invoice_id.isnot(None))
    if customer_id is not None:
        query = query.filter_by(customer_id=customer_id)

    removed = 0
    seen_invoices: set[int] = set()
    for plan in query.all():
        invoice_id = int(plan.invoice_id)
        if invoice_id in seen_invoices:
            continue
        seen_invoices.add(invoice_id)
        invoice = Invoice.query.get(invoice_id)
        if not invoice:
            continue
        if is_canceled(invoice.status, invoice.payment_status) or is_returned(
            invoice.status, invoice.payment_status
        ):
            reason = "إلغاء" if is_canceled(invoice.status, invoice.payment_status) else "ترجيع"
            removed += remove_invoice_credit_plans(invoice_id, reason=reason)
    return removed


def sync_invoice_from_plan(plan: CustomerCreditPlan):
    if not plan.invoice_id:
        return
    invoice = Invoice.query.get(plan.invoice_id)
    if not invoice:
        return
    prev_eff = _effective_paid_amount_inv(invoice)
    paid = int(plan.paid_amount or 0)
    total = int(plan.total_amount or 0)
    if paid > 0:
        from utils.order_stock_policy import ensure_stock_for_transition

        ensure_stock_for_transition(
            invoice,
            target_status="تم التوصيل" if paid >= total and total > 0 else invoice.status,
            target_payment_status="مسدد" if paid >= total and total > 0 else "جزئي",
        )
    invoice.paid_amount = min(paid, total)
    if paid >= total and total > 0:
        invoice.payment_status = "مسدد"
        if invoice.status not in ("تم التوصيل", "مرتجع", "ملغي"):
            invoice.status = "تم التوصيل"
    elif paid > 0:
        invoice.payment_status = "جزئي"
    else:
        invoice.payment_status = "غير مسدد"
        invoice.paid_amount = 0
    delta = _effective_paid_amount_inv(invoice) - prev_eff
    if delta:
        append_payment_ledger_delta(invoice.id, delta)


def create_credit_invoice(customer: Customer, employee: Employee | None, items: list[dict], note: str = ""):
    from utils.order_stock_policy import deferred_stock_enabled

    defer_stock = deferred_stock_enabled()
    invoice = Invoice(
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=employee.id if employee else None,
        employee_name=employee.name if employee else None,
        total=0,
        status="تم الطلب",
        payment_status="غير مسدد",
        paid_amount=0,
        note=note or "بيع آجل — أقساط",
        created_at=datetime.utcnow(),
        stock_is_deducted=False,
    )
    db.session.add(invoice)
    db.session.flush()

    total = 0
    for row in items:
        product = Product.query.get(row.get("product_id"))
        if not product:
            raise ValueError("منتج غير موجود")
        qty = max(1, int(row.get("qty") or 1))
        if not defer_stock:
            validation = validate_sale_quantity(product.id, qty)
            if not validation.get("valid"):
                raise ValueError(validation.get("message") or "كمية غير متاحة")

        custom_price = row.get("price")
        if custom_price and int(custom_price) > 0:
            item_price = int(custom_price)
        else:
            item_price = int(product.sale_price or 0)

        item_total = item_price * qty
        order_item = OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=qty,
            price=item_price,
            cost=int(product.buy_price or 0),
            total=item_total,
        )
        total += item_total
        db.session.add(order_item)
        db.session.flush()

    invoice.total = total
    if not defer_stock:
        from utils.order_stock_policy import deduct_order_stock, select_order_stock_branch

        preferred_branch_id = (
            getattr(employee, "branch_id", None)
            or getattr(customer, "branch_id", None)
        )
        select_order_stock_branch(invoice, preferred_branch_id)
        deduct_order_stock(invoice)
    return invoice


def create_credit_plan(
    customer_id: int,
    entry_type: str,
    total_amount: int,
    installments_count: int,
    first_due_date: date,
    interval: str,
    description: str = "",
    invoice_id: int | None = None,
    employee_id: int | None = None,
):
    if entry_type not in ENTRY_TYPES:
        raise ValueError("نوع البند غير صالح")
    if total_amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
    if not first_due_date:
        raise ValueError("تاريخ أول استحقاق مطلوب")

    plan = CustomerCreditPlan(
        customer_id=customer_id,
        entry_type=entry_type,
        invoice_id=invoice_id,
        description=description or None,
        total_amount=total_amount,
        paid_amount=0,
        installments_count=max(1, int(installments_count or 1)),
        employee_id=employee_id,
    )
    db.session.add(plan)
    db.session.flush()

    for inst in generate_installment_rows(
        plan.id, total_amount, plan.installments_count, first_due_date, interval
    ):
        db.session.add(inst)
    return plan


def _redistribute_installment_amounts(installments: list[CustomerInstallment], new_total: int):
    rows = sorted(installments, key=lambda item: item.sequence)
    if not rows:
        raise ValueError("لا توجد أقساط لإعادة التوزيع")

    new_total = int(new_total or 0)
    paid_list = [int(inst.paid_amount or 0) for inst in rows]
    paid_total = sum(paid_list)
    if new_total < paid_total:
        raise ValueError("المبلغ الجديد أقل من المسدد")

    amounts = split_installment_amounts(new_total, len(rows))
    for idx, paid_i in enumerate(paid_list):
        if amounts[idx] >= paid_i:
            continue
        deficit = paid_i - amounts[idx]
        amounts[idx] = paid_i
        for j in range(len(rows) - 1, idx, -1):
            available = amounts[j] - paid_list[j]
            if available <= 0:
                continue
            take = min(available, deficit)
            amounts[j] -= take
            deficit -= take
            if deficit <= 0:
                break
        if deficit > 0:
            raise ValueError("تعذر إعادة توزيع الأقساط")

    for inst, amount in zip(rows, amounts):
        inst.amount = int(amount)
        inst.status = compute_installment_status(inst)


def update_credit_plan(
    plan_id: int,
    description: str | None = None,
    total_amount: int | None = None,
):
    plan = CustomerCreditPlan.query.get(plan_id)
    if not plan:
        raise ValueError("البند غير موجود")

    if description is not None:
        cleaned = (description or "").strip()
        plan.description = cleaned or None

    if total_amount is not None:
        if plan.entry_type == "products" and plan.invoice_id:
            raise ValueError("لا يمكن تعديل مبلغ بند مرتبط بفاتورة منتجات")
        new_total = int(total_amount or 0)
        if new_total <= 0:
            raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
        paid = int(plan.paid_amount or 0)
        if new_total < paid:
            raise ValueError("المبلغ الجديد أقل من المسدد")
        plan.total_amount = new_total
        _redistribute_installment_amounts(list(plan.installments), new_total)
        refresh_installment_statuses(plan)
        sync_invoice_from_plan(plan)

    return plan


def allocate_payment_fifo(
    customer_id: int,
    amount: int,
    note: str = "",
    employee_id: int | None = None,
    payment_date: date | None = None,
):
    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر")

    plans = (
        CustomerCreditPlan.query.filter_by(customer_id=customer_id)
        .order_by(CustomerCreditPlan.created_at.asc())
        .with_for_update()
        .all()
    )
    total_remaining = sum(p.remaining for p in plans)
    if amount > total_remaining:
        raise ValueError("المبلغ أكبر من المتبقي")

    remaining_pay = amount
    payments_created = []
    touched_plans = set()
    paid_at = datetime.utcnow()
    if payment_date:
        paid_at = datetime.combine(payment_date, datetime.min.time().replace(hour=12))

    account, customer = None, None
    if any(plan.invoice_id is None and plan.remaining > 0 for plan in plans):
        from models.customer import Customer
        from utils.treasury_helpers import get_default_cash_account
        from utils.financial_period_guard import assert_date_period_open
        customer = db.session.get(Customer, customer_id)
        if not customer:
            raise ValueError("العميل غير موجود")
        assert_date_period_open(paid_at.date(), "تسديد دين مستقل")
        # Account setup can commit schema/bootstrap changes; resolve it before any payment mutation.
        account = get_default_cash_account(customer.branch_id)

    installments = (
        CustomerInstallment.query.join(CustomerCreditPlan)
        .filter(CustomerCreditPlan.customer_id == customer_id)
        .order_by(CustomerInstallment.due_date.asc(), CustomerInstallment.sequence.asc())
        .with_for_update()
        .all()
    )

    for inst in installments:
        if remaining_pay <= 0:
            break
        inst_remaining = inst.remaining
        if inst_remaining <= 0:
            continue
        pay_slice = min(remaining_pay, inst_remaining)
        inst.paid_amount = int(inst.paid_amount or 0) + pay_slice
        inst.status = compute_installment_status(inst)
        plan = inst.plan
        plan.paid_amount = int(plan.paid_amount or 0) + pay_slice
        touched_plans.add(plan.id)

        payment = CustomerCreditPayment(
            customer_id=customer_id,
            plan_id=plan.id,
            installment_id=inst.id,
            amount=pay_slice,
            note=note or None,
            employee_id=employee_id,
            created_at=paid_at,
        )
        db.session.add(payment)
        if plan.invoice_id is None:
            from models.account_transaction import AccountTransaction
            db.session.flush()
            db.session.add(AccountTransaction(type="deposit", branch_id=customer.branch_id or account.branch_id,
                treasury_account_id=account.id, amount=pay_slice, created_at=paid_at,
                note=f"صندوق - تسديد دين مستقل #{plan.id} [CP:{payment.id}]"))
        payments_created.append(payment)
        remaining_pay -= pay_slice

    for plan_id in touched_plans:
        plan = CustomerCreditPlan.query.get(plan_id)
        if plan:
            refresh_installment_statuses(plan)
            sync_invoice_from_plan(plan)

    return payments_created, amount - remaining_pay


def credit_plan_financial_summary() -> dict:
    """ملخص ديون الأجل/الأقساط للتقرير المالي."""
    plans = CustomerCreditPlan.query.all()
    total_remaining = sum(p.remaining for p in plans)
    unlinked_remaining = sum(p.remaining for p in plans if not p.invoice_id)
    linked_remaining = max(0, int(total_remaining) - int(unlinked_remaining))
    active_plans = sum(1 for p in plans if p.remaining > 0)
    return {
        "installment_debt_total": int(total_remaining),
        "installment_debt_unlinked": int(unlinked_remaining),
        "installment_debt_linked": int(linked_remaining),
        "installment_active_plans": int(active_plans),
    }


def visible_credit_plans(customer_id: int) -> list[CustomerCreditPlan]:
    """Ignore obsolete invoice debt for display without deleting financial history."""
    from sqlalchemy.orm import joinedload
    from utils.order_status import is_canceled, is_returned

    plans = (
        CustomerCreditPlan.query.options(joinedload(CustomerCreditPlan.invoice))
        .filter_by(customer_id=customer_id)
        .order_by(CustomerCreditPlan.created_at.desc())
        .all()
    )
    return [plan for plan in plans if not (
        plan.invoice and (
            is_canceled(plan.invoice.status, plan.invoice.payment_status)
            or is_returned(plan.invoice.status, plan.invoice.payment_status)
        )
    )]


def customer_credit_summary(customer_id: int) -> dict:
    plans = visible_credit_plans(customer_id)
    total_debt = sum(int(p.total_amount or 0) for p in plans)
    total_paid = sum(int(p.paid_amount or 0) for p in plans)
    remaining = max(0, total_debt - total_paid)
    active_plans = sum(1 for p in plans if p.remaining > 0)

    today = date.today()
    installments = (
        CustomerInstallment.query.join(CustomerCreditPlan)
        .filter(CustomerInstallment.plan_id.in_([plan.id for plan in plans]))
        .order_by(CustomerInstallment.due_date.asc(), CustomerInstallment.sequence.asc())
        .all()
    )
    overdue_count = 0
    next_inst = None
    for inst in installments:
        st = compute_installment_status(inst, today)
        if st == "overdue":
            overdue_count += 1
        if next_inst is None and st in ("pending", "partial", "overdue") and inst.remaining > 0:
            next_inst = inst

    return {
        "total_debt": total_debt,
        "total_paid": total_paid,
        "remaining": remaining,
        "active_plans": active_plans,
        "overdue_count": overdue_count,
        "next_installment": next_inst,
    }
