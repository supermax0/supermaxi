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


def test_post_due_respects_expense_post_time():
    """مصروف اليوم بساعة لاحقة يبقى معلّقاً حتى تحين الساعة."""
    _fresh_tenant_db()
    from datetime import datetime, time

    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.expense import Expense
    from routes.expenses import post_due_unposted_expenses
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_schema_guard import ensure_treasury_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_treasury_schema()
        cash = get_default_cash_account()
        db.session.add(AccountTransaction(type="deposit", amount=500000, note="open", treasury_account_id=cash.id))
        day = date(2026, 9, 5)
        pending = Expense(
            title="يومي 10م",
            category="other",
            amount=100000,
            expense_date=day,
            post_time=time(22, 0),
            treasury_account_id=cash.id,
            cash_posted=False,
        )
        due = Expense(
            title="يومي مستحق",
            category="other",
            amount=50000,
            expense_date=day,
            post_time=time(10, 0),
            treasury_account_id=cash.id,
            cash_posted=False,
        )
        db.session.add_all([pending, due])
        db.session.commit()
        cash_id = cash.id
        pending_id = pending.id
        due_id = due.id

        posted, skipped = post_due_unposted_expenses(now=datetime(2026, 9, 5, 15, 0))
        assert posted == 1
        assert skipped == 0
        assert Expense.query.get(due_id).cash_posted is True
        assert Expense.query.get(pending_id).cash_posted is False
        assert calculate_treasury_balance(cash_id) == 450000

        posted, skipped = post_due_unposted_expenses(now=datetime(2026, 9, 5, 22, 0))
        assert posted == 1
        assert Expense.query.get(pending_id).cash_posted is True
        assert calculate_treasury_balance(cash_id) == 350000


def test_edit_scheduled_expense_series_updates_unposted_only():
    """تعديل السلسلة يغيّر المجدول فقط ويحافظ على المخصوم."""
    _fresh_tenant_db()
    from datetime import datetime, time, timedelta

    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.expense import Expense
    from models.treasury_account import TreasuryAccount
    from routes.expenses import _post_expense_to_treasury
    from utils.expense_series import build_repeat_note, new_series_id, update_scheduled_series
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_schema_guard import ensure_treasury_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_treasury_schema()
        cash = get_default_cash_account()
        card = TreasuryAccount(name="بطاقة إعلان", account_type="bank", is_active=True)
        db.session.add(card)
        db.session.add(AccountTransaction(type="deposit", amount=1_000_000, note="open", treasury_account_id=cash.id))
        db.session.flush()

        series_id = new_series_id()
        start = date(2026, 9, 5)
        rows = []
        for i in range(3):
            row = Expense(
                title="إعلان",
                category="advertising",
                amount=100000,
                note=build_repeat_note("", i + 1, 3),
                expense_date=start + timedelta(days=i),
                post_time=time(22, 0),
                treasury_account_id=cash.id,
                repeat_series_id=series_id,
                cash_posted=False,
            )
            db.session.add(row)
            rows.append(row)
        db.session.flush()
        _post_expense_to_treasury(rows[0], cash.id)
        db.session.commit()

        first_id = rows[0].id
        second_id = rows[1].id
        third_id = rows[2].id
        card_id = card.id

        updated = update_scheduled_series(
            Expense.query.get(second_id),
            {
                "title": "إعلان فيسبوك",
                "category": "advertising",
                "amount": 120000,
                "treasury_account_id": card_id,
                "post_time": "21:30",
                "base_note": "حملة يومية",
            },
        )
        db.session.commit()

        posted = Expense.query.get(first_id)
        second = Expense.query.get(second_id)
        third = Expense.query.get(third_id)

        assert posted.cash_posted is True
        assert posted.title == "إعلان"
        assert posted.amount == 100000
        assert posted.treasury_account_id == cash.id

        assert second.cash_posted is False
        assert third.cash_posted is False
        assert second.title == "إعلان فيسبوك"
        assert third.title == "إعلان فيسبوك"
        assert second.amount == 120000
        assert third.amount == 120000
        assert second.treasury_account_id == card_id
        assert third.treasury_account_id == card_id
        assert second.post_time == time(21, 30)
        assert "حملة يومية" in (second.note or "")
        assert "تكرار 2/3" in (second.note or "")
        assert "تكرار 3/3" in (third.note or "")
        assert updated["scheduled_count"] == 2
        assert updated["posted_count"] == 1


if __name__ == "__main__":
    test_delete_expense_reverses_exact_treasury_account_and_blocks_payroll_expense_delete()
    test_post_due_respects_expense_post_time()
    test_edit_scheduled_expense_series_updates_unposted_only()
    print("expense posting accounting tests passed")
