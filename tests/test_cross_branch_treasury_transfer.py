"""Admin treasury transfers may cross branches without mixing ledger sides."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_cross_branch_treasury_{os.getpid()}"


def test_admin_transfers_cash_to_bank_across_branches():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.account_transaction import AccountTransaction
    from models.branch import Branch
    from models.employee import Employee
    from models.treasury_account import TreasuryAccount
    from utils.branch_context import init_branch_context
    from utils.branch_migration import ensure_branch_schema, get_default_branch
    from utils.treasury_calculations import record_treasury_transfer
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_branch_schema()
        main = get_default_branch()
        second = Branch(code="TR-B2", name="فرع التحويل الثاني", is_active=True)
        admin = Employee(
            name="Treasury Admin",
            username=f"treasury-admin-{os.getpid()}",
            password="x",
            role="admin",
            is_active=True,
            branch_id=main.id,
        )
        db.session.add_all([second, admin])
        db.session.commit()
        main_id = main.id
        second_id = second.id
        admin_id = admin.id

        with app.test_request_context("/accounts/transfer", method="POST"):
            g.tenant = TENANT
            session.update(
                user_id=admin_id,
                role="admin",
                tenant_slug=TENANT,
                branch_id=main_id,
                view_all_branches=False,
            )
            init_branch_context()
            source_cash = get_default_cash_account(second_id)
            destination_bank = TreasuryAccount(
                branch_id=main_id,
                name="بنك الفرع الرئيسي",
                account_type="bank",
                is_active=True,
            )
            db.session.add(destination_bank)
            db.session.flush()
            db.session.add(AccountTransaction(
                branch_id=second_id,
                type="deposit",
                amount=1000,
                note="رصيد افتتاحي للاختبار",
                treasury_account_id=source_cash.id,
            ))
            db.session.commit()

            transfer = record_treasury_transfer(
                source_cash.id,
                destination_bank.id,
                400,
                "إيداع مصرفي",
                allow_cross_branch=True,
            )

            rows = (
                AccountTransaction.query.execution_options(skip_branch_scope=True)
                .filter_by(treasury_transfer_id=transfer.id)
                .order_by(AccountTransaction.type.asc())
                .all()
            )
            assert transfer.branch_id == second_id
            assert len(rows) == 2
            deposit = next(row for row in rows if row.type == "deposit")
            withdrawal = next(row for row in rows if row.type == "withdraw")
            assert withdrawal.branch_id == second_id
            assert withdrawal.treasury_account_id == source_cash.id
            assert deposit.branch_id == main_id
            assert deposit.treasury_account_id == destination_bank.id
            assert withdrawal.amount == deposit.amount == 400

