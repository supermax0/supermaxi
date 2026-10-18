"""Branch profile — descriptive / operational details of a branch (multi-branch spec, phase 3).

A separate 1:1 table on purpose: ``branch`` is read by the ORM scope and by every request, on every tenant
database in every migration state. Adding columns to it would break those queries on databases that were
not altered yet. This table is created lazily with ``checkfirst`` and only read by the branch-management API.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db

BRANCH_TYPES: dict[str, str] = {
    "sales": "فرع مبيعات",
    "showroom": "معرض",
    "distribution": "مركز توزيع",
    "warehouse": "مستودع",
    "service": "مركز خدمة",
    "hq": "مقر إدارة",
}


class BranchProfile(db.Model):
    __tablename__ = "branch_profile"

    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), primary_key=True)
    short_name = db.Column(db.String(60), nullable=True)
    branch_type = db.Column(db.String(20), nullable=False, default="sales")
    governorate = db.Column(db.String(80), nullable=True)
    city = db.Column(db.String(80), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    email = db.Column(db.String(120), nullable=True)
    manager_name = db.Column(db.String(120), nullable=True)
    manager_employee_id = db.Column(db.Integer, nullable=True)
    currency = db.Column(db.String(10), nullable=True)
    timezone = db.Column(db.String(60), nullable=True)
    default_warehouse_id = db.Column(db.Integer, nullable=True)
    default_cash_account_id = db.Column(db.Integer, nullable=True)
    opened_on = db.Column(db.Date, nullable=True)
    print_settings = db.Column(db.Text, nullable=True)  # JSON
    numbering_settings = db.Column(db.Text, nullable=True)  # JSON
    created_by_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = db.Column(db.DateTime, nullable=True)
    archived_by_id = db.Column(db.Integer, nullable=True)
    archive_reason = db.Column(db.String(255), nullable=True)
