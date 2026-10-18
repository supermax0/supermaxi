"""Per-employee permission exceptions on top of roles.

Effective permission of a non-admin employee:  DENY override  >  GRANT override  >  any assigned role.
A general admin is not subject to overrides (admins hold everything and cannot be locked out by a row).
"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class EmployeePermissionOverride(db.Model):
    __tablename__ = "employee_permission_override"
    __table_args__ = (db.UniqueConstraint("employee_id", "permission", name="uq_employee_permission_override"),)

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    permission = db.Column(db.String(80), nullable=False)
    effect = db.Column(db.String(5), nullable=False)  # grant | deny
    note = db.Column(db.String(255), nullable=True)
    created_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
