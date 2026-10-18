"""Shared fixture for FINORA CORE backend tests: isolated Flask app (temporary SQLite Core DB + house tenant) and a
fake Graph API. No request ever reaches Meta and no real customer is messaged."""
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

HOUSE = "finora_house"
SECRET = "0123456789abcdef0123456789abcdef"
PAGE_ID = "1000001"
IG_ID = "17840000001"
PASSWORD = "correct horse battery"


# ───────────────────────────── fake Graph API ─────────────────────────────


class FakeResponse:
    def __init__(self, status: int, body: Any, headers: dict | None = None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body)
        self.url = ""

    def json(self):
        return self._body


class FakeGraph:
    """Routes Graph calls by (method, path suffix). Unmatched GETs return an empty profile."""

    def __init__(self):
        self.calls: list[dict] = []
        self.queue: dict[tuple[str, str], list[FakeResponse]] = {}

    def on(self, method: str, suffix: str, *responses: FakeResponse) -> None:
        self.queue.setdefault((method, suffix), []).extend(responses)

    def __call__(self, method, url, headers=None, params=None, json=None, timeout=None):  # noqa: A002
        self.calls.append({"method": method, "url": url, "params": params, "json": json})
        for (m, suffix), items in self.queue.items():
            if m == method and url.split("?")[0].endswith(suffix) and items:
                item = items.pop(0) if len(items) > 1 else items[0]
                return item(json) if callable(item) else item
        if method == "GET":
            return FakeResponse(200, {})
        return FakeResponse(500, {"error": {"message": "unexpected call in test", "code": 1}})

    def sends(self) -> list[dict]:
        return [c for c in self.calls if c["method"] == "POST" and c["url"].endswith("/messages")]


_mid_counter = [0]


def unique_mid(_payload=None) -> FakeResponse:
    """Successful Send API response with a fresh message id (provider ids are unique per channel)."""
    _mid_counter[0] += 1
    return FakeResponse(200, {"recipient_id": "x", "message_id": f"m_sent_{_mid_counter[0]}"})


def meta_error(status: int, code: int, subcode: int | None = None, headers: dict | None = None) -> FakeResponse:
    err = {"message": f"meta error {code}", "code": code}
    if subcode is not None:
        err["error_subcode"] = subcode
    return FakeResponse(status, {"error": err}, headers)


# ───────────────────────────── fixtures ─────────────────────────────


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FINORA_CORE_HOUSE_TENANT", HOUSE)
    monkeypatch.setenv("FINORA_ENV", "production")
    monkeypatch.setenv("FINORA_CORE_DEV_LOOPBACK", "1")  # must be ignored in production
    monkeypatch.delenv("META_REQUIRE_SIGNATURE", raising=False)
    import models  # noqa: F401
    import models.delivery_agent  # noqa: F401
    import extensions_tenant
    from extensions import db
    from models.core.super_admin import SuperAdmin
    from modules.ai_sales import channels as ai_channels
    from modules.ai_sales import meta_policy, routes as ai_routes
    from modules.ai_sales import schema as ai_schema
    from modules.finora_core import auth as fc_auth
    from modules.finora_core import init_finora_core
    from modules.finora_core import store as fc_store
    from modules.finora_core import sync as fc_sync

    monkeypatch.setattr(extensions_tenant, "_tenant_engines", {})
    monkeypatch.setattr(fc_store, "_HOUSE_SCHEMA_READY", set())
    monkeypatch.setattr(ai_schema, "_DEDUPE_INDEX_DONE", set())
    monkeypatch.setattr(fc_auth, "_failures", {})
    monkeypatch.setattr(fc_sync, "_last_run", 0.0)
    monkeypatch.setattr(fc_sync, "_last_maintenance", 0.0)
    meta_policy.reset_for_tests()

    graph = FakeGraph()
    monkeypatch.setattr(ai_channels.requests, "request", graph)
    dispatched: list[int] = []
    monkeypatch.setattr(ai_routes, "dispatch_inbound_async", lambda app, slug, mid, send_external=True: dispatched.append(mid))
    monkeypatch.setattr(ai_routes, "dispatch_attachment_storage_async", lambda app, slug, ids: None)

    app = Flask(__name__, root_path=str(tmp_path))
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'core.db'}", SECRET_KEY="test-secret", TESTING=True)
    db.init_app(app)
    with app.app_context():
        SuperAdmin.__table__.create(bind=db.engine, checkfirst=True)
        admin = SuperAdmin(username="owner")
        admin.set_password(PASSWORD)
        db.session.add(admin)
        db.session.commit()
    init_finora_core(app)
    app.register_blueprint(ai_routes.ai_sales_webhook_bp)
    ids = _seed(app)
    yield {"app": app, "graph": graph, "dispatched": dispatched, **ids}


def _seed(app) -> dict[str, Any]:
    from extensions import db
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.ai_sales.security import encrypt_secret
    from modules.finora_core.store import use_house

    from extensions_tenant import init_tenant_db

    with app.test_request_context():
        g.tenant = HOUSE
        init_tenant_db(HOUSE)  # exactly how `flask finora-house init` provisions the house tenant
        from modules.facebook_routing.schema import ensure_facebook_routing_schema

        ensure_facebook_routing_schema()
        db.session.commit()
        g.pop("tenant", None)
        with use_house():
            connector = AISalesChannelAccount(channel_type="meta", name="FINORA Meta", is_active=True,
                                              connection_status="connected", app_secret_encrypted=encrypt_secret(SECRET),
                                              verify_token_encrypted=encrypt_secret("verify-me"))
            db.session.add(connector)
            db.session.flush()
            fb = AISalesChannelAccount(channel_type="messenger", name="FINORA FB", parent_channel_id=connector.id,
                                       external_account_id=PAGE_ID, page_id=PAGE_ID, is_active=True, reply_mode="ai",
                                       connection_status="connected", access_token_encrypted=encrypt_secret("PAGE-TOKEN-SECRET"))
            ig = AISalesChannelAccount(channel_type="instagram", name="FINORA IG", parent_channel_id=connector.id,
                                       external_account_id=IG_ID, page_id=PAGE_ID, is_active=True, reply_mode="ai",
                                       connection_status="connected", access_token_encrypted=encrypt_secret("PAGE-TOKEN-SECRET"))
            db.session.add_all([fb, ig])
            db.session.commit()
            return {"key": connector.webhook_key, "connector": connector.id, "fb": fb.id, "ig": ig.id}


def now_ms() -> int:
    """Meta timestamps are epoch milliseconds (UTC). Never derive them from naive utcnow().timestamp()."""
    return int(time.time() * 1000)


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(env, payload: dict, *, signature: str | None = "auto"):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        headers["X-Hub-Signature-256"] = _sign(body)
    elif signature:
        headers["X-Hub-Signature-256"] = signature
    return env["app"].test_client().post(f"/api/v1/ai-sales/webhooks/meta/{HOUSE}/{env['key']}", data=body, headers=headers)


def _message_event(*, platform="page", account=PAGE_ID, sender="cust-1", mid="m_1", text="مرحبا", ts=None, attachments=None):
    message: dict[str, Any] = {"mid": mid}
    if text is not None:
        message["text"] = text
    if attachments is not None:
        message["attachments"] = attachments
    ts = ts or now_ms()
    return {"object": platform, "entry": [{"id": account, "time": ts, "messaging": [
        {"sender": {"id": sender}, "recipient": {"id": account}, "timestamp": ts, "message": message}]}]}


def _messages(env, **filters):
    from modules.ai_sales.models import AISalesMessage
    from modules.finora_core.store import use_house

    with env["app"].test_request_context():
        with use_house():
            return [
                {"id": m.id, "mid": m.external_message_id, "text": m.text_content, "status": m.status,
                 "direction": m.direction, "created_at": m.created_at, "conversation_id": m.conversation_id,
                 "meta": m.get_media_metadata(), "type": m.message_type}
                for m in AISalesMessage.query.filter_by(**filters).order_by(AISalesMessage.id).all()
            ]


def _channel_status(env, channel_id: int) -> str:
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.finora_core.store import use_house

    with env["app"].test_request_context():
        with use_house():
            return AISalesChannelAccount.query.get(channel_id).connection_status


def _auth(env) -> dict[str, str]:
    res = env["app"].test_client().post("/api/v1/finora-core/auth/login", json={"username": "owner", "password": PASSWORD})
    return {"Authorization": f"Bearer {res.get_json()['accessToken']}"}


def _api(env, method: str, path: str, **kw):
    client = env["app"].test_client()
    return getattr(client, method)(f"/api/v1/finora-core{path}", **kw)


