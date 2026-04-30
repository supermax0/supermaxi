from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import func

from extensions import db
from models.account_transaction import AccountTransaction
from models.beauty_appointment import BeautyAppointment
from models.expense import Expense
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
    note = f"{note_prefix} - {appointment.customer.name if appointment.customer else ''}"
    if appointment.payment_method:
        note = f"{note} - {appointment.payment_method}"
    if existing:
        existing.type = "deposit"
        existing.amount = paid
        existing.note = note
    else:
        db.session.add(AccountTransaction(type="deposit", amount=paid, note=note))


def _expenses_amount_for_beauty_range(date_from: date | None, date_to: date | None) -> int:
    """مصاريف الصرفيات بنفس نطاق التقرير؛ بدون تواريخ = مجموع كل المصاريف ذات التاريخ."""
    if date_from is not None and date_to is not None:
        return expenses_sum_for_range(date_from, date_to)
    total = db.session.query(func.sum(Expense.amount)).filter(Expense.expense_date.isnot(None)).scalar() or 0
    return int(total or 0)


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
        .filter(Expense.expense_date.isnot(None))
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
