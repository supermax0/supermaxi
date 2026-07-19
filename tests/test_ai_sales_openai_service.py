from pathlib import Path
from types import SimpleNamespace

from flask import Flask

from modules.ai_sales.openai_service import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_REALTIME_MODEL,
    _master_speech_file,
    is_corrupted_text,
    probe_openai_services,
    prepare_text_for_speech,
    settings_for_profile,
)


def test_openai_models_are_independent_and_profile_overrides_environment():
    app = Flask(__name__)
    app.config.update(
        OPENAI_CHAT_MODEL="chat-from-config",
        OPENAI_VISION_MODEL="vision-from-config",
        OPENAI_TTS_MODEL="tts-from-config",
        OPENAI_TRANSCRIBE_MODEL="stt-from-config",
        OPENAI_REALTIME_MODEL="realtime-from-config",
        OPENAI_TTS_VOICE="alloy",
        OPENAI_TTS_FORMAT="opus",
    )
    profile = SimpleNamespace(
        text_model="gpt-5.6",
        vision_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        transcription_model="gpt-4o-mini-transcribe",
        realtime_model="",
        voice_name="coral",
        audio_format="mp3",
        voice_speed=0.92,
        audio_quality="professional",
        voice_instructions="نبرة عراقية طبيعية",
        max_audio_size_mb=20,
    )
    with app.app_context():
        settings = settings_for_profile(profile)
    assert settings.chat_model == "gpt-5.6"
    assert settings.vision_model == "gpt-5.4-mini"
    assert settings.tts_model == "gpt-4o-mini-tts"
    assert settings.transcription_model == "gpt-4o-mini-transcribe"
    assert settings.realtime_model == "realtime-from-config"
    assert settings.voice == "coral"
    assert settings.audio_format == "mp3"
    assert settings.voice_speed == 0.92
    assert settings.audio_quality == "professional"
    assert settings.max_audio_size_mb == 20


def test_realtime_documented_default_is_used_when_no_override_exists():
    app = Flask(__name__)
    with app.app_context():
        settings = settings_for_profile(None)
    assert settings.realtime_model == DEFAULT_REALTIME_MODEL
    assert settings.chat_model == DEFAULT_CHAT_MODEL


def test_openai_health_probe_checks_text_vision_and_transcription(monkeypatch):
    calls = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(("response", kwargs))
            return SimpleNamespace(output_text="OK")

    class FakeTranscriptions:
        def create(self, **kwargs):
            calls.append(("transcription", kwargs))
            return SimpleNamespace(text="")

    fake_client = SimpleNamespace(
        responses=FakeResponses(),
        audio=SimpleNamespace(transcriptions=FakeTranscriptions()),
    )
    monkeypatch.setattr("modules.ai_sales.openai_service.get_openai_client", lambda: fake_client)
    app = Flask(__name__)
    app.config.update(
        OPENAI_CHAT_MODEL="gpt-5.4-mini",
        OPENAI_VISION_MODEL="gpt-5.4-mini",
        OPENAI_TRANSCRIBE_MODEL="gpt-4o-mini-transcribe",
    )
    with app.app_context():
        checks = probe_openai_services(settings_for_profile(None))

    assert all(check["ok"] for check in checks.values())
    assert [name for name, _ in calls] == ["response", "response", "transcription"]
    assert calls[1][1]["input"][0]["content"][1]["detail"] == "low"


def test_question_mark_encoding_damage_is_detected_without_rejecting_normal_text():
    assert is_corrupted_text("???????? ?????? ????????") is True
    assert is_corrupted_text("تكلم بوضوح؟ وخلي النبرة طبيعية.") is False


def test_speech_preparation_removes_markup_links_and_reads_iraqi_price():
    prepared = prepare_text_for_speech(
        "**السعر:** 399,000 د.ع ✅\n• التفاصيل https://example.com/product"
    )
    assert "**" not in prepared
    assert "https://" not in prepared
    assert "ثلاثمية وتسعة وتسعين ألف دينار عراقي" in prepared
    assert "دزيتلك الرابط ويا الرسالة" in prepared


def test_speech_preparation_reads_iraqi_phone_digit_by_digit():
    prepared = prepare_text_for_speech("رقمي 07734049148 والسعر ٢٧٠٬٠٠٠ د.ع")
    assert "رقم الهاتف صفر سبعة سبعة ثلاثة أربعة صفر أربعة تسعة واحد أربعة ثمانية" in prepared
    assert "ميتين وسبعين ألف دينار عراقي" in prepared


def test_professional_mastering_uses_loudness_normalization_and_opus(monkeypatch, tmp_path):
    source = tmp_path / "source.wav"
    target = tmp_path / "reply.ogg"
    source.write_bytes(b"wav")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs

    monkeypatch.setattr("modules.ai_sales.openai_service.get_ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr("modules.ai_sales.openai_service.subprocess.run", fake_run)
    _master_speech_file(Path(source), Path(target), audio_format="opus", quality="professional")

    command = captured["command"]
    assert any("loudnorm=I=-16" in part for part in command)
    assert "libopus" in command
    assert "72k" in command
    assert captured["kwargs"]["check"] is True
