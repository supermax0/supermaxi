"""Regression tests for expense posting, reversal, and payroll expense protection."""
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_expense_posting_accounting_{os.getpid()}"


def _fresh_tenant_db():
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def _login(emp_id):
    from flask import session

    session["user_id"] = emp_id
    session["role"] = "admin"


def test_delete_expense_reverses_exact_treasury_account_and_blocks_payroll_expense_delete():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.employee import Employee
    from models.expense import Expense
    from models.treasury_account import TreasuryAccount
    from routes.expenses import _post_expense_to_treasury, delete_expense
    from utils.expense_queries import sum_posted_expenses
    from utils.payroll_schema import ensure_payroll_schema
    from utils.payroll_service import pay_salary
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_schema_guard import ensure_treasury_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_treasury_schema()
        ensure_payroll_schema()

        admin = Employee(name="Expense Admin", username="expense-admin", password="x", role="admin", is_active=True)
        salary_emp = Employee(
            name="Salary Employee",
            username="salary-employee",
            password="x",
            role="cashier",
            is_active=True,
            pay_type="monthly",
            salary=100,
            payroll_effective_from=date(2026, 7, 1),
        )
        cash = get_default_cash_account()
        bank = TreasuryAccount(name="Expense Bank", account_type="bank", is_active=True)
        db.session.add_all([admin, salary_emp, bank])
        db.session.flush()
        db.session.add_all(
            [
                AccountTransaction(type="deposit", amount=1000, note="opening cash", treasury_account_id=cash.id),
                AccountTransaction(type="deposit", amount=1000, note="opening bank", treasury_account_id=bank.id),
            ]
        )
        db.session.commit()

        cash_expense = Expense(
            title="Duplicate Rent",
            category="office",
            amount=300,
            expense_date=date(2026, 7, 10),
            treasury_account_id=cash.id,
            cash_posted=False,
        )
        bank_expense = Expense(
            title="Duplicate Rent",
            category="office",
            amount=300,
            expense_date=date(2026, 7, 10),
            treasury_account_id=bank.id,
            cash_posted=False,
        )
        db.session.add_all([cash_expense, bank_expense])
        db.session.flush()
        _post_expense_to_treasury(cash_expense, cash.id)
        _post_expense_to_treasury(bank_expense, bank.id)
        db.session.commit()

        assert calculate_treasury_balance(cash.id) == 700
        assert calculate_treasury_balance(bank.id) == 700
        assert sum_posted_expenses() == 600
        admin_id = admin.id
        salary_emp_id = salary_emp.id
        cash_id = cash.id
        bank_id = bank.id
        cash_expense_id = cash_expense.id

    with app.test_request_context(f"/expenses/delete/{cash_expense_id}"):
        g.tenant = TENANT
        _login(admin_id)
        delete_expense(cash_expense_id)

    with app.app_context():
        g.tenant = TENANT
        assert Expense.query.get(cash_expense_id) is None
        assert calculate_treasury_balance(cash_id) == 1000
        assert calculate_treasury_balance(bank_id) == 700
        assert sum_posted_expenses() == 300

        salary_emp = Employee.query.get(salary_emp_id)
        result = pay_salary(salary_emp, treasury_account_id=cash_id, settled_by=admin_id, manual=True)
        assert result["ok"], result
        payroll_expense_id = result["expense_id"]
        assert calculate_treasury_balance(cash_id) == 900

    with app.test_request_context(f"/expenses/delete/{payroll_expense_id}"):
        g.tenant = TENANT
        _login(admin_id)
        delete_expense(payroll_expense_id)

    with app.app_context():
        g.tenant = TENANT
        assert Expense.query.get(payroll_expense_id) is not None
        assert calculate_treasury_balance(cash_id) == 900


if __name__ == "__main__":
    test_delete_expense_reverses_exact_treasury_account_and_blocks_payroll_expense_delete()
    print("expense posting accounting tests passed")
