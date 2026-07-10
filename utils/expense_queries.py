"""Centralized expense queries — posted (cash) expenses only."""
from __future__ import annotations

from datetime import date

from sqlalchemy.sql import func

from extensions import db
from models.expense import Expense


def posted_expense_filter():
    """SQLAlchemy filter: expense was actually withdrawn from treasury."""
    return Expense.cash_posted.is_(True)


def posted_expenses_query(date_from: date | None = None, date_to: date | None = None):
    """Base query for posted expenses, optionally scoped by expense_date."""
    query = Expense.query.filter(
        posted_expense_filter(),
        Expense.expense_date.isnot(None),
    )
    if date_from is not None:
        query = query.filter(func.date(Expense.expense_date) >= date_from)
    if date_to is not None:
        query = query.filter(func.date(Expense.expense_date) <= date_to)
    return query


def sum_posted_expenses(date_from: date | None = None, date_to: date | None = None) -> int:
    """Sum of posted expense amounts; optional date range on expense_date."""
    query = db.session.query(func.sum(Expense.amount)).filter(
        posted_expense_filter(),
        Expense.expense_date.isnot(None),
    )
    if date_from is not None:
        query = query.filter(func.date(Expense.expense_date) >= date_from)
    if date_to is not None:
        query = query.filter(func.date(Expense.expense_date) <= date_to)
    total = query.scalar() or 0
    return int(total)
