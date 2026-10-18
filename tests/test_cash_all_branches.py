from datetime import date, datetime
import os
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def test_all_branches_cash_combines_balances_movements_and_summary(monkeypatch):
    from flask import Flask

    from utils.cash_calculations import (
        calculate_cash_balance,
        get_cash_movements,
        get_cash_summary,
    )
    import utils.branch_scope as branch_scope
    import utils.treasury_calculations as treasury_calculations
    import utils.treasury_helpers as treasury_helpers

    cash_main = SimpleNamespace(id=1, name="صندوق الفرع الرئيسي", branch_id=1, is_cash=True)
    bank = SimpleNamespace(id=2, name="بطاقة ماستر", branch_id=1, is_cash=False)
    cash_second = SimpleNamespace(id=3, name="صندوق الفرع الثاني", branch_id=2, is_cash=True)

    balances = {1: -55_492_150, 2: 4_162_000, 3: 73_945_000}
    movements = {
        1: [
            {
                "date": datetime(2026, 8, 2).date(),
                "datetime": datetime(2026, 8, 2, 10),
                "type": "cash_in",
                "amount": 100,
                "reference_type": "invoice",
                "reference_id": 1,
                "balance_after": 100,
            },
            {
                "date": datetime(2026, 8, 3).date(),
                "datetime": datetime(2026, 8, 3, 10),
                "type": "cash_out",
                "amount": 30,
                "reference_type": "account_transaction",
                "reference_id": 2,
                "balance_after": 70,
            },
        ],
        3: [
            {
                "date": datetime(2026, 8, 1).date(),
                "datetime": datetime(2026, 8, 1, 10),
                "type": "cash_in",
                "amount": 200,
                "reference_type": "invoice_payment_ledger",
                "reference_id": 3,
                "balance_after": 200,
            },
            {
                "date": datetime(2026, 8, 4).date(),
                "datetime": datetime(2026, 8, 4, 10),
                "type": "cash_out",
                "amount": 50,
                "reference_type": "account_transaction",
                "reference_id": 4,
                "balance_after": 150,
            },
        ],
    }

    monkeypatch.setattr(branch_scope, "viewing_all_branches", lambda: True)
    monkeypatch.setattr(
        treasury_calculations,
        "list_treasury_accounts",
        lambda: [cash_main, bank, cash_second],
    )
    monkeypatch.setattr(
        treasury_calculations,
        "calculate_treasury_balance",
        lambda account_id: balances[account_id],
    )
    monkeypatch.setattr(
        treasury_calculations,
        "get_treasury_movements",
        lambda account_id: movements[account_id],
    )
    monkeypatch.setattr(
        treasury_helpers,
        "get_default_cash_account",
        lambda: (_ for _ in ()).throw(AssertionError("default cash must not be used")),
    )

    app = Flask(__name__)
    with app.test_request_context("/cash/"):
        assert calculate_cash_balance() == 18_452_850

        combined = get_cash_movements()
        assert [item["amount"] for item in combined] == [200, 100, 30, 50]
        assert [item["balance_after"] for item in combined] == [200, 300, 270, 220]
        assert [item["branch_id"] for item in combined] == [2, 1, 1, 2]

        summary = get_cash_summary()
        assert summary == {
            "total_in": 300,
            "total_out": 80,
            "current_balance": 18_452_850,
            "movements_count": 4,
            "undated_collection_balance": 0,
        }


def test_default_branch_cash_keeps_legacy_unassigned_movements():
    tenant = f"test_cash_legacy_branch_{os.getpid()}"
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(tenant)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.account_transaction import AccountTransaction
    from models.branch import Branch
    from models.employee import Employee
    from utils.branch_context import init_branch_context
    from utils.branch_migration import ensure_branch_schema, get_default_branch
    from utils.cash_calculations import calculate_cash_balance, get_cash_summary
    from utils.daily_report_data import _cash_summary_for_day
    from utils.business_time import business_date
    from utils.treasury_helpers import get_default_cash_account

    report_day = business_date(datetime.utcnow())

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_branch_schema()
        main = get_default_branch()
        second = Branch(code="CASH-B2", name="فرع الصندوق الثاني", is_active=True)
        admin = Employee(
            name="Cash Admin",
            username=f"cash-admin-{os.getpid()}",
            password="x",
            role="admin",
            is_active=True,
            branch_id=main.id,
        )
        db.session.add_all([second, admin])
        db.session.commit()

        main_cash = get_default_cash_account(main.id)
        second_cash = get_default_cash_account(second.id)
        db.session.add_all(
            [
                AccountTransaction(
                    type="deposit",
                    amount=500,
                    note="حركة قديمة بلا فرع",
                ),
                AccountTransaction(
                    branch_id=main.id,
                    type="deposit",
                    amount=100,
                    note="حركة الفرع الرئيسي",
                    treasury_account_id=main_cash.id,
                ),
                AccountTransaction(
                    branch_id=second.id,
                    type="deposit",
                    amount=200,
                    note="حركة الفرع الثاني",
                    treasury_account_id=second_cash.id,
                ),
            ]
        )
        db.session.commit()

        main_id = int(main.id)
        second_id = int(second.id)
        admin_id = int(admin.id)

        with app.test_request_context("/cash/"):
            g.tenant = tenant
            session.update(
                user_id=admin_id,
                role="admin",
                tenant_slug=tenant,
                branch_id=main_id,
                view_all_branches=False,
            )
            init_branch_context()
            assert calculate_cash_balance() == 600
            assert get_cash_summary()["movements_count"] == 2
            assert _cash_summary_for_day(report_day)["closing_balance"] == 600

        with app.test_request_context("/cash/"):
            g.tenant = tenant
            session.update(
                user_id=admin_id,
                role="admin",
                tenant_slug=tenant,
                branch_id=second_id,
                view_all_branches=False,
            )
            init_branch_context()
            assert calculate_cash_balance() == 200
            assert get_cash_summary()["movements_count"] == 1
            assert _cash_summary_for_day(report_day)["closing_balance"] == 200

        with app.test_request_context("/cash/"):
            g.tenant = tenant
            session.update(
                user_id=admin_id,
                role="admin",
                tenant_slug=tenant,
                view_all_branches=True,
            )
            session.pop("branch_id", None)
            init_branch_context()
            assert calculate_cash_balance() == 800
            assert get_cash_summary()["movements_count"] == 3
            daily_cash = _cash_summary_for_day(report_day)
            assert daily_cash["closing_balance"] == 800
            assert daily_cash["cash_in"] == 800
            assert daily_cash["movement_count"] == 3
