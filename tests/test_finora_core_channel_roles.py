import json

import pytest

from tests.finora_core_support import env, _api, _auth, IG_ID  # noqa: F401
from tests.test_finora_core_brain import brain, core, say as social_say, customer_of, FakeProvider, model_plan  # noqa: F401
from tests.test_finora_core_telegram import telegram, say as telegram_say  # noqa: F401
from modules.finora_core.brain import channel_roles, approvals
from modules.finora_core.brain.tools import ToolError, run_tool
from modules.finora_core.brain.models import FcCustomer, FcAgentRun, FcApproval, FcToolCall


@pytest.mark.parametrize("channel", ["telegram", "instagram", "messenger", "unknown"])
@pytest.mark.parametrize("action", sorted(channel_roles.ACCOUNT_ACTIONS | channel_roles.PROJECT_ACTIONS))
def test_channel_action_matrix(channel, action):
    expected = channel in {"instagram", "messenger"} if action in channel_roles.ACCOUNT_ACTIONS else channel == "telegram"
    assert channel_roles.allowed(channel, action) == expected


@pytest.mark.parametrize("platform,account", [("page", None), ("instagram", IG_ID)])
def test_social_custom_project_request_redirects_without_planning_or_account_actions(brain, monkeypatch, platform, account):
    from modules.finora_core.brain import project_consultation
    calls = []
    monkeypatch.setattr(project_consultation, "consult", lambda *a, **kw: calls.append(kw))
    kwargs = dict(platform=platform)
    if account:
        kwargs["account"] = account
    reply = social_say(brain, "اريد تطبيق مخصص لمتجر ملابس مع موقع للطلبات", **kwargs)
    assert "بالتلكرام" in reply and calls == []
    english = social_say(brain, "I want a custom website for my shop", sender="english-customer", **kwargs)
    assert "Telegram" in english and calls == []
    assert core(brain, lambda s: s.query(FcApproval).count()) == 0
    assert core(brain, lambda s: s.query(FcToolCall).count()) == 0


def test_telegram_account_creation_and_old_intake_cannot_request_an_approval(telegram):
    from modules.finora_core.brain import intake
    telegram_say(telegram, "مرحبا")
    def seed(s):
        customer = s.query(FcCustomer).one()
        intake.save(s, customer, "1", {"action": {"type": "start_trial"}, "waiting": "phone", "expires": 9999999999})
        s.commit()
    core(telegram, seed)
    reply = telegram_say(telegram, "سوولي حساب تجريبي فينورا اسم المحل ملابس النور ورقمي 07701234567")
    assert "إنستغرام أو فيسبوك" in reply
    telegram_say(telegram, "07701234567")
    assert core(telegram, lambda s: s.query(FcApproval).count()) == 0
    assert core(telegram, lambda s: s.query(FcToolCall).count()) == 0
    assert core(telegram, lambda s: s.query(FcCustomer).one().tenant_slug) is None


def test_open_telegram_discussion_stays_read_only_and_does_not_collect_account_fields(telegram):
    provider = FakeProvider({"answer": "المخزون حسب اللون والمقاس يفيد متجرك؛ تريد بيع أونلاين لو إدارة داخلية؟", "questions": []})
    telegram["state"]["provider"] = provider
    reply = telegram_say(telegram, "عندي محل ملابس شنو تنصحني بميزات تسهّل شغلي؟")
    assert "اللون والمقاس" in reply and "finora_project_advice" not in reply
    assert json.loads(provider.calls[0]["user"])["UNTRUSTED_SCOPE"] == {}
    assert core(telegram, lambda s: s.query(FcApproval).count()) == 0
    assert core(telegram, lambda s: s.query(FcToolCall).count()) == 0


def test_old_telegram_account_approval_and_direct_executor_are_blocked(telegram):
    telegram_say(telegram, "مرحبا")
    def attempt(s):
        customer = s.query(FcCustomer).one()
        run = s.query(FcAgentRun).one()
        with pytest.raises(ToolError) as created:
            approvals.request(s, customer=customer, conversation_ref="1", run_id=run.id,
                              action={"type": "start_trial"}, risk="high", agent_limit=None)
        assert created.value.code == "CHANNEL_ROLE"
        stale = FcApproval(customer_id=customer.id, conversation_ref="1", action="start_trial", title="قديم",
                           risk="high", status="pending", args_json="{}", reason="طلب سابق", new_value="تجربة")
        s.add(stale); s.flush()
        with pytest.raises(ToolError) as rejected:
            approvals.decide(s, stale, "approved", actor="operator", plan_hash_seen="irrelevant")
        assert rejected.value.code == "CHANNEL_ROLE" and stale.status == "pending"
        with pytest.raises(ToolError) as executed:
            run_tool(s, "recommend_plan", {"plan_key": "basic"}, customer=customer, actor="AI", actor_type="ai", run_id=run.id)
        assert executed.value.code == "CHANNEL_ROLE"
        with pytest.raises(ToolError) as unscoped:
            run_tool(s, "recommend_plan", {"plan_key": "basic"}, customer=customer, actor="AI", actor_type="ai")
        assert unscoped.value.code == "CHANNEL_SCOPE"
        assert s.query(FcToolCall).count() == 0
    with telegram["app"].test_request_context():
        core(telegram, attempt)


def test_social_project_approval_is_rejected_before_building_a_plan(brain):
    social_say(brain, "مرحبا")
    def attempt(s):
        customer = s.query(FcCustomer).one()
        with pytest.raises(ToolError) as error:
            approvals.request(s, customer=customer, conversation_ref="1", run_id=None,
                              action={"type": "publish_project_quote"}, risk="high", agent_limit=None)
        assert error.value.code == "CHANNEL_ROLE"
        assert s.query(FcApproval).count() == 0
    with brain["app"].test_request_context():
        core(brain, attempt)


def test_telegram_custom_app_registration_is_a_project_feature_not_finora_provisioning(telegram, monkeypatch):
    from modules.finora_core.brain import project_consultation
    calls = []
    def consult(*args, **kwargs):
        calls.append(args[3])
        return {"reply": "نضيف تسجيل دخول للزبائن داخل تطبيقك المخصص.", "action": None, "model": "test"}
    monkeypatch.setattr(project_consultation, "consult", consult)
    reply = telegram_say(telegram, "اريد تطبيق مخصص لمتجري بيه إنشاء حساب للزبائن وتسجيل دخول")
    assert "داخل تطبيقك" in reply and len(calls) == 1
    assert core(telegram, lambda s: s.query(FcApproval).count()) == 0
    assert core(telegram, lambda s: s.query(FcToolCall).count()) == 0


def test_valid_social_request_replaces_same_plan_with_invalid_old_channel_scope(brain):
    social_say(brain, "سوولي حساب تجريبي لعيادة اسنان اسمها النور رقمي 07701234567")
    def retry(s):
        old = s.query(FcApproval).one()
        old.conversation_ref = "99999"
        new = approvals.request(s, customer=s.get(FcCustomer, old.customer_id), conversation_ref="1", run_id=None,
                                action={"type": "start_trial"}, risk="high", agent_limit=None)
        assert new.id != old.id and new.conversation_ref == "1"
        assert new.plan_hash == old.plan_hash
        assert old.status == "superseded" and old.superseded_by_id == new.id
    with brain["app"].test_request_context():
        core(brain, retry)


def test_semantic_channel_routing_uses_analysis_without_executing_an_action(telegram):
    from tests.test_finora_core_understanding import DeliberatingProvider, interpretation
    project_text = "حاب نناقش مشروع جديد لبيع ملابس من الموبايل"
    provider = DeliberatingProvider(interpretation(project_text, topic="custom_project"))
    telegram["state"]["provider"] = provider
    assert "بالتلكرام" in social_say(telegram, project_text)
    assert len(provider.calls) == 1
    finora_text = "شلون أوزع الصلاحيات للموظفين بفينورا؟"
    provider = DeliberatingProvider(interpretation(finora_text, topic="finora"))
    telegram["state"]["provider"] = provider
    assert "إنستغرام أو فيسبوك" in telegram_say(telegram, finora_text)
    assert len(provider.calls) == 1
    assert core(telegram, lambda s: s.query(FcApproval).count()) == 0
    assert core(telegram, lambda s: s.query(FcToolCall).count()) == 0


def test_old_social_project_cannot_be_revised_or_manually_resent(brain):
    social_say(brain, "مرحبا")
    def seed(s):
        customer = s.query(FcCustomer).one()
        old = FcApproval(customer_id=customer.id, conversation_ref="1", action="publish_project_quote",
                         title="عرض قديم", reason="طلب سابق", new_value="عرض", risk="high", status="pending",
                         args_json="{}", plan_hash="old")
        s.add(old); s.commit()
        return str(old.id)
    approval = core(brain, seed)
    res = _api(brain, "patch", f"/approvals/{approval}/project", headers=_auth(brain),
               json={"planHash": "old", "terms": {}})
    assert res.status_code == 409 and "بالتلكرام" in res.get_json()["error"]["message"]
    res = _api(brain, "post", "/conversations/1/project/send-offer", headers=_auth(brain))
    assert res.status_code == 409 and "بالتلكرام" in res.get_json()["error"]["message"]
    assert core(brain, lambda s: s.query(FcApproval).one().status) == "pending"
