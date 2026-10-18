import copy
import json
from types import SimpleNamespace

import pytest
import jsonschema

from tests.finora_core_support import env  # noqa: F401
from tests.test_finora_core_brain import brain, core, FakeProvider, model_plan, say, conv_id_for  # noqa: F401
from tests.test_finora_core_telegram import telegram  # noqa: F401
from tests.test_finora_core_projects import approved_offer, profile, price_issues, pending, brief
from modules.finora_core.brain import understanding
from modules.finora_core.brain.provider import OpenAIProvider, HybridProvider, OllamaProvider, ProviderError, with_timeout


class DeliberatingProvider(FakeProvider):
    supports_understanding = True


def interpretation(value, *, intent="question", topic="finora", confidence=.95):
    return {"goal": "فهم طلب العميل والجواب المناسب", "intent": intent, "topic": topic, "evidence": value,
            "confidence": confidence, "complexity": "complex", "questions": [value],
            "searchQueries": ["ديون الزبائن تسجيل دفعة متابعة حساب"], "missingInformation": [],
            "replyOutline": ["اشرح النقطة الحالية من المعلومات الموثقة"], "requiresReview": intent == "negotiation",
            "needsProjectExplanation": topic == "custom_project" and intent == "question", "asksCommercialTerms": False,
            "requestParts": []}


def analyze(provider, value, **kwargs):
    return understanding.analyze(provider, value=value, recent=kwargs.pop("recent", []), facts=kwargs.pop("facts", {}), **kwargs)


def test_interpretation_uses_current_context_and_hides_private_estimate_and_contacts():
    value = "مو على كدي هالمبلغ"
    provider = DeliberatingProvider(interpretation(value, intent="negotiation", topic="custom_project"))
    project = {"brief": brief(), "phase": "quote_sent", "evidence": [], "quoteHash": "approved"}
    result, usage = analyze(provider, value, project=project, facts={"phone": {"value": "+9647712345678"}},
                            recent=[{"role": "finora", "text": "توافق على هذا العرض؟"}])
    payload = json.loads(provider.calls[0]["user"])
    assert payload["CURRENT_MESSAGE"] == value and payload["RECENT_DIALOGUE"][0]["role"] == "finora"
    assert payload["CURRENT_PROJECT"]["hasApprovedOffer"]
    assert "estimate" not in json.dumps(payload) and "+9647712345678" not in json.dumps(payload)
    assert understanding.trusted_intent(result, "negotiation", "custom_project") and usage.model == "fake-model"


@pytest.mark.parametrize("evidence", ["", "العميل وافق على العرض", "خصم طلبه قبل يوم"])
def test_old_or_invented_evidence_cannot_drive_semantic_routing(evidence):
    value = "اشرحلي صفحة الحجز"
    data = interpretation(value); data["evidence"] = evidence
    with pytest.raises((ProviderError, jsonschema.ValidationError)):
        analyze(DeliberatingProvider(data), value, recent=[{"role": "customer", "text": evidence}])


def test_low_confidence_and_unsupported_provider_keep_original_guards():
    value = "ها وهاي"
    data, _ = analyze(DeliberatingProvider(interpretation(value, intent="scope_change", topic="custom_project", confidence=.6)), value)
    assert not understanding.trusted_intent(data, "scope_change")
    provider = FakeProvider({})
    assert analyze(provider, value) == (None, None) and provider.calls == []


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\t", "\x00", "\x7f"])
def test_multiline_message_keeps_full_context_with_printable_exact_evidence(separator):
    value = separator.join(["مثلا من داخل تفاصيل المنتج", "نكدر نختار الحجم مال شاشه", "32 43 50 وهكذا ومن نختار حجم تطلع الفيديو وصور والسعرالخاصه بي"])
    evidence = "نكدر نختار الحجم مال شاشه"
    data = interpretation(evidence, topic="custom_project")
    class StrictEvidenceProvider(DeliberatingProvider):
        def generate_structured(self, **kwargs):
            self.submitted_schema = kwargs['schema']
            return super().generate_structured(**kwargs)
    provider = StrictEvidenceProvider(data)
    result, _ = analyze(provider, value)
    assert json.loads(provider.calls[0]['user'])['CURRENT_MESSAGE'] == value
    candidates = provider.submitted_schema['properties']['evidence']['enum']
    assert candidates and all(part in value for part in candidates)
    assert all(not any(ord(char) < 32 or ord(char) == 127 for char in part) for part in candidates)
    assert result['evidence'] == evidence and not result['asksCommercialTerms']


def test_dependent_subrequests_are_grounded_and_forwarded_without_paraphrasing():
    value = 'بصفحة الدرس ضيف حفظ مكان المشاهدة، وبعد كل الدروس يفتح الاختبار، النجاح 70%، عدل المشاهدة إلى 90% بدل 80%'
    parts = ['بصفحة الدرس ضيف حفظ مكان المشاهدة', 'وبعد كل الدروس يفتح الاختبار', 'النجاح 70%', 'عدل المشاهدة إلى 90% بدل 80%']
    data = interpretation(value, intent='scope_change', topic='custom_project');data['requestParts'] = parts
    provider = DeliberatingProvider(data)
    result, _ = analyze(provider, value)
    assert result['requestParts'] == parts
    assert json.loads(provider.calls[0]['user'])['CURRENT_MESSAGE'] == value


def test_a_subrequest_from_another_turn_cannot_enter_current_analysis():
    value = 'عدل شرط المشاهدة إلى 90%'
    data = interpretation(value, intent='scope_change', topic='custom_project')
    data['requestParts'] = ['غير النجاح بالاختبار إلى 90%']
    with pytest.raises((ProviderError, jsonschema.ValidationError)):
        analyze(DeliberatingProvider(data), value)


@pytest.mark.parametrize('long_request,expected', [(False,25),(True,35)])
def test_complex_literal_subrequests_receive_a_bounded_extra_analysis_budget(monkeypatch,long_request,expected):
    value='ضيف اختيار لون' if not long_request else '، '.join(['ضيف اختيار اللون مع صور خاصة باللون والمقاسات المتوفرة والمخزون المرتبط']*4)
    budgets=[]
    monkeypatch.setattr(understanding,'with_timeout',lambda provider,timeout: budgets.append(timeout) or provider)
    data=interpretation(value);data['questions']=[]
    analyze(DeliberatingProvider(data),value)
    assert budgets==[expected]


def test_secret_like_interpretation_is_rejected():
    data = interpretation("شنو احتاج؟"); data["goal"] = "sk-proj-not-a-real-secret-1234567890"
    with pytest.raises(ProviderError, match="secret-like"):
        analyze(DeliberatingProvider(data), "شنو احتاج؟")


@pytest.mark.parametrize("schema_name,effort", [("finora_message_understanding", "high"), ("finora_project_consultation", "medium"), ("finora_project_scope", "low"), ("finora_project_workflows", "low"), ("finora_project_repair", "low"), ("finora_project_advice", "high"), ("finora_core_plan", "medium")])
def test_reasoning_model_uses_documented_effort_without_retention(monkeypatch, schema_name, effort):
    from modules.ai_sales import openai_service
    calls = []
    monkeypatch.setattr(openai_service, "create_response", lambda **kwargs: calls.append(kwargs) or SimpleNamespace(output_text='{}'))
    OpenAIProvider("gpt-5.4-mini", api_key="test-only").generate_structured(system="system", user="request", schema={}, schema_name=schema_name)
    assert calls[0]["reasoning"] == {"effort": effort} and calls[0]["store"] is False
    assert calls[0]["max_retries"] == 0


def test_nonreasoning_cloud_models_and_hybrid_timeout_remain_compatible(monkeypatch):
    from modules.ai_sales import openai_service
    calls = []
    monkeypatch.setattr(openai_service, "create_response", lambda **kwargs: calls.append(kwargs) or SimpleNamespace(output_text='{}'))
    OpenAIProvider("gpt-4o-mini", api_key="test-only").generate_structured(system="system", user="request", schema={}, schema_name="finora_message_understanding")
    assert "reasoning" not in calls[0]
    provider = with_timeout(HybridProvider(OllamaProvider("http://127.0.0.1:11434", "local-model"), OpenAIProvider("gpt-5.4-mini")), 20)
    assert provider.supports_understanding and provider.cloud.supports_understanding and provider.local.timeout <= 8


def test_targeted_graph_repair_receives_reasoning_without_exposing_retained_responses(monkeypatch):
    from modules.ai_sales import openai_service
    calls = []
    monkeypatch.setattr(openai_service, "create_response", lambda **kwargs: calls.append(kwargs) or SimpleNamespace(output_text='{}'))
    OpenAIProvider("gpt-5.4-mini", api_key="test-only").generate_structured(system="system", user="request", schema={"properties": {"workflows": {}}}, schema_name="finora_project_repair")
    assert calls[0]["reasoning"] == {"effort": "medium"} and calls[0]["store"] is False


def test_analysis_precedes_retrieval_and_answer_in_actual_worker(brain):
    value = "شلون أسجل المبلغ الباقي على الزبون وأتابع دفعاته؟"
    provider = DeliberatingProvider(interpretation(value), model_plan("تتابع رصيد الزبون ودفعاته من صفحة الزبائن.",
                                      intents=(("training_request", .95),), cited=("guide:customers.credit",)))
    brain["state"]["provider"] = provider
    answer = say(brain, value)
    assert "الزبائن" in answer and len(provider.calls) == 2
    payload = json.loads(provider.calls[1]["user"])
    assert payload["MESSAGE_UNDERSTANDING"]["questions"] == [value]
    assert any(k["id"] == "guide:customers.credit" for k in payload["KNOWLEDGE"])
    from modules.finora_core.brain.models import FcAgentRun
    run = core(brain, lambda s: s.query(FcAgentRun).filter_by(conversation_ref=str(conv_id_for(brain))).one())
    trace = json.loads(run.trace_json)
    assert trace["understanding"]["status"] == "ready" and trace["understanding"]["inputCount"] == 120
    assert run.input_tokens == 240 and run.output_tokens == 80
    assert run.cost_usd is None  # Unknown model prices are never invented.
    assert not trace["proposedActions"]


def test_analysis_failure_keeps_customer_request_and_safe_planning(brain):
    value = "مرحبا"
    provider = DeliberatingProvider(ProviderError("rate_limited", "unavailable"), model_plan("هلا بيك، شنو تحتاج؟"))
    brain["state"]["provider"] = provider
    assert "هلا" in say(brain, value)
    assert json.loads(provider.calls[1]["user"])["CURRENT_CUSTOMER_MESSAGE"] == value
    from modules.finora_core.brain.models import FcAgentRun
    run = core(brain, lambda s: s.query(FcAgentRun).one())
    assert json.loads(run.trace_json)["understanding"] == {"status": "unavailable", "code": "rate_limited"}


def test_indirect_budget_statement_raises_review_without_changing_offer(telegram):
    from tests.test_finora_core_telegram import say as telegram_say
    approved_offer(telegram)
    before = profile(telegram)["project"]
    value = "هالمبلغ مو على كدي، نكدر نتفاهم عليها؟"
    provider = DeliberatingProvider(interpretation(value, intent="negotiation", topic="custom_project"))
    telegram["state"]["provider"] = provider
    reply = telegram_say(telegram, value)
    assert "رفعت طلب التخفيض" in reply and len(provider.calls) == 1
    assert profile(telegram)["project"] == before and pending(telegram) == []
    assert value in price_issues(telegram)[0]["details"]


def test_feasibility_question_with_change_words_does_not_rebuild_plan(monkeypatch):
    from modules.finora_core.brain import project_consultation as project
    draft = {"brief": brief(), "revision": 1, "phase": "quote_sent", "evidence": [], "quoteHash": "quote"}
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: copy.deepcopy(draft))
    value = "إذا أغير طريقة الدفع شنو يصير على الطلبات؟"
    provider = FakeProvider({"answer": "نناقش تأثير اختيار الدفع على تأكيد الطلب قبل ما نغير الخطة.", "questions": []})
    reply = project.consult(None, None, "1", value, provider=provider, message_id="new-question",
                            understanding=interpretation(value, topic="custom_project"))
    assert "نناقش" in reply["reply"] and reply["action"] is None
    assert json.loads(provider.calls[0]["user"])["MESSAGE_UNDERSTANDING"]["questions"] == [value]


def test_product_question_during_project_uses_product_knowledge_path(monkeypatch):
    from modules.finora_core.brain import project_consultation as project
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: {"brief": brief(), "phase": "quote_sent"})
    assert project.consult(None, None, "1", "شلون أضيف زبون بفينورا؟", provider=None, message_id="product-question",
                           understanding=interpretation("شلون أضيف زبون بفينورا؟")) is None


def test_model_confirmation_after_aside_never_approves_quote(monkeypatch):
    from modules.finora_core.brain import project_consultation as project
    draft = {"brief": brief(), "revision": 1, "phase": "quote_sent", "evidence": [], "quoteHash": "quote"}
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: copy.deepcopy(draft))
    reply = project.consult(None, None, "1", "اي", provider=None, message_id="yes-to-page",
                            recent=[{"role": "finora", "text": "تحب نوضح صفحات الحجز؟"}],
                            understanding=interpretation("اي", intent="confirmation", topic="custom_project"))
    assert reply["action"] is None and "أي صفحة" in reply["reply"]


def test_semantic_price_reminder_uses_approved_terms_without_repricing(monkeypatch):
    from modules.finora_core.brain import project_consultation as project
    draft = {"brief": brief(), "revision": 1, "phase": "quote_sent", "evidence": [], "quoteHash": "quote",
             "terms": {"amount": 650000, "currency": "IQD", "days": 30, "mvpDays": 15}}
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: copy.deepcopy(draft))
    value = "شكد المبلغ كتلي"
    data = interpretation(value, topic="custom_project")
    data.update(asksCommercialTerms=True, needsProjectExplanation=False)
    reply = project.consult(None, None, "1", value, provider=None, message_id="price-reminder", understanding=data)
    assert "650,000" in reply["reply"] and reply["action"] is None
    assert len(reply["reply"]) < 350 and "توافق" not in reply["reply"]
    assert draft["terms"]["amount"] == 650000


def test_combined_price_and_feature_question_answers_both_without_repricing(monkeypatch):
    from modules.finora_core.brain import project_consultation as project
    draft = {"brief": brief(), "revision": 1, "phase": "quote_sent", "evidence": [], "quoteHash": "quote",
             "terms": {"amount": 1000000, "currency": "IQD", "days": 30, "mvpDays": 10}}
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: copy.deepcopy(draft))
    value = "شنو السعر وشنو صلاحيات مالك الملعب؟"
    data = interpretation(value, topic="custom_project"); data["questions"] = ["شنو السعر؟", "شنو صلاحيات مالك الملعب؟"]
    data['asksCommercialTerms'] = True
    provider = FakeProvider({"answer": "المالك يدير ملاعبه وحجوزاتها فقط، بدون الوصول لملاعب غيره.", "questions": []})
    reply = project.consult(None, None, "1", value, provider=provider, message_id="two-points", understanding=data)
    assert "1,000,000" in reply["reply"] and "بدون الوصول" in reply["reply"]
    assert json.loads(provider.calls[0]["user"])["SERVER_REPLY"].startswith("عرض فينورا المعتمد")
    assert reply["action"] is None


def test_product_price_question_does_not_send_development_quote(monkeypatch):
    from modules.finora_core.brain import project_consultation as project
    draft = {"brief": brief(), "revision": 1, "phase": "quote_sent", "evidence": [], "quoteHash": "quote",
             "terms": {"amount": 650000, "currency": "IQD", "days": 30, "mvpDays": 15}}
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: copy.deepcopy(draft))
    value = "شلون يتحسب السعر بالسلة؟"
    provider = FakeProvider({'answer': 'السلة تجمع أسعار المنتجات والكميات مع رسوم التوصيل المتفق عليها.', 'questions': []})
    reply = project.consult(None, None, '1', value, provider=provider, message_id='cart-price',
                            understanding=interpretation(value, topic='custom_project'))
    assert '650,000' not in reply['reply'] and 'السلة تجمع' in reply['reply']
    assert reply['action'] is None


def test_unapproved_commercial_terms_still_wait_for_owner(monkeypatch):
    from modules.finora_core.brain import project_consultation as project
    draft = {"brief": brief(), "revision": 1, "phase": "internal_review", "evidence": [], "quoteHash": None, 'terms': None}
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: copy.deepcopy(draft))
    value = 'شكد المبلغ كتلي'
    data = interpretation(value, topic='custom_project')
    data.update(asksCommercialTerms=True, needsProjectExplanation=False)
    reply = project.consult(None, None, '1', value, provider=None, message_id='not-approved', understanding=data)
    assert 'يعتمد العرض' in reply['reply'] and reply['action'] is None
