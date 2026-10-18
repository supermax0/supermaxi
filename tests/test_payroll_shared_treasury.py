"""Shared-mode payroll may pay from the company treasury even if branch ids differ."""
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _fresh_tenant_db(tenant):
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(tenant)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def _enable_legacy_shared_mode():
    from models.system_settings import SystemSettings
    from utils.branch_mode import clear_branch_mode_cache

    settings = SystemSettings.query.first()
    flags = settings.get_ui_flags()
    flags["independent_branches_enabled"] = False
    flags["branch_scope_v3_done"] = True
    flags["legacy_shared_mode_enabled"] = True
    settings.set_ui_flags(flags)
    from extensions import db

    db.session.commit()
    clear_branch_mode_cache()


def _seed_mismatch_salary_case():
    from extensions import db
    from models.account_transaction import AccountTransaction
    from models.branch import Branch
    from models.employee import Employee
    from models.treasury_account import TreasuryAccount
    from utils.branch_migration import ensure_branch_schema, get_default_branch
    from utils.payroll_schema import ensure_payroll_schema
    from utils.treasury_schema_guard import ensure_treasury_schema

    ensure_treasury_schema()
    ensure_payroll_schema()
    ensure_branch_schema()

    main = get_default_branch()
    second = Branch(code="PAY-B2", name="فرع ثانٍ", is_active=True)
    db.session.add(second)
    db.session.flush()

    cash = TreasuryAccount.query.filter_by(account_type="cash", is_active=True).first()
    if cash is None:
        cash = TreasuryAccount(name="صندوق الشركة", account_type="cash", is_default=True, is_active=True)
        db.session.add(cash)
        db.session.flush()
    cash.branch_id = main.id
    cash.name = "صندوق الشركة"

    employee = Employee(
        name="AH",
        username=f"pay-shared-{os.getpid()}",
        password="x",
        role="cashier",
        is_active=True,
        pay_type="monthly",
        salary=100_000,
        payroll_effective_from=date(2026, 7, 1),
        branch_id=second.id,
    )
    db.session.add(employee)
    db.session.add(
        AccountTransaction(type="deposit", amount=500_000, note="opening", treasury_account_id=cash.id)
    )
    db.session.commit()
    return employee, cash


def test_shared_mode_allows_salary_from_company_treasury():
    tenant = f"test_payroll_shared_treasury_{os.getpid()}"
    _fresh_tenant_db(tenant)
    from app import app
    from flask import g
    from extensions_tenant import init_tenant_db
    from utils.payroll_service import pay_salary, resolve_payroll_payout_branch

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        _enable_legacy_shared_mode()
        employee, cash = _seed_mismatch_salary_case()

        branch_id, error = resolve_payroll_payout_branch(cash, employee)
        assert error is None
        assert branch_id == employee.branch_id

        result = pay_salary(employee, treasury_account_id=cash.id, manual=True, today=date(2026, 9, 10))
        assert result["ok"], result


def test_independent_mode_requires_employee_branch_treasury():
    tenant = f"test_payroll_independent_treasury_{os.getpid()}"
    _fresh_tenant_db(tenant)
    from app import app
    from flask import g
    from extensions_tenant import init_tenant_db
    from utils.payroll_service import pay_salary, resolve_payroll_payout_branch

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        employee, cash = _seed_mismatch_salary_case()

        branch_id, error = resolve_payroll_payout_branch(cash, employee)
        assert branch_id is None
        assert error == "يجب صرف الراتب من خزينة فرع الموظف"

        result = pay_salary(employee, treasury_account_id=cash.id, manual=True, today=date(2026, 9, 10))
        assert result == {"ok": False, "error": "يجب صرف الراتب من خزينة فرع الموظف"}
