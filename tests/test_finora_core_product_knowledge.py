"""Product awareness, grounded education and vertical isolation; no real providers or tenant data."""
from pathlib import Path

import pytest

from modules.finora_core.brain.extract import extract
from modules.finora_core.brain.knowledge import KnowledgeItem, retrieve, retrieval_query
from modules.finora_core.brain.planner import Plan, build_user_payload, plan_with_rules, verify_plan
from modules.finora_core.brain.product_knowledge import catalog_items, coverage, guide_definitions, guide_items
from utils.tenant_feature_flags import TENANT_FEATURE_GROUPS


def test_every_registered_feature_has_a_catalog_entry():
    expected = {f"feature:{key}" for group in TENANT_FEATURE_GROUPS for key, _ in group["features"]}
    items = catalog_items()
    assert {i.id for i in items} == expected
    assert coverage(items)["featureCount"] == len(expected)
    disabled = next(i for i in items if i.id == "feature:trade_in_sales")
    assert "معطلة افتراضياً" in disabled.text
    assert all("لا يعني أنها مفعلة" in i.text for i in items)


def test_guides_reference_existing_sources_and_registered_features():
    root = Path(__file__).resolve().parents[1]
    keys = {key for group in TENANT_FEATURE_GROUPS for key, _ in group["features"]}
    ids = set()
    for guide in guide_definitions():
        assert guide["id"] not in ids
        ids.add(guide["id"])
        assert set(guide["features"]) <= keys
        assert 2 <= len(guide["steps"]) <= 4
        assert guide["sources"] and all((root / p).is_file() for p in guide["sources"])


@pytest.mark.parametrize(("text", "expected"), [
    ("شلون اضيف منتج للمخزون؟", "guide:inventory.add"),
    ("شلون اسجل مصروف؟", "guide:expenses.add"),
    ("شلون اتابع حالة الطلب؟", "guide:orders.track"),
    ("شلون اغير قالب الفاتورة؟", "guide:settings.invoice"),
    ("شلون اضيف منتج اقساط؟", "guide:installments.product"),
    ("شلون اسجل حضور وانصراف؟", "guide:hr.attendance"),
    ("شلون اراجع مسير الرواتب؟", "guide:hr.payroll"),
    ("شلون اغير سعر الصرف بالجملة؟", "guide:wholesale.settings"),
    ("شلون اسوي بيع بكاشير المواد الغذائية؟", "guide:food.cashier"),
])
def test_retrieval_finds_the_task_instead_of_common_instruction_words(text, expected):
    items = guide_items() + catalog_items()
    assert retrieve(items, text)[0].id == expected
    assert "training_request" in extract(text).intents


def test_unknown_topic_does_not_match_generic_teaching_words():
    assert retrieve(guide_items() + catalog_items(), "شلون استخدم جهاز ليزر فضائي؟") == []


def test_vertical_and_starter_scope_is_filtered_before_retrieval():
    general = guide_items(business_type="general") + catalog_items(business_type="general")
    assert not any(i.business_type for i in general)
    assert not any(i.id.startswith("feature:dental.") for i in general)
    assert any(i.id == "feature:dental.chart.view" for i in catalog_items(business_type="clinics"))
    assert retrieve(general, "شلون اسجل حضور وانصراف HR؟") == []
    clinic = guide_items(business_type="clinics")
    assert not any(i.id == "guide:pos.sell" for i in clinic)
    starter = catalog_items(business_type="starter_business")
    assert not any(i.id == "feature:ai_sales" for i in starter)


def test_catalog_alone_cannot_justify_model_teaching_steps():
    item = catalog_items()[0]
    plan = Plan(intents=[{"name": "training_request", "confidence": 0.9}], facts=[], actions=[],
                reply_text="اضغط زر التخمين ثم احفظ", language="ar-iq", needs_human=False, handoff_reason=None,
                cited=[item.id], source="model", model="test")
    checked = verify_plan(plan, customer_text="شلون استخدم لوحة القيادة؟", extraction=extract("شلون استخدم لوحة القيادة؟"),
                          knowledge=[item], plan_prices=set(), plan_keys=set())
    assert checked.needs_human


def test_rules_teach_a_grounded_task_without_an_unrelated_sales_question():
    text = "شلون اضيف منتج للمخزون؟"
    items = retrieve(guide_items(), text)
    plan = plan_with_rules(extraction=extract(text), text=text, facts={}, knowledge=items, plan_keys=set())
    assert "إضافة منتج" in plan.reply_text and "1." in plan.reply_text
    assert "نوع نشاط" not in plan.reply_text
    assert not plan.needs_human and plan.cited == ["guide:inventory.add"]


def test_followup_retains_customer_lesson_but_a_new_topic_replaces_it():
    recent = [{"role": "customer", "text": "شلون اضيف منتج؟"},
              {"role": "finora", "text": "افتح المخزون"}, {"role": "customer", "text": "تمام شنو بعدها؟"}]
    assert "اضيف منتج" in retrieval_query("تمام شنو بعدها؟", recent)
    assert retrieval_query("تمام شلون اسجل مصروف؟", recent) == "تمام شلون اسجل مصروف؟"
    assert retrieval_query("رقمي 07701234567", recent) == "رقمي 07701234567"
    assert retrieval_query("كمل", []) == "كمل"


def test_model_payload_keeps_steps_and_scope():
    import json

    item = guide_items(business_type="hr_management")[-3]
    payload = json.loads(build_user_payload(recent=[], facts={}, lead_stage="new", knowledge=[item], policy={}))
    assert payload["KNOWLEDGE"][0]["text"] == item.text
    assert "business_type" in payload["KNOWLEDGE"][0]


def test_missing_feature_support_uses_access_guide_instead_of_sales_questions():
    text = "ليش ما تظهر الميزة؟"
    items = retrieve(guide_items(), text)
    plan = plan_with_rules(extraction=extract(text), text=text, facts={}, knowledge=items, plan_keys=set())
    assert not plan.needs_human
    assert plan.cited == ["guide:access.missing"]
    assert "صلاحية" in plan.reply_text and "نوع نشاطكم" not in plan.reply_text


def test_uncovered_technical_support_cannot_guess_a_fix():
    text = "خطأ بجهاز ليزر فضائي"
    plan = plan_with_rules(extraction=extract(text), text=text, facts={}, knowledge=[], plan_keys=set())
    assert plan.needs_human


@pytest.mark.parametrize(("question", "expected"), [
    ("الزبون عليه فلوس وين اشوفها؟", "guide:customers.credit"),
    ("الكميات مو مطابقة", "guide:inventory.ledger"),
    ("شلون ادخل بضاعة بالمخزن؟", "guide:inventory.add"),
    ("اريد اشوف ديون الموردين", "guide:suppliers.review"),
    ("شلون اغير لوكو الفاتورة؟", "guide:settings.invoice"),
    ("القائمة مختفية", "guide:access.missing"),
    ("القسط متأخر", "guide:installments.follow"),
    ("مصاريف المحل", "guide:expenses.add"),
    ("الموظف يشوف بس الطلبات", "guide:permissions.manage"),
    ("الزبون سدد", "guide:receipts.record"),
])
def test_customer_dialect_retrieves_the_reviewed_task(question, expected):
    assert retrieve(guide_items() + catalog_items(), question)[0].id == expected


def test_activity_knowledge_uses_only_registered_templates_and_matching_scope():
    from modules.finora_core.brain.product_knowledge import activity_items
    from modules.finora_core.brain.tenant_setup import PROFILES

    items = activity_items()
    assert {i.id for i in items} == {f"activity:{key}" for key in PROFILES}
    assert all(PROFILES[i.id.split(":")[1]]["needs"] in i.text for i in items)
    assert {i.id for i in activity_items(business_type="clinics")} == {"activity:clinic", "activity:dental_clinic"}
    assert retrieve(items, "قالب محل ورد وهدايا")[0].id == "activity:flowers"
    assert all("باقته وصلاحياته" in i.text for i in items)


@pytest.mark.parametrize("followup", ["ما لقيت الزر", "شلون اعدلها؟", "وضحلي اكثر", "واذا ما ظهر؟"])
def test_implicit_lesson_followup_uses_customer_topic_not_assistant_claims(followup):
    recent = [{"role": "customer", "text": "شلون اضيف منتج للمخزون؟"},
              {"role": "finora", "text": "معلومات غير موثقة عن دمج مصرف"},
              {"role": "customer", "text": "تمام"}]
    query = retrieval_query(followup, recent)
    assert "اضيف منتج" in query and "مصرف" not in query
    recent.append({"role": "customer", "text": "شكد سعر الاشتراك؟"})
    assert retrieval_query(followup, recent) == followup


def test_current_request_and_sources_survive_history_excerpting():
    import json

    current = "اريد شرح " + "المخزون " * 100 + "وشلون احفظ المنتج؟"
    item = guide_items()[0]
    payload = json.loads(build_user_payload(recent=[{"role": "customer", "text": "ملخص الرسالة"}],
                         facts={}, lead_stage="new", knowledge=[item], policy={}, current_text=current))
    assert payload["CURRENT_CUSTOMER_MESSAGE"] == current
    assert payload["KNOWLEDGE"][0]["source"] == item.source
