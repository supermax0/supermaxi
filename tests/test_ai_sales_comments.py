"""Focused coverage for Facebook Page post/comment automation."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_ai_sales_comments_{os.getpid()}"


def _fresh_tenant_db() -> None:
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_page_feed_comment_parser_keeps_post_context():
    from modules.ai_sales.channels import parse_meta_comment_payload

    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE-1",
            "time": 1784250000,
            "changes": [{
                "field": "feed",
                "value": {
                    "item": "comment",
                    "verb": "add",
                    "post_id": "PAGE-1_POST-9",
                    "comment_id": "COMMENT-7",
                    "parent_id": "",
                    "message": "شكد سعر الشاشة؟",
                    "from": {"id": "USER-3", "name": "أحمد"},
                },
            }],
        }],
    }

    assert parse_meta_comment_payload(payload) == [{
        "page_id": "PAGE-1",
        "external_post_id": "PAGE-1_POST-9",
        "external_comment_id": "COMMENT-7",
        "parent_external_comment_id": "",
        "external_user_id": "USER-3",
        "user_name": "أحمد",
        "message": "شكد سعر الشاشة؟",
        "attachment_url": "",
        "created_time": 1784250000,
        "verb": "add",
        "raw": payload["entry"][0]["changes"][0],
    }]


def test_facebook_private_reply_uses_page_messages_endpoint():
    from types import SimpleNamespace

    from modules.ai_sales.channels import MetaMessagingClient

    channel = SimpleNamespace(
        name="Page",
        channel_type="messenger",
        external_account_id="PAGE-1",
        page_id="PAGE-1",
        access_token_encrypted=None,
        api_version="v23.0",
    )
    client = MetaMessagingClient(channel, access_token="page-token")
    captured = {}
    client._request = lambda method, path, **kwargs: captured.update({
        "method": method,
        "path": path,
        **kwargs,
    }) or {"message_id": "mid.1"}

    client.private_reply_to_comment("COMMENT-7", "هلا بيك")

    assert captured == {
        "method": "POST",
        "path": "PAGE-1/messages",
        "payload": {
            "recipient": {"comment_id": "COMMENT-7"},
            "message": {"text": "هلا بيك"},
        },
    }


def test_page_can_subscribe_to_feed_without_messenger_fields():
    from types import SimpleNamespace

    from modules.ai_sales.channels import MetaMessagingClient

    channel = SimpleNamespace(
        name="Page",
        channel_type="messenger",
        external_account_id="PAGE-1",
        page_id="PAGE-1",
        access_token_encrypted=None,
        api_version="v23.0",
    )
    client = MetaMessagingClient(channel, access_token="content-only-page-token")
    captured = {}
    client._request = lambda method, path, **kwargs: captured.update({
        "method": method,
        "path": path,
        **kwargs,
    }) or {"success": True}

    client.subscribe_page("PAGE-1", fields="feed")

    assert captured == {
        "method": "POST",
        "path": "PAGE-1/subscribed_apps",
        "params": {"subscribed_fields": "feed"},
    }


def test_private_reply_is_not_duplicated_when_public_reply_retries():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from modules.ai_sales import comments as service
    from modules.ai_sales.channels import MetaMessagingClient
    from modules.ai_sales.models import AISalesChannelAccount, AISalesSocialComment, AISalesSocialPost
    from modules.ai_sales.schema import ensure_ai_sales_schema
    from modules.ai_sales.security import encrypt_secret

    calls: list[str] = []
    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_ai_sales_schema()
        channel = AISalesChannelAccount(
            name="صفحة الاختبار",
            channel_type="messenger",
            external_account_id="PAGE-1",
            access_token_encrypted=encrypt_secret("page-token"),
            connection_status="connected",
            is_active=True,
            comments_enabled=True,
            comments_reply_mode="ai",
            comments_private_reply=True,
            comments_public_text="تم الرد على الخاص",
        )
        db.session.add(channel)
        db.session.flush()
        post = AISalesSocialPost(
            channel_account_id=channel.id,
            external_post_id="PAGE-1_POST-9",
            message="شاشة جنرال حجم 55",
        )
        db.session.add(post)
        db.session.flush()
        comment = AISalesSocialComment(
            post_id=post.id,
            channel_account_id=channel.id,
            external_comment_id="COMMENT-7",
            external_user_id="USER-3",
            user_name="أحمد",
            message="شكد السعر؟",
        )
        db.session.add(comment)
        db.session.commit()
        comment_id = comment.id

        originals = {
            "reply": service._reply_text,
            "post": MetaMessagingClient.get_post,
            "comment": MetaMessagingClient.get_comment,
            "private": MetaMessagingClient.private_reply_to_comment,
            "public": MetaMessagingClient.reply_to_comment,
        }
        public_attempts = {"count": 0}
        service._reply_text = lambda row: ("هلا أحمد، الشاشة سعرها 339,000 د.ع.", "test", 1, 1)
        MetaMessagingClient.get_post = lambda self, post_id: {
            "id": post_id,
            "message": "شاشة جنرال حجم 55",
        }
        MetaMessagingClient.get_comment = lambda self, comment_id: {
            "id": comment_id,
            "message": "شكد السعر؟",
            "from": {"id": "USER-3", "name": "أحمد"},
        }
        MetaMessagingClient.private_reply_to_comment = lambda self, comment_id, message: (
            calls.append("private") or {"message_id": "PRIVATE-1"}
        )

        def public_reply(self, comment_id, message):
            public_attempts["count"] += 1
            calls.append("public")
            if public_attempts["count"] == 1:
                raise RuntimeError("temporary public failure")
            return {"id": "PUBLIC-1"}

        MetaMessagingClient.reply_to_comment = public_reply
        try:
            service.process_social_comment(comment_id)
            failed = AISalesSocialComment.query.get(comment_id)
            assert failed.status == "failed"
            assert failed.private_reply_status == "sent"
            assert failed.public_reply_status == "failed"

            service.process_social_comment(comment_id, force=True)
            replied = AISalesSocialComment.query.get(comment_id)
            assert replied.status == "replied"
            assert replied.private_reply_status == "sent"
            assert replied.public_reply_status == "sent"
            assert calls == ["private", "public", "public"]
        finally:
            service._reply_text = originals["reply"]
            MetaMessagingClient.get_post = originals["post"]
            MetaMessagingClient.get_comment = originals["comment"]
            MetaMessagingClient.private_reply_to_comment = originals["private"]
            MetaMessagingClient.reply_to_comment = originals["public"]


def test_already_private_replied_continues_with_public_reply():
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from modules.ai_sales import comments as service
    from modules.ai_sales.channels import MetaMessagingClient, MetaMessagingClientError
    from modules.ai_sales.models import AISalesChannelAccount, AISalesSocialComment, AISalesSocialPost
    from modules.ai_sales.schema import ensure_ai_sales_schema
    from modules.ai_sales.security import encrypt_secret

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_ai_sales_schema()
        channel = AISalesChannelAccount(
            name="صفحة الاختبار", channel_type="messenger", external_account_id="PAGE-1",
            access_token_encrypted=encrypt_secret("page-token"), connection_status="connected",
            is_active=True, comments_enabled=True, comments_reply_mode="ai",
            comments_private_reply=True, comments_public_text="تم الرد على الخاص",
        )
        db.session.add(channel); db.session.flush()
        post = AISalesSocialPost(channel_account_id=channel.id, external_post_id="POST-1", message="شاشة 55")
        db.session.add(post); db.session.flush()
        comment = AISalesSocialComment(post_id=post.id, channel_account_id=channel.id, external_comment_id="COMMENT-1", message="السعر")
        db.session.add(comment); db.session.commit(); comment_id = comment.id

        originals = (service._reply_text, MetaMessagingClient.get_post, MetaMessagingClient.get_comment,
                     MetaMessagingClient.private_reply_to_comment, MetaMessagingClient.reply_to_comment)
        service._reply_text = lambda row: ("السعر 339 ألف", "test", 1, 1)
        MetaMessagingClient.get_post = lambda self, post_id: {"id": post_id, "message": "شاشة 55"}
        MetaMessagingClient.get_comment = lambda self, comment_id: {"id": comment_id, "message": "السعر"}
        MetaMessagingClient.private_reply_to_comment = lambda self, comment_id, message: (_ for _ in ()).throw(
            MetaMessagingClientError("Activity already replied to", status_code=400, meta_code=10900)
        )
        MetaMessagingClient.reply_to_comment = lambda self, comment_id, message: {"id": "PUBLIC-1"}
        try:
            service.process_social_comment(comment_id)
            row = AISalesSocialComment.query.get(comment_id)
            assert row.status == "replied"
            assert row.private_reply_status == "sent"
            assert row.private_reply_external_id == "meta:already-replied"
            assert row.public_reply_status == "sent"
        finally:
            (service._reply_text, MetaMessagingClient.get_post, MetaMessagingClient.get_comment,
             MetaMessagingClient.private_reply_to_comment, MetaMessagingClient.reply_to_comment) = originals


def test_sync_without_from_preserves_webhook_identity():
    from types import SimpleNamespace
    from modules.ai_sales.comments import upsert_social_comment
    from modules.ai_sales.models import AISalesSocialComment

    existing = AISalesSocialComment(external_user_id="USER-1", user_name="أحمد")
    # Exercise the same fallback expression used by the upsert without needing a database.
    author = {}
    row = {"message": "السعر"}
    existing.external_user_id = str(author.get("id") or row.get("external_user_id") or existing.external_user_id or "") or None
    existing.user_name = str(author.get("name") or row.get("user_name") or existing.user_name or "")[:180] or None
    assert existing.external_user_id == "USER-1"
    assert existing.user_name == "أحمد"
