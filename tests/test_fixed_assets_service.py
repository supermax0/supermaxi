"""اختبارات وحدة لخدمة الأصول الثابتة."""
from datetime import date

from utils.fixed_assets_service import (
    calculate_monthly_depreciation,
    calculate_total_cost,
    resolve_depreciation_start,
)


def test_calculate_total_cost_basic():
    assert calculate_total_cost(1000, 100, 50, 0, 0) == 1150


def test_calculate_total_cost_with_discount():
    assert calculate_total_cost(1000, 0, 0, 0, 200) == 800


def test_calculate_total_cost_never_negative():
    assert calculate_total_cost(100, 0, 0, 0, 500) == 0


def test_calculate_monthly_depreciation_straight_line():
    # (12000 - 2000) / 60 = 166.67 -> 167
    assert calculate_monthly_depreciation(12000, 2000, 60) == 167


def test_calculate_monthly_depreciation_zero_life():
    assert calculate_monthly_depreciation(10000, 0, 0) == 0


def test_calculate_monthly_depreciation_salvage_equals_cost():
    assert calculate_monthly_depreciation(5000, 5000, 36) == 0


def test_resolve_depreciation_start_from_purchase():
    purchase = date(2026, 3, 15)
    assert resolve_depreciation_start("purchase", purchase, None) == purchase


def test_resolve_depreciation_start_from_ready():
    purchase = date(2026, 3, 15)
    ready = date(2026, 4, 1)
    assert resolve_depreciation_start("ready", purchase, ready) == ready


def test_resolve_depreciation_start_next_month():
    purchase = date(2026, 3, 15)
    assert resolve_depreciation_start("next_month", purchase, None) == date(2026, 4, 1)


def test_resolve_depreciation_start_next_month_december():
    purchase = date(2026, 12, 10)
    assert resolve_depreciation_start("next_month", purchase, None) == date(2027, 1, 1)
