"""Regression: financial report balance sheet must include bank treasury accounts."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT = f"test_financial_report_treasury_{os.getpid()}"


def _fresh_tenant_db():
    try:
        from extensions_tenant import clear_tenant_engine

        clear_tenant_engine(TENANT)
    except Exception:
        pass
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_financial_report_assets_include_cash_and_bank_balances():
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.treasury_account import TreasuryAccount
    from utils.financial_report_data import get_financial_report_data
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)

        cash = get_default_cash_account()
        bank = TreasuryAccount(name="Test Bank", account_type="bank", is_default=False, is_active=True)
        db.session.add(bank)
        db.session.flush()
        db.session.add_all(
            [
                AccountTransaction(
                    type="deposit",
                    amount=700,
                    note="cash opening",
                    treasury_account_id=cash.id,
                ),
                AccountTransaction(
                    type="deposit",
                    amount=1500,
                    note="bank opening",
                    treasury_account_id=bank.id,
                ),
            ]
        )
        db.session.commit()

        data = get_financial_report_data("this_month")

        assert data["cash_balance"] == 700
        assert data["bank_balance_total"] == 1500
        assert data["total_liquidity"] == 2200
        assert data["total_assets"] == 2200
        assert data["bank_balances"] == [
            {
                "account_id": bank.id,
                "name": "Test Bank",
                "account_type": "bank",
                "is_cash": False,
                "is_default": False,
                "balance": 1500,
            }
        ]


if __name__ == "__main__":
    test_financial_report_assets_include_cash_and_bank_balances()
    print("financial report treasury balance tests passed")
