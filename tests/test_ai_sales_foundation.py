"""Regression tests for the Finora Sales AI foundation."""
import hashlib
import hmac
import io
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT_LOCAL = f"test_ai_sales_local_{os.getpid()}"
TENANT_WEBHOOK = f"test_ai_sales_webhook_{os.getpid()}"
TENANT_MEDIA = f"test_ai_sales_media_{os.getpid()}"
TENANT_META = f"test_ai_sales_meta_{os.getpid()}"
TENANT_META_PAGES = f"test_ai_sales_meta_pages_{os.getpid()}"
TENANT_INBOX = f"test_ai_sales_inbox_{os.getpid()}"
TENANT_ACTIONS = f"test_ai_sales_actions_{os.getpid()}"


def _fresh_tenant_db(tenant):
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_meta_expired_token_enters_persistent_cooldown_and_can_be_cleared():
    from datetime import datetime, timedelta

    from modules.ai_sales.channels import MetaMessagingClientError
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.ai_sales.routes import (
        _clear_meta_sync_failure,
        _meta_sync_is_blocked,
        _record_meta_sync_failure,
    )

    now = datetime(2026, 7, 14, 9, 0, 0)
    channel = AISalesChannelAccount(
        name="Expired Meta Page",
        channel_type="messenger",
        connection_status="connected",
        is_active=True,
    )
    error = MetaMessagingClientError(
        "Session has expired",
        status_code=401,
        meta_code=190,
    )

    requires_reconnect = _record_meta_sync_failure(channel, error, now)

    assert requires_reconnect is True
    assert channel.connection_status == "auth_expired"
    assert channel.last_sync_at == now
    assert channel.sync_blocked_until == now + timedelta(hours=12)
    assert _meta_sync_is_blocked(channel, now + timedelta(hours=1)) is True

    _clear_meta_sync_failure(channel)

    assert channel.connection_status == "ready"
    assert channel.sync_blocked_until is None
    assert channel.last_error is None


def test_ai_sales_local_reply_uses_live_product_data():
    tenant = TENANT_LOCAL
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from modules.ai_sales import agent
    from modules.ai_sales.engine import get_or_create_conversation, mark_customer_activity, process_inbound_message
    from modules.ai_sales.models import AISalesCall, AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.product_tools import search_products
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        db.session.add_all(
            [
                Product(name="شاشة Super Max 55", buy_price=250000, sale_price=325000, quantity=7, active=True),
                Product(name="شاشة جنرال حجم 50", buy_price=220000, sale_price=270000, quantity=5, active=True),
                Product(name="شاشة هيتاشي حجم 42", buy_price=160000, sale_price=195000, quantity=150, active=True),
                Product(name="ثلاجة شارب 5 قدم لون أبيض", buy_price=110000, sale_price=145000, quantity=3, active=True),
                Product(name="ثلاجة إيفولي 7 قدم", buy_price=130000, sale_price=169000, quantity=3, active=True),
            ]
        )
        channel = AISalesChannelAccount(name="Local Test", connection_status="simulator", is_active=False)
        db.session.add(channel)
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="9647700000011",
            phone="9647700000011",
            contact_name="أحمد",
        )
        inbound = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="local-1",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="عندكم شاشة 55؟",
            status="received",
        )
        db.session.add(inbound)
        db.session.flush()
        mark_customer_activity(conversation)
        db.session.commit()

        original = agent._openai_key
        agent._openai_key = lambda: ""
        try:
            outbound = process_inbound_message(inbound.id, send_external=False)
        finally:
            agent._openai_key = original

        assert outbound is not None
        assert "325,000" in outbound.text_content
        assert "متوفر 7" not in outbound.text_content
        assert "•" in outbound.text_content
        assert inbound.status == "processed"
        assert conversation.sales_stage == "product_selection"
        nearby = search_products("شاشة 55 بحدود 300 ألف", max_price=300000, limit=3)
        assert nearby[0]["name"] == "شاشة جنرال حجم 50"
        exact_fridge = search_products("أريد ثلاجة 5 قدم", limit=3)
        assert [row["name"] for row in exact_fridge] == ["ثلاجة شارب 5 قدم لون أبيض"]


def test_whatsapp_webhook_verification_signature_and_idempotency():
    tenant = TENANT_WEBHOOK
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from modules.ai_sales.models import AISalesCall, AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema
    from modules.ai_sales.security import encrypt_secret

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        channel = AISalesChannelAccount(
            name="Webhook Test",
            phone_number_id="12345",
            verify_token_encrypted=encrypt_secret("verify-me"),
            app_secret_encrypted=encrypt_secret("app-secret"),
            is_active=True,
        )
        db.session.add(channel)
        db.session.commit()
        webhook_key = channel.webhook_key

    client = app.test_client()
    verify = client.get(
        f"/api/v1/ai-sales/webhooks/whatsapp/{tenant}/{webhook_key}",
        query_string={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "777"},
    )
    assert verify.status_code == 200, (verify.status_code, verify.get_data(as_text=True))
    assert verify.get_data(as_text=True) == "777"

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "12345"},
                    "contacts": [{"wa_id": "9647700000099", "profile": {"name": "سارة"}}],
                    "messages": [{
                        "id": "wamid.test-image-1",
                        "from": "9647700000099",
                        "timestamp": "1783872000",
                        "type": "image",
                        "image": {"id": "media-1", "mime_type": "image/jpeg", "caption": "عندكم مثل هاي؟"},
                    }],
                },
                "field": "messages",
            }]
        }]
    }
    import json

    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    url = f"/api/v1/ai-sales/webhooks/whatsapp/{tenant}/{webhook_key}"
    first = client.post(url, data=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"})
    second = client.post(url, data=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"})
    assert first.status_code == 200
    assert second.status_code == 200

    call_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "12345"},
                    "contacts": [{
                        "wa_id": "9647700000099",
                        "user_id": "bsuid-99",
                        "profile": {"name": "سارة"},
                    }],
                    "calls": [{
                        "id": "wacid.test-1",
                        "from": "9647700000099",
                        "to": "9647700000000",
                        "from_user_id": "bsuid-99",
                        "event": "connect",
                        "direction": "USER_INITIATED",
                        "timestamp": "1783872001",
                        "session": {"sdp_type": "offer", "sdp": "secret-sdp-body"},
                    }],
                },
                "field": "calls",
            }]
        }]
    }
    call_raw = json.dumps(call_payload, separators=(",", ":")).encode("utf-8")
    call_signature = hmac.new(b"app-secret", call_raw, hashlib.sha256).hexdigest()
    call_response = client.post(
        url,
        data=call_raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={call_signature}"},
    )
    assert call_response.status_code == 200

    with app.app_context():
        g.tenant = tenant
        assert AISalesMessage.query.filter_by(external_message_id="wamid.test-image-1").count() == 1
        call = AISalesCall.query.filter_by(external_call_id="wacid.test-1").one()
        assert call.status == "ringing"
        assert call.direction == "USER_INITIATED"
        assert call.sdp_type == "offer"
        assert "secret-sdp-body" not in (call.raw_payload_json or "")
        assert "[REDACTED_SDP]" in (call.raw_payload_json or "")
        assert AISalesMessage.query.filter_by(external_message_id="call:wacid.test-1:connect").count() == 1


def test_voice_transcription_pipeline_and_approved_product_media():
    tenant = TENANT_MEDIA
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from modules.ai_sales import agent, engine as engine_module, media as media_module
    from modules.ai_sales.channels import MetaMessagingClient
    from modules.ai_sales.engine import get_or_create_conversation, process_inbound_message
    from modules.ai_sales.models import AISalesAgentProfile, AISalesChannelAccount, AISalesMessage, ProductMediaAsset
    from modules.ai_sales.product_tools import get_product_media
    from modules.ai_sales.schema import ensure_ai_sales_schema
    from modules.ai_sales.security import encrypt_secret

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        product = Product(name="راوتر Super Max", buy_price=90000, sale_price=125000, quantity=4, active=True)
        db.session.add(product)
        db.session.flush()
        db.session.add(
            ProductMediaAsset(
                product_id=product.id,
                media_type="image",
                storage_path="https://example.test/router.jpg",
                public_url="https://example.test/router.jpg",
                title="صورة الراوتر",
                ai_approved=True,
            )
        )
        channel = AISalesChannelAccount(name="Voice Test", connection_status="simulator", is_active=False)
        db.session.add(channel)
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="9647700000022",
            phone="9647700000022",
            contact_name="علي",
        )
        inbound = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="voice-1",
            direction="inbound",
            sender_type="customer",
            message_type="voice",
            transcription="أريد راوتر سعره مية وخمسة وعشرين ألف",
            status="received",
        )
        db.session.add(inbound)
        AISalesAgentProfile.query.first().voice_enabled = False
        db.session.commit()

        original = agent._openai_key
        agent._openai_key = lambda: ""
        try:
            outbound = process_inbound_message(inbound.id, send_external=False)
        finally:
            agent._openai_key = original

        assert outbound is not None
        assert "125,000" in outbound.text_content
        assets = get_product_media(product.id, "image")
        assert len(assets) == 1
        assert assets[0]["title"] == "صورة الراوتر"

        meta_channel = AISalesChannelAccount(
            channel_type="messenger",
            name="Messenger Voice Test",
            external_account_id="page-voice-1",
            access_token_encrypted=encrypt_secret("page-token"),
            connection_status="connected",
            is_active=True,
        )
        db.session.add(meta_channel)
        db.session.flush()
        meta_conversation = get_or_create_conversation(
            meta_channel,
            external_contact_id="psid-voice-1",
            phone=None,
            contact_name="Meta Voice Customer",
        )
        meta_audio = AISalesMessage(
            conversation_id=meta_conversation.id,
            channel_account_id=meta_channel.id,
            external_message_id="meta-voice-1",
            direction="inbound",
            sender_type="customer",
            message_type="audio",
            external_media_id="https://cdn.fbsbx.com/test/voice.ogg",
            mime_type="audio/ogg",
            status="received",
        )
        db.session.add(meta_audio)
        db.session.commit()

        original_download = MetaMessagingClient.download_media
        MetaMessagingClient.download_media = lambda self, url, max_bytes: (b"OggS-test-audio", "audio/ogg")
        try:
            stored_path = media_module.download_inbound_media(meta_audio)
        finally:
            MetaMessagingClient.download_media = original_download
        assert Path(stored_path).exists()
        Path(stored_path).unlink()

        failed_audio = AISalesMessage(
            conversation_id=meta_conversation.id,
            channel_account_id=meta_channel.id,
            external_message_id="meta-voice-failure",
            direction="inbound",
            sender_type="customer",
            message_type="audio",
            external_media_id="https://cdn.fbsbx.com/test/failure.ogg",
            status="received",
        )
        db.session.add(failed_audio)
        db.session.commit()
        original_transcribe = engine_module.transcribe_audio
        engine_module.transcribe_audio = lambda message: (_ for _ in ()).throw(RuntimeError("temporary media failure"))
        try:
            fallback = process_inbound_message(failed_audio.id, send_external=False)
        finally:
            engine_module.transcribe_audio = original_transcribe
        assert fallback is not None
        assert "التسجيل الصوتي" in fallback.text_content
        assert meta_conversation.ai_enabled is True
        assert meta_conversation.human_takeover is False

        profile = AISalesAgentProfile.query.first()
        profile.voice_enabled = True
        profile.voice_reply_mode = "match_customer"
        voice_reply_input = AISalesMessage(
            conversation_id=meta_conversation.id,
            channel_account_id=meta_channel.id,
            external_message_id="meta-voice-reply",
            direction="inbound",
            sender_type="customer",
            message_type="audio",
            transcription="السلام عليكم",
            status="received",
        )
        db.session.add(voice_reply_input)
        db.session.commit()
        fake_speech = ROOT / "test-meta-voice-reply.mp3"
        fake_speech.write_bytes(b"ID3-test-audio")
        original_key = agent._openai_key
        original_speech = engine_module.generate_speech
        agent._openai_key = lambda: ""
        engine_module.generate_speech = lambda *args, **kwargs: str(fake_speech)
        try:
            process_inbound_message(voice_reply_input.id, send_external=False)
        finally:
            agent._openai_key = original_key
            engine_module.generate_speech = original_speech
            fake_speech.unlink(missing_ok=True)
        voice_reply = (
            AISalesMessage.query
            .filter_by(conversation_id=meta_conversation.id, direction="outbound", message_type="audio")
            .order_by(AISalesMessage.id.desc())
            .first()
        )
        assert voice_reply is not None
        assert voice_reply.status == "sent"
        assert voice_reply.get_media_metadata().get("public_token")


def test_meta_webhook_routes_page_to_configured_employee():
    tenant = TENANT_META
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.employee import Employee
    from modules.ai_sales.channels import MetaMessagingClient
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation, AISalesMessage
    from modules.ai_sales.routes import _mark_missing_meta_channels_unavailable, api_meta_stop_ai
    from modules.ai_sales.schema import ensure_ai_sales_schema
    from modules.ai_sales.security import encrypt_secret

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        employee = Employee(name="موظف ماسنجر", username="messenger-agent", password="test", role="cashier", is_active=True)
        db.session.add(employee)
        db.session.flush()
        connector = AISalesChannelAccount(
            channel_type="meta",
            name="Meta Test",
            access_token_encrypted=encrypt_secret("user-token"),
            app_secret_encrypted=encrypt_secret("meta-secret"),
            verify_token_encrypted=encrypt_secret("meta-verify"),
            is_active=True,
        )
        db.session.add(connector)
        db.session.flush()
        page = AISalesChannelAccount(
            channel_type="messenger",
            name="Test Page",
            parent_channel_id=connector.id,
            external_account_id="page-123",
            page_id="page-123",
            access_token_encrypted=encrypt_secret("page-token"),
            reply_mode="employee",
            default_employee_id=employee.id,
            is_active=True,
        )
        db.session.add(page)
        db.session.commit()
        webhook_key = connector.webhook_key
        employee_id = employee.id
        connector_id = connector.id
        page_channel_id = page.id

    payload = {
        "object": "page",
        "entry": [{
            "id": "page-123",
            "messaging": [{
                "sender": {"id": "psid-789"},
                "recipient": {"id": "page-123"},
                "timestamp": 1783980000000,
                "message": {"mid": "mid.meta.1", "text": "السلام عليكم"},
            }],
        }],
    }
    import json

    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"meta-secret", raw, hashlib.sha256).hexdigest()
    original_profile = MetaMessagingClient.contact_profile
    MetaMessagingClient.contact_profile = lambda self, contact_id: {
        "name": "زبون ماسنجر",
        "profile_pic": "https://cdn.example.test/customer.jpg",
    }
    try:
        response = app.test_client().post(
            f"/api/v1/ai-sales/webhooks/meta/{tenant}/{webhook_key}",
            data=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"},
        )
    finally:
        MetaMessagingClient.contact_profile = original_profile
    assert response.status_code == 200, response.get_data(as_text=True)

    echo_payload = {
        "object": "page",
        "entry": [{
            "id": "page-123",
            "messaging": [{
                "sender": {"id": "page-123"},
                "recipient": {"id": "psid-789"},
                "timestamp": 1783980060000,
                "message": {
                    "mid": "mid.meta.echo.1",
                    "text": "تم الرد من تطبيق Meta",
                    "is_echo": True,
                },
            }],
        }],
    }
    raw = json.dumps(echo_payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"meta-secret", raw, hashlib.sha256).hexdigest()
    response = app.test_client().post(
        f"/api/v1/ai-sales/webhooks/meta/{tenant}/{webhook_key}",
        data=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"},
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    with app.app_context():
        g.tenant = tenant
        conversation = AISalesConversation.query.filter_by(external_contact_id="psid-789").one()
        assert conversation.assigned_employee_id == employee_id
        assert conversation.human_takeover is True
        assert conversation.ai_enabled is False
        assert conversation.contact_profile_picture_url == "https://cdn.example.test/customer.jpg"
        assert conversation.to_dict()["contact_profile_picture_url"] == "https://cdn.example.test/customer.jpg"
        assert AISalesMessage.query.filter_by(external_message_id="mid.meta.1").count() == 1
        echo = AISalesMessage.query.filter_by(external_message_id="mid.meta.echo.1").one()
        assert echo.conversation_id == conversation.id
        assert echo.direction == "outbound"
        assert echo.sender_type == "employee"
        assert echo.status == "sent"
        assert conversation.last_business_message_at == echo.sent_at
        with app.test_request_context("/ai-sales/api/meta/stop-ai", method="POST"):
            g.tenant = tenant
            session["user_id"] = employee_id
            session["role"] = "admin"
            response = api_meta_stop_ai()
            assert response.get_json()["mode"] == "inbox"
        page = AISalesChannelAccount.query.get(page_channel_id)
        conversation = AISalesConversation.query.filter_by(external_contact_id="psid-789").one()
        assert page.reply_mode == "inbox"
        assert page.default_employee_id == employee_id
        assert conversation.ai_enabled is False
        assert conversation.human_takeover is False
        assert conversation.assigned_employee_id == employee_id
        assert conversation.status == "open"
        inbox_conversation = get_or_create_conversation(
            page,
            external_contact_id="psid-inbox-only",
            phone="",
            contact_name="Inbox Customer",
        )
        assert inbox_conversation.ai_enabled is False
        assert inbox_conversation.human_takeover is False
        assert inbox_conversation.assigned_employee_id == employee_id
        assert inbox_conversation.status == "open"
        stale = AISalesChannelAccount(
            channel_type="messenger",
            name="Old Page",
            parent_channel_id=connector_id,
            external_account_id="old-page",
            is_active=True,
            connection_status="auth_expired",
        )
        db.session.add(stale)
        db.session.flush()
        missing_ids = _mark_missing_meta_channels_unavailable(
            AISalesChannelAccount.query.get(connector_id),
            [page_channel_id],
        )
        assert stale.id in missing_ids
        assert stale.is_active is False
        assert stale.connection_status == "unavailable"
        assert AISalesChannelAccount.query.get(page_channel_id).is_active is True


def test_meta_multi_page_management_keeps_tokens_private_and_scales_past_thirty_pages():
    tenant = TENANT_META_PAGES
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.employee import Employee
    from modules.ai_sales.channels import MetaMessagingClient
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation
    from modules.ai_sales import routes
    from modules.ai_sales.routes import api_channels, api_connect_meta_page, api_delete_meta_page, api_meta_pages_bulk, api_meta_sync_pages
    from modules.ai_sales.schema import ensure_ai_sales_schema
    from modules.ai_sales.security import encrypt_secret

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        admin = Employee(name="Meta Admin", username="meta-pages-admin", password="test", role="admin", is_active=True)
        db.session.add(admin)
        db.session.flush()
        connector = AISalesChannelAccount(
            channel_type="meta",
            name="Meta Multi Page",
            external_account_id="app-123",
            access_token_encrypted=encrypt_secret("legacy-user-token"),
            app_secret_encrypted=encrypt_secret("meta-app-secret"),
            verify_token_encrypted=encrypt_secret("private-verify-token"),
            is_active=True,
        )
        db.session.add(connector)
        db.session.flush()
        pages = []
        for index in range(35):
            page = AISalesChannelAccount(
                channel_type="messenger",
                name=f"Facebook Page {index + 1}",
                parent_channel_id=connector.id,
                external_account_id=f"page-{index + 1}",
                page_id=f"page-{index + 1}",
                access_token_encrypted=encrypt_secret(f"page-token-{index + 1}"),
                reply_mode="inbox",
                connection_status="connected",
                is_active=True,
            )
            db.session.add(page)
            pages.append(page)
        db.session.flush()
        conversation = get_or_create_conversation(
            pages[0],
            external_contact_id="multi-page-contact",
            phone="",
            contact_name="Multi Page Customer",
        )
        db.session.commit()
        page_ids = [page.id for page in pages]
        first_page_id = pages[0].id
        conversation_id = conversation.id
        admin_id = admin.id

        assert MetaMessagingClient(pages[0]).access_token == "page-token-1"
        assert MetaMessagingClient(connector, access_token="temporary-import-token").access_token == "temporary-import-token"

        client = MetaMessagingClient(connector)
        graph_calls = []

        def fake_request(method, path, *, params=None, payload=None):
            graph_calls.append((method, path, params))
            if len(graph_calls) == 1:
                return {
                    "data": [{"id": f"remote-{index}"} for index in range(30)],
                    "paging": {"next": "https://graph.facebook.com/v23.0/next-pages"},
                }
            return {"data": [{"id": f"remote-{index}"} for index in range(30, 35)]}

        client._request = fake_request
        assert len(client.list_pages()) == 35
        assert len(graph_calls) == 2

        original_meta_client = routes.MetaMessagingClient

        class FakeMetaClient:
            def __init__(self, channel, *, access_token=None):
                self.channel = channel
                if channel.channel_type == "meta":
                    assert access_token == "temporary-import-token"

            def configure_app_webhook(self, *args, **kwargs):
                return {"success": True}

            def list_pages(self):
                return [
                    {
                        "id": f"page-{index + 1}",
                        "name": f"Facebook Page {index + 1}",
                        "access_token": f"fresh-page-token-{index + 1}",
                    }
                    for index in range(35)
                ]

            def subscribe_page(self, page_id):
                return {"success": True, "page_id": page_id}

            def subscribe_instagram(self, instagram_id):
                return {"success": True, "instagram_id": instagram_id}

        routes.MetaMessagingClient = FakeMetaClient
        try:
            with app.test_request_context(
                f"/ai-sales/api/meta/sync-pages/{connector.id}",
                method="POST",
                json={"user_access_token": "temporary-import-token"},
            ):
                g.tenant = tenant
                session["user_id"] = admin_id
                session["role"] = "admin"
                result = api_meta_sync_pages(connector.id).get_json()
                assert result["pages_found"] == 35
        finally:
            routes.MetaMessagingClient = original_meta_client

        connector = AISalesChannelAccount.query.get(connector.id)
        assert connector.access_token_encrypted is None
        assert MetaMessagingClient(AISalesChannelAccount.query.get(first_page_id)).access_token == "fresh-page-token-1"

        class FakeManualMetaClient:
            def __init__(self, channel, *, access_token=None):
                assert channel.id == connector.id
                assert access_token == "manual-page-token"

            def account_profile(self):
                return {
                    "id": "page-1",
                    "name": "Facebook Page One",
                    "picture": {"data": {"url": "https://cdn.example.test/page-1.jpg"}},
                }

            def configure_app_webhook(self, *args, **kwargs):
                return {"success": True}

            def subscribe_page(self, page_id):
                assert page_id == "page-1"
                return {"success": True}

        routes.MetaMessagingClient = FakeManualMetaClient
        try:
            with app.test_request_context(
                "/ai-sales/api/meta/pages/manual",
                method="POST",
                json={"connector_id": connector.id, "page_access_token": "manual-page-token"},
            ):
                g.tenant = tenant
                session["user_id"] = admin_id
                session["role"] = "admin"
                result = api_connect_meta_page().get_json()
                assert result["success"] is True
                assert result["created"] is False
                assert result["channel"]["external_account_id"] == "page-1"
        finally:
            routes.MetaMessagingClient = original_meta_client

        manually_updated = AISalesChannelAccount.query.get(first_page_id)
        assert manually_updated.name == "Facebook Page One"
        assert manually_updated.profile_picture_url == "https://cdn.example.test/page-1.jpg"
        assert MetaMessagingClient(manually_updated).access_token == "manual-page-token"

        with app.test_request_context("/ai-sales/api/channels", method="GET"):
            g.tenant = tenant
            session["user_id"] = admin_id
            session["role"] = "admin"
            payload = api_channels().get_json()
            serialized = str(payload)
            assert all("verify_token" not in channel for channel in payload["channels"])
            assert "private-verify-token" not in serialized
            assert "legacy-user-token" not in serialized
            assert "page-token-1" not in serialized
            assert "manual-page-token" not in serialized

        with app.test_request_context(
            "/ai-sales/api/meta/pages/bulk",
            method="POST",
            json={"ids": page_ids, "action": "ai"},
        ):
            g.tenant = tenant
            session["user_id"] = admin_id
            session["role"] = "admin"
            result = api_meta_pages_bulk().get_json()
            assert result["pages_updated"] == 35

        assert AISalesChannelAccount.query.filter_by(parent_channel_id=connector.id, reply_mode="ai").count() == 35
        assert AISalesConversation.query.get(conversation_id).ai_enabled is True

        with app.test_request_context(f"/ai-sales/api/meta/pages/{first_page_id}", method="DELETE"):
            g.tenant = tenant
            session["user_id"] = admin_id
            session["role"] = "admin"
            result = api_delete_meta_page(first_page_id).get_json()
            assert result["archived"] is True

        removed = AISalesChannelAccount.query.get(first_page_id)
        assert removed.connection_status == "removed"
        assert removed.access_token_encrypted is None
        assert removed.is_active is False
        assert AISalesConversation.query.get(conversation_id) is not None
        assert AISalesConversation.query.get(conversation_id).ai_enabled is False


def test_inbox_read_close_reopen_and_incremental_messages():
    tenant = TENANT_INBOX
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.employee import Employee
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesChannelAccount, AISalesConversationRead, AISalesMessage
    from modules.ai_sales.routes import (
        api_close_conversation,
        api_conversations,
        api_mark_conversation_read,
        api_messages,
        api_reopen_conversation,
    )
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        employee = Employee(name="Inbox Admin", username="inbox-admin", password="test", role="admin", is_active=True)
        channel = AISalesChannelAccount(name="Inbox Test", reply_mode="ai", is_active=True)
        db.session.add_all([employee, channel])
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="9647700000066",
            phone="9647700000066",
            contact_name="زبون الصندوق",
        )
        first = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="inbox-1",
            direction="inbound",
            sender_type="customer",
            text_content="الرسالة الأولى",
            status="received",
        )
        second = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="inbox-2",
            direction="inbound",
            sender_type="customer",
            text_content="الرسالة الثانية",
            status="received",
        )
        db.session.add_all([first, second])
        db.session.commit()
        employee_id = employee.id
        conversation_id = conversation.id
        first_id = first.id

        with app.test_request_context("/ai-sales/api/conversations"):
            g.tenant = tenant
            session["user_id"] = employee_id
            session["role"] = "admin"
            payload = api_conversations().get_json()
            assert payload["conversations"][0]["unread_count"] == 2

        with app.test_request_context(f"/ai-sales/api/conversations/{conversation_id}/messages?after_id={first_id}"):
            g.tenant = tenant
            session["user_id"] = employee_id
            session["role"] = "admin"
            payload = api_messages(conversation_id).get_json()
            assert [row["text_content"] for row in payload["messages"]] == ["الرسالة الثانية"]

        outbound = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="inbox-reply-1",
            direction="outbound",
            sender_type="employee",
            text_content="تم الرد",
            status="sent",
        )
        db.session.add(outbound)
        db.session.commit()
        with app.test_request_context("/ai-sales/api/conversations"):
            g.tenant = tenant
            session["user_id"] = employee_id
            session["role"] = "admin"
            payload = api_conversations().get_json()
            assert payload["conversations"][0]["unread_count"] == 0

        third = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="inbox-3",
            direction="inbound",
            sender_type="customer",
            text_content="رسالة بعد الرد",
            status="received",
        )
        db.session.add(third)
        db.session.commit()
        with app.test_request_context("/ai-sales/api/conversations"):
            g.tenant = tenant
            session["user_id"] = employee_id
            session["role"] = "admin"
            payload = api_conversations().get_json()
            assert payload["conversations"][0]["unread_count"] == 1

        with app.test_request_context(f"/ai-sales/api/conversations/{conversation_id}/read", method="POST"):
            g.tenant = tenant
            session["user_id"] = employee_id
            session["role"] = "admin"
            assert api_mark_conversation_read(conversation_id).get_json()["unread_count"] == 0
            assert AISalesConversationRead.query.filter_by(conversation_id=conversation_id, employee_id=employee_id).count() == 1

        with app.test_request_context(f"/ai-sales/api/conversations/{conversation_id}/close", method="POST"):
            g.tenant = tenant
            session["user_id"] = employee_id
            session["role"] = "admin"
            closed = api_close_conversation(conversation_id).get_json()["conversation"]
            assert closed["status"] == "closed"
            assert closed["ai_enabled"] is False

        with app.test_request_context(f"/ai-sales/api/conversations/{conversation_id}/reopen", method="POST"):
            g.tenant = tenant
            session["user_id"] = employee_id
            session["role"] = "admin"
            reopened = api_reopen_conversation(conversation_id).get_json()["conversation"]
            assert reopened["status"] == "open"
            assert reopened["ai_enabled"] is True

        api_close_conversation_context = app.test_request_context(f"/ai-sales/api/conversations/{conversation_id}/close", method="POST")
        with api_close_conversation_context:
            g.tenant = tenant
            session["user_id"] = employee_id
            session["role"] = "admin"
            api_close_conversation(conversation_id)
        reopened_automatically = get_or_create_conversation(
            channel,
            external_contact_id="9647700000066",
            phone="9647700000066",
            contact_name="زبون الصندوق",
        )
        assert reopened_automatically.status == "open"
        assert reopened_automatically.ai_enabled is True


def test_message_actions_and_manual_media_delivery():
    tenant = TENANT_ACTIONS
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.employee import Employee
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
    from modules.ai_sales import routes
    from modules.ai_sales.schema import ensure_ai_sales_schema

    class FakeClient:
        def upload_media(self, path, mime_type):
            assert Path(path).exists()
            assert mime_type == "image/png"
            return "media-test-1"

        def send_media(self, recipient, media_type, **kwargs):
            assert recipient == "9647700000077"
            assert media_type == "image"
            assert kwargs["media_id"] == "media-test-1"
            return {"messages": [{"id": "wamid.media-test-1"}]}

        def send_text(self, recipient, text):
            assert recipient == "9647700000077"
            return {"messages": [{"id": "wamid.edited-test-1"}]}

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        employee = Employee(name="Media Admin", username="media-admin", password="test", role="admin", is_active=True)
        channel = AISalesChannelAccount(
            channel_type="whatsapp",
            name="Media Channel",
            phone_number_id="phone-media-test",
            is_active=True,
        )
        db.session.add_all([employee, channel])
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="9647700000077",
            phone="9647700000077",
            contact_name="زبون الوسائط",
        )
        failed = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            direction="outbound",
            sender_type="employee",
            message_type="text",
            text_content="نص قديم",
            status="failed",
        )
        db.session.add(failed)
        db.session.commit()
        employee_id = employee.id
        conversation_id = conversation.id
        failed_id = failed.id
        assert channel.to_dict()["channel_type"] == "whatsapp"

        original_client = routes.channel_client
        routes.channel_client = lambda _channel: FakeClient()
        try:
            with app.test_request_context(
                f"/ai-sales/api/conversations/{conversation_id}/send-media",
                method="POST",
                data={
                    "file": (io.BytesIO(b"\x89PNG\r\n\x1a\nfixture"), "product.png"),
                    "caption": "صورة المنتج",
                },
                content_type="multipart/form-data",
            ):
                g.tenant = tenant
                session["user_id"] = employee_id
                session["role"] = "admin"
                media_payload = routes.api_manual_send_media(conversation_id).get_json()
                assert media_payload["message"]["status"] == "sent"
                assert media_payload["message"]["message_type"] == "image"
                assert media_payload["message"]["original_filename"] == "product.png"
                media_id = media_payload["message"]["id"]

            media_message = db.session.get(AISalesMessage, media_id)
            public_token = media_message.get_media_metadata().get("public_token")
            with app.test_request_context(
                f"/ai-sales/public/media/{tenant}/{media_id}/{public_token}",
                method="GET",
            ):
                public_response = routes.public_tenant_message_media(tenant, media_id, public_token)
                assert public_response.status_code == 200
                assert public_response.mimetype == "image/png"

            with app.test_request_context(
                f"/ai-sales/api/messages/{failed_id}",
                method="PATCH",
                json={"text": "نص مصحح"},
            ):
                g.tenant = tenant
                session["user_id"] = employee_id
                session["role"] = "admin"
                edited = routes.api_message_action(failed_id).get_json()["message"]
                assert edited["text_content"] == "نص مصحح"
                assert edited["status"] == "sent"
                assert edited["edited_at"]

            with app.test_request_context(f"/ai-sales/api/messages/{media_id}", method="DELETE"):
                g.tenant = tenant
                session["user_id"] = employee_id
                session["role"] = "admin"
                deleted = routes.api_message_action(media_id).get_json()["message"]
                assert deleted["is_deleted"] is True
                assert deleted["media_url"] == ""

            with app.test_request_context(f"/ai-sales/api/messages/{failed_id}?scope=everyone", method="DELETE"):
                g.tenant = tenant
                session["user_id"] = employee_id
                session["role"] = "admin"
                response, status = routes.api_message_action(failed_id)
                assert status == 409
                assert response.get_json()["unsupported"] is True
        finally:
            routes.channel_client = original_client


if __name__ == "__main__":
    test_ai_sales_local_reply_uses_live_product_data()
    test_whatsapp_webhook_verification_signature_and_idempotency()
    test_voice_transcription_pipeline_and_approved_product_media()
    test_meta_webhook_routes_page_to_configured_employee()
    test_inbox_read_close_reopen_and_incremental_messages()
    test_message_actions_and_manual_media_delivery()
    print("Finora Sales AI foundation tests passed")
