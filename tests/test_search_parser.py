"""The Iraqi shopping phrases of the spec, parsed into intent (pure functions, no database)."""
from __future__ import annotations

import pytest

from modules.search.lexicon import compact, normalize
from modules.search.parser import attributes, parse


def test_normalisation_unifies_spelling_digits_and_diacritics():
    assert normalize("شاشةٌ  ذكيّة") == normalize("شاشه ذكيه")
    assert normalize("إنفرتر") == normalize("انفرتر")
    assert normalize("٥٥ بوصة") == "55 بوصه"
    assert compact("UA-55 CU7000") == compact("ua55cu7000")


@pytest.mark.parametrize("phrase,expected", [
    ("شاشة 55 سمارت بأقل من 400 ألف", {"category": "شاشات", "size_inch": 55.0, "max_price": 400_000, "features": {"smart"}}),
    ("سبلت طن ونص انفرتر", {"category": "سبالت", "ton": 1.5, "features": {"inverter"}}),
    ("غسالة حوضين 12 كيلو", {"category": "غسالات", "kg": 12.0, "features": {"twin_tub"}}),
    ("الجي خمسين", {"brand": "LG", "size_inch": 50.0}),
    ("TCL 55C7K", {"brand": "TCL", "codes": ["55c7k"]}),
    ("شاشة للـ PS5", {"category": "شاشات", "features": {"gaming"}}),
    ("ثلاجة كبيرة وما تصرف كهرباء هواي", {"category": "ثلاجات", "features": {"large", "efficient"}}),
    ("مكيف جري طنين", {"category": "سبالت", "brand": "Gree", "ton": 2.0}),
    ("تلفزيون سامسونك 65 انج تحت مليون", {"category": "شاشات", "brand": "Samsung", "size_inch": 65.0, "max_price": 1_000_000}),
    ("براد من 300 الى 600 الف", {"category": "ثلاجات", "min_price": 300_000, "max_price": 600_000}),
    ("8806094970002", {"codes": ["8806094970002"]}),
])
def test_iraqi_phrases(phrase, expected):
    intent = parse(phrase)
    for key, value in expected.items():
        got = getattr(intent, key)
        if key == "features":
            assert value <= got, (phrase, got)
        else:
            assert got == value, (phrase, key, got)


def test_free_terms_keep_what_was_not_understood_and_drop_filler():
    intent = parse("اريد غسالة لون ابيض")
    assert intent.category == "غسالات" and "ابيض" in intent.terms and "اريد" not in intent.terms


def test_company_synonyms_apply_before_parsing():
    intent = parse("كاونتر", synonyms={"كاونتر": "ثلاجة"})
    assert intent.category == "ثلاجات"


def test_product_attribute_extraction():
    a = attributes(normalize("سبلت جري 18000 BTU انفرتر حار بارد"), "سبالت")
    assert a.ton == 1.5 and {"inverter", "hot_cold"} <= a.features
    assert attributes(normalize("شاشة LG 55 UHD سمارت"), "شاشات").size_inch == 55.0
    assert attributes(normalize("غسالة سامسونج 9 كغم"), "غسالات").kg == 9.0
