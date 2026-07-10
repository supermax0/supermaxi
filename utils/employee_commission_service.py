"""Employee commission from delivered+paid orders and monthly settlement."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, or_

from extensions import db
from models.employee import Employee
from models.employee_commission_line import EmployeeCommissionLine
from models.employee_commission_settlement import EmployeeCommissionSettlement
from models.invoice import Invoice
from utils.employee_commission import (
    get_employee_commission_amount,
    get_fixed_employee_commission_amount,
    is_commission_eligible_employee,
)
from utils.order_status import CANCELED_STATUSES, invoice_returned_condition


def _normalize_name(value: Optional[str]) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def delivered_paid_filter():
    """Orders fully paid and eligible for commission (matches is_completed logic)."""
    paid = or_(
        Invoice.payment_status == "مسدد",
        Invoice.status == "مسدد",
        and_(Invoice.payment_status.is_(None), Invoice.status == "تم التوصيل"),
    )
    not_canceled = and_(
        ~Invoice.status.in_(list(CANCELED_STATUSES)),
        or_(
            Invoice.payment_status.is_(None),
            ~Invoice.payment_status.in_(list(CANCELED_STATUSES)),
        ),
    )
    return and_(paid, not_canceled, ~invoice_returned_condition(Invoice))


def backfill_invoice_employee_ids() -> int:
    """Link legacy invoices to employees using employee_name when employee_id is missing."""
    employees = Employee.query.all()
    if not employees:
        return 0

    name_to_id: dict[str, int] = {}
    for employee in employees:
        key = _normalize_name(employee.name)
        if key and key not in name_to_id:
            name_to_id[key] = employee.id

    invoices = (
        Invoice.query.filter(
            Invoice.employee_id.is_(None),
            Invoice.employee_name.isnot(None),
            Invoice.employee_name != "",
        )
        .limit(5000)
        .all()
    )

    updated = 0
    for invoice in invoices:
        employee_id = name_to_id.get(_normalize_name(invoice.employee_name))
        if employee_id:
            invoice.employee_id = employee_id
            updated += 1

    if updated:
        db.session.commit()
    return updated


def attach_session_employee_to_invoice(invoice: Invoice) -> None:
    """Set invoice employee from the logged-in session when missing."""
    if invoice is None or invoice.employee_id:
        return
    try:
        from flask import session
    except Exception:
        return

    user_id = session.get("user_id")
    if not user_id:
        return

    employee = Employee.query.get(user_id)
    if not employee:
        return

    invoice.employee_id = employee.id
    if not invoice.employee_name:
        invoice.employee_name = employee.name


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    _, last_day = monthrange(year, month)
    end = datetime(year, month, last_day, 23, 59, 59)
    return start, end


def _apply_period_filter(query, year: Optional[int], month: Optional[int]):
    if year is None or month is None:
        return query
    start, end = _month_bounds(year, month)
    return query.filter(Invoice.created_at >= start, Invoice.created_at <= end)


def _commission_query(
    employee_id: Optional[int] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    unsettled_only: bool = True,
):
    q = Invoice.query.filter(
        Invoice.employee_id.isnot(None),
        delivered_paid_filter(),
    )
    if employee_id is not None:
        q = q.filter(Invoice.employee_id == employee_id)
    if unsettled_only:
        q = q.filter(Invoice.employee_commission_settled_at.is_(None))
    q = _apply_period_filter(q, year, month)
    return q


def count_commission_orders(
    employee_id: int,
    year: Optional[int] = None,
    month: Optional[int] = None,
    unsettled_only: bool = True,
) -> int:
    pending_q = EmployeeCommissionLine.query.filter_by(employee_id=employee_id, status="pending")
    if year is not None and month is not None:
        start, end = _month_bounds(year, month)
        pending_q = pending_q.filter(
            EmployeeCommissionLine.accrued_at >= start,
            EmployeeCommissionLine.accrued_at <= end,
        )
    if unsettled_only:
        return pending_q.count()
    return _commission_query(employee_id, year, month, unsettled_only).count()


def compute_commission_due(
    employee_id: int,
    year: Optional[int] = None,
    month: Optional[int] = None,
    unsettled_only: bool = True,
) -> int:
    employee = Employee.query.get(employee_id)
    if not is_commission_eligible_employee(employee):
        return 0
    if unsettled_only:
        from utils.payroll_service import get_pending_commission_total

        pending = get_pending_commission_total(employee_id)
        if year is not None and month is not None:
            start, end = _month_bounds(year, month)
            lines = [
                l
                for l in pending["lines"]
                if l.accrued_at and start <= l.accrued_at <= end
            ]
            return sum(int(l.amount or 0) for l in lines)
        return int(pending["amount"] or 0)
    count = count_commission_orders(employee_id, year, month, unsettled_only)
    return count * get_employee_commission_amount(employee)


def _commission_eligible_employee_ids() -> set[int]:
    return {
        e.id
        for e in Employee.query.filter(Employee.role != "admin").all()
        if is_commission_eligible_employee(e)
    }


def build_employee_commission_stats_map(
    unsettled_only: bool = True,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict[int, dict]:
    """Aggregate commission stats per employee for the grid or statement."""
    from utils.payroll_service import get_pending_commission_total

    eligible_ids = _commission_eligible_employee_ids()
    if not eligible_ids:
        return {}

    stats_map: dict[int, dict] = {}
    for employee_id in eligible_ids:
        pending = get_pending_commission_total(employee_id)
        lines = pending["lines"]
        if year is not None and month is not None:
            start, end = _month_bounds(year, month)
            lines = [l for l in lines if l.accrued_at and start <= l.accrued_at <= end]
        if unsettled_only and not lines:
            continue
        orders = len(lines)
        commission = sum(int(l.amount or 0) for l in lines)
        if orders <= 0 and unsettled_only:
            continue
        employee = Employee.query.get(employee_id)
        rate = get_employee_commission_amount(employee) if employee else get_fixed_employee_commission_amount()
        sales = 0
        for line in lines:
            if line.invoice:
                sales += int(line.invoice.total or 0)
        stats_map[employee_id] = {
            "orders": orders,
            "sales": sales,
            "commission": commission,
            "total_due": commission,
            "commission_rate": rate,
        }

    if not unsettled_only:
        q = (
            db.session.query(
                Invoice.employee_id,
                func.count(Invoice.id).label("orders"),
                func.coalesce(func.sum(Invoice.total), 0).label("sales"),
            )
            .filter(
                Invoice.employee_id.isnot(None),
                Invoice.employee_id.in_(eligible_ids),
                delivered_paid_filter(),
            )
        )
        q = _apply_period_filter(q, year, month)
        rows = q.group_by(Invoice.employee_id).all()
        employees = Employee.query.filter(Employee.id.in_([r.employee_id for r in rows])).all() if rows else []
        rate_map = {e.id: get_employee_commission_amount(e) for e in employees}
        for row in rows:
            if row.employee_id not in eligible_ids:
                continue
            orders = int(row.orders or 0)
            rate = rate_map.get(row.employee_id, get_fixed_employee_commission_amount())
            stats_map[row.employee_id] = {
                "orders": orders,
                "sales": int(row.sales or 0),
                "commission": orders * rate,
                "total_due": orders * rate,
                "commission_rate": rate,
            }

    return stats_map


def build_monthly_statement(year: int, month: int) -> list[dict]:
    """Unsettled commission lines in the given month, per employee."""
    stats_map = build_employee_commission_stats_map(
        unsettled_only=True,
        year=year,
        month=month,
    )
    employees = Employee.query.filter(Employee.id.in_(stats_map.keys())).all() if stats_map else []
    employee_names = {e.id: e.name for e in employees}

    rows = []
    for employee_id, stats in stats_map.items():
        if stats["orders"] <= 0:
            continue
        rows.append(
            {
                "employee_id": employee_id,
                "employee_name": employee_names.get(employee_id, f"#{employee_id}"),
                "orders": stats["orders"],
                "amount": stats["total_due"],
                "commission_rate": stats.get("commission_rate", 0),
            }
        )
    rows.sort(key=lambda r: r["employee_name"])
    return rows


def settle_employee_commission(
    employee_id: int,
    year: int,
    month: int,
    settled_by: Optional[int] = None,
    treasury_account_id: Optional[int] = None,
) -> dict:
    """Settle pending commission lines with optional treasury payout."""
    if treasury_account_id is not None:
        from utils.payroll_service import settle_employee_commission_payment

        return settle_employee_commission_payment(
            employee_id,
            treasury_account_id=treasury_account_id,
            settled_by=settled_by,
            year=year,
            month=month,
        )

    employee = Employee.query.get(employee_id)
    if not employee:
        return {"ok": False, "error": "الموظف غير موجود"}
    if not is_commission_eligible_employee(employee):
        return {"ok": False, "error": "المدير غير مشمول بعمولة الطلبات"}

    from utils.payroll_service import get_pending_commission_lines

    lines = get_pending_commission_lines(employee_id)
    if year and month:
        start, end = _month_bounds(year, month)
        lines = [l for l in lines if l.accrued_at and start <= l.accrued_at <= end]
    if not lines:
        return {"ok": False, "error": "لا توجد طلبات مستحقة للسداد في هذه الفترة"}

    now = datetime.utcnow()
    order_count = len(lines)
    amount = sum(int(l.amount or 0) for l in lines)

    for line in lines:
        line.status = "paid"
        if line.invoice:
            line.invoice.employee_commission_settled_at = now

    settlement = EmployeeCommissionSettlement(
        employee_id=employee_id,
        period_year=year,
        period_month=month,
        order_count=order_count,
        amount=amount,
        settled_at=now,
        settled_by=settled_by,
    )
    db.session.add(settlement)
    db.session.commit()

    return {
        "ok": True,
        "employee_id": employee_id,
        "employee_name": employee.name,
        "order_count": order_count,
        "amount": amount,
        "period_year": year,
        "period_month": month,
    }
