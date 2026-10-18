"""FINORA CORE desktop API (Phase 6): auth, RBAC, conversations façade, idempotency, kill switch, SSE outbox.

Runs against an isolated Flask app with a temporary SQLite Core DB and a temporary house tenant — never the real
databases."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask, g

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOUSE = "fc-house-test"
PASSWORD = "correct horse battery"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FINORA_CORE_HOUSE_TENANT", HOUSE)
    monkeypatch.setenv("FINORA_ENV", "development")
    monkeypatch.setenv("FINORA_CORE_DEV_LOOPBACK", "1")
    import models  # noqa: F401  full mapper graph (relationships resolve by class name)
    import models.delivery_agent  # noqa: F401
    import modules.ai_sales.models  # noqa: F401
    from extensions import db
    import extensions_tenant
    from models.core.super_admin import SuperAdmin
    from modules.finora_core import init_finora_core
    from modules.finora_core import auth as fc_auth
    from modules.finora_core import store as fc_store
    from modules.finora_core import sync as fc_sync

    monkeypatch.setattr(extensions_tenant, "_tenant_engines", {})
    monkeypatch.setattr(fc_store, "_HOUSE_SCHEMA_READY", set())
    monkeypatch.setattr(fc_auth, "_failures", {})
    monkeypatch.setattr(fc_sync, "_last_run", 0.0)

    app = Flask(__name__, root_path=str(tmp_path))
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'core.db'}",
        SECRET_KEY="test-secret",
        TESTING=True,
    )
    db.init_app(app)
    with app.app_context():
        SuperAdmin.__table__.create(bind=db.engine, checkfirst=True)
        admin = SuperAdmin(username="owner")
        admin.set_password(PASSWORD)
        reader = SuperAdmin(username="viewer")
        reader.set_password(PASSWORD)
        db.session.add_all([admin, reader])
        db.session.commit()
    init_finora_core(app)
    with app.app_context():
        from modules.finora_core.models import FcOperatorRole
        from modules.finora_core.store import core_session

        with core_session() as s:
            s.add(FcOperatorRole(superadmin_id=2, role="read_only"))
            s.commit()
    yield app


def _seed_house(app):
    from extensions import db
    from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation, AISalesMessage
    from modules.finora_core.store import use_house

    from extensions_tenant import get_tenant_engine

    with app.test_request_context():
        db.Model.metadata.create_all(get_tenant_engine(HOUSE))  # a real house tenant is a fully initialized tenant
        with use_house():
            ig = AISalesChannelAccount(channel_type="instagram", name="FINORA IG", is_active=True, connection_status="connected", reply_mode="ai")
            fb = AISalesChannelAccount(channel_type="messenger", name="FINORA FB", is_active=False, connection_status="auth_expired", reply_mode="ai")
            wa = AISalesChannelAccount(channel_type="whatsapp", name="Other", is_active=True, connection_status="connected")
            db.session.add_all([ig, fb, wa])
            db.session.flush()
            now = datetime.utcnow()
            c1 = AISalesConversation(channel_account_id=ig.id, external_contact_id="ig-1", contact_name="أحمد علي",
                                     last_customer_message_at=now - timedelta(minutes=1))
            c2 = AISalesConversation(channel_account_id=fb.id, external_contact_id="fb-1", contact_name="د. سارة",
                                     last_customer_message_at=now - timedelta(minutes=10), external_phone="+9647700000000")
            c3 = AISalesConversation(channel_account_id=wa.id, external_contact_id="wa-1", contact_name="WhatsApp only")
            db.session.add_all([c1, c2, c3])
            db.session.flush()
            db.session.add_all([
                AISalesMessage(conversation_id=c1.id, channel_account_id=ig.id, direction="inbound", sender_type="customer",
                               text_content="عندي عيادة أسنان وأريد نظام", status="processed"),
                AISalesMessage(conversation_id=c1.id, channel_account_id=ig.id, direction="outbound", sender_type="ai",
                               text_content="أهلاً دكتور", status="sent", delivered_at=now),
                AISalesMessage(conversation_id=c2.id, channel_account_id=fb.id, direction="inbound", sender_type="customer",
                               text_content="كم سعر الباقات؟", status="received"),
                AISalesMessage(conversation_id=c3.id, channel_account_id=wa.id, direction="inbound", sender_type="customer",
                               text_content="hidden", status="received"),
            ])
            db.session.commit()
            return {"c1": c1.id, "c2": c2.id, "c3": c3.id, "ig": ig.id}


def _login(client, username="owner", password=PASSWORD):
    return client.post("/api/v1/finora-core/auth/login", json={"username": username, "password": password})


def _auth(client, username="owner"):
    res = _login(client, username)
    assert res.status_code == 200, res.get_json()
    return {"Authorization": f"Bearer {res.get_json()['accessToken']}"}, res.get_json()


# ───────────────────────────── auth ─────────────────────────────


def test_login_issues_tokens_and_rejects_bad_credentials(env):
    client = env.test_client()
    bad = _login(client, password="wrong")
    assert bad.status_code == 401
    assert bad.get_json()["error"]["code"] == "AUTH_ERROR"
    headers, body = _auth(client)
    assert body["operator"]["role"] == "super_admin"
    assert "settings.manage" in body["operator"]["permissions"]
    assert client.get("/api/v1/finora-core/me", headers=headers).get_json()["username"] == "owner"


def test_login_is_rate_limited_after_repeated_failures(env):
    client = env.test_client()
    for _ in range(5):
        assert _login(client, password="nope").status_code == 401
    assert _login(client).status_code == 429


def test_missing_or_forged_tokens_are_rejected(env):
    client = env.test_client()
    assert client.get("/api/v1/finora-core/me").status_code == 401
    assert client.get("/api/v1/finora-core/me", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_refresh_rotates_and_detects_reuse(env):
    client = env.test_client()
    _, body = _auth(client)
    first = body["refreshToken"]
    rotated = client.post("/api/v1/finora-core/auth/refresh", json={"refreshToken": first})
    assert rotated.status_code == 200
    second = rotated.get_json()["refreshToken"]
    assert second != first
    # Replaying the rotated-out token revokes the whole session.
    assert client.post("/api/v1/finora-core/auth/refresh", json={"refreshToken": first}).status_code == 401
    assert client.post("/api/v1/finora-core/auth/refresh", json={"refreshToken": second}).status_code == 401
    access = rotated.get_json()["accessToken"]
    assert client.get("/api/v1/finora-core/me", headers={"Authorization": f"Bearer {access}"}).status_code == 401


def test_logout_revokes_the_access_token(env):
    client = env.test_client()
    headers, _ = _auth(client)
    assert client.post("/api/v1/finora-core/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/finora-core/me", headers=headers).status_code == 401


def test_read_only_role_cannot_send_or_change_settings(env):
    ids = _seed_house(env)
    client = env.test_client()
    headers, body = _auth(client, "viewer")
    assert body["operator"]["role"] == "read_only"
    assert client.get("/api/v1/finora-core/conversations", headers=headers).status_code == 200
    send = client.post(f"/api/v1/finora-core/conversations/{ids['c2']}/messages", json={"text": "x"},
                       headers={**headers, "Idempotency-Key": "k"})
    assert send.status_code == 403
    assert client.post("/api/v1/finora-core/automation", json={"paused": True, "reason": "x"}, headers=headers).status_code == 403
    assert client.post(f"/api/v1/finora-core/conversations/{ids['c1']}/takeover", headers=headers).status_code == 403


def test_cors_only_for_allowed_origins(env):
    client = env.test_client()
    ok = client.options("/api/v1/finora-core/me", headers={"Origin": "http://tauri.localhost"})
    assert ok.status_code == 204
    assert ok.headers["Access-Control-Allow-Origin"] == "http://tauri.localhost"
    evil = client.options("/api/v1/finora-core/me", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in evil.headers


# ───────────────────────────── conversations ─────────────────────────────


def test_conversations_only_expose_instagram_and_facebook_with_contract_shape(env):
    ids = _seed_house(env)
    client = env.test_client()
    headers, _ = _auth(client)
    items = client.get("/api/v1/finora-core/conversations", headers=headers).get_json()["items"]
    assert [i["id"] for i in items] == [str(ids["c1"]), str(ids["c2"])]  # most recent activity first, no WhatsApp
    first = items[0]
    assert first["channel"] == "instagram" and first["control"] == "ai" and first["agentState"] == "waiting_customer"
    assert first["lastMessageText"] == "أهلاً دكتور"
    assert first["lastActivityAt"].endswith("Z")
    assert items[1]["channel"] == "facebook" and items[1]["unreadCount"] == 1
    fb_only = client.get("/api/v1/finora-core/conversations?channel=facebook", headers=headers).get_json()["items"]
    assert [i["id"] for i in fb_only] == [str(ids["c2"])]
    found = client.get("/api/v1/finora-core/conversations?q=أسنان", headers=headers).get_json()["items"]
    assert [i["id"] for i in found] == [str(ids["c1"])]
    assert client.get(f"/api/v1/finora-core/conversations/{ids['c3']}/messages", headers=headers).status_code == 404
    assert client.get("/api/v1/finora-core/conversations?filter=bogus", headers=headers).status_code == 400


def test_messages_map_senders_and_real_delivery_state(env):
    ids = _seed_house(env)
    client = env.test_client()
    headers, _ = _auth(client)
    msgs = client.get(f"/api/v1/finora-core/conversations/{ids['c1']}/messages", headers=headers).get_json()["items"]
    assert [m["sender"] for m in msgs] == ["customer", "core"]
    assert msgs[0]["delivery"] is None and msgs[1]["delivery"] == "delivered"


def test_read_marker_is_per_operator(env):
    ids = _seed_house(env)
    client = env.test_client()
    owner, _ = _auth(client)
    viewer, _ = _auth(client, "viewer")
    assert client.post(f"/api/v1/finora-core/conversations/{ids['c2']}/read", headers=owner).status_code == 200
    def unread(h):
        items = client.get("/api/v1/finora-core/conversations", headers=h).get_json()["items"]
        return {i["id"]: i["unreadCount"] for i in items}[str(ids["c2"])]
    assert unread(owner) == 0
    assert unread(viewer) == 1


def test_manual_send_requires_takeover_and_is_idempotent(env):
    ids = _seed_house(env)
    client = env.test_client()
    headers, _ = _auth(client)
    url = f"/api/v1/finora-core/conversations/{ids['c1']}/messages"
    blocked = client.post(url, json={"text": "مرحبا"}, headers={**headers, "Idempotency-Key": "k1"})
    assert blocked.status_code == 409 and blocked.get_json()["error"]["code"] == "CONFLICT"
    assert client.post(url, json={"text": "مرحبا"}, headers=headers).status_code == 400  # key required

    taken = client.post(f"/api/v1/finora-core/conversations/{ids['c1']}/takeover", headers=headers).get_json()
    assert taken["control"] == "human"
    first = client.post(url, json={"text": "أهلاً من الفريق"}, headers={**headers, "Idempotency-Key": "k2"})
    again = client.post(url, json={"text": "أهلاً من الفريق"}, headers={**headers, "Idempotency-Key": "k2"})
    assert first.status_code == 201 and again.status_code == 201
    assert first.get_json()["message"]["id"] == again.get_json()["message"]["id"]
    assert first.get_json()["message"]["sender"] == "human"
    msgs = client.get(url, headers=headers).get_json()["items"]
    assert sum(1 for m in msgs if m["text"] == "أهلاً من الفريق") == 1

    resumed = client.post(f"/api/v1/finora-core/conversations/{ids['c1']}/resume", headers=headers).get_json()
    assert resumed["control"] == "ai"


def test_provider_failure_is_reported_never_faked(env, monkeypatch):
    ids = _seed_house(env)
    monkeypatch.setenv("FINORA_CORE_DEV_LOOPBACK", "0")
    from modules.finora_core import transport

    from modules.ai_sales.channels import MetaMessagingClientError

    def boom(*_a, **_k):
        # Permanent provider rejection (invalid recipient). Transient 5xx / network errors are retried instead:
        # covered in tests/test_finora_core_meta.py.
        raise MetaMessagingClientError("invalid recipient", status_code=400, meta_code=100)

    monkeypatch.setattr(transport, "channel_client", lambda channel: type("C", (), {"send_text": boom})())
    client = env.test_client()
    headers, _ = _auth(client)
    client.post(f"/api/v1/finora-core/conversations/{ids['c1']}/takeover", headers=headers)
    res = client.post(f"/api/v1/finora-core/conversations/{ids['c1']}/messages", json={"text": "x"},
                      headers={**headers, "Idempotency-Key": "fail-1"})
    assert res.status_code == 502
    body = res.get_json()
    assert body["message"]["delivery"] == "failed" and body["error"]["retryable"] is True


def test_loopback_is_refused_outside_development(env, monkeypatch):
    from modules.finora_core.transport import loopback_enabled

    assert loopback_enabled() is True
    monkeypatch.setenv("FINORA_ENV", "production")
    assert loopback_enabled() is False


def test_customer_profile_never_guesses_business_facts(env):
    ids = _seed_house(env)
    client = env.test_client()
    headers, _ = _auth(client)
    profile = client.get(f"/api/v1/finora-core/customers/{ids['c2']}", headers=headers).get_json()
    assert profile["facts"]["phone"]["value"] == "+9647700000000"
    assert profile["facts"]["businessType"] is None and profile["recommendedPlan"] is None
    added = client.post(f"/api/v1/finora-core/customers/{ids['c2']}/notes", json={"body": "اتصل صباحاً"}, headers=headers)
    assert added.status_code == 201
    assert added.get_json()["notes"][0]["body"] == "اتصل صباحاً"


# ───────────────────────────── status, kill switch, activity ─────────────────────────────


def test_status_reports_real_channel_health(env):
    _seed_house(env)
    client = env.test_client()
    headers, _ = _auth(client)
    body = client.get("/api/v1/finora-core/status", headers=headers).get_json()
    assert body["channels"] == {"instagram": "connected", "facebook": "disconnected", "telegram": "disconnected"}
    assert body["conversationCount"] == 2 and body["devLoopback"] is True


def test_house_tenant_without_database_is_not_created_silently(env, monkeypatch):
    monkeypatch.setenv("FINORA_CORE_HOUSE_TENANT", "fc-house-missing")
    client = env.test_client()
    headers, _ = _auth(client)
    res = client.get("/api/v1/finora-core/conversations", headers=headers)
    assert res.status_code == 503
    assert not (Path(env.root_path) / "tenants" / "fc-house-missing.db").exists()


def test_status_without_house_tenant_is_honest(env, monkeypatch):
    monkeypatch.delenv("FINORA_CORE_HOUSE_TENANT")
    client = env.test_client()
    headers, _ = _auth(client)
    body = client.get("/api/v1/finora-core/status", headers=headers).get_json()
    assert body["houseConfigured"] is False and body["channels"]["instagram"] == "unknown"
    res = client.get("/api/v1/finora-core/conversations", headers=headers)
    assert res.status_code == 503 and res.get_json()["error"]["code"] == "HOUSE_NOT_CONFIGURED"


def test_kill_switch_requires_reason_is_audited_and_stops_the_worker(env):
    _seed_house(env)
    client = env.test_client()
    headers, _ = _auth(client)
    assert client.post("/api/v1/finora-core/automation", json={"paused": True, "reason": " "}, headers=headers).status_code == 400
    res = client.post("/api/v1/finora-core/automation", json={"paused": True, "reason": "صيانة"}, headers=headers)
    assert res.get_json()["automationPaused"] is True
    activity = client.get("/api/v1/finora-core/activity?category=ai", headers=headers).get_json()["items"]
    assert activity[0]["title"] == "تم إيقاف كل الأتمتة" and activity[0]["detail"] == "صيانة"

    from modules.finora_core.killswitch import automation_paused_for_current_tenant

    with env.test_request_context():
        g.tenant = HOUSE
        assert automation_paused_for_current_tenant() is True
        g.tenant = "some-other-tenant"
        assert automation_paused_for_current_tenant() is False  # never affects customer tenants


def test_kill_switch_holds_inbound_message_in_ai_sales_worker(env):
    ids = _seed_house(env)
    client = env.test_client()
    headers, _ = _auth(client)
    client.post("/api/v1/finora-core/automation", json={"paused": True, "reason": "test"}, headers=headers)
    from extensions import db
    from modules.ai_sales import engine
    from modules.ai_sales.models import AISalesMessage
    from modules.finora_core.store import use_house

    with env.test_request_context():
        with use_house():
            inbound = AISalesMessage.query.filter_by(conversation_id=ids["c2"]).first()
            engine._external_auto_reply_enabled = lambda: True  # isolate from global Sales AI config
            assert engine.process_inbound_message(inbound.id) is None
            db.session.refresh(inbound)
            assert inbound.status == "received"  # collected, not processed, not dropped


# ───────────────────────────── realtime outbox ─────────────────────────────


def test_house_sync_turns_new_messages_into_events_once(env):
    ids = _seed_house(env)
    from extensions import db
    from modules.ai_sales.models import AISalesMessage
    from modules.finora_core.models import FcEvent
    from modules.finora_core.store import core_session, use_house
    from modules.finora_core.sync import sync_house

    with env.test_request_context():
        assert sync_house(force=True) == 0  # first pass anchors the cursor; history is not replayed
        with use_house():
            db.session.add(AISalesMessage(conversation_id=ids["c1"], channel_account_id=ids["ig"], direction="inbound",
                                          sender_type="customer", text_content="رسالة جديدة", status="received"))
            db.session.commit()
        assert sync_house(force=True) >= 1
        assert sync_house(force=True) == 0
        with core_session() as s:
            types = [e.type for e in s.query(FcEvent).order_by(FcEvent.seq).all()]
            payloads = [json.loads(e.payload_json) for e in s.query(FcEvent).filter_by(type="message.received").all()]
    assert types.count("message.received") == 1
    assert payloads[0]["message"]["text"] == "رسالة جديدة"
    assert "conversation.updated" in types


def test_sse_stream_replays_after_last_event_id(env):
    ids = _seed_house(env)
    from modules.finora_core import api as fc_api

    client = env.test_client()
    headers, _ = _auth(client)
    client.post(f"/api/v1/finora-core/conversations/{ids['c1']}/takeover", headers=headers)
    original = fc_api.STREAM_LIFETIME_SECONDS
    fc_api.STREAM_LIFETIME_SECONDS = 0.5
    try:
        res = client.get("/api/v1/finora-core/events/stream", headers={**headers, "Last-Event-ID": "0"})
        text = res.get_data(as_text=True)
    finally:
        fc_api.STREAM_LIFETIME_SECONDS = original
    assert res.headers["Content-Type"].startswith("text/event-stream")
    assert "event: conversation.updated" in text and "id: " in text


def test_sync_reanchors_when_the_house_database_is_recreated(env):
    """A restored / re-provisioned house DB restarts message ids; live events must not hide behind a stale cursor."""
    ids = _seed_house(env)
    from extensions import db
    from modules.ai_sales.models import AISalesMessage
    from modules.finora_core.models import FcEvent
    from modules.finora_core.store import core_session, set_setting, use_house
    from modules.finora_core.sync import _keys, sync_house

    with env.test_request_context():
        with core_session() as s:
            set_setting(s, _keys(HOUSE)[0], "999999", "test")  # cursor from a previous incarnation of the house DB
            s.commit()
        assert sync_house(force=True) == 0  # re-anchored, history not replayed
        with use_house():
            db.session.add(AISalesMessage(conversation_id=ids["c1"], channel_account_id=ids["ig"], direction="inbound",
                                          sender_type="customer", text_content="بعد الاستعادة", status="received"))
            db.session.commit()
        assert sync_house(force=True) >= 1
        with core_session() as s:
            texts = [json.loads(e.payload_json)["message"]["text"] for e in s.query(FcEvent).filter_by(type="message.received")]
    assert "بعد الاستعادة" in texts
