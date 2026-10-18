"""Voice permissions, verified alerts, bounded costs and provider error/secret isolation."""
from types import SimpleNamespace
from tests.finora_core_support import env, _api, _auth  # noqa: F401


def test_notification_voice_authentication_validation_privacy_and_limits(env, monkeypatch):
    from modules.finora_core import voice_api
    from modules.finora_core.brain.models import FcApproval
    from modules.finora_core.models import FcOperatorRole, FcSetting
    from modules.finora_core.store import core_session
    calls = []
    def post(url, **kw):
        calls.append((url, kw))
        return SimpleNamespace(ok=True, json=lambda: {"session": {"id": "live_test"}, "transport": {"sdp": "v=0\r\nanswer"}})
    monkeypatch.setattr(voice_api.requests, "post", post)
    monkeypatch.setattr(voice_api, "cloud_key", lambda s: "sk-test-never-exposed")
    path = "/voice/notifications/session"
    request = {"kind": "test", "sdp": "v=0\r\noffer"}
    assert _api(env, "post", path, json=request).status_code == 401
    auth = _auth(env)
    for invalid in ({**request, "text": "read this secret"}, {**request, "kind": "arbitrary"},
                    {**request, "sdp": "bad"}, {**request, "sdp": "v=0" + "x"*65536}):
        assert _api(env, "post", path, headers=auth, json=invalid).status_code == 400
    assert not calls
    with env["app"].app_context(), core_session() as s:
        row = FcApproval(action="start_trial", args_json="{}", title="Private customer name", reason="private detail",
                         new_value="account", risk="high", status="pending")
        s.add(row); s.commit(); approval_id = row.id
    response = _api(env, "post", path, headers=auth, json={**request, "kind": "approval", "ref": str(approval_id)})
    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    assert body["model"] == "gpt-live-1" and "موافقة" in body["announcement"]
    assert "Private customer" not in str(body) and "sk-test" not in str(body)
    assert response.headers["Cache-Control"] == "no-store"
    url, upstream = calls[-1]
    assert url == "https://api.openai.com/v1/live/sessions"
    assert upstream["json"]["session"]["model"] == "gpt-live-1"
    assert upstream["json"]["session"]["store"] is False
    assert "Private customer" not in str(upstream["json"])
    with env["app"].app_context(), core_session() as s:
        row = s.get(FcApproval, approval_id); row.status = "executed"; s.commit()
    assert _api(env, "post", path, headers=auth, json={**request, "kind": "approval", "ref": str(approval_id)}).status_code == 409
    assert _api(env, "post", path, headers=auth, json={**request, "kind": "support", "ref": "999999"}).status_code == 404
    monkeypatch.setattr(voice_api, "cloud_key", lambda s: None)
    assert _api(env, "post", path, headers=auth, json=request).status_code == 503
    monkeypatch.setattr(voice_api, "cloud_key", lambda s: "sk-test-never-exposed")
    monkeypatch.setattr(voice_api.requests, "post", lambda *a, **kw: SimpleNamespace(ok=False))
    failed = _api(env, "post", path, headers=auth, json=request)
    assert failed.status_code == 502 and failed.get_json()["error"]["code"] == "VOICE_UNAVAILABLE"
    monkeypatch.setattr(voice_api.requests, "post", post)
    for _ in range(4):
        assert _api(env, "post", path, headers=auth, json=request).status_code == 201
    assert _api(env, "post", path, headers=auth, json=request).status_code == 429
    with env["app"].app_context(), core_session() as s:
        s.add(FcOperatorRole(superadmin_id=1, role="read_only"))
        s.delete(s.get(FcSetting, "voice.rate:1")); s.commit()
    restricted = _auth(env)
    assert _api(env, "post", path, headers=restricted, json={**request, "kind": "approval", "ref": str(approval_id)}).status_code == 403
