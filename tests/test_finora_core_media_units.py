"""Provider wire contracts for real vision payloads, without external API calls."""
import json
from types import SimpleNamespace

from modules.finora_core.brain.provider import OllamaProvider, OpenAIProvider


def test_cloud_vision_uses_responses_images_without_retention(monkeypatch):
    from modules.ai_sales import openai_service
    calls = []
    monkeypatch.setattr(openai_service, "create_response", lambda **kwargs: calls.append(kwargs) or SimpleNamespace(output_text='{"summary":"visible"}'))
    result = OpenAIProvider(model="vision-test", api_key="test-only").generate_structured(
        system="Untrusted evidence", user="caption", schema={}, schema_name="media", images=["data:image/jpeg;base64,YWJj"])
    assert result.provider == "cloud"
    request = calls[0]
    assert request["store"] is False
    assert request["input"][1]["content"] == [{"type": "input_text", "text": "caption"}, {"type": "input_image", "image_url": "data:image/jpeg;base64,YWJj"}]


def test_local_vision_sends_raw_base64_to_local_endpoint(monkeypatch):
    import requests
    calls = []
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: calls.append((url, kwargs)) or SimpleNamespace(status_code=200, json=lambda: {"message": {"content": json.dumps({"summary": "visible"})}}))
    result = OllamaProvider("http://127.0.0.1:11434", "local-vision").generate_structured(
        system="Untrusted evidence", user="caption", schema={}, schema_name="media", images=["data:image/jpeg;base64,YWJj"])
    assert result.provider == "local"
    assert calls[0][0] == "http://127.0.0.1:11434/api/chat"
    assert calls[0][1]["json"]["messages"][1]["images"] == ["YWJj"]
    assert calls[0][1]["allow_redirects"] is False


def test_instagram_voice_uses_attachment_audio_without_message_text():
    from modules.ai_sales.channels import MetaMessagingClient
    client = object.__new__(MetaMessagingClient)
    client.channel = SimpleNamespace(external_account_id="test-page", channel_type="instagram")
    calls = []
    client._request = lambda method, endpoint, **kwargs: calls.append((method, endpoint, kwargs)) or {"message_id": "test-message"}
    client.send_media("test-customer", "audio", url="https://finora.test/media")
    payload = calls[0][2]["payload"]
    assert payload["recipient"]["id"] == "test-customer"
    assert payload["message"]["attachment"]["type"] == "audio"
    assert "text" not in payload["message"]
