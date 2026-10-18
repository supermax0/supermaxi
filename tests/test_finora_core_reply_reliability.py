import copy
import json
import time
from dataclasses import replace

import pytest

from tests.finora_core_support import env, PAGE_ID, meta_error, unique_mid  # noqa: F401
from tests.test_finora_core_brain import brain, core, say, customer_of, FakeProvider, model_plan  # noqa: F401
from tests.test_finora_core_telegram import telegram  # noqa: F401
from tests.test_finora_core_understanding import DeliberatingProvider, interpretation
from modules.finora_core.brain.provider import RequestProvider, ProviderError, HybridProvider, StructuredResult, with_timeout
from modules.finora_core.brain.reply_review import review


def test_idempotency_comparison_ignores_object_order_but_not_changed_inputs():
    from modules.finora_core.brain.tools import _same_input
    assert _same_input('{"a": 1, "b": 2}', '{"b": 2, "a": 1}')
    assert not _same_input('{"a": 1}', '{"a": 2}')


@pytest.mark.parametrize("code", sorted(RequestProvider.STOP_CODES))
def test_permanent_failure_stops_calls_across_timeouts_but_not_the_next_request(code):
    original = FakeProvider(ProviderError(code, "test-only"), {"ok": True})
    provider = RequestProvider(original)
    kwargs = dict(system="s", user="u", schema={}, schema_name="test")
    with pytest.raises(ProviderError):
        with_timeout(provider, 10).generate_structured(**kwargs)
    with pytest.raises(ProviderError):
        with_timeout(provider, 35).generate_structured(**kwargs)
    assert len(original.calls) == 1
    assert RequestProvider(original).generate_structured(**kwargs).data == {"ok": True}


def test_transient_failure_can_recover_without_a_persistent_error():
    provider = RequestProvider(FakeProvider(ProviderError("timeout", "temporary"), {"ok": True}))
    kwargs = dict(system="s", user="u", schema={}, schema_name="test")
    with pytest.raises(ProviderError):
        provider.generate_structured(**kwargs)
    provider.generate_structured(**kwargs)
    assert provider.state == {}


def test_hybrid_cloud_review_keeps_same_request_latch_and_avoids_a_second_local_probe():
    local = FakeProvider(ProviderError("local_unreachable", "offline"))
    cloud = FakeProvider({"answer": "first"}, ProviderError("insufficient_quota", "blocked"))
    provider = RequestProvider(HybridProvider(local, cloud))
    kwargs = dict(system="s", user="u", schema={}, schema_name="test")
    result = provider.generate_structured(**kwargs)
    result.provider = "cloud"
    with pytest.raises(ProviderError):
        provider.for_review(result).generate_structured(**kwargs)
    with pytest.raises(ProviderError):
        provider.generate_structured(**kwargs)
    assert len(local.calls) == 1 and len(cloud.calls) == 2


def test_wrapped_hybrid_staged_plan_does_not_probe_the_unavailable_local_model_at_every_stage():
    from modules.finora_core.brain import project_consultation as project
    from tests.test_finora_core_consultation_routing import brief, REQUEST
    data = brief()
    fields = {"title", "kind", "goal", "audience", "platforms", "requirements", "suggestions", "questions", "ready"}
    discovery = {k: v for k, v in data.items() if k in fields}
    scope = {k: v for k, v in data.items() if k not in fields and k != "workflows"}
    class Cloud(FakeProvider):
        def generate_structured(self, **kwargs):
            result = super().generate_structured(**kwargs)
            result.provider = "cloud"
            return result
    local = FakeProvider(ProviderError("local_unreachable", "offline"))
    cloud = Cloud(discovery, scope, {"workflows": data["workflows"]})
    provider = RequestProvider(HybridProvider(local, cloud))
    result = project.generate_staged_brief(provider, {"CURRENT_CUSTOMER_MESSAGE": REQUEST,
                                          "CUSTOMER_MESSAGES": [{"id": "1", "text": REQUEST}]},
                                          project.BRIEF_SCHEMA, time.monotonic() + 150)
    assert result.data["ready"] and len(local.calls) == 1 and len(cloud.calls) == 3


def test_review_removes_duplicate_questions_but_preserves_rules_on_different_pages():
    result = review("صفحة الدرس\nالمشاهدة 90%\n\nصفحة الاختبار\nالنجاح 70%\nالمشاهدة 90%\nشنو اللون؟\n\nشنو اللون؟",
                    current="عدل المشاهدة بس", recent=[])
    assert result.text.count("شنو اللون؟") == 1
    assert result.text.count("المشاهدة 90%") == 2 and "النجاح 70%" in result.text
    assert not result.needs_review


def test_repeated_answer_to_a_new_request_is_not_delivered_as_if_it_answered_it():
    recent = [{"role": "customer", "text": "شكد السعر؟"}, {"role": "finora", "text": "السعر ينتظر مراجعة."},
              {"role": "customer", "text": "ضيف اختيار حجم الشاشه"}]
    result = review("السعر ينتظر مراجعة.", current="ضيف اختيار حجم الشاشه", recent=recent, generated=True)
    assert result.needs_review and "repeated_answer_to_new_request" in result.issues
    assert result.text != "السعر ينتظر مراجعة."
    assert not review("السعر ينتظر مراجعة.", current="شكد السعر؟", recent=recent, generated=True).needs_review
    assert not review("السعر ينتظر مراجعة.", current="ذكرني بالسعر", recent=recent, generated=True, allow_repeat=True).needs_review


def test_runtime_repetition_creates_a_customer_scoped_review_request(brain):
    from modules.finora_core.brain.support import FcSupportIssue
    brain["state"]["provider"] = FakeProvider(model_plan("أني وياك، شنو النقطة؟"))
    assert say(brain, "مرحبا") == "أني وياك، شنو النقطة؟"
    reply = say(brain, "جاهز؟")
    assert "جواب دقيق" in reply
    customer = core(brain, customer_of(brain))
    issue = core(brain, lambda s: s.query(FcSupportIssue).filter_by(kind="reply_quality").one())
    assert issue.customer_id == customer["id"]


def test_runtime_quota_failure_notifies_owner_and_does_not_call_each_stage(brain):
    from modules.finora_core.brain.support import FcSupportIssue
    provider = DeliberatingProvider(ProviderError("insufficient_quota", "test-only"))
    brain["state"]["provider"] = provider
    assert say(brain, "مرحبا")
    assert len(provider.calls) == 1
    issue = core(brain, lambda s: s.query(FcSupportIssue).filter_by(kind="provider_error").one())
    assert "الرصيد" in issue.details and "insufficient_quota" in issue.details
    assert say(brain, "مرحبا مرة ثانية")
    assert len(provider.calls) == 2
    assert core(brain, lambda s: s.query(FcSupportIssue).filter_by(kind="provider_error").count()) == 1


@pytest.mark.parametrize("status,code,expected", [(400, 100, "delivery_failed"), (429, 4, "retry_scheduled")])
def test_runtime_does_not_mark_failed_or_pending_delivery_completed(brain, status, code, expected):
    from modules.finora_core.brain.models import FcAgentRun
    brain["graph"].queue[("POST", f"{PAGE_ID}/messages")] = [meta_error(status, code)]
    assert say(brain, "مرحبا")
    run = core(brain, lambda s: s.query(FcAgentRun).order_by(FcAgentRun.id.desc()).first())
    assert run.status == expected
    assert json.loads(run.trace_json)["reply"]["status"] in {"failed", "retry_scheduled"}


def test_multipart_reply_failure_is_not_hidden_by_the_last_successful_part(telegram, monkeypatch):
    from modules.finora_core.brain import project_consultation
    from modules.finora_core.brain.models import FcAgentRun
    from modules.finora_core import transport
    from modules.ai_sales.telegram import TelegramError
    from tests.test_finora_core_telegram import say as telegram_say
    reply = "تفاصيل الجزء الأول " * 70 + "\n\n" + "تفاصيل الجزء الثاني " * 70
    monkeypatch.setattr(project_consultation, "consult", lambda *a, **kw: {"reply": reply, "action": None,
                        "model": "project-rules", "usage": None})
    original_send = transport.send_text
    sent = []
    def send(conversation, text):
        sent.append(text)
        if len(sent) == 1:
            raise TelegramError(400)
        return original_send(conversation, text)
    monkeypatch.setattr(transport, "send_text", send)
    assert telegram_say(telegram, "اريد تطبيق مخصص")
    run = core(telegram, lambda s: s.query(FcAgentRun).order_by(FcAgentRun.id.desc()).first())
    assert run.status == "delivery_failed" and "delivery_failed" in run.outcome
    assert json.loads(run.trace_json)["reply"]["parts"][0] == "failed"
    assert json.loads(run.trace_json)["reply"]["parts"][-1] == "sent"


@pytest.mark.parametrize("failure", ["negative_result", "postcondition", "exception"])
def test_failed_core_tool_rolls_back_its_own_changes_and_keeps_failure_record(brain, monkeypatch, failure):
    from modules.finora_core.brain import tools, registry, memory
    from modules.finora_core.brain.models import FcCustomer, FcToolCall, FcMemoryFact
    say(brain, "مرحبا")
    cid = core(brain, customer_of(brain))["id"]
    def implementation(s, customer, args):
        memory.remember(s, customer.id, "recommendedPlan", "غير معتمد", confidence=1, source="tool")
        if failure == "exception":
            raise ValueError("simulated failure")
        return tools.ToolResult(failure != "negative_result", {"plan_key": "basic", "plan_name": "غير معتمد"})
    monkeypatch.setitem(tools.IMPLEMENTATIONS, "recommend_plan", implementation)
    original = registry.spec_for
    monkeypatch.setattr(registry, "spec_for", lambda name: replace(original(name), verify=lambda *a, **kw: False)
                        if name == "recommend_plan" else original(name))
    def attempt(s):
        memory.remember(s, cid, "recommendedPlan", "الخطة السابقة", confidence=1, source="tool")
        s.commit()
        with pytest.raises(tools.ToolError, match="did not report success|post-condition|rolled back"):
            from modules.finora_core.brain.models import FcAgentRun
            run = s.query(FcAgentRun).filter_by(customer_id=cid).first()
            tools.run_tool(s, "recommend_plan", {"plan_key": "basic"}, customer=s.get(FcCustomer, cid), actor="test", actor_type="ai", run_id=run.id)
        s.commit()
        assert memory.active_facts(s, cid)["recommendedPlan"]["value"] == "الخطة السابقة"
        assert s.query(FcMemoryFact).filter_by(customer_id=cid, key="recommendedPlan").count() == 1
        assert s.query(FcToolCall).filter_by(tool="recommend_plan").one().status == "failed"
    core(brain, attempt)


def test_idempotent_result_cannot_be_replayed_for_another_customer_or_a_lost_postcondition(brain, monkeypatch):
    from modules.finora_core.brain import tools, registry
    from modules.finora_core.brain.models import FcCustomer, FcAgentRun
    say(brain, "مرحبا", sender="owner"); say(brain, "مرحبا", sender="other")
    own = core(brain, customer_of(brain, "owner"))["id"]
    other = core(brain, customer_of(brain, "other"))["id"]
    def attempt(s):
        customer = s.get(FcCustomer, own)
        run = s.query(FcAgentRun).filter_by(customer_id=own).first()
        kwargs = dict(actor="test", actor_type="ai", run_id=run.id, idempotency_key="shared-key")
        result = tools.run_tool(s, "recommend_plan", {"plan_key": "basic"}, customer=customer, **kwargs)
        assert result.ok
        with pytest.raises(tools.ToolError, match="يختلف"):
            tools.run_tool(s, "recommend_plan", {"plan_key": "pro"}, customer=customer, **kwargs)
        with pytest.raises(tools.ToolError, match="عميلاً آخر|تخص العميل نفسه"):
            tools.run_tool(s, "recommend_plan", {"plan_key": "basic"}, customer=s.get(FcCustomer, other), **kwargs)
        original = registry.spec_for
        monkeypatch.setattr(registry, "spec_for", lambda name: replace(original(name), verify=lambda *a, **kw: False))
        with pytest.raises(tools.ToolError, match="لم تعد مؤكدة"):
            tools.run_tool(s, "recommend_plan", {"plan_key": "basic"}, customer=customer, **kwargs)
    core(brain, attempt)


def test_understanding_receives_all_current_page_constraints_and_roles():
    from modules.finora_core.brain.understanding import analyze
    from tests.test_finora_core_projects import brief
    value = "عدل المشاهدة إلى 90% وخلي النجاح مثل ما هو"
    draft = brief(); draft["pages"][0]["features"] += ["حفظ موضع المشاهدة", "النجاح بالاختبار 70%"]
    draft["roles"] = [{"name": "طالب", "permissions": ["شهادته فقط"]}]
    original = copy.deepcopy(draft)
    provider = DeliberatingProvider(interpretation(value, topic="custom_project"))
    analyze(provider, value=value, recent=[], facts={}, project={"brief": draft, "phase": "scope_review"})
    context = json.loads(provider.calls[0]["user"])["CURRENT_PROJECT"]
    assert context["pages"][0]["features"] == draft["pages"][0]["features"]
    assert context["requirements"] == draft["requirements"] and context["roles"] == draft["roles"]
    assert "estimate" not in context and draft == original


def test_owner_provider_alert_reopens_after_resolution_and_redacts_sensitive_details(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from types import SimpleNamespace
    from modules.finora_core.brain import support
    engine = create_engine("sqlite:///:memory:")
    support.FcSupportIssue.__table__.create(engine)
    events = []
    monkeypatch.setattr(support, "audit", lambda *a, **kw: None)
    monkeypatch.setattr(support, "emit", lambda *a, **kw: events.append(kw or a[-1]))
    customer = SimpleNamespace(id=3, display_name="تجريبي", tenant_slug="own")
    with Session(engine) as s:
        args = dict(kind="provider_error", details="insufficient_quota sk-proj-test-secret-1234567890", source="provider:own:quota", verified=True)
        first = support.report(s, customer, "own", **args)
        assert "sk-proj" not in first.details
        assert support.report(s, customer, "own", **args).id == first.id and len(events) == 1
        first.status, first.resolved_by = "resolved", "operator"
        reopened = support.report(s, customer, "own", **args)
        assert reopened.id == first.id and reopened.status == "open" and reopened.resolved_by is None
        assert len(events) == 2
    engine.dispose()
