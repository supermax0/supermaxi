"""حماية الفترات المحاسبية المغلقة."""
from __future__ import annotations

from datetime import date

from extensions import db
from models.financial_period_close import FinancialPeriodClose


class PeriodClosedError(Exception):
  pass


def is_period_closed(year: int, month: int) -> bool:
    from flask import has_app_context

    if not has_app_context():
        return False
    if month < 1 or month > 12:
        return False
    return (
        FinancialPeriodClose.query.filter_by(
            period_year=int(year), period_month=int(month)
        ).first()
        is not None
    )


def is_date_in_closed_period(value: date | None) -> bool:
    if not value:
        return False
    return is_period_closed(value.year, value.month)


def list_closed_periods(limit: int = 120):
    from flask import has_app_context

    if not has_app_context():
        return []
    return (
        FinancialPeriodClose.query.order_by(
            FinancialPeriodClose.period_year.desc(),
            FinancialPeriodClose.period_month.desc(),
        )
        .limit(limit)
        .all()
    )


def close_financial_period(year: int, month: int, user_id=None, notes: str | None = None):
    year, month = int(year), int(month)
    if month < 1 or month > 12:
        raise PeriodClosedError("شهر غير صالح")
    if is_period_closed(year, month):
        raise PeriodClosedError(f"الفترة {year}-{month:02d} مغلقة مسبقاً")
    row = FinancialPeriodClose(
        period_year=year,
        period_month=month,
        closed_by=user_id,
        notes=(notes or "").strip() or None,
    )
    db.session.add(row)
    return row


def reopen_financial_period(year: int, month: int):
    year, month = int(year), int(month)
    row = FinancialPeriodClose.query.filter_by(
        period_year=year, period_month=month
    ).first()
    if not row:
        raise PeriodClosedError(f"الفترة {year}-{month:02d} غير مغلقة")
    db.session.delete(row)
    return True


def assert_period_open(year: int, month: int, action_label: str = "هذه العملية"):
    if is_period_closed(year, month):
        raise PeriodClosedError(
            f"الفترة {year}-{month:02d} مغلقة محاسبياً، لا يمكن {action_label}."
        )


def assert_date_period_open(value: date | None, action_label: str = "تنفيذ العملية"):
    if value and is_date_in_closed_period(value):
        raise PeriodClosedError(
            f"الفترة {value.year}-{value.month:02d} مغلقة محاسبياً، لا يمكن {action_label}."
        )
