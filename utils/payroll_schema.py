"""Schema helpers for payroll module."""

from __future__ import annotations

from sqlalchemy import inspect, text

from extensions import db


def _resolve_engine():
    from flask import g

    if getattr(g, "tenant", None):
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(g.tenant)
    return db.engine


def _add_column_if_missing(conn, table: str, columns: set, name: str, ddl: str) -> bool:
    if name in columns:
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    return True


def ensure_payroll_schema() -> None:
    """Create payroll tables and add columns expected by the ORM."""
    try:
        engine = _resolve_engine()
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        dialect = engine.dialect.name
        date_type = "DATE" if dialect == "postgresql" else "DATE"
        datetime_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

        from models.employee_commission_line import EmployeeCommissionLine
        from models.employee_payment import EmployeePayment

        EmployeePayment.__table__.create(engine, checkfirst=True)
        EmployeeCommissionLine.__table__.create(engine, checkfirst=True)
        from models.employee_commission_settlement import EmployeeCommissionSettlement

        EmployeeCommissionSettlement.__table__.create(engine, checkfirst=True)

        with engine.connect() as conn:
            changed = False

            if "employee" in tables:
                columns = {col["name"] for col in inspector.get_columns("employee")}
                for name, ddl in (
                    ("pay_type", "pay_type VARCHAR(30) DEFAULT 'none'"),
                    ("pay_day_of_month", "pay_day_of_month INTEGER DEFAULT 25"),
                    ("pay_weekday", "pay_weekday INTEGER DEFAULT 4"),
                    ("payroll_effective_from", f"payroll_effective_from {date_type}"),
                    ("last_salary_paid_at", f"last_salary_paid_at {datetime_type}"),
                ):
                    if _add_column_if_missing(conn, "employee", columns, name, ddl):
                        changed = True

            if "delivery_agent" in tables:
                columns = {col["name"] for col in inspector.get_columns("delivery_agent")}
                for name, ddl in (
                    ("pay_type", "pay_type VARCHAR(30) DEFAULT 'none'"),
                    ("pay_day_of_month", "pay_day_of_month INTEGER DEFAULT 25"),
                    ("pay_weekday", "pay_weekday INTEGER DEFAULT 4"),
                    ("payroll_effective_from", f"payroll_effective_from {date_type}"),
                    ("last_salary_paid_at", f"last_salary_paid_at {datetime_type}"),
                ):
                    if _add_column_if_missing(conn, "delivery_agent", columns, name, ddl):
                        changed = True

            if "expense" in tables:
                columns = {col["name"] for col in inspector.get_columns("expense")}
                for name, ddl in (
                    ("employee_id", "employee_id INTEGER"),
                    ("employee_payment_id", "employee_payment_id INTEGER"),
                ):
                    if _add_column_if_missing(conn, "expense", columns, name, ddl):
                        changed = True

            if "employee_commission_settlement" in tables:
                columns = {col["name"] for col in inspector.get_columns("employee_commission_settlement")}
                for name, ddl in (
                    ("payment_id", "payment_id INTEGER"),
                    ("treasury_account_id", "treasury_account_id INTEGER"),
                ):
                    if _add_column_if_missing(conn, "employee_commission_settlement", columns, name, ddl):
                        changed = True

            if changed:
                conn.commit()
    except Exception as e:
        msg = str(e).lower()
        if "duplicate column" not in msg and "already exists" not in msg:
            print(f"[payroll_schema] ensure failed: {e}")


def backfill_commission_lines() -> int:
    """Create commission lines for eligible delivered+paid invoices missing a line."""
    from datetime import datetime

    from models.employee import Employee
    from models.employee_commission_line import EmployeeCommissionLine
    from models.invoice import Invoice
    from utils.employee_commission import get_employee_commission_amount, is_commission_eligible_employee
    from utils.employee_commission_service import delivered_paid_filter

    invoices = (
        Invoice.query.filter(
            Invoice.employee_id.isnot(None),
            delivered_paid_filter(),
        )
        .order_by(Invoice.id.asc())
        .limit(10000)
        .all()
    )
    if not invoices:
        return 0

    employee_ids = {inv.employee_id for inv in invoices if inv.employee_id}
    employees = Employee.query.filter(Employee.id.in_(employee_ids)).all() if employee_ids else []
    employee_map = {e.id: e for e in employees}

    existing = {
        (row.invoice_id, row.employee_id)
        for row in EmployeeCommissionLine.query.filter(
            EmployeeCommissionLine.invoice_id.in_([i.id for i in invoices])
        ).all()
    }

    created = 0
    for inv in invoices:
        emp = employee_map.get(inv.employee_id)
        if not emp or not is_commission_eligible_employee(emp):
            continue
        key = (inv.id, inv.employee_id)
        if key in existing:
            continue
        amount = get_employee_commission_amount(emp)
        if amount <= 0:
            continue
        status = "paid" if inv.employee_commission_settled_at else "pending"
        line = EmployeeCommissionLine(
            code=EmployeeCommissionLine.make_code(inv.id, inv.employee_id),
            invoice_id=inv.id,
            employee_id=inv.employee_id,
            amount=amount,
            status=status,
            accrued_at=inv.employee_commission_settled_at or inv.created_at or datetime.utcnow(),
        )
        db.session.add(line)
        created += 1

    if created:
        db.session.commit()
    return created
