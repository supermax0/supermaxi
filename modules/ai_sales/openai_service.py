"""Central OpenAI configuration and media services for Finora Sales AI."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import requests
from flask import current_app, g, has_app_context


DEFAULT_CHAT_MODEL = "gpt-5.6-sol"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_REALTIME_MODEL = "gpt-realtime-2.1"
DEFAULT_VOICE = "marin"
DEFAULT_AUDIO_FORMAT = "opus"
DEFAULT_VOICE_SPEED = 0.96
DEFAULT_AUDIO_QUALITY = "professional"
SUPPORTED_TTS_VOICES = {
    "alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx",
    "sage", "shimmer", "verse", "marin", "cedar",
}
DEFAULT_VOICE_INSTRUCTIONS = (
    "تكلم باللهجة العراقية الطبيعية بصوت بشري دافئ وواضح وواثق. "
    "انطق أسماء المنتجات والأسعار بوضوح، واستعمل وقفات قصيرة طبيعية بين الجمل. "
    "خلي النبرة ودودة ومهنية وهادئة، بدون قراءة آلية أو مبالغة بالتمثيل والحماس."
)

_CLIENT = None
_CLIENT_API_KEY = None
_CLIENT_LOCK = Lock()


class AIServiceError(RuntimeError):
    """Safe, structured error that can be persisted without exposing secrets."""

    def __init__(self, code: str, operation: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.operation = operation
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "operation": self.operation,
            "message": str(self),
            "status_code": self.status_code,
        }


@dataclass(frozen=True)
class OpenAISettings:
    chat_model: str = DEFAULT_CHAT_MODEL
    tts_model: str = DEFAULT_TTS_MODEL
    transcription_model: str = DEFAULT_TRANSCRIBE_MODEL
    realtime_model: str = DEFAULT_REALTIME_MODEL
    voice: str = DEFAULT_VOICE
    audio_format: str = DEFAULT_AUDIO_FORMAT
    voice_speed: float = DEFAULT_VOICE_SPEED
    audio_quality: str = DEFAULT_AUDIO_QUALITY
    voice_instructions: str = DEFAULT_VOICE_INSTRUCTIONS
    max_audio_size_mb: int = 25

    def public_dict(self) -> dict[str, Any]:
        return {
            "chat_model": self.chat_model,
            "tts_model": self.tts_model,
            "transcription_model": self.transcription_model,
            "realtime_model": self.realtime_model,
            "voice": self.voice,
            "audio_format": self.audio_format,
            "voice_speed": self.voice_speed,
            "audio_quality": self.audio_quality,
            "max_audio_size_mb": self.max_audio_size_mb,
        }


def get_openai_api_key() -> str:
    """Resolve the server-side key without ever returning it to the browser."""
    key = (os.environ.get("OPENAI_API_KEY") or current_app.config.get("OPENAI_API_KEY") or "").strip()
    if key:
        return key
    try:
        previous_tenant = getattr(g, "tenant", None)
        try:
            g.tenant = None
            from models.core.global_setting import GlobalSetting

            return (GlobalSetting.get_setting("OPENAI_API_KEY", "") or "").strip()
        finally:
            g.tenant = previous_tenant
    except Exception:
        return ""


def get_ffmpeg_binary() -> str:
    """Resolve FFmpeg even when the systemd service has a venv-only PATH."""
    configured = str(
        os.environ.get("FFMPEG_BINARY")
        or (current_app.config.get("FFMPEG_BINARY") if has_app_context() else "")
        or ""
    ).strip()
    candidates = [
        configured,
        shutil.which("ffmpeg") or "",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise AIServiceError("ffmpeg_missing", "speech", "خدمة معالجة الصوت غير مثبتة على الخادم")


def settings_for_profile(profile=None) -> OpenAISettings:
    config = current_app.config

    def profile_value(name: str) -> str:
        value = str(getattr(profile, name, "") or "").strip() if profile else ""
        return "" if is_corrupted_text(value) else value

    return OpenAISettings(
        chat_model=(
            profile_value("text_model")
            or str(config.get("OPENAI_CHAT_MODEL") or config.get("OPENAI_MODEL") or DEFAULT_CHAT_MODEL).strip()
        ),
        tts_model=(
            profile_value("tts_model")
            or str(config.get("OPENAI_TTS_MODEL") or os.environ.get("FINORA_SALES_TTS_MODEL") or DEFAULT_TTS_MODEL).strip()
        ),
        transcription_model=(
            profile_value("transcription_model")
            or str(
                config.get("OPENAI_TRANSCRIBE_MODEL")
                or os.environ.get("FINORA_SALES_STT_MODEL")
                or DEFAULT_TRANSCRIBE_MODEL
            ).strip()
        ),
        realtime_model=(
            profile_value("realtime_model")
            or str(config.get("OPENAI_REALTIME_MODEL") or DEFAULT_REALTIME_MODEL).strip()
        ),
        voice=profile_value("voice_name") or str(config.get("OPENAI_TTS_VOICE") or DEFAULT_VOICE).strip(),
        audio_format=(
            profile_value("audio_format")
            or str(config.get("OPENAI_TTS_FORMAT") or DEFAULT_AUDIO_FORMAT).strip().lower()
        ),
        voice_speed=max(
            0.75,
            min(
                float(getattr(profile, "voice_speed", DEFAULT_VOICE_SPEED) or DEFAULT_VOICE_SPEED),
                1.25,
            ),
        ),
        audio_quality=(
            profile_value("audio_quality")
            or str(config.get("OPENAI_TTS_QUALITY") or DEFAULT_AUDIO_QUALITY).strip().lower()
        ),
        voice_instructions=(
            profile_value("voice_instructions")
            or str(config.get("OPENAI_TTS_INSTRUCTIONS") or DEFAULT_VOICE_INSTRUCTIONS).strip()
        ),
        max_audio_size_mb=max(1, min(int(getattr(profile, "max_audio_size_mb", 25) or 25), 25)),
    )


def is_corrupted_text(value: str) -> bool:
    """Detect text that was replaced by question marks during a bad encoding hop."""
    text = str(value or "").strip()
    visible = [character for character in text if not character.isspace()]
    return len(visible) >= 8 and (visible.count("?") / len(visible)) >= 0.30


def get_openai_client(*, api_key: str | None = None):
    key = (api_key or get_openai_api_key()).strip()
    if not key:
        raise AIServiceError("openai_key_missing", "configuration", "مفتاح OpenAI غير مضبوط")
    global _CLIENT, _CLIENT_API_KEY
    if _CLIENT is None or _CLIENT_API_KEY != key:
        with _CLIENT_LOCK:
            if _CLIENT is None or _CLIENT_API_KEY != key:
                from openai import OpenAI

                _CLIENT = OpenAI(api_key=key, timeout=30.0, max_retries=1)
                _CLIENT_API_KEY = key
    return _CLIENT


def create_response(*, api_key: str | None = None, **kwargs):
    try:
        return get_openai_client(api_key=api_key).responses.create(**kwargs)
    except AIServiceError:
        raise
    except Exception as exc:
        raise _safe_provider_error(exc, "response") from exc


def transcribe_file(path: str, settings: OpenAISettings, *, language: str = "ar") -> dict[str, Any]:
    started = time.monotonic()
    file_path = Path(path)
    maximum = settings.max_audio_size_mb * 1024 * 1024
    if not file_path.exists():
        raise AIServiceError("audio_file_missing", "transcription", "الملف الصوتي غير موجود")
    if file_path.stat().st_size > maximum:
        raise AIServiceError(
            "audio_too_large",
            "transcription",
            f"حجم التسجيل يتجاوز {settings.max_audio_size_mb} MB",
            status_code=413,
        )
    try:
        with file_path.open("rb") as audio:
            result = get_openai_client().audio.transcriptions.create(
                model=settings.transcription_model,
                file=audio,
                language=language,
                prompt=(
                    "المتحدث يتكلم باللهجة العراقية عن الأجهزة الكهربائية، المنتجات، "
                    "الأسعار بالدينار العراقي، المقاسات، العناوين وأرقام الهواتف."
                ),
                timeout=60,
            )
        text = str(getattr(result, "text", result) or "").strip()
        if not text:
            raise AIServiceError("empty_transcription", "transcription", "لم يتم التعرف على كلام واضح في التسجيل")
        return {
            "text": text,
            "model": settings.transcription_model,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "request_id": str(getattr(result, "_request_id", "") or ""),
        }
    except AIServiceError:
        raise
    except Exception as exc:
        raise _safe_provider_error(exc, "transcription") from exc


def generate_speech_file(
    text: str,
    target: str | Path,
    settings: OpenAISettings,
    *,
    disclose_ai: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    spoken_text = prepare_text_for_speech(text)
    if disclose_ai and not re.search(r"مساعد(?:نا)?\s+الذكي|ذكاء\s+اصطناعي", spoken_text):
        spoken_text = f"وياك مساعدنا الذكي. {spoken_text}"
    if not spoken_text:
        raise AIServiceError("empty_speech_text", "speech", "لا يوجد نص صالح للتحويل إلى صوت")
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="finora-tts-",
            suffix=".wav",
            dir=target_path.parent,
            delete=False,
        ) as source_file:
            source_path = Path(source_file.name)
        response = get_openai_client().audio.speech.create(
            model=settings.tts_model,
            voice=settings.voice,
            instructions=settings.voice_instructions,
            input=spoken_text[:2400],
            response_format="wav",
            speed=settings.voice_speed,
            timeout=60,
        )
        response.write_to_file(source_path)
        _master_speech_file(
            source_path,
            target_path,
            audio_format=settings.audio_format,
            quality=settings.audio_quality,
        )
        return {
            "path": str(target_path),
            "model": settings.tts_model,
            "voice": settings.voice,
            "format": settings.audio_format,
            "speed": settings.voice_speed,
            "quality": settings.audio_quality,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "request_id": str(getattr(response, "_request_id", "") or ""),
            "spoken_text": spoken_text,
        }
    except AIServiceError:
        raise
    except Exception as exc:
        raise _safe_provider_error(exc, "speech") from exc
    finally:
        if source_path and source_path != target_path:
            source_path.unlink(missing_ok=True)


def _master_speech_file(source: Path, target: Path, *, audio_format: str, quality: str) -> None:
    """Normalize generated speech and encode a stable, channel-friendly master."""
    audio_format = str(audio_format or DEFAULT_AUDIO_FORMAT).lower()
    quality = str(quality or DEFAULT_AUDIO_QUALITY).lower()
    if quality == "original" and audio_format == "wav":
        source.replace(target)
        return

    filters = ["aresample=async=1:first_pts=0"]
    if quality == "professional":
        filters = [
            "highpass=f=65",
            "lowpass=f=12000",
            "acompressor=threshold=0.125:ratio=2:attack=20:release=180:makeup=1.35",
            "loudnorm=I=-16:LRA=7:TP=-1.5",
        ]

    codecs = {
        "opus": [
            "-c:a", "libopus", "-b:a", "72k", "-vbr", "on",
            "-compression_level", "10", "-application", "audio",
            "-ar", "48000", "-ac", "1", "-f", "ogg",
        ],
        "mp3": ["-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "1"],
        "aac": ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "1"],
        "flac": ["-c:a", "flac", "-compression_level", "8", "-ar", "48000", "-ac", "1"],
        "wav": ["-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1"],
    }
    if audio_format not in codecs:
        raise AIServiceError("unsupported_audio_format", "speech", "صيغة الصوت المحددة غير مدعومة")
    command = [
        get_ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source), "-vn", "-af", ",".join(filters),
        *codecs[audio_format], str(target),
    ]
    try:
        subprocess.run(command, check=True, timeout=90, capture_output=True)
    except FileNotFoundError as exc:
        target.unlink(missing_ok=True)
        raise AIServiceError("ffmpeg_missing", "speech", "تعذر تشغيل خدمة معالجة الصوت على الخادم") from exc
    except subprocess.CalledProcessError as exc:
        target.unlink(missing_ok=True)
        details = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise AIServiceError(
            "audio_mastering_failed",
            "speech",
            f"تعذرت معالجة جودة الصوت: {details[:300] or 'FFmpeg failed'}",
        ) from exc


def create_realtime_client_secret(settings: OpenAISettings, *, instructions: str = "") -> dict[str, Any]:
    """Mint an ephemeral WebRTC secret. The normal API key never leaves the server."""
    key = get_openai_api_key()
    if not key:
        raise AIServiceError("openai_key_missing", "realtime", "مفتاح OpenAI غير مضبوط")
    payload = {
        "session": {
            "type": "realtime",
            "model": settings.realtime_model,
            "instructions": instructions or "تحدث بالعربية العراقية بوضوح واختصار، واستمع للمتصل قبل الرد.",
            "audio": {
                "output": {"voice": settings.voice},
                "input": {
                    "turn_detection": {
                        "type": "server_vad",
                        "create_response": True,
                        "interrupt_response": True,
                    }
                },
            },
        }
    }
    try:
        response = requests.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise AIServiceError("realtime_network_error", "realtime", "تعذر الاتصال بخدمة الصوت المباشر") from exc
    if response.status_code >= 400:
        try:
            body = response.json()
            message = str((body.get("error") or {}).get("message") or "فشل إنشاء جلسة الصوت المباشر")
            code = str((body.get("error") or {}).get("code") or "realtime_provider_error")
        except ValueError:
            message, code = "فشل إنشاء جلسة الصوت المباشر", "realtime_provider_error"
        raise AIServiceError(code, "realtime", message, status_code=response.status_code)
    data = response.json()
    # This object contains only a short-lived client secret minted for WebRTC.
    return {
        "value": data.get("value") or data.get("client_secret", {}).get("value"),
        "expires_at": data.get("expires_at") or data.get("client_secret", {}).get("expires_at"),
        "session": data.get("session") or {},
        "model": settings.realtime_model,
    }


def prepare_text_for_speech(value: str) -> str:
    text = str(value or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", " دزيتلك الرابط ويا الرسالة ", text)
    text = re.sub(r"\bAI\b", "إيه آي", text, flags=re.IGNORECASE)
    text = re.sub(r"\bTV\b", "تي في", text, flags=re.IGNORECASE)
    text = re.sub(r"\bUSB\b", "يو إس بي", text, flags=re.IGNORECASE)
    text = re.sub(r"\b4K\b", "فور كي", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:HD|FHD)\b", "إتش دي", text, flags=re.IGNORECASE)
    text = re.sub(r"[`*_#>|]", " ", text)
    text = re.sub(r"^[\t \-•]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "", text)
    text = re.sub(
        r"(?<!\d)(?:\+?964|0)7\d{9}(?!\d)",
        lambda match: "رقم الهاتف " + _digits_as_words(match.group(0)),
        text,
    )
    text = re.sub(
        r"(?<!\d)(\d{1,3}(?:[,٬]\d{3})+|\d{3,9})\s*(?:د\.?\s*ع|دينار(?:\s+عراقي)?|IQD)",
        lambda match: f"{_iraqi_number_words(int(re.sub(r'[,٬]', '', match.group(1))))} دينار عراقي",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?<!\d)(\d{1,3})\s*(?:%|بالمية)",
        lambda match: f"{_iraqi_number_words(int(match.group(1)))} بالمية",
        text,
    )
    text = re.sub(r"\s*\n+\s*", ". ", text)
    text = re.sub(r"\s*[:؛]\s*", ". ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\.\s*", ". ", text)
    text = re.sub(r"(?:\.\s*){2,}", ". ", text)
    return text.strip(" .،")


def _digits_as_words(value: str) -> str:
    words = {
        "0": "صفر", "1": "واحد", "2": "اثنين", "3": "ثلاثة", "4": "أربعة",
        "5": "خمسة", "6": "ستة", "7": "سبعة", "8": "ثمانية", "9": "تسعة",
    }
    return " ".join(words[digit] for digit in str(value or "") if digit in words)


def _iraqi_number_words(number: int) -> str:
    if number == 0:
        return "صفر"
    if number < 0:
        return "ناقص " + _iraqi_number_words(abs(number))
    if number >= 1_000_000:
        millions, remainder = divmod(number, 1_000_000)
        head = "مليون" if millions == 1 else "مليونين" if millions == 2 else f"{_iraqi_number_words(millions)} مليون"
        return head if not remainder else f"{head} و{_iraqi_number_words(remainder)}"
    if number >= 1000:
        thousands, remainder = divmod(number, 1000)
        if thousands == 1:
            head = "ألف"
        elif thousands == 2:
            head = "ألفين"
        elif 3 <= thousands <= 10:
            head = f"{_iraqi_number_words(thousands)} آلاف"
        else:
            head = f"{_iraqi_number_words(thousands)} ألف"
        return head if not remainder else f"{head} و{_iraqi_number_words(remainder)}"
    hundreds, remainder = divmod(number, 100)
    hundred_words = {
        1: "مية", 2: "ميتين", 3: "ثلاثمية", 4: "أربعمية", 5: "خمسمية",
        6: "ستمية", 7: "سبعمية", 8: "ثمانمية", 9: "تسعمية",
    }
    if hundreds:
        head = hundred_words[hundreds]
        return head if not remainder else f"{head} و{_iraqi_number_words(remainder)}"
    units = {
        1: "واحد", 2: "اثنين", 3: "ثلاثة", 4: "أربعة", 5: "خمسة", 6: "ستة",
        7: "سبعة", 8: "ثمانية", 9: "تسعة", 10: "عشرة", 11: "احدعش", 12: "اثنعش",
        13: "ثلاثطعش", 14: "اربعطعش", 15: "خمسطعش", 16: "ستطعش", 17: "سبعطعش",
        18: "ثمنطعش", 19: "تسعطعش",
    }
    if number in units:
        return units[number]
    tens, unit = divmod(number, 10)
    tens_words = {2: "عشرين", 3: "ثلاثين", 4: "أربعين", 5: "خمسين", 6: "ستين", 7: "سبعين", 8: "ثمانين", 9: "تسعين"}
    return tens_words[tens] if not unit else f"{units[unit]} و{tens_words[tens]}"


def _safe_provider_error(exc: Exception, operation: str) -> AIServiceError:
    status_code = getattr(exc, "status_code", None)
    provider_code = str(getattr(exc, "code", "") or "").strip()
    message = str(getattr(exc, "message", "") or str(exc) or "فشل طلب OpenAI")
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", message)
    if len(message) > 700:
        message = message[:700]
    return AIServiceError(provider_code or f"openai_{operation}_failed", operation, message, status_code=status_code)
