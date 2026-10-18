from __future__ import annotations

import logging

from flask import g
from sqlalchemy import inspect, text

from extensions import db

_log = logging.getLogger(__name__)


def hr_workspace_enabled():
    if not inspect(_current_engine()).has_table("hr_record"):
        return False
    return bool(db.session.execute(text("SELECT 1 FROM hr_record WHERE kind='legacy_history_import' LIMIT 1")).scalar())


def salary_owned_by_hr_workspace(employee_id: int) -> bool:
    """Once approval takes ownership, legacy full-salary payers must defer to it."""
    engine = _current_engine()
    if not inspect(engine).has_table("hr_payroll_run"):
        return False
    return bool(db.session.execute(text(
        "SELECT 1 FROM hr_person p JOIN hr_payroll_item i ON i.person_id=p.id "
        "JOIN hr_payroll_run r ON r.id=i.run_id WHERE p.employee_id=:employee_id "
        "AND r.status='approved' LIMIT 1"
    ), {"employee_id": employee_id}).scalar())


def legacy_record_managed(kind, source_id):
    engine = _current_engine()
    if not inspect(engine).has_table("hr_legacy_link"):
        return False
    return bool(db.session.execute(text("SELECT 1 FROM hr_legacy_link WHERE kind=:kind AND source_id=:source LIMIT 1"),
        {"kind":kind,"source":source_id}).scalar())


def workspace_attendance_exists(employee_id, on):
    if not inspect(_current_engine()).has_table("hr_work_record"):
        return False
    return bool(db.session.execute(text("SELECT 1 FROM hr_work_record w JOIN hr_person p ON p.id=w.person_id WHERE p.employee_id=:employee AND w.work_date=:on LIMIT 1"),
        {"employee":employee_id,"on":on.isoformat()}).scalar())


def sync_legacy_history_if_enabled():
    if hr_workspace_enabled():
        from modules.hr.common import ensure_schema
        from modules.hr.legacy import import_history
        ensure_schema()
        import_history(force=True)


def _current_engine():
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def _table_exists(engine, name: str) -> bool:
    return name in inspect(engine).get_table_names()


def _column_exists(engine, table: str, column: str) -> bool:
    if not _table_exists(engine, table):
        return False
    return column in {c["name"] for c in inspect(engine).get_columns(table)}


def _add_column_if_missing(engine, table: str, column: str, ddl: str) -> None:
    if not _table_exists(engine, table) or _column_exists(engine, table, column):
        return
    with engine.begin() as conn:
        conn.execute(text(ddl))


def ensure_hr_schema() -> None:
    """Create the HR tables on the active tenant without a manual migration."""
    try:
        from models.hr import (
            HRAttendance,
            HRDepartment,
            HREmployeeDocument,
            HREmployeeProfile,
            HRLeaveRequest,
            HRPayrollAdjustment,
            HRSettings,
        )

        engine = _current_engine()
        for model in (
            HRDepartment,
            HREmployeeProfile,
            HRAttendance,
            HRLeaveRequest,
            HREmployeeDocument,
            HRPayrollAdjustment,
            HRSettings,
        ):
            model.__table__.create(bind=engine, checkfirst=True)

        _add_column_if_missing(
            engine,
            "hr_employee_profile",
            "email",
            "ALTER TABLE hr_employee_profile ADD COLUMN email VARCHAR(200)",
        )
        _add_column_if_missing(engine, "hr_department", "branch_id", "ALTER TABLE hr_department ADD COLUMN branch_id INTEGER")
        _add_column_if_missing(engine, "hr_department", "version", "ALTER TABLE hr_department ADD COLUMN version INTEGER DEFAULT 1 NOT NULL")
        for column, ddl in (
            ("email_enabled", "ALTER TABLE hr_settings ADD COLUMN email_enabled BOOLEAN DEFAULT 0 NOT NULL"),
            ("smtp_host", "ALTER TABLE hr_settings ADD COLUMN smtp_host VARCHAR(200)"),
            ("smtp_port", "ALTER TABLE hr_settings ADD COLUMN smtp_port INTEGER DEFAULT 587 NOT NULL"),
            ("smtp_user", "ALTER TABLE hr_settings ADD COLUMN smtp_user VARCHAR(200)"),
            ("smtp_password", "ALTER TABLE hr_settings ADD COLUMN smtp_password VARCHAR(200)"),
            ("smtp_from", "ALTER TABLE hr_settings ADD COLUMN smtp_from VARCHAR(200)"),
            ("email_sender_name", "ALTER TABLE hr_settings ADD COLUMN email_sender_name VARCHAR(120)"),
            ("email_default_subject", "ALTER TABLE hr_settings ADD COLUMN email_default_subject VARCHAR(200)"),
            ("salary_payout_method", "ALTER TABLE hr_settings ADD COLUMN salary_payout_method VARCHAR(30) DEFAULT 'direct' NOT NULL"),
            ("payroll_cash_account_id", "ALTER TABLE hr_settings ADD COLUMN payroll_cash_account_id INTEGER"),
            ("payroll_source_account_id", "ALTER TABLE hr_settings ADD COLUMN payroll_source_account_id INTEGER"),
            ("payroll_fund_account_id", "ALTER TABLE hr_settings ADD COLUMN payroll_fund_account_id INTEGER"),
            ("payroll_bank_account_id", "ALTER TABLE hr_settings ADD COLUMN payroll_bank_account_id INTEGER"),
        ):
            _add_column_if_missing(engine, "hr_settings", column, ddl)

        for column, ddl in (
            ("payout_method", "ALTER TABLE employee_payment ADD COLUMN payout_method VARCHAR(30)"),
            ("voucher_code", "ALTER TABLE employee_payment ADD COLUMN voucher_code VARCHAR(40)"),
            ("period_year", "ALTER TABLE employee_payment ADD COLUMN period_year INTEGER"),
            ("period_month", "ALTER TABLE employee_payment ADD COLUMN period_month INTEGER"),
        ):
            _add_column_if_missing(engine, "employee_payment", column, ddl)
    except Exception:
        _log.exception("ensure_hr_schema failed")
