"""HR payroll payout: methods, monthly net pay, fund allocation, vouchers."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import and_, or_

from extensions import db
from models.employee import Employee
from models.employee_payment import EmployeePayment
from models.hr import HRPayrollAdjustment, HRSettings
from models.treasury_account import TreasuryAccount
from utils.payroll_service import _create_payroll_expense, resolve_payroll_payout_branch
from utils.treasury_calculations import InsufficientTreasuryBalance, record_treasury_transfer
from utils.treasury_helpers import get_default_cash_account, resolve_treasury_account_id
from utils.treasury_schema_guard import ensure_treasury_schema

PAYOUT_DIRECT = "direct"
PAYOUT_SALARY_FUND = "salary_fund"
PAYOUT_BANK = "bank"

PAYOUT_METHODS = {
    PAYOUT_DIRECT: "صرف مباشر من الصندوق",
    PAYOUT_SALARY_FUND: "صندوق الرواتب (تخصيص ثم صرف)",
    PAYOUT_BANK: "تحويل بنكي",
}

HR_PERIOD_NOTE_PREFIX = "hr_period:"


def period_note_tag(year: int, month: int) -> str:
    return f"{HR_PERIOD_NOTE_PREFIX}{int(year):04d}-{int(month):02d}"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def ensure_hr_payroll_accounts() -> dict[str, TreasuryAccount]:
    """Ensure default cash / salary-fund / bank accounts exist for HR payouts."""
    ensure_treasury_schema()
    cash = get_default_cash_account()

    def _find_or_create(name: str, account_type: str) -> TreasuryAccount:
        row = (
            TreasuryAccount.query.filter(
                TreasuryAccount.is_active.is_(True),
                TreasuryAccount.account_type == account_type,
                TreasuryAccount.name == name,
            )
            .order_by(TreasuryAccount.id.asc())
            .first()
        )
        if row:
            return row
        row = TreasuryAccount(
            name=name,
            account_type=account_type,
            is_default=False,
            is_active=True,
            branch_id=cash.branch_id,
        )
        db.session.add(row)
        db.session.flush()
        return row

    fund = _find_or_create("صندوق الرواتب", "cash")
    bank = _find_or_create("حساب رواتب بنكي", "bank")
    db.session.commit()
    return {"cash": cash, "fund": fund, "bank": bank}


def deposit_to_payroll_account(
    *,
    treasury_account_id: int,
    amount: int,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Deposit cash into a treasury account so salaries can be paid."""
    from models.account_transaction import AccountTransaction

    ensure_treasury_schema()
    amount = int(amount or 0)
    if amount <= 0:
        return {"ok": False, "error": "مبلغ الإيداع يجب أن يكون أكبر من صفر"}
    account = TreasuryAccount.query.filter_by(id=int(treasury_account_id), is_active=True).first()
    if not account:
        return {"ok": False, "error": "حساب الإيداع غير صالح"}
    tx = AccountTransaction(
        branch_id=account.branch_id,
        type="deposit",
        amount=amount,
        note=(note or "").strip() or f"إيداع رصيد رواتب — {account.name}",
        treasury_account_id=account.id,
    )
    db.session.add(tx)
    db.session.commit()
    return {"ok": True, "transaction_id": tx.id, "amount": amount, "account_id": account.id, "account_name": account.name}


def get_payout_method(settings: Optional[HRSettings] = None) -> str:
    method = (getattr(settings, "salary_payout_method", None) or PAYOUT_DIRECT).strip()
    return method if method in PAYOUT_METHODS else PAYOUT_DIRECT


def resolve_hr_payout_account_id(settings: HRSettings, *, method: Optional[str] = None) -> int:
    """Resolve the treasury account used when paying an employee salary."""
    ensure_treasury_schema()
    method = method or get_payout_method(settings)
    preferred = None
    if method == PAYOUT_SALARY_FUND:
        preferred = settings.payroll_fund_account_id
    elif method == PAYOUT_BANK:
        preferred = settings.payroll_bank_account_id
    else:
        preferred = settings.payroll_cash_account_id
    if preferred:
        account = TreasuryAccount.query.filter_by(id=int(preferred), is_active=True).first()
        if account:
            return int(account.id)
    return resolve_treasury_account_id(None)


def employee_month_adjustments(employee_id: int, year: int, month: int) -> dict[str, Any]:
    rows = HRPayrollAdjustment.query.filter_by(
        employee_id=employee_id, period_year=year, period_month=month
    ).all()
    allowance = sum(int(r.amount or 0) for r in rows if r.adjustment_type == "allowance")
    deduction = sum(int(r.amount or 0) for r in rows if r.adjustment_type == "deduction")
    return {"allowance": allowance, "deduction": deduction, "items": rows}


def compute_employee_net(employee: Employee, year: int, month: int) -> dict[str, Any]:
    basic = max(0, int(employee.salary or 0))
    adj = employee_month_adjustments(employee.id, year, month)
    net = max(0, basic + adj["allowance"] - adj["deduction"])
    return {
        "basic": basic,
        "allowance": adj["allowance"],
        "deduction": adj["deduction"],
        "net": net,
        "items": adj["items"],
    }


def find_hr_salary_payment(employee_id: int, year: int, month: int) -> Optional[EmployeePayment]:
    tag = period_note_tag(year, month)
    return (
        EmployeePayment.query.filter(
            EmployeePayment.payee_type == "employee",
            EmployeePayment.payee_id == employee_id,
            EmployeePayment.payment_kind.in_(("salary_monthly", "salary_weekly")),
            or_(
                and_(
                    EmployeePayment.period_year == year,
                    EmployeePayment.period_month == month,
                ),
                EmployeePayment.note.contains(tag),
            ),
        )
        .order_by(EmployeePayment.id.desc())
        .first()
    )


def is_hr_salary_paid(employee_id: int, year: int, month: int) -> bool:
    return find_hr_salary_payment(employee_id, year, month) is not None


def _next_voucher_code(year: int, month: int) -> str:
    prefix = f"HR-{int(year):04d}{int(month):02d}-"
    last = (
        EmployeePayment.query.filter(EmployeePayment.voucher_code.like(f"{prefix}%"))
        .order_by(EmployeePayment.id.desc())
        .first()
    )
    seq = 1
    if last and last.voucher_code:
        try:
            seq = int(str(last.voucher_code).rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = EmployeePayment.query.filter(EmployeePayment.voucher_code.like(f"{prefix}%")).count() + 1
    return f"{prefix}{seq:04d}"


def pay_hr_employee_salary(
    employee: Employee,
    *,
    year: int,
    month: int,
    settings: HRSettings,
    settled_by: Optional[int] = None,
    treasury_account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Pay monthly HR net salary using the configured payout method."""
    if not employee or not employee.is_active:
        return {"ok": False, "error": "الموظف غير نشط أو غير موجود"}
    from utils.hr_schema import salary_owned_by_hr_workspace
    if salary_owned_by_hr_workspace(employee.id):
        return {"ok": False, "error": "راتب الموظف تديره مسيرات الموارد البشرية المعتمدة؛ استخدم صرف المسير"}

    breakdown = compute_employee_net(employee, year, month)
    amount = int(breakdown["net"] or 0)
    if amount <= 0:
        return {"ok": False, "error": "لا يوجد صافي راتب للصرف لهذا الشهر"}

    if is_hr_salary_paid(employee.id, year, month):
        return {"ok": False, "error": "تم صرف راتب هذا الشهر مسبقاً"}

    method = get_payout_method(settings)
    try:
        account_id = resolve_treasury_account_id(
            treasury_account_id or resolve_hr_payout_account_id(settings, method=method)
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc) or "حساب الصرف غير محدد"}

    treasury = TreasuryAccount.query.get(account_id)
    if not treasury or not treasury.is_active:
        return {"ok": False, "error": "حساب الصرف غير صالح"}

    if method == PAYOUT_SALARY_FUND and not settings.payroll_fund_account_id:
        return {"ok": False, "error": "حدّد صندوق الرواتب من إعدادات HR أولاً"}
    if method == PAYOUT_BANK and not settings.payroll_bank_account_id:
        return {"ok": False, "error": "حدّد حساب التحويل البنكي من إعدادات HR أولاً"}

    branch_id, branch_error = resolve_payroll_payout_branch(treasury, employee)
    if branch_error:
        return {"ok": False, "error": branch_error}

    period_start, period_end = month_bounds(year, month)
    method_label = PAYOUT_METHODS.get(method, method)
    tag = period_note_tag(year, month)
    voucher = _next_voucher_code(year, month)
    title_suffix = {
        PAYOUT_DIRECT: "",
        PAYOUT_SALARY_FUND: " من صندوق الرواتب",
        PAYOUT_BANK: " (تحويل بنكي)",
    }.get(method, "")

    try:
        expense = _create_payroll_expense(
            title=f"راتب {employee.name}{title_suffix}",
            amount=amount,
            treasury_account_id=account_id,
            employee_id=employee.id,
            note=f"payroll:employee:{employee.id}:salary_monthly|{tag}|{method}",
            branch_id=branch_id,
        )
        payment = EmployeePayment(
            branch_id=branch_id,
            payee_type="employee",
            payee_id=employee.id,
            payment_kind="salary_monthly",
            amount=amount,
            period_start=period_start,
            period_end=period_end,
            period_year=year,
            period_month=month,
            treasury_account_id=account_id,
            settled_by=settled_by,
            payout_method=method,
            voucher_code=voucher,
            note=f"راتب شهري — {employee.name} — {method_label} — {tag}",
        )
        db.session.add(payment)
        db.session.flush()
        expense.employee_payment_id = payment.id
        payment.expense_id = expense.id
        employee.last_salary_paid_at = datetime.combine(period_end, datetime.min.time())
        db.session.commit()
    except InsufficientTreasuryBalance as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc) or "تعذر صرف الراتب"}

    return {
        "ok": True,
        "payment_id": payment.id,
        "voucher_code": voucher,
        "expense_id": expense.id,
        "amount": amount,
        "method": method,
        "employee_id": employee.id,
        "employee_name": employee.name,
        "year": year,
        "month": month,
        "breakdown": breakdown,
    }


def allocate_salary_fund(
    *,
    year: int,
    month: int,
    settings: HRSettings,
    amount: Optional[int] = None,
    employee_ids: Optional[list[int]] = None,
) -> dict[str, Any]:
    """Move payroll cash into the salary fund account for the selected period."""
    if get_payout_method(settings) != PAYOUT_SALARY_FUND:
        return {"ok": False, "error": "طريقة الصرف الحالية ليست صندوق الرواتب"}
    source_id = settings.payroll_source_account_id
    fund_id = settings.payroll_fund_account_id
    if not source_id or not fund_id:
        return {"ok": False, "error": "حدّد حساب المصدر وصندوق الرواتب من الإعدادات"}
    if int(source_id) == int(fund_id):
        return {"ok": False, "error": "حساب المصدر وصندوق الرواتب يجب أن يكونا مختلفين"}

    query = Employee.query.filter(Employee.role != "admin", Employee.is_active.is_(True))
    if employee_ids:
        query = query.filter(Employee.id.in_(employee_ids))
    employees = query.order_by(Employee.name).all()

    unpaid_total = 0
    for employee in employees:
        if is_hr_salary_paid(employee.id, year, month):
            continue
        unpaid_total += int(compute_employee_net(employee, year, month)["net"] or 0)

    transfer_amount = int(amount) if amount is not None else unpaid_total
    if transfer_amount <= 0:
        return {"ok": False, "error": "لا يوجد مبلغ لتخصيصه لصندوق الرواتب"}

    note = f"تخصيص رواتب {month:02d}/{year} — {period_note_tag(year, month)}"
    try:
        transfer = record_treasury_transfer(
            int(source_id),
            int(fund_id),
            transfer_amount,
            note=note,
            allow_cross_branch=True,
        )
    except (InsufficientTreasuryBalance, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "amount": transfer_amount,
        "transfer_id": transfer.id,
        "unpaid_total": unpaid_total,
        "year": year,
        "month": month,
    }


def pay_all_hr_salaries(
    *,
    year: int,
    month: int,
    settings: HRSettings,
    settled_by: Optional[int] = None,
) -> dict[str, Any]:
    employees = (
        Employee.query.filter(Employee.role != "admin", Employee.is_active.is_(True))
        .order_by(Employee.name)
        .all()
    )
    paid = []
    skipped = []
    for employee in employees:
        if is_hr_salary_paid(employee.id, year, month):
            skipped.append({"employee_name": employee.name, "error": "مصروف مسبقاً"})
            continue
        net = compute_employee_net(employee, year, month)["net"]
        if net <= 0:
            skipped.append({"employee_name": employee.name, "error": "لا يوجد صافي"})
            continue
        result = pay_hr_employee_salary(
            employee,
            year=year,
            month=month,
            settings=settings,
            settled_by=settled_by,
        )
        if result.get("ok"):
            paid.append(result)
        else:
            skipped.append({"employee_name": employee.name, "error": result.get("error")})
    return {
        "ok": True,
        "paid": paid,
        "skipped": skipped,
        "paid_count": len(paid),
        "skipped_count": len(skipped),
        "paid_total": sum(int(row.get("amount") or 0) for row in paid),
    }


def list_hr_salary_payments(*, year: int, month: int) -> list[EmployeePayment]:
    tag = period_note_tag(year, month)
    return (
        EmployeePayment.query.filter(
            EmployeePayment.payee_type == "employee",
            EmployeePayment.payment_kind.in_(("salary_monthly", "salary_weekly")),
            or_(
                and_(
                    EmployeePayment.period_year == year,
                    EmployeePayment.period_month == month,
                ),
                EmployeePayment.note.contains(tag),
            ),
        )
        .order_by(EmployeePayment.paid_at.desc(), EmployeePayment.id.desc())
        .all()
    )
