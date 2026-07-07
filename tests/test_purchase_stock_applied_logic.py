from types import SimpleNamespace
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from routes.purchases import _purchase_stock_applied


def test_confirmed_purchase_is_stock_applied_even_with_legacy_false_flag():
    purchase = SimpleNamespace(status="confirmed", stock_applied=False)

    assert _purchase_stock_applied(purchase) is True


def test_draft_purchase_is_not_stock_applied_with_false_flag():
    purchase = SimpleNamespace(status="draft", stock_applied=False)

    assert _purchase_stock_applied(purchase) is False


if __name__ == "__main__":
    test_confirmed_purchase_is_stock_applied_even_with_legacy_false_flag()
    test_draft_purchase_is_not_stock_applied_with_false_flag()
    print("purchase stock_applied logic tests passed")
