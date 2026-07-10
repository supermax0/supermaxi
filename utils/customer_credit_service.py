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


def sync_invoice_from_plan(plan: CustomerCreditPlan):
    if not plan.invoice_id:
        return
    invoice = Invoice.query.get(plan.invoice_id)
    if not invoice:
        return
    prev_eff = _effective_paid_amount_inv(invoice)
    paid = int(plan.paid_amount or 0)
    total = int(plan.total_amount or 0)
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
    )
    db.session.add(invoice)
    db.session.flush()

    total = 0
    for row in items:
        product = Product.query.get(row.get("product_id"))
        if not product:
            raise ValueError("منتج غير موجود")
        qty = max(1, int(row.get("qty") or 1))
        validation = validate_sale_quantity(product.id, qty)
        if not validation.get("valid"):
            raise ValueError(validation.get("message") or "كمية غير متاحة")
        if product.quantity < qty:
            raise ValueError(f"الكمية المتوفرة ({product.quantity}) أقل من المطلوب ({qty})")

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
        product.quantity -= qty
        total += item_total
        db.session.add(order_item)

    invoice.total = total
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


def allocate_payment_fifo(customer_id: int, amount: int, note: str = "", employee_id: int | None = None):
    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر")

    plans = (
        CustomerCreditPlan.query.filter_by(customer_id=customer_id)
        .order_by(CustomerCreditPlan.created_at.asc())
        .all()
    )
    total_remaining = sum(p.remaining for p in plans)
    if amount > total_remaining:
        raise ValueError("المبلغ أكبر من المتبقي")

    remaining_pay = amount
    payments_created = []
    touched_plans = set()

    installments = (
        CustomerInstallment.query.join(CustomerCreditPlan)
        .filter(CustomerCreditPlan.customer_id == customer_id)
        .order_by(CustomerInstallment.due_date.asc(), CustomerInstallment.sequence.asc())
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
        )
        db.session.add(payment)
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


def customer_credit_summary(customer_id: int) -> dict:
    plans = CustomerCreditPlan.query.filter_by(customer_id=customer_id).all()
    total_debt = sum(int(p.total_amount or 0) for p in plans)
    total_paid = sum(int(p.paid_amount or 0) for p in plans)
    remaining = max(0, total_debt - total_paid)
    active_plans = sum(1 for p in plans if p.remaining > 0)

    today = date.today()
    installments = (
        CustomerInstallment.query.join(CustomerCreditPlan)
        .filter(CustomerCreditPlan.customer_id == customer_id)
        .order_by(CustomerInstallment.due_date.asc(), CustomerInstallment.sequence.asc())
        .all()
    )
    overdue_count = 0
    next_inst = None
    for inst in installments:
        st = compute_installment_status(inst, today)
        inst.status = st
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
