import requests
from types import SimpleNamespace

from utils.meta_graph import GRAPH_API_VERSION, GRAPH_BASE


def test_meta_graph_default_is_current_supported_release():
    assert GRAPH_API_VERSION == "v25.0"
    assert GRAPH_BASE == "https://graph.facebook.com/v25.0"


def test_monitor_token_check_uses_shared_graph_release(monkeypatch):
    from modules.facebook_monitor import routes

    called = {}

    class Response:
        def json(self):
            return {
                "data": {
                    "is_valid": True,
                    "type": "PAGE",
                    "profile_id": "123",
                    "scopes": ["pages_messaging"],
                }
            }

    def fake_get(url, **kwargs):
        called["url"] = url
        called["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)
    result = routes._inspect_token("page-token")

    assert result["ok"] is True
    assert result["profile_id"] == "123"
    assert called["url"] == f"{GRAPH_BASE}/debug_token"


def test_page_webhook_subscription_uses_shared_graph_release(monkeypatch):
    from modules.facebook_monitor import webhook

    called = {}

    class Response:
        def json(self):
            return {"success": True}

    def fake_post(url, **kwargs):
        called["url"] = url
        called["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr(webhook.requests, "post", fake_post)

    assert webhook.subscribe_page("123", "page-token") == ""
    assert called["url"] == f"{GRAPH_BASE}/123/subscribed_apps"


def test_expired_page_token_error_is_actionable_in_arabic():
    from modules.facebook_monitor.routes import _graph_error_text

    message = _graph_error_text({
        "error": {
            "code": 190,
            "message": "Error validating access token: Session has expired.",
        }
    })

    assert "رمز الصفحة منتهي" in message
    assert "Page Access Token" in message


def test_messenger_conversation_listing_follows_graph_pagination():
    from modules.ai_sales.channels import MetaMessagingClient

    channel = SimpleNamespace(
        page_id="page-123",
        external_account_id="page-123",
        channel_type="messenger",
        api_version="v25.0",
    )
    client = MetaMessagingClient(channel, access_token="page-token")
    calls = []

    def fake_request(method, path, *, params=None, payload=None):
        calls.append((method, path, params))
        if len(calls) == 1:
            return {
                "data": [{"id": f"thread-{index}"} for index in range(100)],
                "paging": {"next": "https://graph.facebook.com/v25.0/next-page"},
            }
        return {"data": [{"id": f"thread-{index}"} for index in range(100, 125)]}

    client._request = fake_request
    conversations = client.list_conversations(limit=125)

    assert len(conversations) == 125
    assert calls[0][1] == "page-123/conversations"
    assert calls[0][2]["limit"] == 100
    assert calls[1][1] == "https://graph.facebook.com/v25.0/next-page"
    assert calls[1][2] is None


def test_ai_sales_channel_secret_cipher_round_trip():
    from app import app
    from modules.ai_sales.security import decrypt_secret, encrypt_secret

    with app.app_context():
        encrypted = encrypt_secret("page-token")

        assert encrypted != "page-token"
        assert decrypt_secret(encrypted) == "page-token"
