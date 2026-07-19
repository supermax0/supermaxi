"""Inbound media storage, speech transcription, image understanding, and TTS."""
from __future__ import annotations

import base64
import mimetypes
import uuid
from pathlib import Path

from flask import current_app, g

from extensions import db
from .channels import channel_client
from .models import AISalesAgentProfile, AISalesMessage, AISalesUsageLog
from .openai_service import (
    AIServiceError,
    create_response,
    generate_speech_file,
    settings_for_profile,
    transcribe_file,
)


MEDIA_LIMITS = {
    "image": 10 * 1024 * 1024,
    "audio": 25 * 1024 * 1024,
    "voice": 25 * 1024 * 1024,
    "video": 50 * 1024 * 1024,
    "document": 20 * 1024 * 1024,
}

MIME_EXTENSIONS = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
    "audio/aac": ".aac", "audio/webm": ".webm", "audio/opus": ".opus",
    "audio/wav": ".wav", "audio/flac": ".flac",
    "video/mp4": ".mp4", "video/3gpp": ".3gp",
    "application/pdf": ".pdf",
}


def _storage_path(kind: str, mime_type: str) -> Path:
    tenant = str(getattr(g, "tenant", None) or "core")
    ext = MIME_EXTENSIONS.get(mime_type.split(";", 1)[0].lower()) or mimetypes.guess_extension(mime_type) or ".bin"
    folder = Path(current_app.root_path) / "uploads" / "ai_sales" / tenant / kind
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{uuid.uuid4().hex}{ext}"


def download_inbound_media(message: AISalesMessage) -> str:
    if message.media_path and Path(message.media_path).exists():
        return message.media_path
    if not message.external_media_id:
        raise ValueError("الرسالة لا تحتوي Media ID")
    kind = message.message_type if message.message_type in MEDIA_LIMITS else "document"
    content, detected_mime = channel_client(message.conversation.channel).download_media(
        message.external_media_id,
        max_bytes=MEDIA_LIMITS[kind],
    )
    mime_type = (message.mime_type or detected_mime or "application/octet-stream").split(";", 1)[0].lower()
    if kind == "image" and not mime_type.startswith("image/"):
        raise ValueError("نوع ملف الصورة غير صالح")
    if kind in {"audio", "voice"} and not mime_type.startswith("audio/"):
        raise ValueError("نوع ملف الصوت غير صالح")
    if kind == "video" and not mime_type.startswith("video/"):
        raise ValueError("نوع ملف الفيديو غير صالح")
    target = _storage_path("inbound", mime_type)
    target.write_bytes(content)
    message.media_path = str(target)
    message.mime_type = mime_type
    db.session.flush()
    return str(target)


def _active_profile() -> AISalesAgentProfile | None:
    return AISalesAgentProfile.query.filter_by(is_active=True).order_by(AISalesAgentProfile.id.asc()).first()


def transcribe_audio(message: AISalesMessage, *, profile: AISalesAgentProfile | None = None) -> str:
    path = download_inbound_media(message)
    settings = settings_for_profile(profile or _active_profile())
    message.transcription_status = "processing"
    message.transcription_model = settings.transcription_model
    message.transcription_error = None
    db.session.flush()
    try:
        result = transcribe_file(path, settings, language="ar")
        text = result["text"]
        message.transcription = text
        message.transcription_status = "completed"
        metadata = message.get_media_metadata()
        metadata["transcription"] = {
            "model": result["model"],
            "duration_ms": result["duration_ms"],
            "request_id": result["request_id"],
        }
        message.set_media_metadata(metadata)
        db.session.add(
            AISalesUsageLog(
                conversation_id=message.conversation_id,
                message_id=message.id,
                provider="openai",
                model=settings.transcription_model,
                operation="transcription",
            )
        )
        current_app.logger.info(
            "AI_SALES_OPENAI operation=transcription message_id=%s model=%s duration_ms=%s status=success",
            message.id,
            settings.transcription_model,
            result["duration_ms"],
        )
        return text
    except Exception as exc:
        error = exc if isinstance(exc, AIServiceError) else AIServiceError("transcription_failed", "transcription", str(exc))
        message.transcription_status = "failed"
        message.transcription_error = str(error)[:700]
        current_app.logger.warning(
            "AI_SALES_OPENAI operation=transcription message_id=%s model=%s status=failed code=%s error=%s",
            message.id,
            settings.transcription_model,
            getattr(error, "code", "transcription_failed"),
            error,
        )
        raise


def analyze_image(message: AISalesMessage) -> str:
    path = download_inbound_media(message)
    mime_type = message.mime_type or "image/jpeg"
    data_url = f"data:{mime_type};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"
    vision_model = str(current_app.config.get("OPENAI_VISION_MODEL") or "gpt-4o-mini")
    response = create_response(
        model=vision_model,
        instructions=(
            "حلل صورة الزبون كمساعد مبيعات عراقي لمتجر أجهزة. اقرأ النص الظاهر بدقة، خصوصاً السعر، العملة، "
            "اسم المنتج، الماركة، الحجم بالبوصة أو القدم، اللون، الموديل، وهل الصورة إعلان/منشور أو صورة منتج. "
            "إذا ظهر رقم مثل 128 أو 128.000 في إعلان بدون د.ع فاعتبره سعراً إعلانياً محتملاً بالدولار واذكره كدليل بحث، "
            "ولا تحوله إلى دينار. لا تخمن موديل غير واضح، لكن استخرج كلمات بحث مفيدة. أرجع وصفاً عربياً منظماً قصيراً."
        ),
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": message.text_content or "أريد منتجاً مشابهاً لهذه الصورة"},
                    {"type": "input_image", "image_url": data_url, "detail": "high"},
                ],
            }
        ],
        max_output_tokens=360,
        store=False,
        timeout=45,
    )
    analysis = (response.output_text or "").strip()
    metadata = message.get_media_metadata()
    metadata["vision_analysis"] = analysis
    metadata["vision_model"] = vision_model
    message.set_media_metadata(metadata)
    usage = getattr(response, "usage", None)
    db.session.add(
        AISalesUsageLog(
            conversation_id=message.conversation_id,
            message_id=message.id,
            provider="openai",
            model=vision_model,
            operation="vision",
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            image_count=1,
        )
    )
    return analysis


def generate_speech(
    text: str,
    *,
    voice: str = "marin",
    conversation_id: int | None = None,
    message_id: int | None = None,
    profile: AISalesAgentProfile | None = None,
    disclose_ai: bool = True,
) -> str:
    profile = profile or _active_profile()
    settings = settings_for_profile(profile)
    if voice:
        settings = type(settings)(**{**settings.__dict__, "voice": voice})
    mime_types = {
        "mp3": "audio/mpeg", "opus": "audio/ogg", "aac": "audio/aac",
        "flac": "audio/flac", "wav": "audio/wav", "pcm": "application/octet-stream",
    }
    target = _storage_path("outbound", mime_types.get(settings.audio_format, "audio/mpeg"))
    result = generate_speech_file(text, target, settings, disclose_ai=disclose_ai)
    db.session.add(
        AISalesUsageLog(
            conversation_id=conversation_id,
            message_id=message_id,
            provider="openai",
            model=settings.tts_model,
            operation="speech",
        )
    )
    current_app.logger.info(
        "AI_SALES_OPENAI operation=speech message_id=%s model=%s voice=%s format=%s duration_ms=%s status=success",
        message_id,
        settings.tts_model,
        settings.voice,
        settings.audio_format,
        result["duration_ms"],
    )
    return result["path"]
