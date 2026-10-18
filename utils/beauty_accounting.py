from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import func

from extensions import db
from models.account_transaction import AccountTransaction
from models.beauty_appointment import BeautyAppointment
from models.expense import Expense
from utils.expense_queries import posted_expense_filter, sum_posted_expenses
from utils.period_net_profit import expenses_sum_for_range

_CASH_NOTE_PREFIX = "مركز التجميل - جلسة #"


def payment_status(total_amount: int, paid_amount: int) -> str:
    total = max(0, int(total_amount or 0))
    paid = max(0, int(paid_amount or 0))
    if total <= 0:
        return "مسدد"
    if paid <= 0:
        return "غير مسدد"
    if paid >= total:
        return "مسدد"
    return "جزئي"


def appointment_receivable(appointment: BeautyAppointment) -> int:
    return max(0, int(appointment.total_amount or 0) - int(appointment.paid_amount or 0))


def sync_beauty_cash_transaction(appointment: BeautyAppointment) -> None:
    """Create/update one cash movement for a paid beauty session."""
    note_prefix = f"{_CASH_NOTE_PREFIX}{appointment.id}"
    existing = AccountTransaction.query.filter(AccountTransaction.note.like(f"{note_prefix}%")).first()
    paid = int(appointment.paid_amount or 0)
    if paid <= 0:
        if existing:
            db.session.delete(existing)
        return
    from models.treasury_account import TreasuryAccount
    from utils.branch_context import current_branch_id

    branch_id = current_branch_id()
    method = str(appointment.payment_method or "cash").strip().lower()
    if method in {"bank", "card", "بنك", "بطاقة"}:
        query = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(
            account_type="bank", is_active=True
        )
        if branch_id:
            query = query.filter(TreasuryAccount.branch_id == int(branch_id))
        treasury_account = query.order_by(TreasuryAccount.id.asc()).first()
        if not treasury_account:
            raise ValueError("لا يوجد حساب بنكي فعال لتسجيل دفعة الجلسة")
    else:
        query = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(
            account_type="cash", is_default=True, is_active=True
        )
        if branch_id:
            query = query.filter(TreasuryAccount.branch_id == int(branch_id))
        treasury_account = query.order_by(TreasuryAccount.id.asc()).first()
        if not treasury_account:
            treasury_account = TreasuryAccount(
                branch_id=branch_id,
                name="الصندوق",
                account_type="cash",
                is_default=True,
                is_active=True,
            )
            db.session.add(treasury_account)
            db.session.flush()
    note = f"{note_prefix} - {appointment.customer.name if appointment.customer else ''}"
    if appointment.payment_method:
        note = f"{note} - {appointment.payment_method}"
    if existing:
        existing.type = "deposit"
        existing.amount = paid
        existing.note = note
        existing.branch_id = treasury_account.branch_id
        existing.treasury_account_id = treasury_account.id
    else:
        db.session.add(AccountTransaction(
            branch_id=treasury_account.branch_id,
            type="deposit",
            amount=paid,
            note=note,
            treasury_account_id=treasury_account.id,
        ))


def _expenses_amount_for_beauty_range(date_from: date | None, date_to: date | None) -> int:
    """مصاريف الصرفيات الفعلية بنفس نطاق التقرير."""
    if date_from is not None and date_to is not None:
        return expenses_sum_for_range(date_from, date_to)
    return sum_posted_expenses()


def beauty_summary(date_from: date | None = None, date_to: date | None = None) -> dict:
    query = BeautyAppointment.query.filter(BeautyAppointment.status == "done")
    if date_from:
        query = query.filter(BeautyAppointment.completed_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(BeautyAppointment.completed_at <= datetime.combine(date_to, time.max))
    rows = query.all()
    revenue = sum(int(row.total_amount or 0) for row in rows)
    paid = sum(int(row.paid_amount or 0) for row in rows)
    material_cost = sum(int(row.material_cost or 0) for row in rows)
    receivable = sum(appointment_receivable(row) for row in rows)
    expenses_period = _expenses_amount_for_beauty_range(date_from, date_to)
    gross_margin = revenue - material_cost
    profit = gross_margin - expenses_period
    return {
        "sessions_count": len(rows),
        "revenue": revenue,
        "paid": paid,
        "material_cost": material_cost,
        "receivable": receivable,
        "expenses": expenses_period,
        "profit": profit,
        "rows": rows,
    }


def beauty_net_profit_calendar_day(day: date) -> int:
    """صافي ربح يوم تقويمي للمركز: هامش الجلسات المكتملة ذلك اليوم ناقص مصاريف ذلك اليوم."""
    return int(beauty_summary(day, day)["profit"])


def beauty_daily_revenue_points(days: int = 14) -> list[dict]:
    rows = (
        db.session.query(
            func.date(BeautyAppointment.completed_at).label("day"),
            func.sum(BeautyAppointment.total_amount).label("revenue"),
            func.sum(BeautyAppointment.material_cost).label("material_cost"),
        )
        .filter(BeautyAppointment.status == "done", BeautyAppointment.completed_at.isnot(None))
        .group_by(func.date(BeautyAppointment.completed_at))
        .order_by(func.date(BeautyAppointment.completed_at).desc())
        .limit(days)
        .all()
    )
    exp_rows = (
        db.session.query(func.date(Expense.expense_date).label("day"), func.sum(Expense.amount).label("amt"))
        .filter(Expense.expense_date.isnot(None), posted_expense_filter())
        .group_by(func.date(Expense.expense_date))
        .all()
    )
    exp_by_day = {str(r.day): int(r.amt or 0) for r in exp_rows}
    points = []
    for row in rows:
        day_key = str(row.day)
        rev = int(row.revenue or 0)
        mc = int(row.material_cost or 0)
        exp_d = exp_by_day.get(day_key, 0)
        points.append(
            {
                "day": day_key,
                "revenue": rev,
                "material_cost": mc,
                "expenses": exp_d,
                "profit": rev - mc - exp_d,
            }
        )
    return list(reversed(points))
