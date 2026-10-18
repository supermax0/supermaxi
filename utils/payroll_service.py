"""Payroll: salary scheduling, commission accrual, treasury payout."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any, Optional, Union

from extensions import db
from models.account_transaction import AccountTransaction
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from models.employee_commission_line import EmployeeCommissionLine
from models.employee_commission_settlement import EmployeeCommissionSettlement
from models.employee_payment import EmployeePayment
from models.expense import Expense
from models.invoice import Invoice
from utils.employee_commission import get_employee_commission_amount, is_commission_eligible_employee
from utils.employee_commission_service import delivered_paid_filter
from utils.treasury_calculations import InsufficientTreasuryBalance, assert_sufficient_balance
from utils.treasury_helpers import resolve_treasury_account_id
from utils.treasury_schema_guard import ensure_treasury_schema
from utils.branch_scope import active_branch_id, scope_query, viewing_all_branches

PAY_TYPE_NONE = "none"
PAY_TYPE_MONTHLY = "monthly"
PAY_TYPE_WEEKLY = "weekly"
PAY_TYPE_COMMISSION = "commission"
PAY_TYPE_MONTHLY_COMMISSION = "monthly_commission"
PAY_TYPE_WEEKLY_COMMISSION = "weekly_commission"

SALARY_PAY_TYPES = {PAY_TYPE_MONTHLY, PAY_TYPE_WEEKLY, PAY_TYPE_MONTHLY_COMMISSION, PAY_TYPE_WEEKLY_COMMISSION}
COMMISSION_PAY_TYPES = {PAY_TYPE_COMMISSION, PAY_TYPE_MONTHLY_COMMISSION, PAY_TYPE_WEEKLY_COMMISSION}
WEEKLY_PAY_TYPES = {PAY_TYPE_WEEKLY, PAY_TYPE_WEEKLY_COMMISSION}
MONTHLY_PAY_TYPES = {PAY_TYPE_MONTHLY, PAY_TYPE_MONTHLY_COMMISSION}

WEEKDAY_LABELS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


Payee = Union[Employee, DeliveryAgent]


def _payee_type(payee: Payee) -> str:
    return "delivery_agent" if isinstance(payee, DeliveryAgent) else "employee"


def _payee_id(payee: Payee) -> int:
    return int(payee.id)


def _payee_name(payee: Payee) -> str:
    return str(payee.name or "")


def _get_pay_type(payee: Payee) -> str:
    return str(getattr(payee, "pay_type", None) or PAY_TYPE_NONE)


def _has_salary_schedule(payee: Payee) -> bool:
    pay_type = _get_pay_type(payee)
    return pay_type in SALARY_PAY_TYPES and int(getattr(payee, "salary", 0) or 0) > 0


def _has_commission(payee: Payee) -> bool:
    if isinstance(payee, DeliveryAgent):
        return False
    pay_type = _get_pay_type(payee)
    if pay_type not in COMMISSION_PAY_TYPES and pay_type != PAY_TYPE_NONE:
        return False
    if pay_type == PAY_TYPE_NONE:
        return is_commission_eligible_employee(payee) and get_employee_commission_amount(payee) > 0
    return is_commission_eligible_employee(payee)


def apply_payroll_config(
    payee: Payee,
    *,
    pay_type: Optional[str] = None,
    salary: Optional[int] = None,
    pay_day_of_month: Optional[int] = None,
    pay_weekday: Optional[int] = None,
    commission: Optional[int] = None,
) -> None:
    """Apply payroll settings; set payroll_effective_from on first salary schedule."""
    old_type = _get_pay_type(payee)
    old_salary = int(getattr(payee, "salary", 0) or 0)

    if pay_type is not None:
        payee.pay_type = pay_type
    if salary is not None:
        payee.salary = max(0, int(salary))
    if pay_day_of_month is not None:
        payee.pay_day_of_month = max(1, min(28, int(pay_day_of_month)))
    if pay_weekday is not None:
        payee.pay_weekday = max(0, min(6, int(pay_weekday)))
    if commission is not None and isinstance(payee, Employee):
        payee.commission_percent = max(0, int(commission))

    new_type = _get_pay_type(payee)
    new_salary = int(getattr(payee, "salary", 0) or 0)
    schedule_changed = (
        new_type in SALARY_PAY_TYPES
        and new_salary > 0
        and (old_type != new_type or old_salary <= 0 or not getattr(payee, "payroll_effective_from", None))
    )
    if schedule_changed:
        payee.payroll_effective_from = date.today()


def _clamp_month_day(year: int, month: int, day: int) -> date:
    _, last = monthrange(year, month)
    return date(year, month, min(day, last))


def _month_datetime_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    _, last = monthrange(year, month)
    return datetime(year, month, 1), datetime(year, month, last, 23, 59, 59)


def _next_monthly_date(after: date, day_of_month: int) -> date:
    year, month = after.year, after.month
    candidate = _clamp_month_day(year, month, day_of_month)
    if candidate > after:
        return candidate
    if month == 12:
        return _clamp_month_day(year + 1, 1, day_of_month)
    return _clamp_month_day(year, month + 1, day_of_month)


def _next_weekly_date(after: date, weekday: int) -> date:
    days_ahead = (weekday - after.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return after + timedelta(days=days_ahead)


def compute_next_salary_date(payee: Payee, *, today: Optional[date] = None) -> Optional[date]:
    """First pay date on or after today according to schedule."""
    if not _has_salary_schedule(payee):
        return None

    today = today or date.today()
    effective = getattr(payee, "payroll_effective_from", None)
    if effective is None:
        return None

    pay_type = _get_pay_type(payee)
    anchor = max(today, effective)
    if pay_type in MONTHLY_PAY_TYPES:
        return _next_monthly_date(anchor - timedelta(days=1), int(getattr(payee, "pay_day_of_month", 25) or 25))
    if pay_type in WEEKLY_PAY_TYPES:
        return _next_weekly_date(anchor - timedelta(days=1), int(getattr(payee, "pay_weekday", 4) or 4))
    return None


def _salary_cycle_start(payee: Payee, *, today: Optional[date] = None) -> Optional[date]:
    """Return the beginning of the salary cycle that contains ``today``."""
    if not _has_salary_schedule(payee):
        return None

    today = today or date.today()
    pay_type = _get_pay_type(payee)
    if pay_type in MONTHLY_PAY_TYPES:
        pay_day = int(getattr(payee, "pay_day_of_month", 25) or 25)
        current_month_date = _clamp_month_day(today.year, today.month, pay_day)
        if current_month_date <= today:
            cycle_start = current_month_date
        elif today.month == 1:
            cycle_start = _clamp_month_day(today.year - 1, 12, pay_day)
        else:
            cycle_start = _clamp_month_day(today.year, today.month - 1, pay_day)
    elif pay_type in WEEKLY_PAY_TYPES:
        pay_weekday = int(getattr(payee, "pay_weekday", 4) or 4)
        cycle_start = today - timedelta(days=(today.weekday() - pay_weekday) % 7)
    else:
        return None

    effective = getattr(payee, "payroll_effective_from", None)
    if effective:
        cycle_start = max(cycle_start, effective)
    return cycle_start


def salary_paid_in_current_cycle(payee: Payee, *, today: Optional[date] = None) -> bool:
    """Whether this payee already received the salary for the active cycle."""
    today = today or date.today()
    cycle_start = _salary_cycle_start(payee, today=today)
    last_paid = getattr(payee, "last_salary_paid_at", None)
    if cycle_start is None or last_paid is None:
        return False
    last_paid_date = last_paid.date() if isinstance(last_paid, datetime) else last_paid
    return cycle_start <= last_paid_date <= today


def is_salary_due(payee: Payee, *, today: Optional[date] = None) -> bool:
    today = today or date.today()
    next_date = compute_next_salary_date(payee, today=today)
    if next_date is None:
        return False
    if next_date > today:
        return False
    last_paid = getattr(payee, "last_salary_paid_at", None)
    if last_paid and last_paid.date() >= next_date:
        return False
    return True


def get_salary_due_amount(payee: Payee) -> int:
    if not _has_salary_schedule(payee):
        return 0
    return int(getattr(payee, "salary", 0) or 0)


def _invoice_is_commission_eligible(invoice: Invoice) -> bool:
    if invoice is None or not invoice.employee_id:
        return False
    row = Invoice.query.filter(Invoice.id == invoice.id).filter(delivered_paid_filter()).first()
    if not row:
        return False
    employee = Employee.query.get(invoice.employee_id)
    return bool(employee and _has_commission(employee))


def sync_commission_line_for_invoice(invoice: Invoice) -> Optional[EmployeeCommissionLine]:
    """Create, void, or keep commission line when invoice state changes."""
    if invoice is not None:
        from modules.hr.commissions import sync_invoice
        if sync_invoice(invoice):
            return EmployeeCommissionLine.query.filter_by(invoice_id=invoice.id).first()
    if invoice is None or not invoice.employee_id:
        return None

    line = EmployeeCommissionLine.query.filter_by(
        invoice_id=invoice.id,
        employee_id=invoice.employee_id,
    ).first()

    eligible = _invoice_is_commission_eligible(invoice)
    if not eligible:
        if line and line.status == "pending":
            line.status = "void"
        return line

    employee = Employee.query.get(invoice.employee_id)
    if not employee:
        return line

    amount = get_employee_commission_amount(employee)
    if amount <= 0:
        if line and line.status == "pending":
            line.status = "void"
        return line

    if line:
        if line.status == "paid":
            return line
        if line.status == "void":
            line.status = "pending"
        line.amount = amount
        return line

    if invoice.employee_commission_settled_at:
        status = "paid"
    else:
        status = "pending"

    line = EmployeeCommissionLine(
        code=EmployeeCommissionLine.make_code(invoice.id, invoice.employee_id),
        invoice_id=invoice.id,
        employee_id=invoice.employee_id,
        amount=amount,
        status=status,
        accrued_at=invoice.created_at or datetime.utcnow(),
    )
    db.session.add(line)
    return line


def _payroll_expense_withdraw_note(expense: Expense) -> str:
    note_extra = f" - {expense.note}" if expense.note else ""
    return (
        f"مصروف: {expense.title} ({expense.category}) "
        f"بتاريخ {expense.expense_date}{note_extra}"
    )


def remove_commission_lines_for_deleted_invoice(
    invoice_id: int,
    *,
    allow_paid: bool = False,
) -> int:
    """Remove invoice commission and, when authorized, its paid payroll share.

    A commission payment may contain many invoices.  In that case only this
    invoice's share is removed from the payment, expense, treasury withdrawal,
    and monthly settlement instead of deleting the other employees' history.
    """
    from sqlalchemy import inspect
    if inspect(db.session.get_bind()).has_table("hr_commission"):
        from modules.hr.models import HRCommission
        if HRCommission.query.filter_by(invoice_id=int(invoice_id)).first():
            raise ValueError("الفاتورة مرتبطة بسجل عمولة؛ استخدم الإلغاء والتسوية لحفظ التاريخ المالي")
    lines = EmployeeCommissionLine.query.filter_by(invoice_id=int(invoice_id)).all()
    paid_lines = [line for line in lines if line.status == "paid" or line.payment_id]
    if paid_lines and not allow_paid:
        raise ValueError("لا يمكن حذف الطلب لأن عمولته مدفوعة ضمن الرواتب")

    paid_by_payment: dict[int, int] = {}
    for line in paid_lines:
        if line.payment_id:
            paid_by_payment[int(line.payment_id)] = (
                paid_by_payment.get(int(line.payment_id), 0)
                + max(0, int(line.amount or 0))
            )

    payments_to_delete = []
    for payment_id, removed_amount in paid_by_payment.items():
        payment = EmployeePayment.query.get(payment_id)
        if not payment:
            continue
        old_amount = max(0, int(payment.amount or 0))
        new_amount = max(0, old_amount - removed_amount)
        expense = payment.expense or Expense.query.filter_by(
            employee_payment_id=payment.id
        ).first()
        withdraw_tx = None
        if expense:
            withdraw_tx = AccountTransaction.query.filter_by(
                type="withdraw",
                note=_payroll_expense_withdraw_note(expense),
            ).order_by(AccountTransaction.id.desc()).first()

        settlements = EmployeeCommissionSettlement.query.filter_by(
            payment_id=payment.id
        ).all()
        for settlement in settlements:
            settlement.amount = max(0, int(settlement.amount or 0) - removed_amount)
            settlement.order_count = max(0, int(settlement.order_count or 0) - 1)

        if new_amount > 0:
            payment.amount = new_amount
            if expense:
                expense.amount = new_amount
            if withdraw_tx:
                withdraw_tx.amount = new_amount
            for settlement in settlements:
                if int(settlement.amount or 0) <= 0:
                    db.session.delete(settlement)
        else:
            for settlement in settlements:
                db.session.delete(settlement)
            if withdraw_tx:
                db.session.delete(withdraw_tx)
            if expense:
                payment.expense_id = None
                expense.employee_payment_id = None
                db.session.delete(expense)
            payments_to_delete.append(payment)

    for line in lines:
        db.session.delete(line)
    if payments_to_delete:
        # Remove child rows first.  Several tenant databases enforce the
        # commission-line/payment foreign key immediately during autoflush.
        db.session.flush()
        for payment in payments_to_delete:
            db.session.delete(payment)
    return len(lines)


def get_pending_commission_lines(
    employee_id: int,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    include_carried: bool = True,
) -> list[EmployeeCommissionLine]:
    """Pending commission lines, optionally scoped to a settlement month.

    When ``year``/``month`` are set:
    - lines accrued in that month are included
    - if ``include_carried`` (default): unpaid lines from earlier months are
      also included so former "جاري شحن" orders that delivered later are paid
      with the selected month and are never lost after a prior settlement
    - lines accrued after the selected month are excluded
    """
    query = (
        EmployeeCommissionLine.query
        .join(Invoice, Invoice.id == EmployeeCommissionLine.invoice_id)
        .filter(EmployeeCommissionLine.employee_id == employee_id, EmployeeCommissionLine.status == "pending")
    )
    branch_id = active_branch_id()
    if branch_id is None and viewing_all_branches():
        from flask import has_request_context, request

        if has_request_context() and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            payload = request.get_json(silent=True) if request.is_json else request.form
            try:
                branch_id = int((payload or {}).get("branch_id") or 0) or None
            except (TypeError, ValueError):
                branch_id = None
    if branch_id is not None and not viewing_all_branches():
        query = query.filter(Invoice.branch_id == int(branch_id))
    elif branch_id is not None:
        query = query.filter(Invoice.branch_id == int(branch_id))
    lines = (
        query
        .order_by(EmployeeCommissionLine.accrued_at.asc(), EmployeeCommissionLine.id.asc())
        .all()
    )
    if year is not None and month is not None:
        start, end = _month_datetime_bounds(int(year), int(month))
        if include_carried:
            lines = [line for line in lines if line.accrued_at and line.accrued_at <= end]
        else:
            lines = [
                line
                for line in lines
                if line.accrued_at and start <= line.accrued_at <= end
            ]
    return lines


def get_pending_commission_total(
    employee_id: int,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    include_carried: bool = True,
) -> dict[str, Any]:
    lines = get_pending_commission_lines(
        employee_id,
        year=year,
        month=month,
        include_carried=include_carried,
    )
    carried_orders = 0
    if year is not None and month is not None and lines:
        start, _end = _month_datetime_bounds(int(year), int(month))
        carried_orders = sum(1 for line in lines if line.accrued_at and line.accrued_at < start)
    return {
        "orders": len(lines),
        "amount": sum(int(l.amount or 0) for l in lines),
        "carried_orders": carried_orders,
        "lines": lines,
    }


def _post_payroll_expense_to_treasury(expense: Expense, treasury_account_id: Optional[int] = None) -> AccountTransaction:
    ensure_treasury_schema()
    account_id = resolve_treasury_account_id(treasury_account_id or expense.treasury_account_id)
    assert_sufficient_balance(account_id, expense.amount)
    note_extra = f" - {expense.note}" if expense.note else ""
    withdraw_tx = AccountTransaction(
        branch_id=expense.branch_id,
        type="withdraw",
        amount=expense.amount,
        note=f"مصروف: {expense.title} ({expense.category}) بتاريخ {expense.expense_date}{note_extra}",
        treasury_account_id=account_id,
    )
    db.session.add(withdraw_tx)
    expense.treasury_account_id = account_id
    expense.cash_posted = True
    return withdraw_tx


def _create_payroll_expense(
    *,
    title: str,
    amount: int,
    treasury_account_id: int,
    employee_id: Optional[int] = None,
    note: Optional[str] = None,
    branch_id: Optional[int] = None,
) -> Expense:
    expense = Expense(
        branch_id=branch_id,
        title=title,
        category="salary",
        amount=amount,
        note=note,
        expense_date=date.today(),
        treasury_account_id=treasury_account_id,
        cash_posted=False,
        employee_id=employee_id,
    )
    db.session.add(expense)
    db.session.flush()
    _post_payroll_expense_to_treasury(expense, treasury_account_id)
    return expense


def _salary_payment_kind(payee: Payee) -> str:
    if _get_pay_type(payee) in WEEKLY_PAY_TYPES:
        return "salary_weekly"
    return "salary_monthly"


def resolve_payroll_payout_branch(treasury, payee) -> tuple[Optional[int], Optional[str]]:
    """Pick the expense branch for a salary payout.

    Shared/legacy companies use one logical treasury. A leftover branch_id on
    the cash box must not block paying employees who belong to another branch.
    Independent-branch companies must pay from the employee's branch treasury.
    """
    from utils.branch_mode import independent_branches_enabled

    payee_branch_id = int(getattr(payee, "branch_id", 0) or 0) or None
    treasury_branch_id = int(getattr(treasury, "branch_id", 0) or 0) if treasury else None
    if not independent_branches_enabled():
        return payee_branch_id or treasury_branch_id, None
    branch_id = treasury_branch_id or payee_branch_id
    if payee_branch_id and branch_id != payee_branch_id:
        return None, "يجب صرف الراتب من خزينة فرع الموظف"
    return branch_id, None


def pay_salary(
    payee: Payee,
    *,
    treasury_account_id: int,
    settled_by: Optional[int] = None,
    manual: bool = False,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Pay fixed salary for employee or delivery agent."""
    if isinstance(payee, Employee):
        from utils.hr_schema import salary_owned_by_hr_workspace
        if salary_owned_by_hr_workspace(payee.id):
            return {"ok": False, "error": "راتب الموظف مُدار بمسير الموارد البشرية؛ استخدم صرف المسير المعتمد"}
    today = today or date.today()
    amount = get_salary_due_amount(payee)
    if amount <= 0:
        return {"ok": False, "error": "لا يوجد راتب محدد"}

    if salary_paid_in_current_cycle(payee, today=today):
        return {"ok": False, "error": "تم صرف راتب هذه الدورة مسبقاً"}

    if not manual and not is_salary_due(payee, today=today):
        return {"ok": False, "error": "الراتب غير مستحق بعد"}

    treasury_account_id = resolve_treasury_account_id(treasury_account_id)
    from models.treasury_account import TreasuryAccount
    treasury = TreasuryAccount.query.get(treasury_account_id)
    branch_id, branch_error = resolve_payroll_payout_branch(treasury, payee)
    if branch_error:
        return {"ok": False, "error": branch_error}
    payee_type = _payee_type(payee)
    payee_id = _payee_id(payee)
    name = _payee_name(payee)
    kind = _salary_payment_kind(payee)
    employee_id = payee_id if payee_type == "employee" else getattr(payee, "employee_id", None)

    try:
        expense = _create_payroll_expense(
            title=f"راتب {name}",
            amount=amount,
            treasury_account_id=treasury_account_id,
            employee_id=employee_id,
            note=f"payroll:{payee_type}:{payee_id}:{kind}",
            branch_id=branch_id,
        )
        payment = EmployeePayment(
            branch_id=branch_id,
            payee_type=payee_type,
            payee_id=payee_id,
            payment_kind=kind,
            amount=amount,
            period_start=today,
            period_end=today,
            treasury_account_id=treasury_account_id,
            settled_by=settled_by,
            note=f"راتب {'أسبوعي' if kind == 'salary_weekly' else 'شهري'} — {name}",
        )
        db.session.add(payment)
        db.session.flush()
        expense.employee_payment_id = payment.id
        payment.expense_id = expense.id
        # Keep the logical payroll date aligned with ``today`` even when the
        # server timezone differs from the business timezone.
        payee.last_salary_paid_at = datetime.combine(today, datetime.min.time())
        db.session.commit()
    except InsufficientTreasuryBalance as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "payment_id": payment.id,
        "expense_id": expense.id,
        "amount": amount,
        "payee_type": payee_type,
        "payee_id": payee_id,
        "payee_name": name,
    }


def settle_employee_commission_payment(
    employee_id: int,
    *,
    treasury_account_id: int,
    settled_by: Optional[int] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict[str, Any]:
    """Settle all pending commission lines with treasury payout."""
    employee = Employee.query.get(employee_id)
    if not employee:
        return {"ok": False, "error": "الموظف غير موجود"}
    if not is_commission_eligible_employee(employee):
        return {"ok": False, "error": "المدير غير مشمول بعمولة الطلبات"}

    lines = get_pending_commission_lines(employee_id, year=year, month=month)
    if not lines:
        if year is not None and month is not None:
            return {"ok": False, "error": f"لا توجد عمولات معلّقة لشهر {year}-{int(month):02d}"}
        return {"ok": False, "error": "لا توجد عمولات معلّقة للسداد"}

    amount = sum(int(l.amount or 0) for l in lines)
    order_count = len(lines)
    treasury_account_id = resolve_treasury_account_id(treasury_account_id)
    from models.treasury_account import TreasuryAccount
    treasury = TreasuryAccount.query.get(treasury_account_id)
    branch_id = int(treasury.branch_id) if treasury and treasury.branch_id else int(employee.branch_id or 0) or None
    now = datetime.utcnow()
    period_year = year or now.year
    period_month = month or now.month

    try:
        expense = _create_payroll_expense(
            title=f"عمولة {employee.name}",
            amount=amount,
            treasury_account_id=treasury_account_id,
            employee_id=employee_id,
            note=f"commission_settle:{employee_id}:{period_year}-{period_month:02d}",
            branch_id=branch_id,
        )
        payment = EmployeePayment(
            branch_id=branch_id,
            payee_type="employee",
            payee_id=employee_id,
            payment_kind="commission",
            amount=amount,
            paid_at=now,
            treasury_account_id=treasury_account_id,
            settled_by=settled_by,
            note=f"عمولة {order_count} طلب — {employee.name}",
        )
        db.session.add(payment)
        db.session.flush()
        expense.employee_payment_id = payment.id
        payment.expense_id = expense.id

        for line in lines:
            line.status = "paid"
            line.payment_id = payment.id
            if line.invoice:
                line.invoice.employee_commission_settled_at = now

        settlement = EmployeeCommissionSettlement(
            employee_id=employee_id,
            period_year=period_year,
            period_month=period_month,
            order_count=order_count,
            amount=amount,
            settled_at=now,
            settled_by=settled_by,
            payment_id=payment.id,
            treasury_account_id=treasury_account_id,
        )
        db.session.add(settlement)
        db.session.commit()
    except InsufficientTreasuryBalance as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "employee_id": employee_id,
        "employee_name": employee.name,
        "order_count": order_count,
        "amount": amount,
        "payment_id": payment.id,
        "period_year": period_year,
        "period_month": period_month,
    }


def process_due_salary_payments(
    *,
    today: Optional[date] = None,
    treasury_account_id: Optional[int] = None,
    settled_by: Optional[int] = None,
) -> dict[str, Any]:
    """Auto-pay all due salaries (employees + delivery agents)."""
    today = today or date.today()
    treasury_account_id = resolve_treasury_account_id(treasury_account_id)
    paid = []
    skipped = []

    payees: list[Payee] = list(scope_query(Employee.query, Employee).filter(Employee.is_active.is_(True)).all())
    payees.extend(DeliveryAgent.query.filter(DeliveryAgent.is_active.is_(True)).all())

    for payee in payees:
        if not is_salary_due(payee, today=today):
            continue
        result = pay_salary(
            payee,
            treasury_account_id=treasury_account_id,
            settled_by=settled_by,
            manual=False,
            today=today,
        )
        if result.get("ok"):
            paid.append(result)
        else:
            skipped.append({"payee_name": _payee_name(payee), "error": result.get("error")})

    return {"paid": paid, "skipped": skipped, "paid_count": len(paid), "skipped_count": len(skipped)}


def _serialize_payee_due(payee: Payee, *, today: Optional[date] = None) -> Optional[dict[str, Any]]:
    today = today or date.today()
    payee_type = _payee_type(payee)
    payee_id = _payee_id(payee)
    pay_type = _get_pay_type(payee)
    rows = []

    if _has_salary_schedule(payee):
        salary_amount = get_salary_due_amount(payee)
        next_date = compute_next_salary_date(payee, today=today)
        due = is_salary_due(payee, today=today)
        paid_in_cycle = salary_paid_in_current_cycle(payee, today=today)
        rows.append(
            {
                "kind": "salary",
                "payee_type": payee_type,
                "payee_id": payee_id,
                "name": _payee_name(payee),
                "pay_type": pay_type,
                "amount": salary_amount,
                "next_pay_date": next_date.isoformat() if next_date else None,
                "is_due": due,
                "paid_in_current_cycle": paid_in_cycle,
                "can_pay_manually": not paid_in_cycle,
                "schedule_label": _schedule_label(payee),
            }
        )

    if payee_type == "employee" and _has_commission(payee):
        pending = get_pending_commission_total(payee_id)
        if pending["orders"] > 0:
            rows.append(
                {
                    "kind": "commission",
                    "payee_type": "employee",
                    "payee_id": payee_id,
                    "name": _payee_name(payee),
                    "pay_type": pay_type,
                    "amount": pending["amount"],
                    "orders": pending["orders"],
                    "is_due": True,
                    "schedule_label": "عند السداد",
                }
            )

    return rows if rows else None


def _schedule_label(payee: Payee) -> str:
    pay_type = _get_pay_type(payee)
    if pay_type in MONTHLY_PAY_TYPES:
        day = int(getattr(payee, "pay_day_of_month", 25) or 25)
        return f"شهري — يوم {day}"
    if pay_type in WEEKLY_PAY_TYPES:
        wd = int(getattr(payee, "pay_weekday", 4) or 4)
        return f"أسبوعي — {WEEKDAY_LABELS[wd]}"
    return ""


def build_payroll_dashboard(
    *,
    today: Optional[date] = None,
    commission_year: Optional[int] = None,
    commission_month: Optional[int] = None,
) -> dict[str, Any]:
    today = today or date.today()
    due_rows: list[dict[str, Any]] = []
    schedule_rows: list[dict[str, Any]] = []

    employees = scope_query(Employee.query, Employee).filter(Employee.is_active.is_(True)).order_by(Employee.name).all()
    agents = DeliveryAgent.query.filter(DeliveryAgent.is_active.is_(True)).order_by(DeliveryAgent.name).all()

    for emp in employees:
        items = _serialize_payee_due(emp, today=today)
        if items:
            due_rows.extend(items)
        if _has_salary_schedule(emp):
            nd = compute_next_salary_date(emp, today=today)
            schedule_rows.append(
                {
                    "payee_type": "employee",
                    "payee_id": emp.id,
                    "name": emp.name,
                    "next_pay_date": nd.isoformat() if nd else None,
                    "amount": get_salary_due_amount(emp),
                    "schedule_label": _schedule_label(emp),
                }
            )

    for agent in agents:
        if not agent.username:
            continue
        items = _serialize_payee_due(agent, today=today)
        if items:
            due_rows.extend(items)
        if _has_salary_schedule(agent):
            nd = compute_next_salary_date(agent, today=today)
            schedule_rows.append(
                {
                    "payee_type": "delivery_agent",
                    "payee_id": agent.id,
                    "name": agent.name,
                    "next_pay_date": nd.isoformat() if nd else None,
                    "amount": get_salary_due_amount(agent),
                    "schedule_label": _schedule_label(agent),
                }
            )

    commission_employees = []
    for emp in employees:
        if not _has_commission(emp):
            continue
        pending = get_pending_commission_total(
            emp.id,
            year=commission_year,
            month=commission_month,
        )
        if pending["orders"] <= 0:
            continue
        commission_employees.append(
            {
                "employee_id": emp.id,
                "employee_name": emp.name,
                "orders": pending["orders"],
                "carried_orders": pending.get("carried_orders", 0),
                "amount": pending["amount"],
                "commission_rate": get_employee_commission_amount(emp),
            }
        )

    total_salary_due = sum(r["amount"] for r in due_rows if r["kind"] == "salary" and r.get("is_due"))
    total_commission_due = sum(r["amount"] for r in due_rows if r["kind"] == "commission")

    return {
        "today": today.isoformat(),
        "due_rows": due_rows,
        "schedule_rows": schedule_rows,
        "commission_employees": commission_employees,
        "commission_year": commission_year,
        "commission_month": commission_month,
        "total_salary_due": total_salary_due,
        "total_commission_due": total_commission_due,
        "total_due": total_salary_due + total_commission_due,
    }


def get_payment_history(*, limit: int = 100) -> list[dict[str, Any]]:
    payments = (
        EmployeePayment.query.order_by(EmployeePayment.paid_at.desc(), EmployeePayment.id.desc())
        .limit(limit)
        .all()
    )
    rows = []
    for p in payments:
        name = ""
        if p.payee_type == "employee":
            emp = Employee.query.get(p.payee_id)
            name = emp.name if emp else f"#{p.payee_id}"
        else:
            agent = DeliveryAgent.query.get(p.payee_id)
            name = agent.name if agent else f"#{p.payee_id}"
        kind_labels = {
            "salary_weekly": "راتب أسبوعي",
            "salary_monthly": "راتب شهري",
            "commission": "عمولة",
        }
        rows.append(
            {
                "id": p.id,
                "payee_type": p.payee_type,
                "payee_id": p.payee_id,
                "payee_name": name,
                "payment_kind": p.payment_kind,
                "payment_kind_label": kind_labels.get(p.payment_kind, p.payment_kind),
                "amount": p.amount,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                "expense_id": p.expense_id,
                "note": p.note,
            }
        )
    return rows


def serialize_commission_lines(
    employee_id: int,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> list[dict[str, Any]]:
    lines = get_pending_commission_lines(employee_id, year=year, month=month)
    result = []
    for line in lines:
        inv = line.invoice
        result.append(
            {
                "id": line.id,
                "code": line.code,
                "invoice_id": line.invoice_id,
                "amount": line.amount,
                "accrued_at": line.accrued_at.isoformat() if line.accrued_at else None,
                "invoice_total": int(inv.total or 0) if inv else 0,
                "customer_name": inv.customer_name if inv else "",
            }
        )
    return result


def build_monthly_orders_statement(year: int, month: int) -> dict[str, Any]:
    """Monthly employee order sheet with full status breakdown.

    Counts for the selected month:
    - orders created in that month (all statuses)
    - plus still-open (pending/shipping) orders created in earlier months
      so they roll into the next month until closed — employee credit is not lost

    Columns: total = delivered + returned + canceled + pending
    """
    from sqlalchemy import and_, case, func, not_, or_

    from utils.order_status import CANCELED_STATUSES, COMPLETED_STATUSES, RETURN_STATUSES

    start = datetime(year, month, 1)
    _, last_day = monthrange(year, month)
    end = datetime(year, month, last_day, 23, 59, 59)

    returned_list = list(RETURN_STATUSES)
    canceled_list = list(CANCELED_STATUSES)
    completed_list = list(COMPLETED_STATUSES)

    is_returned = or_(
        func.coalesce(Invoice.status, "").in_(returned_list),
        func.coalesce(Invoice.payment_status, "").in_(returned_list),
    )
    is_canceled = or_(
        func.coalesce(Invoice.status, "").in_(canceled_list),
        func.coalesce(Invoice.payment_status, "").in_(canceled_list),
    )
    is_delivered = and_(
        not_(is_returned),
        not_(is_canceled),
        or_(
            func.coalesce(Invoice.payment_status, "") == "مسدد",
            func.coalesce(Invoice.status, "").in_(completed_list),
        ),
    )
    # جاري = أي طلب لم يُغلق بعد (تم الطلب / معباة / جاري الشحن / غيرها)
    is_pending = and_(not_(is_returned), not_(is_canceled), not_(is_delivered))

    # طلبات الشهر المحدد + طلبات جاري مرحّلة من أشهر سابقة
    in_month = and_(Invoice.created_at >= start, Invoice.created_at <= end)
    carried_open = and_(Invoice.created_at < start, is_pending)

    rows_q = (
        db.session.query(
            Invoice.employee_id,
            func.sum(case((is_delivered, 1), else_=0)).label("delivered_orders"),
            func.sum(case((or_(is_canceled, is_returned), 1), else_=0)).label(
                "returned_orders"
            ),
            func.sum(case((is_pending, 1), else_=0)).label("pending_orders"),
            func.sum(case((carried_open, 1), else_=0)).label("carried_pending"),
        )
        .filter(
            Invoice.employee_id.isnot(None),
            or_(in_month, carried_open),
        )
        .group_by(Invoice.employee_id)
        .all()
    )

    empty = {
        "year": year,
        "month": month,
        "title": f"طلبات شهر {month}",
        "rows": [],
        "totals": {
            "total_orders": 0,
            "returned_orders": 0,
            "delivered_orders": 0,
            "pending_orders": 0,
            "carried_pending": 0,
            "total_amount": 0,
        },
        "note": (
            "الكلي = الواصل + الراجع/الملغي + الجاري. "
            "المبلغ الكلي = عمولة الطلبات الواصلة فقط. "
            "طلبات جاري الشحن المفتوحة من أشهر سابقة تُرحَّل لهذا الشهر حتى تُغلق "
            "حتى لا يضيع حق الموظف."
        ),
    }
    if not rows_q:
        return empty

    employee_ids = [r.employee_id for r in rows_q]
    employees = Employee.query.filter(Employee.id.in_(employee_ids)).all()
    emp_map = {e.id: e for e in employees}

    rows = []
    for r in rows_q:
        emp = emp_map.get(r.employee_id)
        if emp and getattr(emp, "role", None) == "admin":
            continue
        delivered = int(r.delivered_orders or 0)
        returned = int(r.returned_orders or 0)
        pending = int(r.pending_orders or 0)
        carried = int(r.carried_pending or 0)
        rate = get_employee_commission_amount(emp) if emp else 0
        amount = delivered * rate
        total = delivered + returned + pending
        if total <= 0:
            continue
        rows.append(
            {
                "employee_id": r.employee_id,
                "employee_name": emp.name if emp else f"#{r.employee_id}",
                "transfer_number": (getattr(emp, "transfer_number", None) or "").strip() if emp else "",
                "total_orders": total,
                "delivered_orders": delivered,
                "returned_orders": returned,
                "pending_orders": pending,
                "carried_pending": carried,
                "commission_rate": rate,
                "total_amount": amount,
            }
        )

    rows.sort(key=lambda x: x["employee_name"])
    totals = {
        "total_orders": sum(x["total_orders"] for x in rows),
        "returned_orders": sum(x["returned_orders"] for x in rows),
        "delivered_orders": sum(x["delivered_orders"] for x in rows),
        "pending_orders": sum(x["pending_orders"] for x in rows),
        "carried_pending": sum(x["carried_pending"] for x in rows),
        "total_amount": sum(x["total_amount"] for x in rows),
    }
    return {
        "year": year,
        "month": month,
        "title": f"طلبات شهر {month}",
        "rows": rows,
        "totals": totals,
        "note": empty["note"],
    }
