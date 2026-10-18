"""Phase 7 — FINORA house tenant on Meta (Messenger + Instagram) through the existing ai_sales pipeline.

Isolated app (temporary SQLite Core DB + house tenant DB) and a fake Graph API: no request ever reaches Meta and no
real customer is messaged."""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from flask import Flask, g

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.finora_core_support import (  # noqa: F401  shared fixture + helpers
    FakeResponse,
    FakeGraph,
    meta_error,
    env,
    now_ms,
    _seed,
    _sign,
    _post,
    _message_event,
    _messages,
    _channel_status,
    _auth,
    _api,
    HOUSE,
    SECRET,
    PAGE_ID,
    IG_ID,
    PASSWORD,
)


# ───────────────────────────── webhook security ─────────────────────────────


def test_webhook_verification_challenge(env):
    client = env["app"].test_client()
    base = f"/api/v1/ai-sales/webhooks/meta/{HOUSE}/{env['key']}"
    ok = client.get(f"{base}?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=CHALLENGE-42")
    assert ok.status_code == 200 and ok.get_data(as_text=True) == "CHALLENGE-42"
    assert client.get(f"{base}?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=x").status_code == 403
    assert client.get(f"{base}?hub.mode=unsubscribe&hub.verify_token=verify-me&hub.challenge=x").status_code == 403


def test_valid_signature_stores_message_and_queues_ai(env):
    res = _post(env, _message_event(mid="m_valid", text="عندي عيادة"))
    assert res.status_code == 200
    rows = _messages(env, external_message_id="m_valid")
    assert len(rows) == 1 and rows[0]["direction"] == "inbound" and rows[0]["status"] == "received"
    assert env["dispatched"] == [rows[0]["id"]]


def test_invalid_signature_is_rejected_and_repeated_failures_mark_webhook_invalid(env):
    for _ in range(3):
        res = _post(env, _message_event(mid="m_forged"), signature="sha256=" + "0" * 64)
        assert res.status_code == 403
    assert _messages(env, external_message_id="m_forged") == []
    assert _channel_status(env, env["connector"]) == "webhook_invalid"
    status = _api(env, "get", "/status", headers=_auth(env)).get_json()
    assert status["channels"] == {"instagram": "webhook_invalid", "facebook": "webhook_invalid", "telegram": "disconnected"}
    # A correctly signed event clears it again.
    assert _post(env, _message_event(mid="m_after")).status_code == 200
    assert _channel_status(env, env["connector"]) == "connected"


def test_missing_signature_header_is_rejected(env):
    assert _post(env, _message_event(mid="m_nosig"), signature=None).status_code == 403
    assert _messages(env, external_message_id="m_nosig") == []


@pytest.mark.parametrize("stored_secret", ["", "not-a-meta-secret", "UNDECRYPTABLE"])
def test_missing_or_unusable_secret_fails_closed_in_production(env, stored_secret):
    from extensions import db
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.ai_sales.security import encrypt_secret
    from modules.finora_core.store import use_house

    with env["app"].test_request_context():
        with use_house():
            c = AISalesChannelAccount.query.get(env["connector"])
            c.app_secret_encrypted = (
                "gAAAAA-corrupted" if stored_secret == "UNDECRYPTABLE" else (encrypt_secret(stored_secret) if stored_secret else None)
            )
            db.session.commit()
    res = _post(env, _message_event(mid="m_unverified"))
    assert res.status_code == 503 and res.get_json()["error"] == "webhook_not_configured"
    assert _messages(env, external_message_id="m_unverified") == []
    assert _channel_status(env, env["connector"]) == "webhook_invalid"


def test_customer_tenants_keep_their_existing_behaviour(env, monkeypatch):
    from modules.ai_sales.meta_policy import signature_required

    assert signature_required(HOUSE) is True
    assert signature_required("some-customer") is False
    monkeypatch.setenv("META_REQUIRE_SIGNATURE", "1")
    assert signature_required("some-customer") is True


# ───────────────────────────── dedupe, retries, ordering ─────────────────────────────


def test_duplicate_event_from_meta_retry_is_stored_and_answered_once(env):
    payload = _message_event(mid="m_dup", text="سؤال")
    assert _post(env, payload).status_code == 200
    assert _post(env, payload).status_code == 200  # Meta retry of the same delivery
    assert len(_messages(env, external_message_id="m_dup")) == 1
    assert len(env["dispatched"]) == 1


def test_duplicate_message_inside_one_payload_is_stored_once(env):
    payload = _message_event(mid="m_twice")
    payload["entry"].append(json.loads(json.dumps(payload["entry"][0])))
    assert _post(env, payload).status_code == 200
    assert len(_messages(env, external_message_id="m_twice")) == 1


def test_database_enforces_one_row_per_provider_message_id(env):
    from sqlalchemy.exc import IntegrityError

    from extensions import db
    from modules.ai_sales.models import AISalesMessage
    from modules.finora_core.store import use_house

    _post(env, _message_event(mid="m_unique"))
    conv_id = _messages(env, external_message_id="m_unique")[0]["conversation_id"]
    with env["app"].test_request_context():
        with use_house():
            db.session.add(AISalesMessage(conversation_id=conv_id, channel_account_id=env["fb"], direction="inbound",
                                          sender_type="customer", external_message_id="m_unique", status="received"))
            with pytest.raises(IntegrityError):
                db.session.flush()
            db.session.rollback()


def test_out_of_order_events_are_shown_in_event_order(env):
    later = now_ms()
    earlier = later - 30_000
    _post(env, _message_event(mid="m_B", text="الثانية", ts=later))
    _post(env, _message_event(mid="m_A", text="الأولى", ts=earlier))  # arrives second, happened first
    headers = _auth(env)
    conv_id = _messages(env, external_message_id="m_B")[0]["conversation_id"]
    items = _api(env, "get", f"/conversations/{conv_id}/messages", headers=headers).get_json()["items"]
    assert [m["text"] for m in items] == ["الأولى", "الثانية"]
    from modules.ai_sales.models import AISalesConversation
    from modules.finora_core.store import use_house

    with env["app"].test_request_context():
        with use_house():
            conv = AISalesConversation.query.get(conv_id)
            assert abs((conv.last_customer_message_at - datetime.utcfromtimestamp(later / 1000)).total_seconds()) < 1


def test_delayed_event_older_than_our_reply_is_stored_but_not_auto_answered(env):
    from extensions import db
    from modules.ai_sales.models import AISalesConversation
    from modules.finora_core.store import use_house

    _post(env, _message_event(mid="m_first", text="مرحبا"))
    conv_id = _messages(env, external_message_id="m_first")[0]["conversation_id"]
    with env["app"].test_request_context():
        with use_house():
            conv = AISalesConversation.query.get(conv_id)
            conv.last_business_message_at = datetime.utcnow()  # we already replied
            db.session.commit()
    stale = now_ms() - 10 * 60 * 1000
    env["dispatched"].clear()
    assert _post(env, _message_event(mid="m_stale", text="رسالة متأخرة", ts=stale)).status_code == 200
    assert len(_messages(env, external_message_id="m_stale")) == 1
    assert env["dispatched"] == []


def test_deleted_message_notification_is_not_a_new_message(env):
    payload = _message_event(mid="m_deleted")
    payload["entry"][0]["messaging"][0]["message"]["is_deleted"] = True
    assert _post(env, payload).status_code == 200
    assert _messages(env, external_message_id="m_deleted") == []


# ───────────────────────────── outbound: success, receipts, failures ─────────────────────────────


def _conversation_for(env, *, platform="page", account=PAGE_ID, sender="cust-out"):
    _post(env, _message_event(platform=platform, account=account, sender=sender, mid=f"m_seed_{sender}", text="أهلاً"))
    conv_id = _messages(env, external_message_id=f"m_seed_{sender}")[0]["conversation_id"]
    headers = _auth(env)
    assert _api(env, "post", f"/conversations/{conv_id}/takeover", headers=headers).status_code == 200
    return conv_id, headers


def _send(env, conv_id, headers, text="رد من الفريق", key="k1"):
    return _api(env, "post", f"/conversations/{conv_id}/messages", json={"text": text},
                headers={**headers, "Idempotency-Key": key})


def test_successful_facebook_message_then_delivery_and_read_receipts(env):
    conv_id, headers = _conversation_for(env)
    env["graph"].on("POST", f"{PAGE_ID}/messages", FakeResponse(200, {"recipient_id": "cust-out", "message_id": "m_out_fb_1"}))
    res = _send(env, conv_id, headers)
    assert res.status_code == 201
    assert res.get_json()["message"]["delivery"] == "sent"
    sent = env["graph"].sends()[-1]
    assert sent["json"]["recipient"] == {"id": "cust-out"} and sent["json"]["messaging_type"] == "RESPONSE"
    assert "PAGE-TOKEN-SECRET" not in json.dumps(res.get_json())
    ts = now_ms() + 1000
    delivery = {"object": "page", "entry": [{"id": PAGE_ID, "messaging": [
        {"sender": {"id": "cust-out"}, "recipient": {"id": PAGE_ID}, "delivery": {"mids": ["m_out_fb_1"], "watermark": ts}}]}]}
    assert _post(env, delivery).get_json()["receipts"] == 1
    assert _messages(env, external_message_id="m_out_fb_1")[0]["status"] == "delivered"
    read = {"object": "page", "entry": [{"id": PAGE_ID, "messaging": [
        {"sender": {"id": "cust-out"}, "recipient": {"id": PAGE_ID}, "read": {"watermark": ts + 1000}}]}]}
    _post(env, read)
    assert _messages(env, external_message_id="m_out_fb_1")[0]["status"] == "read"
    items = _api(env, "get", f"/conversations/{conv_id}/messages", headers=headers).get_json()["items"]
    assert items[-1]["delivery"] == "read"


def test_successful_instagram_message_and_read_receipt_by_mid(env):
    conv_id, headers = _conversation_for(env, platform="instagram", account=IG_ID, sender="ig-user")
    env["graph"].on("POST", f"{IG_ID}/messages", FakeResponse(200, {"recipient_id": "ig-user", "message_id": "m_out_ig_1"}))
    res = _send(env, conv_id, headers, key="ig1")
    assert res.status_code == 201
    sent = env["graph"].sends()[-1]
    assert sent["url"].endswith(f"{IG_ID}/messages") and "messaging_type" not in sent["json"]
    read = {"object": "instagram", "entry": [{"id": IG_ID, "messaging": [
        {"sender": {"id": "ig-user"}, "recipient": {"id": IG_ID}, "read": {"mid": "m_out_ig_1"}}]}]}
    _post(env, read)
    assert _messages(env, external_message_id="m_out_ig_1")[0]["status"] == "read"


def test_receipt_never_resurrects_a_failed_message(env):
    conv_id, headers = _conversation_for(env)
    env["graph"].on("POST", f"{PAGE_ID}/messages", meta_error(400, 100))
    assert _send(env, conv_id, headers).status_code == 502
    ts = now_ms() + 5000
    _post(env, {"object": "page", "entry": [{"id": PAGE_ID, "messaging": [
        {"sender": {"id": "cust-out"}, "recipient": {"id": PAGE_ID}, "read": {"watermark": ts}}]}]})
    rows = [m for m in _messages(env, conversation_id=conv_id) if m["direction"] == "outbound"]
    assert rows[-1]["status"] == "failed"


def test_success_without_message_id_is_not_reported_as_sent(env):
    conv_id, headers = _conversation_for(env)
    env["graph"].on("POST", f"{PAGE_ID}/messages", FakeResponse(200, {"recipient_id": "cust-out"}))
    res = _send(env, conv_id, headers)
    assert res.status_code == 502 and res.get_json()["message"]["delivery"] == "failed"


@pytest.mark.parametrize(
    ("response", "channel_state", "desktop_state"),
    [
        (meta_error(401, 190, 463), "auth_expired", "token_expired"),
        (meta_error(400, 190), "token_invalid", "token_expired"),
        (meta_error(403, 10), "permission_missing", "permission_missing"),
        (meta_error(400, 200), "permission_missing", "permission_missing"),
    ],
    ids=["token-expired", "invalid-token", "missing-permission-10", "missing-permission-200"],
)
def test_auth_and_permission_failures_fail_the_message_and_update_health(env, response, channel_state, desktop_state):
    conv_id, headers = _conversation_for(env)
    env["graph"].on("POST", f"{PAGE_ID}/messages", response)
    res = _send(env, conv_id, headers)
    assert res.status_code == 502 and res.get_json()["message"]["delivery"] == "failed"
    assert _channel_status(env, env["fb"]) == channel_state
    status = _api(env, "get", "/status", headers=headers).get_json()
    assert status["channels"]["facebook"] == desktop_state
    assert status["channels"]["instagram"] == "connected"  # the other channel is unaffected


def test_policy_failure_does_not_mark_the_channel_unhealthy(env):
    conv_id, headers = _conversation_for(env)
    env["graph"].on("POST", f"{PAGE_ID}/messages", meta_error(400, 10, 2018278))  # outside the 24h window
    assert _send(env, conv_id, headers).status_code == 502
    assert _channel_status(env, env["fb"]) == "connected"


def test_rate_limit_is_retried_with_backoff_without_losing_the_message(env):
    from modules.ai_sales.meta_retry import retry_due
    from modules.finora_core.store import use_house

    conv_id, headers = _conversation_for(env)
    env["graph"].on("POST", f"{PAGE_ID}/messages", meta_error(429, 4, headers={"Retry-After": "30"}))
    res = _send(env, conv_id, headers)
    assert res.status_code == 202 and res.get_json()["message"]["delivery"] == "sending"
    row = [m for m in _messages(env, conversation_id=conv_id) if m["direction"] == "outbound"][-1]
    assert row["status"] == "retry_scheduled"
    next_at = datetime.fromisoformat(row["meta"]["send"]["next_attempt_at"])
    assert next_at >= datetime.utcnow() + timedelta(seconds=25)  # Meta's Retry-After honoured
    env["graph"].queue.clear()
    env["graph"].on("POST", f"{PAGE_ID}/messages", FakeResponse(200, {"message_id": "m_after_429"}))
    with env["app"].test_request_context():
        with use_house():
            assert retry_due(now=datetime.utcnow())["sent"] == 0  # not due yet
            assert retry_due(now=next_at + timedelta(seconds=1))["sent"] == 1
    assert _messages(env, external_message_id="m_after_429")[0]["status"] == "sent"
    assert _channel_status(env, env["fb"]) == "connected"


def test_meta_5xx_retries_then_gives_up_as_failed(env):
    from modules.ai_sales.meta_reliability import MAX_SEND_ATTEMPTS
    from modules.ai_sales.meta_retry import retry_due
    from modules.finora_core.store import use_house

    conv_id, headers = _conversation_for(env)
    env["graph"].on("POST", f"{PAGE_ID}/messages", meta_error(503, 2))
    assert _send(env, conv_id, headers).status_code == 202
    future = datetime.utcnow()
    with env["app"].test_request_context():
        with use_house():
            for _ in range(MAX_SEND_ATTEMPTS):
                future += timedelta(hours=1)
                retry_due(now=future)
    row = [m for m in _messages(env, conversation_id=conv_id) if m["direction"] == "outbound"][-1]
    assert row["status"] == "failed" and row["meta"]["send"]["attempts"] == MAX_SEND_ATTEMPTS
    assert _channel_status(env, env["fb"]) == "connected"  # Meta outage is not a channel credential problem


def test_failed_outbound_shows_failed_on_desktop(env):
    conv_id, headers = _conversation_for(env)
    env["graph"].on("POST", f"{PAGE_ID}/messages", meta_error(400, 100))
    body = _send(env, conv_id, headers).get_json()
    assert body["error"]["code"] == "META_SEND_FAILED"
    items = _api(env, "get", f"/conversations/{conv_id}/messages", headers=headers).get_json()["items"]
    assert items[-1]["delivery"] == "failed"


def test_dev_loopback_is_never_used_in_production(env):
    from modules.finora_core.transport import loopback_enabled

    assert loopback_enabled() is False  # FINORA_CORE_DEV_LOOPBACK=1 is set, FINORA_ENV=production
    conv_id, headers = _conversation_for(env)
    env["graph"].on("POST", f"{PAGE_ID}/messages", FakeResponse(200, {"message_id": "m_real_send"}))
    assert _send(env, conv_id, headers).status_code == 201
    assert env["graph"].sends(), "production must call Meta, not the loopback"


def test_ordered_reply_parts_wait_behind_a_rate_limited_part(env):
    from extensions import db
    from modules.ai_sales.meta_reliability import record_send_failure
    from modules.ai_sales.meta_retry import retry_due
    from modules.ai_sales.channels import MetaMessagingClientError
    from modules.ai_sales.models import AISalesConversation, AISalesMessage
    from modules.finora_core.store import use_house

    conv_id, _ = _conversation_for(env, sender="parts")
    with env["app"].test_request_context():
        with use_house():
            conv = AISalesConversation.query.get(conv_id)
            first = AISalesMessage(conversation_id=conv_id, channel_account_id=env["fb"], direction="outbound",
                                   sender_type="ai", text_content="جزء 1", status="queued")
            second = AISalesMessage(conversation_id=conv_id, channel_account_id=env["fb"], direction="outbound",
                                    sender_type="ai", text_content="جزء 2", status="retry_scheduled")
            db.session.add_all([first, second])
            db.session.flush()
            record_send_failure(first, conv.channel, MetaMessagingClientError("rl", status_code=429, meta_code=4),
                                now=datetime.utcnow())
            db.session.commit()
            env["graph"].on("POST", f"{PAGE_ID}/messages", FakeResponse(200, {"message_id": "mid_part"}))
            retry_due(now=datetime.utcnow())  # part 1 not due yet → part 2 must not jump ahead
            assert AISalesMessage.query.get(second.id).status == "retry_scheduled"
            assert not env["graph"].sends()


# ───────────────────────────── attachments ─────────────────────────────


def test_attachment_event_keeps_every_attachment_with_safe_metadata(env):
    attachments = [
        {"type": "image", "payload": {"url": "https://scontent.xx.fbcdn.net/v/screenshot.png?sig=abc"}},
        {"type": "file", "payload": {"url": "https://cdn.fbsbx.com/v/quote.pdf?sig=def", "name": "../../etc/quote.pdf"}},
        {"type": "audio", "payload": {"url": "https://cdn.fbsbx.com/v/voice.mp4?sig=ghi"}},
        {"type": "template", "payload": {"template_type": "generic"}},
    ]
    assert _post(env, _message_event(mid="m_att", text=None, attachments=attachments)).status_code == 200
    row = _messages(env, external_message_id="m_att")[0]
    items = row["meta"]["attachments"]
    assert [a["kind"] for a in items] == ["image", "document", "audio", "unsupported"]
    assert items[1]["name"] == "quote.pdf"  # path stripped
    assert items[0]["status"] == "pending" and items[3]["status"] == "unsupported"

    headers = _auth(env)
    msgs = _api(env, "get", f"/conversations/{row['conversation_id']}/messages", headers=headers).get_json()["items"]
    view = msgs[-1]
    assert view["text"] == "[صورة] +3"
    dumped = json.dumps(view)
    assert "fbcdn" not in dumped and "sig=" not in dumped and "stored_path" not in dumped
    assert [a["kind"] for a in view["attachments"]] == ["image", "document", "audio", "unsupported"]


def test_attachment_storage_downloads_hashes_and_never_breaks_on_failure(env, tmp_path):
    from extensions import db
    from modules.ai_sales.attachments import store_message_attachments
    from modules.ai_sales.channels import MetaMessagingClientError
    from modules.ai_sales.models import AISalesMessage
    from modules.finora_core.store import use_house

    attachments = [
        {"type": "image", "payload": {"url": "https://scontent.xx.fbcdn.net/v/a.png?sig=1"}},
        {"type": "image", "payload": {"url": "https://scontent.xx.fbcdn.net/v/b.png?sig=2"}},
        {"type": "image", "payload": {"url": "https://evil.example.com/c.png"}},  # not an allowed Meta host
    ]
    _post(env, _message_event(mid="m_store", text="شوف الصورة", attachments=attachments))

    def downloader(url, max_bytes):
        if "b.png" in url:
            raise MetaMessagingClientError("expired CDN link", status_code=403)
        return b"\x89PNG-fake-bytes", "image/png"

    with env["app"].test_request_context():
        with use_house() as slug:
            message = AISalesMessage.query.filter_by(external_message_id="m_store").first()
            assert store_message_attachments(message, message.conversation.channel, slug, downloader=downloader) == 1
            db.session.commit()
            items = message.get_media_metadata()["attachments"]
    assert [a["status"] for a in items] == ["stored", "failed", "not_downloadable"]
    assert items[0]["sha256"] and items[0]["source_url"] is None and items[0]["size_bytes"] == len(b"\x89PNG-fake-bytes")
    assert (Path(env["app"].root_path) / "uploads" / "ai_sales_media" / HOUSE / items[0]["stored_path"]).exists()


def test_unsupported_message_does_not_break_the_conversation(env):
    payload = _message_event(mid="m_unsup", text=None)
    payload["entry"][0]["messaging"][0]["message"]["is_unsupported"] = True
    assert _post(env, payload).status_code == 200
    row = _messages(env, external_message_id="m_unsup")[0]
    assert row["type"] == "unsupported"
    headers = _auth(env)
    items = _api(env, "get", f"/conversations/{row['conversation_id']}/messages", headers=headers).get_json()["items"]
    assert items[-1]["text"] == "[مرفق غير مدعوم]"


# ───────────────────────────── kill switch + realtime ─────────────────────────────


def test_kill_switch_while_messages_are_arriving(env, monkeypatch):
    from modules.ai_sales import engine
    from modules.ai_sales.models import AISalesMessage
    from modules.finora_core.store import use_house

    headers = _auth(env)
    assert _api(env, "post", "/automation", json={"paused": True, "reason": "اختبار"}, headers=headers).status_code == 200
    for i in range(3):
        assert _post(env, _message_event(mid=f"m_paused_{i}", sender="busy", text=f"رسالة {i}")).status_code == 200
    stored = _messages(env, conversation_id=_messages(env, external_message_id="m_paused_0")[0]["conversation_id"])
    assert len(stored) == 3  # every inbound message collected
    monkeypatch.setattr(engine, "_external_auto_reply_enabled", lambda: True)
    with env["app"].test_request_context():
        with use_house():
            for row in stored:
                assert engine.process_inbound_message(row["id"]) is None
            assert {m.status for m in AISalesMessage.query.filter(AISalesMessage.id.in_([r["id"] for r in stored]))} == {"received"}
    assert env["graph"].sends() == []  # no automatic reply left the building


def test_desktop_receives_a_live_event_from_a_real_normalized_meta_event(env):
    from modules.finora_core import api as fc_api
    from modules.finora_core.sync import sync_house

    headers = _auth(env)
    with env["app"].test_request_context():
        sync_house(force=True)  # anchor cursor
    _post(env, _message_event(mid="m_live", sender="live-user", text="أريد عرض سعر"))
    original = fc_api.STREAM_LIFETIME_SECONDS
    fc_api.STREAM_LIFETIME_SECONDS = 1.5
    try:
        res = _api(env, "get", "/events/stream", headers={**headers, "Last-Event-ID": "0"})
        stream = res.get_data(as_text=True)
    finally:
        fc_api.STREAM_LIFETIME_SECONDS = original
    received = [json.loads(block.split("data: ", 1)[1]) for block in stream.split("\n\n")
                if "event: message.received" in block]
    assert any(e["message"]["text"] == "أريد عرض سعر" and e["message"]["sender"] == "customer" for e in received)
    assert "PAGE-TOKEN-SECRET" not in stream and SECRET not in stream


# ───────────────────────────── activation + health ─────────────────────────────


def test_activation_fails_closed_without_a_valid_app_secret(env):
    from modules.finora_core.meta_house import ActivationError, connect_meta, validate_app_secret

    with pytest.raises(ActivationError, match="missing"):
        validate_app_secret("123456", "")
    with pytest.raises(ActivationError, match="malformed"):
        validate_app_secret("123456", "short")
    with pytest.raises(ActivationError, match="rejected"):
        validate_app_secret("123456", SECRET, http_get=lambda *a, **k: FakeResponse(400, {"error": {"code": 190}}))
    validate_app_secret("123456", SECRET, http_get=lambda *a, **k: FakeResponse(200, {"id": "123456"}))
    with env["app"].test_request_context():
        with pytest.raises(ActivationError):
            connect_meta(app_id="123456", app_secret="bad", user_token="t")


def test_live_health_check_detects_missing_webhook_subscription(env):
    env["graph"].on("GET", f"{PAGE_ID}/subscribed_apps", FakeResponse(200, {"data": []}))
    env["graph"].on("GET", IG_ID, FakeResponse(200, {"id": IG_ID}))
    res = _api(env, "post", "/channels/health-check", headers=_auth(env))
    assert res.status_code == 200
    assert res.get_json()["channels"] == {"facebook": "webhook_invalid", "instagram": "connected", "telegram": "disconnected"}


def test_live_health_check_detects_expired_token(env):
    env["graph"].on("GET", IG_ID, meta_error(401, 190, 463))
    env["graph"].on("GET", f"{PAGE_ID}/subscribed_apps", FakeResponse(200, {"data": [{"id": "app"}]}))
    body = _api(env, "post", "/channels/health-check", headers=_auth(env)).get_json()
    assert body["channels"]["instagram"] == "token_expired"
    assert body["channels"]["facebook"] == "connected"


def test_tokens_and_secrets_never_reach_the_desktop(env):
    headers = _auth(env)
    _post(env, _message_event(mid="m_leak", text="hello"))
    blobs = [
        _api(env, "get", "/status", headers=headers).get_data(as_text=True),
        _api(env, "get", "/conversations", headers=headers).get_data(as_text=True),
    ]
    conv_id = _messages(env, external_message_id="m_leak")[0]["conversation_id"]
    blobs.append(_api(env, "get", f"/conversations/{conv_id}/messages", headers=headers).get_data(as_text=True))
    blobs.append(_api(env, "get", f"/customers/{conv_id}", headers=headers).get_data(as_text=True))
    for blob in blobs:
        assert "PAGE-TOKEN-SECRET" not in blob and SECRET not in blob and "verify-me" not in blob


def test_customer_reply_in_the_same_second_as_our_reply_is_not_late(env):
    """Meta timestamps are whole seconds; a fast customer answer must still be answered (regression, Phase 8)."""
    from extensions import db
    from modules.ai_sales.models import AISalesConversation
    from modules.finora_core.store import use_house

    _post(env, _message_event(mid="m_fast_1", text="مرحبا"))
    conv_id = _messages(env, external_message_id="m_fast_1")[0]["conversation_id"]
    with env["app"].test_request_context():
        with use_house():
            conv = AISalesConversation.query.get(conv_id)
            conv.last_business_message_at = datetime.utcnow()  # we just replied (sub-second precision)
            db.session.commit()
    env["dispatched"].clear()
    assert _post(env, _message_event(mid="m_fast_2", text="تمام", ts=now_ms())).status_code == 200
    assert len(env["dispatched"]) == 1
