"""Bank/card definitions are shared while balances remain branch-local."""
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_shared_branch_banks_{os.getpid()}"


def _fresh_tenant_db():
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_main_branch_cards_are_copied_to_every_branch():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.branch import Branch
    from models.treasury_account import TreasuryAccount
    from utils.branch_migration import ensure_branch_schema, get_default_branch
    from utils.treasury_helpers import sync_bank_accounts_across_branches

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_branch_schema()
        main = get_default_branch()
        second = Branch(code="CARD-B2", name="فرع البطاقات", is_active=True)
        db.session.add(second)
        db.session.flush()
        db.session.add_all([
            TreasuryAccount(
                branch_id=main.id,
                name="زين كاش",
                account_type="bank",
                is_active=True,
            ),
            TreasuryAccount(
                branch_id=main.id,
                name="ماستر كي",
                account_type="bank",
                is_active=True,
            ),
        ])
        db.session.commit()

        assert sync_bank_accounts_across_branches() == 2
        db.session.commit()

        second_cards = (
            TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter_by(branch_id=second.id, account_type="bank", is_active=True)
            .order_by(TreasuryAccount.name.asc())
            .all()
        )
        assert {account.name for account in second_cards} == {"زين كاش", "ماستر كي"}
        assert all(account.branch_id == second.id for account in second_cards)

        # Re-running the guard is idempotent and does not create duplicates.
        assert sync_bank_accounts_across_branches() == 0
        assert (
            TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter_by(account_type="bank")
            .count()
        ) == 4
