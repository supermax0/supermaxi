"""Regression: commission settlement must respect the selected period."""
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = "test_payroll_commission_period"


def _fresh_tenant_db(tenant=TENANT):
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(tenant)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_settle_commission_payment_filters_month():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.customer import Customer
    from models.employee import Employee
    from models.employee_commission_line import EmployeeCommissionLine
    from models.employee_payment import EmployeePayment
    from models.expense import Expense
    from models.invoice import Invoice
    from utils.payroll_schema import ensure_payroll_schema
    from utils.payroll_service import settle_employee_commission_payment
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_schema_guard import ensure_treasury_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_payroll_schema()
        ensure_treasury_schema()

        cash = get_default_cash_account()
        employee = Employee(
            name="Commission Cashier",
            username="commission_cashier",
            password="pw",
            role="cashier",
            is_active=True,
            commission_percent=100,
        )
        customer = Customer(name="Payroll Customer", phone="07710000000")
        db.session.add_all([employee, customer])
        db.session.flush()

        jan_invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            total=1000,
            status="تم التوصيل",
            payment_status="مسدد",
            paid_amount=1000,
            created_at=datetime(2026, 1, 10),
        )
        feb_invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            total=2000,
            status="تم التوصيل",
            payment_status="مسدد",
            paid_amount=2000,
            created_at=datetime(2026, 2, 10),
        )
        db.session.add_all([jan_invoice, feb_invoice])
        db.session.flush()

        jan_line = EmployeeCommissionLine(
            code=EmployeeCommissionLine.make_code(jan_invoice.id, employee.id),
            invoice_id=jan_invoice.id,
            employee_id=employee.id,
            amount=100,
            status="pending",
            accrued_at=datetime(2026, 1, 10),
        )
        feb_line = EmployeeCommissionLine(
            code=EmployeeCommissionLine.make_code(feb_invoice.id, employee.id),
            invoice_id=feb_invoice.id,
            employee_id=employee.id,
            amount=200,
            status="pending",
            accrued_at=datetime(2026, 2, 10),
        )
        db.session.add_all(
            [
                jan_line,
                feb_line,
                AccountTransaction(
                    type="deposit",
                    amount=1000,
                    note="opening cash for payroll test",
                    treasury_account_id=cash.id,
                ),
            ]
        )
        db.session.commit()

        result = settle_employee_commission_payment(
            employee.id,
            treasury_account_id=cash.id,
            year=2026,
            month=1,
        )
        assert result["ok"], result
        assert result["amount"] == 100
        assert result["order_count"] == 1

        db.session.refresh(jan_line)
        db.session.refresh(feb_line)
        assert jan_line.status == "paid"
        assert feb_line.status == "pending"
        assert EmployeePayment.query.count() == 1
        assert int(EmployeePayment.query.first().amount or 0) == 100
        assert int(Expense.query.first().amount or 0) == 100


def test_commission_backfill_includes_legacy_delivered_null_payment_status():
    tenant = f"{TENANT}_legacy_{os.getpid()}"
    _fresh_tenant_db(tenant)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.employee import Employee
    from models.employee_commission_line import EmployeeCommissionLine
    from models.invoice import Invoice
    from sqlalchemy import text
    from utils.payroll_schema import backfill_commission_lines, ensure_payroll_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_payroll_schema()

        employee = Employee(
            name="Legacy Commission Cashier",
            username="legacy_commission_cashier",
            password="pw",
            role="cashier",
            is_active=True,
            commission_percent=75,
        )
        customer = Customer(name="Legacy Payroll Customer", phone="07710000001")
        db.session.add_all([employee, customer])
        db.session.flush()

        legacy_paid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            total=1000,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            paid_amount=0,
            created_at=datetime(2026, 3, 10),
        )
        explicit_unpaid = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=employee.id,
            employee_name=employee.name,
            total=2000,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u063a\u064a\u0631 \u0645\u0633\u062f\u062f",
            paid_amount=0,
            created_at=datetime(2026, 3, 11),
        )
        db.session.add_all([legacy_paid, explicit_unpaid])
        db.session.flush()
        db.session.execute(
            text("UPDATE invoice SET payment_status = NULL WHERE id = :invoice_id"),
            {"invoice_id": legacy_paid.id},
        )
        db.session.commit()

        created = backfill_commission_lines()
        assert created == 1
        rows = EmployeeCommissionLine.query.order_by(EmployeeCommissionLine.invoice_id.asc()).all()
        assert len(rows) == 1
        assert rows[0].invoice_id == legacy_paid.id
        assert int(rows[0].amount or 0) == 75


if __name__ == "__main__":
    test_settle_commission_payment_filters_month()
    test_commission_backfill_includes_legacy_delivered_null_payment_status()
    print("payroll commission period tests passed")
