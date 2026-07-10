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


def remove_commission_lines_for_deleted_invoice(invoice_id: int) -> int:
    """Remove unpaid commission lines before deleting an invoice; block paid lines."""
    lines = EmployeeCommissionLine.query.filter_by(invoice_id=int(invoice_id)).all()
    paid_lines = [line for line in lines if line.status == "paid" or line.payment_id]
    if paid_lines:
        raise ValueError("لا يمكن حذف الطلب لأن عمولته مدفوعة ضمن الرواتب")

    for line in lines:
        db.session.delete(line)
    return len(lines)


def get_pending_commission_lines(employee_id: int) -> list[EmployeeCommissionLine]:
    return (
        EmployeeCommissionLine.query.filter_by(employee_id=employee_id, status="pending")
        .order_by(EmployeeCommissionLine.accrued_at.asc(), EmployeeCommissionLine.id.asc())
        .all()
    )


def get_pending_commission_total(employee_id: int) -> dict[str, Any]:
    lines = get_pending_commission_lines(employee_id)
    return {
        "orders": len(lines),
        "amount": sum(int(l.amount or 0) for l in lines),
        "lines": lines,
    }


def _post_payroll_expense_to_treasury(expense: Expense, treasury_account_id: Optional[int] = None) -> AccountTransaction:
    ensure_treasury_schema()
    account_id = resolve_treasury_account_id(treasury_account_id or expense.treasury_account_id)
    assert_sufficient_balance(account_id, expense.amount)
    note_extra = f" - {expense.note}" if expense.note else ""
    withdraw_tx = AccountTransaction(
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
) -> Expense:
    expense = Expense(
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


def pay_salary(
    payee: Payee,
    *,
    treasury_account_id: int,
    settled_by: Optional[int] = None,
    manual: bool = False,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Pay fixed salary for employee or delivery agent."""
    today = today or date.today()
    amount = get_salary_due_amount(payee)
    if amount <= 0:
        return {"ok": False, "error": "لا يوجد راتب محدد"}

    if not manual and not is_salary_due(payee, today=today):
        return {"ok": False, "error": "الراتب غير مستحق بعد"}

    treasury_account_id = resolve_treasury_account_id(treasury_account_id)
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
        )
        payment = EmployeePayment(
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
        payee.last_salary_paid_at = datetime.utcnow()
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

    lines = get_pending_commission_lines(employee_id)
    if year is not None and month is not None:
        start, end = _month_datetime_bounds(year, month)
        lines = [line for line in lines if line.accrued_at and start <= line.accrued_at <= end]
    if not lines:
        return {"ok": False, "error": "لا توجد عمولات معلّقة للسداد"}

    amount = sum(int(l.amount or 0) for l in lines)
    order_count = len(lines)
    treasury_account_id = resolve_treasury_account_id(treasury_account_id)
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
        )
        payment = EmployeePayment(
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

    payees: list[Payee] = list(Employee.query.filter(Employee.is_active.is_(True)).all())
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


def build_payroll_dashboard(*, today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()
    due_rows: list[dict[str, Any]] = []
    schedule_rows: list[dict[str, Any]] = []

    employees = Employee.query.filter(Employee.is_active.is_(True)).order_by(Employee.name).all()
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
        pending = get_pending_commission_total(emp.id)
        if pending["orders"] <= 0:
            continue
        commission_employees.append(
            {
                "employee_id": emp.id,
                "employee_name": emp.name,
                "orders": pending["orders"],
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


def serialize_commission_lines(employee_id: int) -> list[dict[str, Any]]:
    lines = get_pending_commission_lines(employee_id)
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
