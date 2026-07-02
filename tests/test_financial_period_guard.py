"""اختبارات إغلاق الفترات المحاسبية."""
from datetime import date

from utils.financial_period_guard import (
    assert_date_period_open,
    is_date_in_closed_period,
    is_period_closed,
)


def test_is_period_closed_default_false():
    assert is_period_closed(2099, 1) is False


def test_is_date_in_closed_period_without_db():
    assert is_date_in_closed_period(date(2099, 6, 15)) is False


def test_assert_date_period_open_allows_open_period():
    assert_date_period_open(date(2099, 6, 15), "اختبار")
