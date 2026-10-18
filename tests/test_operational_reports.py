from datetime import date
from types import SimpleNamespace

import pytest

from utils.operational_reports import (
    _compose_payment_labels,
    _normalize_payment_method,
    _payment_filter_key,
    _payment_label,
    _purchase_payment_label,
    _material_type,
    _treasury_method_label,
    build_operational_report,
    resolve_report_period,
)


def test_operational_reports_default_to_today():
    assert resolve_report_period({}, today=date(2026, 8, 24)) == (
        date(2026, 8, 24),
        date(2026, 8, 24),
        "today",
    )


def test_operational_report_custom_dates_are_inclusive_and_normalized():
    assert resolve_report_period(
        {"date_from": "2026-08-10", "date_to": "2026-08-05"},
        today=date(2026, 8, 24),
    ) == (date(2026, 8, 5), date(2026, 8, 10), "custom")


def test_operational_report_keeps_selected_quick_period():
    assert resolve_report_period(
        {"period": "today", "date_from": "2026-08-24", "date_to": "2026-08-24"},
        today=date(2026, 8, 24),
    ) == (date(2026, 8, 24), date(2026, 8, 24), "today")


def test_operational_report_rejects_unknown_type_before_querying():
    with pytest.raises(ValueError, match="غير مدعوم"):
        build_operational_report("unknown", {})


def test_material_type_prefers_beauty_type_then_catalog_category():
    beauty_product = SimpleNamespace(
        meta_json='{"beauty_product_type":"session_material","category":"عناية"}',
        catalog_category="عناية",
    )
    categorized_product = SimpleNamespace(meta_json="{}", catalog_category="أجهزة")
    uncategorized_product = SimpleNamespace(meta_json="not-json", catalog_category="")

    assert _material_type(beauty_product) == ("beauty:session_material", "مادة جلسات")
    assert _material_type(categorized_product) == ("category:أجهزة", "أجهزة")
    assert _material_type(uncategorized_product) == ("uncategorized", "غير مصنف")


def test_sales_payment_method_uses_cash_bank_or_credit_labels():
    unpaid = SimpleNamespace(id=1, payment_status="غير مسدد", paid_amount=0, total=100_000)
    cash = SimpleNamespace(id=2, payment_status="مسدد", paid_amount=100_000, total=100_000)
    partial = SimpleNamespace(id=3, payment_status="جزئي", paid_amount=25_000, total=100_000)

    assert _payment_label(unpaid, {1: "نقدي"}) == "آجل"
    assert _payment_label(cash, {}) == "نقدي"
    assert _payment_label(partial, {3: "تحويل بنكي"}) == "تحويل بنكي (جزئي)"


def test_payment_method_normalization_and_supplier_credit_label():
    assert _normalize_payment_method("bank_transfer") == "تحويل بنكي"
    assert _normalize_payment_method("cash") == "نقدي"
    purchase = SimpleNamespace(id=7, purchase_mode="credit")
    assert _purchase_payment_label(purchase, 0, 50_000, {}) == "آجل"


def test_bank_transfer_includes_account_name_from_treasury():
    details = {5: ("bank", "بطاقة الرافدين")}
    assert _treasury_method_label(5, details) == "تحويل بنكي — بطاقة الرافدين"
    assert _compose_payment_labels({"نقدي", "تحويل بنكي — بطاقة الرافدين"}) == (
        "نقدي + تحويل بنكي — بطاقة الرافدين"
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("نقدي", "cash"),
        ("نقدي (جزئي)", "cash"),
        ("تحويل بنكي — بطاقة الرافدين", "bank"),
        ("تحويل بنكي (جزئي)", "bank"),
        ("نقدي + تحويل بنكي — بطاقة الرافدين", "mixed"),
        ("آجل", "credit"),
    ],
)
def test_sales_payment_method_filter_categories(label, expected):
    assert _payment_filter_key(label) == expected
