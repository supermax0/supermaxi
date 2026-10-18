"""Media permissions, private downloads, actual decoding, idempotency and grounded local vision. No customer sends."""
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from tests.test_finora_core_api import env, _auth, _seed_house  # noqa: F401

PREFIX = "/api/v1/finora-core"


def png():
    data = io.BytesIO()
    Image.new("RGB", (64, 48), "#8176ed").save(data, "PNG")
    return data.getvalue()


def setup(env):
    client = env.test_client()
    ids = _seed_house(env)
    headers, _ = _auth(client)
    client.post(f"{PREFIX}/conversations/{ids['c1']}/takeover", headers=headers)
    return client, ids, headers


def upload(client, cid, headers, content=None, mime="image/png", key="media-test", name="screen.png"):
    return client.post(f"{PREFIX}/conversations/{cid}/media", data={"file": (io.BytesIO(content if content is not None else png()), name, mime)},
                       headers={**headers, "Idempotency-Key": key})


def test_send_image_private_download_and_idempotency(env):
    client, ids, headers = setup(env)
    result = upload(client, ids["c1"], headers)
    assert result.status_code == 201, result.get_json()
    message = result.get_json()["message"]
    item = message["attachments"][0]
    assert item["status"] == "stored" and item["mimeType"] == "image/jpeg"
    assert not {"stored_path", "source_url", "sha256"} & item.keys()
    assert message["delivery"] == "sent"
    path = f"{PREFIX}/conversations/{ids['c1']}/messages/{message['id']}/attachments/0"
    assert client.get(path).status_code == 401
    fetched = client.get(path, headers=headers)
    assert fetched.status_code == 200 and fetched.mimetype == "image/jpeg"
    assert fetched.headers["Cache-Control"] == "no-store"
    assert client.get(path.replace(f"conversations/{ids['c1']}", f"conversations/{ids['c2']}"), headers=headers).status_code == 404
    again = upload(client, ids["c1"], headers)
    assert again.get_json()["message"]["id"] == message["id"]
    assert upload(client, ids["c2"], headers).status_code == 409
    assert upload(client, ids["c1"], headers, content=png() + b"different").status_code == 409


def test_upload_requires_permission_takeover_valid_content_and_type(env):
    client = env.test_client()
    ids = _seed_house(env)
    reader, _ = _auth(client, "viewer")
    owner, _ = _auth(client)
    assert upload(client, ids["c1"], reader).status_code == 403
    assert upload(client, ids["c1"], {}).status_code == 401
    assert upload(client, ids["c1"], owner).status_code == 409
    client.post(f"{PREFIX}/conversations/{ids['c1']}/takeover", headers=owner)
    assert upload(client, ids["c1"], owner, content=b"<svg><script>bad</script></svg>").status_code == 400
    assert upload(client, ids["c1"], owner, content=png(), mime="image/svg+xml").status_code == 400
    assert upload(client, ids["c1"], owner, content=b"#EXTM3U\nhttps://example.invalid/private.mp4", mime="video/mp4", name="playlist.mp4", key="playlist").status_code == 400
    assert upload(client, ids["c1"], owner, content=b"x" * (10 * 1024 * 1024 + 1)).status_code == 413


def test_signed_delivery_is_outbound_scoped_and_expires(env, monkeypatch):
    from modules.finora_core import media
    from modules.finora_core.store import use_house
    from modules.ai_sales.models import AISalesMessage
    client, ids, headers = setup(env)
    message = upload(client, ids["c1"], headers).get_json()["message"]
    with env.test_request_context():
        with use_house() as slug:
            row = AISalesMessage.query.get(int(message["id"]))
            token = media.delivery_url(row, media.attachment(row, "0"), slug).rsplit("/", 1)[1]
            evil = media.signer().dumps({"slug": "another-tenant", "cid": ids["c1"], "mid": row.id, "aid": "0", "hash": "x"})
    assert client.get(f"{PREFIX}/media/delivery/{token}").status_code == 200
    assert client.get(f"{PREFIX}/media/delivery/{token}modified").status_code == 404
    assert client.get(f"{PREFIX}/media/delivery/{evil}").status_code == 404
    import itsdangerous.timed
    monkeypatch.setattr(itsdangerous.timed.TimestampSigner, "get_timestamp", lambda self: 9_999_999_999)
    assert client.get(f"{PREFIX}/media/delivery/{token}").status_code == 404


def test_local_image_analysis_cached_and_never_uses_cloud(env, monkeypatch):
    from modules.finora_core import media_analysis
    seen = []
    class Provider:
        name = "ollama"
        def generate_structured(self, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(data={"summary": "شاشة المخزون", "details": "زر إضافة منتج ظاهر", "needsHuman": False}, model="local-vision", provider="local")
    monkeypatch.setattr(media_analysis, "get_provider", lambda: Provider())
    client, ids, headers = setup(env)
    message = upload(client, ids["c1"], headers).get_json()["message"]
    path = f"{PREFIX}/conversations/{ids['c1']}/messages/{message['id']}/attachments/0/analyze"
    reader, _ = _auth(client, "viewer")
    assert client.post(path, headers=reader).status_code == 403
    response = client.post(path, headers=headers)
    assert response.status_code == 200, response.get_json()
    item = response.get_json()["message"]["attachments"][0]
    assert item["analysis"]["status"] == "completed" and item["analysis"]["provider"] == "local"
    assert seen[0]["images"][0].startswith("data:image/jpeg;base64,")
    assert "untrusted" in seen[0]["system"]
    assert client.post(path, headers=headers).status_code == 200 and len(seen) == 1


def test_media_missing_or_provider_failure_is_not_fabricated(env, monkeypatch):
    from modules.finora_core import media_analysis
    monkeypatch.setattr(media_analysis, "get_provider", lambda: None)
    client, ids, headers = setup(env)
    message = upload(client, ids["c1"], headers).get_json()["message"]
    path = f"{PREFIX}/conversations/{ids['c1']}/messages/{message['id']}/attachments/0/analyze"
    result = client.post(path, headers=headers).get_json()["message"]["attachments"][0]["analysis"]
    assert result["status"] == "failed" and "summary" not in result
    assert client.post(path.replace("attachments/0", "attachments/999"), headers=headers).status_code == 404


def test_processing_guard_paths_and_local_voice_do_not_leak(env, tmp_path, monkeypatch):
    from datetime import datetime
    from extensions import db
    from modules.ai_sales.models import AISalesMessage
    from modules.finora_core import media, media_analysis, settings
    from modules.finora_core.brain.provider import ProviderError
    from modules.finora_core.store import use_house, iso
    client, ids, headers = setup(env)
    message = upload(client, ids["c1"], headers).get_json()["message"]
    with env.test_request_context():
        with use_house() as slug:
            row = db.session.get(AISalesMessage, int(message["id"]))
            meta = row.get_media_metadata()
            meta["attachments"][0]["analysis"] = {"status": "processing", "at": iso(datetime.utcnow())}
            row.set_media_metadata(meta)
            db.session.commit()
            with pytest.raises(ProviderError, match="جارٍ"):
                media_analysis.analyze(row, "0", slug)
            outside = tmp_path / "outside.jpg"
            outside.write_bytes(png())
            with pytest.raises(media.CoreApiError):
                media.stored_path({"status": "stored", "stored_path": str(outside)}, slug)
            monkeypatch.setattr(settings, "read_settings", lambda session: {"provider": "local"})
            monkeypatch.setattr(settings, "cloud_key", lambda session: "test-only")
            with pytest.raises(ProviderError, match="لم يُرسل الصوت للسحابة"):
                media_analysis.transcribe(outside)


def test_actual_voice_and_video_decode_and_frame_sampling(env, tmp_path, monkeypatch):
    from modules.finora_core import media, media_analysis
    from modules.finora_core.store import use_house
    from modules.ai_sales.models import AISalesMessage
    from extensions import db
    from modules.ai_sales import openai_service
    from modules.finora_core import settings
    client, ids, headers = setup(env)
    with env.app_context():
        voice = tmp_path / "recording.webm"
        created = media.run_ffmpeg(["-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libopus", "-live", "1", str(voice)])
        assert created.returncode == 0
        video = tmp_path / "clip.mp4"
        created = media.run_ffmpeg(["-loglevel", "error", "-f", "lavfi", "-i", "color=c=purple:s=160x120:d=2:r=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)])
        assert created.returncode == 0
    voice_response = upload(client, ids["c1"], headers, voice.read_bytes(), mime="audio/webm", key="voice", name="voice.webm")
    assert voice_response.status_code == 201, voice_response.get_json()
    assert voice_response.get_json()["message"]["attachments"][0]["mimeType"] == "audio/mpeg"
    video_response = upload(client, ids["c1"], headers, video.read_bytes(), mime="video/mp4", key="video", name="clip.mp4")
    assert video_response.status_code == 201, video_response.get_json()
    message = video_response.get_json()["message"]
    with env.test_request_context():
        with use_house() as slug:
            row = AISalesMessage.query.get(int(message["id"]))
            frames, times = media_analysis.video_images(media.stored_path(media.attachment(row, "0"), slug))
            assert len(frames) == len(times) == 2 and 0 < times[0] < times[1] < 2.2
            calls = []
            def transcribe(**kwargs):
                assert kwargs["file"].name.endswith("voice.mp3")
                assert kwargs["file"].read(3)
                calls.append(kwargs["model"])
                return SimpleNamespace(text="شلون أضيف منتج للمخزون؟")
            monkeypatch.setattr(settings, "read_settings", lambda session: {"provider": "cloud"})
            monkeypatch.setattr(settings, "cloud_key", lambda session: "test-only")
            monkeypatch.setattr(openai_service, "get_openai_client", lambda **kwargs: SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=transcribe))))
            voice_row = db.session.get(AISalesMessage, int(voice_response.get_json()["message"]["id"]))
            inbound = AISalesMessage(conversation_id=ids["c1"], channel_account_id=voice_row.channel_account_id,
                                     direction="inbound", sender_type="customer", message_type="audio", status="received", text_content="")
            inbound.set_media_metadata({"attachments": voice_row.get_media_metadata()["attachments"]})
            db.session.add(inbound)
            db.session.commit()
            analysis = media_analysis.analyze(inbound, "0", slug)
            assert analysis["status"] == "completed" and analysis["provider"] == "cloud"
            assert inbound.transcription == "شلون أضيف منتج للمخزون؟" and len(calls) == 1


def test_media_retry_sends_file_not_blank_text(env, monkeypatch):
    from extensions import db
    from modules.ai_sales.models import AISalesMessage
    from modules.ai_sales.meta_retry import retry_due
    from modules.finora_core import media
    from modules.finora_core.store import use_house
    client, ids, headers = setup(env)
    message = upload(client, ids["c1"], headers).get_json()["message"]
    sends = []
    monkeypatch.setattr(media, "send_stored", lambda row, slug: sends.append(row.id) or "m_media_retry_ok")
    with env.test_request_context():
        with use_house():
            row = AISalesMessage.query.get(int(message["id"]))
            row.status = "retry_scheduled"
            db.session.commit()
            assert retry_due()["sent"] == 1
            assert sends == [row.id]
