"""Pure unit tests for the FINORA CORE brain (no app): Arabic extraction, plan guards, knowledge retrieval."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.finora_core.brain.extract import extract, normalize, number_grounded  # noqa: E402
from modules.finora_core.brain.knowledge import KnowledgeItem, retrieve  # noqa: E402
from modules.finora_core.brain.planner import Plan, detect_language, plan_with_rules, verify_plan  # noqa: E402


@pytest.mark.parametrize(
    ("text", "facts"),
    [
        ("السلام عليكم عندي عيادة اسنان واريد نظام", {"businessType": "clinic", "specialty": "dentistry"}),
        ("عدنا 3 اطباء و2 موظفين وفرع واحد", {"doctors": 3, "employees": 2, "branches": 1}),
        ("عدي عيادة أسنان و٣ أطباء", {"businessType": "clinic", "specialty": "dentistry", "doctors": 3}),
        ("عندنا طبيبين وفرعين", {"doctors": 2, "branches": 2}),
        ("عندي محل ملابس اونلاين", {"businessType": "commerce"}),
        ("عدنا ثلاث دكاترة", {"doctors": 3}),
    ],
)
def test_extracts_iraqi_arabic_business_facts(text, facts):
    assert extract(text).facts == facts


def test_extracts_contacts_discount_and_intents():
    e = extract("رقمي 07701234567 والايميل Dr.Ahmed@clinic.iq وكم سعر الباقات؟ ممكن خصم ٣٠٪")
    assert e.phones == ["+9647701234567"] and e.emails == ["dr.ahmed@clinic.iq"] and e.discount_percent == 30
    assert {"pricing", "discount_request"} <= set(e.intents)
    assert "human_request" in extract("اريد احجي ويا موظف").intents
    assert "account_creation" in extract("سوولي حساب تجريبي").intents
    assert "training_request" in extract("شلون اضيف طبيب؟").intents


def test_normalization_and_grounding():
    assert normalize("إضافة  أطبّاء ٣") == "اضافه اطباء 3"
    assert number_grounded(3, "عدنا ثلاث اطباء") and number_grounded(2, "وفرعين")
    assert not number_grounded(5, "عدنا ثلاث اطباء")


def test_language_detection():
    assert detect_language("We need a quote") == "en"
    assert detect_language("شلون اسجل؟") == "ar-iq"
    assert detect_language("أرغب بمعرفة الأسعار") == "ar"
    assert detect_language("ايميلي a@clinic.iq") == "ar"
    assert detect_language("اريد نظام https://example.company") == "ar-iq"


PLANS = [KnowledgeItem("plan:basic", "pricing", "باقة الأساسية", "باقة الأساسية: 25,000 د.ع شهرياً", "t")]


def _plan(reply, intents=("greeting",), cited=(), facts=(), actions=()):
    return Plan(intents=[{"name": n, "confidence": 0.9} for n in intents], facts=[dict(f) for f in facts],
                actions=list(actions), reply_text=reply, language="ar-iq", needs_human=False, handoff_reason=None,
                cited=list(cited), source="model", model="m")


def _verify(plan, text="مرحبا", knowledge=PLANS):
    return verify_plan(plan, customer_text=text, extraction=extract(text), knowledge=knowledge,
                       plan_prices={25000, 250000}, plan_keys={"basic"})


def test_telegram_bot_token_cannot_be_echoed_in_a_customer_reply():
    token = "12345678:AbCdeFgHijKlmNopQrsTuvWxyZ_0123456789"
    plan = _verify(_plan(f"رمز البوت: {token}"))
    assert token not in plan.reply_text
    assert "reply: secret-like content blocked" in plan.guard_notes
    assert plan.needs_human


def test_guard_rejects_invented_price_but_keeps_real_one():
    assert _verify(_plan("السعر 30,000 د.ع", ("pricing",), ("plan:basic",))).needs_human
    ok = _verify(_plan("السعر 25,000 د.ع", ("pricing",), ("plan:basic",)))
    assert not ok.needs_human and "25,000" in ok.reply_text


def test_guard_requires_citation_for_factual_answers_and_drops_fake_citations():
    p = _verify(_plan("نعم يدعم الربط مع البنوك", ("feature_question",), ("doc:invented",)))
    assert p.needs_human and p.cited == []


def test_guard_blocks_claims_of_unexecuted_actions_and_links():
    assert _verify(_plan("تم إنشاء حسابك ✓")).needs_human
    assert "http" not in _verify(_plan("سجل من https://evil.example/login")).reply_text


def test_guard_caps_ungrounded_numbers_and_unknown_plans():
    p = _verify(_plan("تمام", facts=[{"key": "doctors", "value": "9", "confidence": 0.95, "evidence": "x"}],
                      actions=[{"type": "recommend_plan", "reason": "r", "plan_key": "gold", "discount_percent": None}]),
                text="عدنا 3 اطباء")
    assert p.facts[0]["confidence"] <= 0.4 and p.actions == []


def test_rules_planner_asks_one_missing_question_and_never_known_ones():
    e = extract("عندي عيادة اسنان")
    p = plan_with_rules(extraction=e, text="عندي عيادة اسنان", facts={}, knowledge=[], plan_keys=set())
    assert p.reply_text.count("؟") == 1 and "كم طبيب" in p.reply_text
    p2 = plan_with_rules(extraction=extract("تمام"), text="تمام",
                         facts={"businessType": {"value": "clinic"}, "specialty": {"value": "dentistry"},
                                "doctors": {"value": 3}}, knowledge=[], plan_keys=set())
    assert "كم طبيب" not in p2.reply_text and "موظف" in p2.reply_text


def test_rules_planner_hands_off_complaints():
    p = plan_with_rules(extraction=extract("عندي شكوى"), text="عندي شكوى", facts={}, knowledge=[], plan_keys=set())
    assert p.needs_human and p.actions[0]["type"] == "handoff_human"


def test_knowledge_retrieval_ranks_relevant_items():
    items = PLANS + [KnowledgeItem("howto:doctor.create", "tutorials", "إضافة طبيب",
                                   "إضافة الطبيب تتم من صفحة الأطباء [اضيف طبيب، طبيب جديد]", "tutor")]
    assert retrieve(items, "شلون اضيف طبيب؟")[0].id == "howto:doctor.create"
    assert retrieve(items, "شلون اضيف طبيب؟", categories={"pricing"}) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("عندي عيادة نسائية", ("businessType", "clinic", "specialty", "gynecology")),
        ("عندي محل مواد غذائية", ("businessType", "food_wholesale_retail", None, None)),
    ],
)
def test_patterns_match_normalized_text(text, expected):
    facts = extract(text).facts
    assert facts.get(expected[0]) == expected[1]
    if expected[2]:
        assert facts.get(expected[2]) == expected[3]
    assert "complaint" in extract("عندي شكوى على الخدمة").intents
    assert "training_request" in extract("وين ألقى التقارير؟").intents


def test_every_pattern_is_written_in_normalized_form():
    import re as _re

    from modules.finora_core.brain import extract as ex

    sources = [p for p, *_ in ex._BUSINESS] + [p for _, p in ex._INTENT_RULES] + [n for pair in ex._COUNT_NOUNS.values() for n in pair]
    for pattern in sources:
        assert not _re.search(r"[ىةأإآؤئ]", pattern), pattern
