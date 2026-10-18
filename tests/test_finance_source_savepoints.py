"""SAVEPOINT release/rollback preserves posting; outer commits stay guarded."""
from datetime import date
import pytest
from tests.test_finance_operations import finance, review_opening


def test_inner_release_and_rollback_do_not_lose_outer_expense_posting(finance):
    from flask import g, session
    from models.expense import Expense
    from modules.finance.common import FinanceError
    from modules.finance import reports, ledger
    f = finance
    review_opening(f)
    with f["app"].test_request_context():
        session.update(user_id=f["admin"].id, employee_id=f["admin"].id, role="admin")
        g.branch=f["branch"]; g.view_all_branches=True; g.independent_branches_enabled=False
        row = Expense(title="مصروف قبل نقطة الحفظ", amount=100, expense_date=date.today(),
            cash_posted=True, treasury_account_id=f["cash"].id, branch_id=f["branch"].id)
        f["db"].session.add(row)
        f["db"].session.flush()
        assert f["db"].session.info.get("finance_sources")
        f["db"].session.info["finance_atomic"] = True
        try:
            with f["db"].session.begin_nested():
                pass
            assert f["db"].session.info.get("finance_sources")
            with pytest.raises(RuntimeError):
                with f["db"].session.begin_nested():
                    row.amount = 200
                    f["db"].session.flush()
                    raise RuntimeError("rollback only the savepoint")
            assert row.amount == 100
            assert f["db"].session.info.get("finance_sources")
            with pytest.raises(FinanceError, match="كوحدة واحدة"):
                f["db"].session.commit()
            # The rejected early commit has not committed any source entry.
            f["db"].session.info["finance_commit_allowed"] = True
            f["db"].session.commit()
            assert ledger.treasury_gl(f["cash"]).balance == 19_999_900
            assert ledger.account("expense").balance == 100
            assert reports.trial_balance({})["profit"] == -100
        finally:
            f["db"].session.info.pop("finance_atomic", None)
            f["db"].session.info.pop("finance_commit_allowed", None)
