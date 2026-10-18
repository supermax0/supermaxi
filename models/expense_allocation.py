"""Expense allocation overlay (multi-branch spec, phase 13).

An allocation never changes the expense row, its amount, its treasury posting or its journal — it only says
how the ONE expense is attributed across branches in branch reports. Total company expense is therefore
unchanged by construction, and the expense is never recorded twice.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class ExpenseAllocation(db.Model):
    __tablename__ = "expense_allocation"

    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expense.id"), nullable=False, unique=True)
    kind = db.Column(db.String(10), nullable=False)  # central | shared
    rule = db.Column(db.String(12), nullable=True)  # fixed | sales | employees | area | manual
    period_from = db.Column(db.Date, nullable=True)
    period_to = db.Column(db.Date, nullable=True)
    note = db.Column(db.String(255), nullable=True)
    created_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ExpenseAllocationLine(db.Model):
    __tablename__ = "expense_allocation_line"

    id = db.Column(db.Integer, primary_key=True)
    allocation_id = db.Column(db.Integer, db.ForeignKey("expense_allocation.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    weight = db.Column(db.Float, nullable=True)
    amount = db.Column(db.Integer, nullable=False)
