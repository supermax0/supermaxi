from types import SimpleNamespace
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from routes.purchases import _purchase_stock_applied, _treasury_paid_amount, _treasury_paid_by_account


def test_confirmed_purchase_is_stock_applied_even_with_legacy_false_flag():
    purchase = SimpleNamespace(status="confirmed", stock_applied=False)

    assert _purchase_stock_applied(purchase) is True


def test_draft_purchase_is_not_stock_applied_with_false_flag():
    purchase = SimpleNamespace(status="draft", stock_applied=False)

    assert _purchase_stock_applied(purchase) is False


def test_purchase_treasury_paid_is_grouped_by_account():
    purchase = SimpleNamespace(
        payments=[
            SimpleNamespace(payment_method="cash", amount=1000, treasury_account_id=1),
            SimpleNamespace(payment_method="bank", amount=2500, treasury_account_id=2),
            SimpleNamespace(payment_method="credit", amount=9000, treasury_account_id=None),
            SimpleNamespace(payment_method="cash", amount=500, treasury_account_id=1),
        ],
        purchase_mode="mixed",
        paid_total=13000,
    )

    with patch("routes.purchases.get_default_cash_account", return_value=SimpleNamespace(id=1)):
        assert _treasury_paid_by_account(purchase) == {1: 1500, 2: 2500}
        assert _treasury_paid_amount(purchase) == 4000


if __name__ == "__main__":
    test_confirmed_purchase_is_stock_applied_even_with_legacy_false_flag()
    test_draft_purchase_is_not_stock_applied_with_false_flag()
    test_purchase_treasury_paid_is_grouped_by_account()
    print("purchase stock_applied logic tests passed")
