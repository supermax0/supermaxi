"""Employee ↔ branch assignments (multi-branch spec, phase 13/16).

``employee.branch_id`` stays the employee's HOME branch exactly as every existing module (HR, payroll, phone
app, POS API …) reads it. This table adds (a) EXTRA branches an employee may also work in and switch to, and
(b) the history of home-branch moves with their effective dates, so past records keep the branch they were
made in and nothing is rewritten when someone moves.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class BranchUserAssignment(db.Model):
    __tablename__ = "branch_user_assignment"
    __table_args__ = (db.Index("ix_branch_user_assignment_employee", "employee_id", "active"),)

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)  # home | extra
    active = db.Column(db.Boolean, nullable=False, default=True)
    valid_from = db.Column(db.Date, nullable=True)
    valid_to = db.Column(db.Date, nullable=True)
    note = db.Column(db.String(255), nullable=True)
    created_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
