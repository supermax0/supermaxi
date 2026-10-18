from types import SimpleNamespace


def test_accounts_visible_balance_sums_cash_from_all_visible_branches():
    from routes.accounts import _visible_cash_balance

    rows = [
        {"account": SimpleNamespace(is_cash=True), "balance": -55_492_150},
        {"account": SimpleNamespace(is_cash=False), "balance": 4_162_000},
        {"account": SimpleNamespace(is_cash=True), "balance": 75_285_000},
        {"account": SimpleNamespace(is_cash=False), "balance": 0},
    ]

    assert _visible_cash_balance(rows) == 19_792_850
