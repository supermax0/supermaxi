"""Actual Flask/brain/approval pipeline; only Telegram's network is simulated."""
import io
import json
import time
from datetime import datetime

import pytest
import requests
from PIL import Image

from tests.finora_core_support import env, _api, _auth, _messages, FakeResponse  # noqa: F401
from tests.test_finora_core_brain import brain, core  # noqa: F401
from tests.test_finora_core_account_brain import decision

TOKEN = "12345678:" + "A" * 35
BOT = {"id": 12345678, "is_bot": True, "first_name": "FINORA", "username": "FINORA_test_bot"}


@pytest.mark.parametrize("base,override,expected", [
    ("https://finora.company", "", "https://www.finora.company"),
    ("https://www.finora.company", "", "https://www.finora.company"),
    ("https://finora.company", "https://support.example.com/core", "https://support.example.com/core"),
])
def test_webhook_uses_final_canonical_origin(base, override, expected, monkeypatch):
    from flask import Flask
    from types import SimpleNamespace
    from modules.finora_core.telegram_api import webhook_url
    app = Flask(__name__)
    app.config["BASE_URL"] = base
    app.add_url_rule("/api/v1/finora-core/webhooks/telegram/<key>", endpoint="finora_core.telegram_webhook")
    monkeypatch.setenv("FINORA_CORE_PUBLIC_URL", override)
    with app.test_request_context():
        assert webhook_url(SimpleNamespace(webhook_key="test-key")) == expected + "/api/v1/finora-core/webhooks/telegram/test-key"


class FakeTelegram:
    def __init__(self):
        self.calls = []
        self.webhook = ""
        self.secret = ""
        self.fail = {}
        self.n = 100
        self.download_path = "photos/file_1.jpg"

    def post(self, url, *, json=None, data=None, files=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        body = json if json is not None else data
        self.calls.append((method, body, bool(files)))
        if method in self.fail:
            status = self.fail[method]
            return FakeResponse(status, {"ok": False, "error_code": status, "description": f"secret {TOKEN}",
                                         "parameters": {"retry_after": 20}})
        if method == "getMe":
            result = BOT
        elif method == "setWebhook":
            self.webhook, self.secret = body["url"], body["secret_token"]
            result = True
        elif method == "getWebhookInfo":
            result = {"url": self.webhook, "pending_update_count": 0}
        elif method == "deleteWebhook":
            self.webhook = ""
            result = True
        elif method == "getFile":
            result = {"file_path": self.download_path, "file_size": 20}
        elif method.startswith("send"):
            self.n += 1
            result = {"message_id": self.n, "chat": {"id": int(body["chat_id"])}}
        else:
            raise AssertionError(method)
        return FakeResponse(200, {"ok": True, "result": result})


@pytest.fixture()
def telegram(brain, monkeypatch):
    from modules.ai_sales import engine, attachments
    from modules.ai_sales.telegram import requests as telegram_requests
    fake = FakeTelegram()
    monkeypatch.setattr(telegram_requests, "post", fake.post)
    monkeypatch.setattr(engine, "dispatch_inbound_async", lambda app, slug, mid, send_external=True: brain["dispatched"].append(mid))
    monkeypatch.setattr(attachments, "dispatch_storage_async", lambda app, slug, ids: None)
    brain["auth"] = _auth(brain)
    res = _api(brain, "post", "/settings/telegram/connect", headers=brain["auth"], json={"botToken": TOKEN})
    assert res.status_code == 200, res.get_json()
    brain["telegram"] = fake
    brain["telegram_settings"] = res.get_json()
    return brain


def update(text="هلا", *, uid=12345, mid=1, **extra):
    return {"update_id": mid, "message": {"message_id": mid, "date": int(time.time()), "text": text,
            "chat": {"id": uid, "type": "private"}, "from": {"id": uid, "is_bot": False, "first_name": "عميل تلگرام"}, **extra}}


def post(telegram, payload, *, secret="valid", path=None):
    headers = {"X-Telegram-Bot-Api-Secret-Token": telegram["telegram"].secret if secret == "valid" else secret} if secret else {}
    return telegram["app"].test_client().post(path or telegram["telegram_settings"]["webhookUrl"].split("www.finora.company", 1)[1],
                                              json=payload, headers=headers)


def say(telegram, text, uid=12345):
    from modules.ai_sales.engine import process_inbound_message
    from modules.finora_core.store import use_house
    say.n = getattr(say, "n", 1000) + 1
    telegram["dispatched"].clear()
    res = post(telegram, update(text, uid=uid, mid=say.n))
    assert res.status_code == 200, res.get_json()
    with telegram["app"].test_request_context(), use_house():
        for mid in telegram["dispatched"]:
            process_inbound_message(mid)
    rows = _messages(telegram, direction="outbound")
    return rows[-1]["text"] if rows else None


def test_connect_encrypted_secret_hidden_and_no_meta_mix(telegram):
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.ai_sales.security import decrypt_secret
    from modules.finora_core.store import use_house
    data = telegram["telegram_settings"]
    assert data["status"] == "connected" and data["botUrl"] == "https://t.me/FINORA_test_bot"
    assert TOKEN not in json.dumps(data) and telegram["telegram"].secret not in json.dumps(data)
    with telegram["app"].test_request_context(), use_house():
        channel = AISalesChannelAccount.query.filter_by(channel_type="telegram").one()
        assert channel.access_token_encrypted != TOKEN and decrypt_secret(channel.access_token_encrypted) == TOKEN
        assert decrypt_secret(channel.verify_token_encrypted) == telegram["telegram"].secret
    assert _api(telegram, "get", "/status", headers=telegram["auth"]).get_json()["channels"]["telegram"] == "connected"
    meta = _api(telegram, "get", "/settings/meta", headers=telegram["auth"]).get_json()
    assert all(row["type"] != "telegram" for row in meta["channels"])
    setup = next(body for method, body, _ in telegram["telegram"].calls if method == "setWebhook")
    assert setup["allowed_updates"] == ["message"] and "drop_pending_updates" not in setup


def test_settings_requires_auth_and_bad_token_preserves_connection(telegram):
    assert _api(telegram, "get", "/settings/telegram").status_code == 401
    assert _api(telegram, "post", "/settings/telegram/connect", headers=telegram["auth"], json={"botToken": "bad"}).status_code == 400
    telegram["telegram"].fail["getMe"] = 401
    response = _api(telegram, "post", "/settings/telegram/connect", headers=telegram["auth"], json={"botToken": TOKEN})
    assert response.status_code == 400 and TOKEN not in response.get_data(as_text=True)
    assert _api(telegram, "get", "/settings/telegram", headers=telegram["auth"]).get_json()["status"] == "connected"


@pytest.mark.parametrize("secret", [None, "wrong", "سر غير صحيح"])
def test_webhook_rejects_untrusted_secret(telegram, secret):
    assert post(telegram, update(), secret=secret).status_code == 403
    assert _messages(telegram) == []


@pytest.mark.parametrize("change", ["group", "bot", "sender", "edit"])
def test_webhook_ignores_non_private_customer_identity(telegram, change):
    payload = update()
    if change == "group":
        payload["message"]["chat"]["type"] = "group"
    elif change == "bot":
        payload["message"]["from"]["is_bot"] = True
    elif change == "sender":
        payload["message"]["from"]["id"] = 777
    else:
        payload["edited_message"] = payload.pop("message")
    assert post(telegram, payload).get_json()["ignored"]
    assert _messages(telegram) == []


def test_private_ingestion_dedupes_by_chat_and_bot_and_channel_filter(telegram):
    assert post(telegram, update("عميل واحد")).status_code == 200
    assert post(telegram, update("عميل واحد")).get_json()["duplicate"]
    assert post(telegram, update("عميل ثاني", uid=98765)).status_code == 200
    rows = _messages(telegram)
    assert len(rows) == 2 and {r["mid"] for r in rows} == {"tg:12345:1", "tg:98765:1"}
    listing = _api(telegram, "get", "/conversations?channel=telegram", headers=telegram["auth"])
    assert listing.status_code == 200
    assert len(listing.get_json()["items"]) == 2
    assert all(c["channel"] == "telegram" for c in listing.get_json()["items"])


def test_disconnected_bot_rejects_webhooks_retains_history(telegram):
    post(telegram, update())
    res = _api(telegram, "post", "/settings/telegram/disconnect", headers=telegram["auth"])
    assert res.get_json()["active"] is False
    assert post(telegram, update(mid=2)).status_code == 403
    assert len(_messages(telegram)) == 1
    body = next(body for method, body, _ in telegram["telegram"].calls if method == "deleteWebhook")
    assert body["drop_pending_updates"] is False


def test_health_and_webhook_registration_failure_are_truthful(telegram):
    telegram["telegram"].webhook = "https://elsewhere.invalid/secret"
    response = _api(telegram, "post", "/settings/telegram/health-check", headers=telegram["auth"])
    assert response.get_json()["status"] == "webhook_invalid"
    assert "elsewhere" not in response.get_data(as_text=True)
    telegram["telegram"].fail["setWebhook"] = 500
    response = _api(telegram, "post", "/settings/telegram/connect", headers=telegram["auth"], json={"botToken": TOKEN})
    assert response.status_code == 400 and TOKEN not in response.get_data(as_text=True)
    assert _api(telegram, "get", "/settings/telegram", headers=telegram["auth"]).get_json()["status"] == "webhook_invalid"


def test_social_account_consultation_trial_approval_and_tenant_configuration(telegram):
    from tests.test_finora_core_brain import say as social_say
    from tests.finora_core_support import IG_ID
    def say(state, text, uid=12345):
        return social_say(state, text, sender=str(uid), platform="instagram", account=IG_ID)
    from extensions import db
    from models.core.subscription_plan import SubscriptionPlan
    from utils.tenant_feature_flags import TENANT_FEATURE_LABELS
    from modules.finora_core.brain.models import FcCustomerIdentity
    from extensions_tenant import get_tenant_engine
    from models.tenant import Tenant
    from sqlalchemy.orm import Session
    with telegram["app"].app_context():
        SubscriptionPlan.query.filter_by(plan_key="basic").one().set_features({key: True for key in TENANT_FEATURE_LABELS})
        db.session.commit()
    assert "مفرد، جملة" in say(telegram, "عندي محل أجهزة كهربائية شنو الميزات الي احتاجها تنصحني؟")
    assert "تقسيط" in say(telegram, "مفرد")
    assert "صيانة" in say(telegram, "نعم")
    assert "توصيل" in say(telegram, "نعم")
    reply = say(telegram, "لا")
    assert "المخزون" in reply and "الأقساط" in reply and "الصيانة" in reply
    assert _api(telegram, "get", "/approvals", headers=telegram["auth"]).get_json()["items"] == []
    assert "طلب حسابك" in say(telegram, "سوولي حساب تجريبي بهذا الاقتراح اسم المحل نور للأجهزة ورقمي 07701234567")
    items = _api(telegram, "get", "/approvals", headers=telegram["auth"]).get_json()["items"]
    assert len(items) == 1
    result = decision(telegram, items[0])
    assert result.status_code == 200, result.get_json()
    slug = result.get_json()["credentials"]["tenantSlug"]
    with telegram["app"].app_context(), Session(get_tenant_engine(slug)) as local:
        features = json.loads(local.query(Tenant).one().feature_overrides_json)
        assert features["inventory"] and features["installments"] and features["maintenance"]
        assert not features["clinics"] and not features["shipping"]
    assert core(telegram, lambda s: s.query(FcCustomerIdentity).filter_by(kind="instagram_id", value="12345").count()) == 1
    assert telegram["graph"].sends()
    assert not any(method == "sendMessage" for method, _, _ in telegram["telegram"].calls)
    assert all(row["status"] == "sent" and row["mid"].startswith("m_sent_") for row in _messages(telegram, direction="outbound"))
    assert "اقتراح ترتيب لحسابك وحده" in say(telegram, "اخفي التقارير بحسابي")
    proposal = _api(telegram, "get", "/approvals", headers=telegram["auth"]).get_json()["items"][0]
    assert proposal["preview"]["accountScope"]["tenantSlug"] == slug
    say(telegram, "اخفي التقارير بحسابي", uid=77777)
    assert len(_api(telegram, "get", "/approvals", headers=telegram["auth"]).get_json()["items"]) == 1
    identities = core(telegram, lambda s: [row.customer_id for row in s.query(FcCustomerIdentity).filter_by(kind="instagram_id").all()])
    assert len(set(identities)) == 2


def test_shadow_kill_switch_and_human_takeover_do_not_send(telegram):
    from tests.test_finora_core_phase9 import _flags
    _flags(telegram, AI_SHADOW_MODE="on")
    say(telegram, "عندي محل ورد واريد نظام")
    assert _messages(telegram, direction="outbound") == []
    _flags(telegram, AI_SHADOW_MODE="off")
    _api(telegram, "post", "/automation", headers=telegram["auth"], json={"paused": True, "reason": "اختبار"})
    say(telegram, "اريد اسعار فينورا", uid=22222)
    assert _messages(telegram, direction="outbound") == []
    _api(telegram, "post", "/automation", headers=telegram["auth"], json={"paused": False, "reason": "انتهى الاختبار"})
    assert post(telegram, update("هلا", uid=33333)).status_code == 200
    cid = _messages(telegram, external_message_id="tg:33333:1")[0]["conversation_id"]
    assert _api(telegram, "post", f"/conversations/{cid}/takeover", headers=telegram["auth"]).status_code == 200
    say(telegram, "سوولي حساب", uid=33333)
    assert _messages(telegram, direction="outbound") == []


@pytest.mark.parametrize("field,kind,mime", [("photo", "image", "image/jpeg"), ("video", "video", "video/mp4"), ("voice", "audio", "audio/ogg")])
def test_inbound_media_stored_privately(telegram, monkeypatch, field, kind, mime):
    from modules.ai_sales.telegram import TelegramBotClient
    from modules.ai_sales.attachments import store_message_attachments, public_view
    from modules.ai_sales.models import AISalesMessage
    from modules.finora_core.store import use_house
    row = {"file_id": "opaque-file-id", "file_size": 20, "mime_type": mime}
    payload = update("", **{field: [row] if field == "photo" else row})
    assert post(telegram, payload).status_code == 200
    monkeypatch.setattr(TelegramBotClient, "download_file", lambda self, file_id, max_bytes: (b"media bytes", mime))
    with telegram["app"].test_request_context(), use_house() as slug:
        message = AISalesMessage.query.filter_by(direction="inbound").one()
        assert store_message_attachments(message, message.conversation.channel, slug) == 1
        item = message.get_media_metadata()["attachments"][0]
        assert item["kind"] == kind and item["status"] == "stored"
        assert "telegram_file_id" not in public_view([item])[0]
        assert TOKEN not in json.dumps(message.get_media_metadata())


def test_manual_image_upload_reaches_telegram_once(telegram):
    post(telegram, update())
    cid = _messages(telegram)[0]["conversation_id"]
    _api(telegram, "post", f"/conversations/{cid}/takeover", headers=telegram["auth"])
    content = io.BytesIO()
    Image.new("RGB", (32, 32), "purple").save(content, "PNG")
    def upload():
        return _api(telegram, "post", f"/conversations/{cid}/media", headers={**telegram["auth"], "Idempotency-Key": "telegram-image"},
                    data={"file": (io.BytesIO(content.getvalue()), "photo.png", "image/png")})
    response = upload()
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["message"]["delivery"] == "sent"
    assert upload().get_json()["message"]["id"] == response.get_json()["message"]["id"]
    assert sum(method == "sendPhoto" for method, _, _ in telegram["telegram"].calls) == 1


def test_transport_failure_redacts_token_and_preserves_other_customers(telegram):
    from modules.ai_sales.telegram import TelegramBotClient, TelegramError
    from modules.ai_sales.meta_reliability import classify, health_for
    assert classify(TelegramError()).retryable
    assert health_for(classify(TelegramError(403))) is None
    assert classify(TelegramError(429, 20)).retry_after == 20
    telegram["telegram"].fail["sendMessage"] = 403
    with pytest.raises(TelegramError) as error:
        TelegramBotClient(token=TOKEN).send_text("12345", "test")
    assert TOKEN not in str(error.value)
    assert _api(telegram, "get", "/status", headers=telegram["auth"]).get_json()["channels"]["telegram"] == "connected"


def test_download_bounds_path_and_stream_do_not_expose_secret(telegram, monkeypatch):
    from modules.ai_sales.telegram import TelegramBotClient, TelegramError
    client = TelegramBotClient(token=TOKEN)
    telegram["telegram"].download_path = "../invalid"
    with pytest.raises(TelegramError):
        client.download_file("opaque", max_bytes=30)
    telegram["telegram"].download_path = "photos/file.jpg"
    class Stream:
        status_code = 200
        headers = {"Content-Type": "image/jpeg"}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def iter_content(self, size): yield b"x" * 31
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Stream())
    with pytest.raises(TelegramError) as error:
        client.download_file("opaque", max_bytes=30)
    assert TOKEN not in str(error.value)
