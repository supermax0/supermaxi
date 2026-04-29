from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import func

from extensions import db
from models.account_transaction import AccountTransaction
from models.beauty_appointment import BeautyAppointment

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
    profit = revenue - material_cost
    return {
        "sessions_count": len(rows),
        "revenue": revenue,
        "paid": paid,
        "material_cost": material_cost,
        "receivable": receivable,
        "profit": profit,
        "rows": rows,
    }


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
    points = [
        {
            "day": str(row.day),
            "revenue": int(row.revenue or 0),
            "material_cost": int(row.material_cost or 0),
            "profit": int((row.revenue or 0) - (row.material_cost or 0)),
        }
        for row in rows
    ]
    return list(reversed(points))
