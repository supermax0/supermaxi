"""Agent settings, credential isolation and real pipeline integration. No external requests or customer sends."""
import pytest

from tests.finora_core_support import _api, _auth, env  # noqa: F401
from tests.test_finora_core_brain import FakeProvider, brain, model_plan, say  # noqa: F401


def test_settings_require_owner_permission_and_roundtrip(env):
    from modules.finora_core.models import FcOperatorRole
    from modules.finora_core.store import core_session

    auth = _auth(env)
    assert _api(env, "get", "/settings/agent").status_code == 401
    assert _api(env, "get", "/settings/knowledge").status_code == 401
    result = _api(env, "patch", "/settings/agent", headers=auth,
                  json={"replyMode": "review", "language": "ar-iq", "minimumConfidence": 0.85})
    assert result.status_code == 200, result.get_json()
    assert result.get_json()["config"]["replyMode"] == "review"
    assert _api(env, "get", "/status", headers=auth).get_json()["shadowMode"] is True
    assert _api(env, "get", "/settings/agent", headers=auth).get_json()["config"]["minimumConfidence"] == 0.85
    with env["app"].app_context(), core_session() as s:
        s.add(FcOperatorRole(superadmin_id=1, role="read_only"))
        s.commit()
    restricted = _auth(env)
    assert _api(env, "get", "/settings/agent", headers=restricted).status_code == 403
    assert _api(env, "post", "/settings/meta/verification", headers=restricted).status_code == 403
    assert _api(env, "get", "/settings/knowledge", headers=restricted).status_code == 403


def test_knowledge_search_and_reply_preview_use_reviewed_guides_without_writes(brain):
    auth = _auth(brain)
    result = _api(brain, "get", "/settings/knowledge?q=شلون اضيف منتج للمخزون", headers=auth)
    assert result.status_code == 200
    data = result.get_json()
    assert data["featureCount"] >= 162 and data["guideCount"] >= 44
    assert data["results"][0]["id"] == "guide:inventory.add"
    assert _api(brain, "get", "/settings/knowledge?businessType=invalid", headers=auth).status_code == 400
    scoped = _api(brain, "get", "/settings/knowledge?businessType=general&q=طبيب", headers=auth).get_json()
    assert not any(r["id"].startswith("howto:") for r in scoped["results"])
    _api(brain, "patch", "/settings/agent", headers=auth, json={"provider": "off"})
    preview = _api(brain, "post", "/settings/agent/preview", headers=auth, json={"text": "شلون اضيف منتج للمخزون؟"}).get_json()
    assert not preview["needsHuman"]
    assert preview["knowledgeSources"][0]["id"] == "guide:inventory.add"
    assert not brain["graph"].sends()


def test_teaching_followup_passes_the_same_scoped_topic_to_the_model(brain):
    import json

    reply = model_plan("افتح المخزون ثم إضافة منتج", intents=(("training_request", 0.9),), cited=("guide:inventory.add",))
    provider = FakeProvider(reply)
    say(brain, "عندي محل ملابس اونلاين")
    brain["state"]["provider"] = provider
    say(brain, "شلون اضيف منتج؟")
    say(brain, "تمام شنو بعدها؟")
    payload = json.loads(provider.calls[-1]["user"])
    assert "guide:inventory.add" in {k["id"] for k in payload["KNOWLEDGE"]}
    assert not any(k["id"].startswith("howto:doctor") for k in payload["KNOWLEDGE"])


@pytest.mark.parametrize("data", [
    {"provider": []}, {"provider": "unknown"}, {"minimumConfidence": True},
    {"minimumConfidence": 2}, {"minimumConfidence": float("nan")}, {"timeoutSeconds": 90},
    {"localUrl": "http://169.254.169.254"}, {"localUrl": "http://user:pass@localhost:11434"},
    {"localUrl": "http://127.0.0.1:11434/api/chat"}, {"provider": "local", "localModel": ""},
    {"apiKey": "should-not-be-settings"}, {"instructions": "x" * 2001},
])
def test_invalid_settings_do_not_change_saved_configuration(env, data):
    auth = _auth(env)
    original = _api(env, "get", "/settings/agent", headers=auth).get_json()
    response = _api(env, "patch", "/settings/agent", json=data, headers=auth)
    assert response.status_code == 400, response.get_json()
    assert _api(env, "get", "/settings/agent", headers=auth).get_json() == original


def test_cloud_key_is_encrypted_isolated_and_absent_from_reads_and_audit(env, monkeypatch):
    from modules.finora_core.models import FcAuditLog
    from modules.finora_core.settings import CLOUD_KEY, cloud_key
    from modules.finora_core.store import core_session, get_setting

    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-fake-key-for-test")
    auth = _auth(env)
    key = "sk-core-fake-key-for-test-123456"
    result = _api(env, "post", "/settings/agent/cloud-key", json={"apiKey": key}, headers=auth)
    assert result.status_code == 200
    assert result.get_json()["cloudKeySource"] == "core"
    assert key not in result.get_data(as_text=True)
    with env["app"].app_context(), core_session() as s:
        assert key not in get_setting(s, CLOUD_KEY)
        assert cloud_key(s) == key
        assert all(key not in (r.input_summary or "") for r in s.query(FcAuditLog).all())
    assert _api(env, "post", "/settings/agent/cloud-key", json={"apiKey": "bad"}, headers=auth).status_code == 400
    result = _api(env, "post", "/settings/agent/cloud-key", json={"apiKey": ""}, headers=auth)
    assert result.get_json()["cloudKeySource"] == "server"
    with env["app"].app_context(), core_session() as s:
        assert cloud_key(s) == "sk-server-fake-key-for-test"


def test_local_provider_never_resolves_cloud_credentials(env, monkeypatch):
    from modules.finora_core.brain.provider import OllamaProvider, get_provider
    from modules.finora_core import settings

    _api(env, "patch", "/settings/agent", headers=_auth(env), json={"provider": "local", "localModel": "installed-model"})
    def forbidden(_s):
        raise AssertionError("local-only mode accessed cloud credentials")
    monkeypatch.setattr(settings, "cloud_key", forbidden)
    with env["app"].app_context():
        assert isinstance(get_provider(), OllamaProvider)


def test_ollama_schema_request_and_hybrid_fallback(env, monkeypatch):
    from modules.finora_core.brain.provider import HybridProvider, OllamaProvider, ProviderError
    from tests.finora_core_support import FakeResponse
    import requests

    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(200, {"message": {"content": '{"ok": true}'}, "prompt_eval_count": 8, "eval_count": 2})
    monkeypatch.setattr(requests, "post", post)
    with env["app"].app_context():
        provider = OllamaProvider("http://127.0.0.1:11434", "installed-model")
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    args = {"system": "s", "user": "u", "schema": schema, "schema_name": "test"}
    result = provider.generate_structured(**args)
    assert result.data == {"ok": True} and result.input_tokens == 8
    assert calls[0][1]["json"]["format"] == schema
    assert calls[0][1]["allow_redirects"] is False
    local = FakeProvider(ProviderError("local_unreachable", "offline"))
    cloud = FakeProvider({"ok": True})
    assert HybridProvider(local, cloud).generate_structured(**args).data == {"ok": True}
    assert len(cloud.calls) == 1
    local = FakeProvider({"ok": "invalid-schema"})
    assert HybridProvider(local, cloud).generate_structured(**args).data == {"ok": True}


def test_meta_read_never_reveals_secret_and_verification_is_explicit(env):
    auth = _auth(env)
    result = _api(env, "get", "/settings/meta", headers=auth)
    assert result.status_code == 200, result.get_json()
    assert "verify-me" not in result.get_data(as_text=True)
    assert "PAGE-TOKEN-SECRET" not in result.get_data(as_text=True)
    assert result.get_json()["secretConfigured"] is True
    revealed = _api(env, "post", "/settings/meta/verification", headers=auth)
    assert revealed.get_json()["verifyToken"] == "verify-me"
    assert revealed.headers["Cache-Control"] == "no-store"


def test_preview_uses_style_and_guards_without_side_effects(brain, monkeypatch):
    from modules.finora_core.brain import provider
    from modules.finora_core.brain.models import FcCustomer
    from modules.finora_core.store import core_session

    auth = _auth(brain)
    _api(brain, "patch", "/settings/agent", json={"language": "ar-iq", "tone": "professional"}, headers=auth)
    fake = FakeProvider(model_plan("هلا بيك في فينورا"))
    monkeypatch.setattr(provider, "get_provider", lambda: fake)
    result = _api(brain, "post", "/settings/agent/preview", json={"text": "هلا"}, headers=auth)
    assert result.status_code == 200, result.get_json()
    assert result.get_json()["source"] == "model"
    assert '"tone": "professional"' in fake.calls[0]["system"]
    assert brain["graph"].sends() == []
    with brain["app"].app_context(), core_session() as s:
        assert s.query(FcCustomer).count() == 0
    fake.outputs = [model_plan("السعر 999,000 د.ع", intents=(("pricing", 0.99),))]
    result = _api(brain, "post", "/settings/agent/preview", json={"text": "كم السعر؟"}, headers=auth)
    assert result.get_json()["needsHuman"] is True
    assert "999" not in result.get_json()["text"]


def test_low_confidence_live_reply_hands_off_and_style_reaches_provider(brain):
    auth = _auth(brain)
    _api(brain, "patch", "/settings/agent", json={"minimumConfidence": 0.85, "language": "ar-iq"}, headers=auth)
    fake = FakeProvider(model_plan("هلا", intents=(("greeting", 0.3),)))
    brain["state"]["provider"] = fake
    reply = say(brain, "هلا")
    assert "أتأكد" in reply
    assert '"language": "ar-iq"' in fake.calls[0]["system"]


def test_review_mode_stores_proposals_without_sending(brain):
    _api(brain, "patch", "/settings/agent", json={"replyMode": "review"}, headers=_auth(brain))
    assert say(brain, "هلا") is None
    assert brain["graph"].sends() == []


def test_meta_connect_sanitizes_failure_and_reuses_saved_app_secret(env, monkeypatch):
    from modules.finora_core import meta_house
    from tests.finora_core_support import SECRET

    received = []
    def connect(**kwargs):
        received.append(kwargs)
        raise meta_house.ActivationError("secret-token-that-must-not-appear")
    monkeypatch.setattr(meta_house, "connect_meta", connect)
    result = _api(env, "post", "/settings/meta/connect", headers=_auth(env),
                  json={"appId": "12345", "userToken": "temporary-test-token", "appSecret": ""})
    assert result.status_code == 400
    assert "secret-token-that-must-not-appear" not in result.get_data(as_text=True)
    assert received[0]["app_secret"] == SECRET


def test_new_house_is_persisted_and_starts_in_review_mode(brain, monkeypatch):
    from modules.finora_core import meta_house
    from modules.ai_sales.meta_policy import signature_required
    from tests.finora_core_support import HOUSE

    monkeypatch.delenv("FINORA_CORE_HOUSE_TENANT")
    assert _api(brain, "get", "/settings/meta", headers=_auth(brain)).get_json()["houseConfigured"] is False
    monkeypatch.setattr(meta_house, "init_house_tenant", lambda slug: HOUSE)
    result = _api(brain, "post", "/settings/meta/provision", headers=_auth(brain))
    assert result.status_code == 200, result.get_json()
    assert result.get_json()["houseConfigured"] is True
    with brain["app"].app_context():
        assert signature_required(HOUSE) is True
    assert _api(brain, "get", "/settings/agent", headers=_auth(brain)).get_json()["config"]["replyMode"] == "review"


def test_human_request_cannot_be_overridden_by_model_in_preview(brain, monkeypatch):
    from modules.finora_core.brain import provider

    monkeypatch.setattr(provider, "get_provider", lambda: FakeProvider(model_plan("راح أبيعك باقة", intents=(("greeting", 0.99),))))
    result = _api(brain, "post", "/settings/agent/preview", headers=_auth(brain), json={"text": "اريد احجي ويا موظف"})
    assert result.get_json()["needsHuman"] is True
    assert "أبيعك" not in result.get_json()["text"]


def test_reply_mode_change_during_generation_prevents_delivery(brain):
    from modules.finora_core.store import core_session, set_setting

    def switch_to_manual():
        with core_session() as s:
            set_setting(s, "flag:AI_AUTO_REPLY", "off", "owner")
            s.commit()
    brain["state"]["provider"] = FakeProvider(model_plan("هلا بيك"), on_call=switch_to_manual)
    assert say(brain, "هلا") is None
    assert brain["graph"].sends() == []


@pytest.mark.parametrize("text", ["عدنا 3 اطباء و2 موظفين وفرع واحد", "رقمي 07701234567", "ايميلي a@clinic.iq"])
def test_grounded_profile_answer_keeps_rules_followup(text):
    from modules.finora_core.settings import DEFAULTS, apply_reply_policy
    from modules.finora_core.brain.extract import extract
    from modules.finora_core.brain.planner import plan_with_rules

    extracted = extract(text)
    plan = plan_with_rules(extraction=extracted, text=text, facts={"businessType": {"value": "clinic"}},
                           knowledge=[], plan_keys=set())
    result = apply_reply_policy(plan, DEFAULTS, extracted)
    assert not result.needs_human
    assert "اختصاص" in result.reply_text
