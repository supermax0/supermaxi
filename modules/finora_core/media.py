"""Private Core media: bounded uploads, verified bytes, scoped paths and temporary Meta delivery URLs."""
from __future__ import annotations

import hashlib
import io
import math
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from flask import current_app, url_for
from itsdangerous import URLSafeTimedSerializer

from modules.ai_sales.attachments import safe_name, storage_root
from modules.ai_sales.openai_service import AIServiceError, get_ffmpeg_binary
from .errors import CoreApiError, not_found, validation_error

MAX_UPLOAD = 25 * 1024 * 1024
KINDS = {"image/jpeg": "image", "image/png": "image", "image/webp": "image", "image/gif": "image",
         "video/mp4": "video", "video/quicktime": "video", "video/webm": "video",
         "audio/webm": "audio", "audio/ogg": "audio", "audio/mpeg": "audio", "audio/mp4": "audio",
         "audio/wav": "audio", "audio/x-wav": "audio", "audio/aac": "audio"}


def run_ffmpeg(args: list[str], *, timeout: int = 45):
    try:
        try:
            executable = get_ffmpeg_binary()
        except AIServiceError:
            try:
                from imageio_ffmpeg import get_ffmpeg_exe
                executable = get_ffmpeg_exe()
            except (ImportError, RuntimeError) as exc:
                raise validation_error("معالجة الصوت والفيديو تحتاج FFmpeg على الخادم أو متطلبات الوسائط المحدّثة") from exc
        return subprocess.run([executable, "-nostdin", "-hide_banner", *args],
                              capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise validation_error("تعذرت معالجة الملف؛ جرّب ملفاً أقصر أو تحقق من خدمة FFmpeg") from exc


def probe(path: Path) -> dict:
    """FFmpeg inspects the local file without decoding the full stream (no external URLs accepted)."""
    result = run_ffmpeg(input_args(path), timeout=15)
    info = result.stderr.decode("utf-8", errors="replace")
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
    duration = (int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])) if match else None
    if duration is None and "matroska,webm" in info:
        # MediaRecorder's live WebM has no header duration. Decode locally with a hard ceiling.
        decoded = run_ffmpeg([*input_args(path), "-t", "601", "-progress", "pipe:1", "-nostats", "-f", "null", "-"], timeout=45)
        stamps = re.findall(rb"out_time_us=(\d+)", decoded.stdout)
        if decoded.returncode == 0 and stamps:
            duration = max(int(value) for value in stamps) / 1_000_000
    if not duration or not math.isfinite(duration):
        raise validation_error("الملف غير صالح أو مدته غير معروفة")
    return {"duration": duration, "video": bool(re.search(r"Stream .*Video:", info)),
            "audio": bool(re.search(r"Stream .*Audio:", info))}


def input_args(path: Path) -> list[str]:
    # No playlists, concat scripts, network streams or arbitrary nested file references.
    return ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm,ogg,wav,mp3,aac", "-i", str(path)]


def image_bytes(content: bytes) -> bytes:
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP", "GIF"} or image.width * image.height > 24_000_000:
                raise validation_error("الصورة غير مدعومة أو أبعادها كبيرة جداً")
            image.seek(0)
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.save(output, "JPEG", quality=88)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
        raise validation_error("محتوى الملف ليس صورة صالحة") from exc


def save_upload(content: bytes, mime: str, name: str, slug: str) -> dict:
    kind = KINDS.get(mime)
    if not kind or not content:
        raise validation_error("اختر صورة أو فيديو أو ملفاً صوتياً بصيغة مدعومة")
    cap = 10 * 1024 * 1024 if kind == "image" else MAX_UPLOAD
    if len(content) > cap:
        raise CoreApiError("VALIDATION_ERROR", f"الملف يتجاوز {cap // (1024 * 1024)} MB", 413)
    root = Path(storage_root(slug))
    stem = f"core-{uuid.uuid4().hex}"
    duration = None
    if kind == "image":
        content, extension, mime = image_bytes(content), ".jpg", "image/jpeg"
    else:
        with tempfile.TemporaryDirectory(dir=root, prefix="processing-") as work:
            source = Path(work) / "source.bin"
            source.write_bytes(content)
            info = probe(source)
            duration = info["duration"]
            if (kind == "video" and not info["video"]) or (kind == "audio" and (not info["audio"] or info["video"])):
                raise validation_error("محتوى الملف لا يطابق نوعه")
            if duration > (180 if kind == "audio" else 600):
                raise validation_error("أقصى مدة للصوت 3 دقائق، وللفيديو 10 دقائق")
            extension, mime = (".mp3", "audio/mpeg") if kind == "audio" else (".mp4", "video/mp4")
            target = Path(work) / f"processed{extension}"
            args = ["-loglevel", "error", *input_args(source), "-map_metadata", "-1"]
            args += (["-vn", "-ac", "1", "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "96k"] if kind == "audio" else
                     ["-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=1280:1280:force_original_aspect_ratio=decrease:force_divisible_by=2",
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"])
            result = run_ffmpeg([*args, "-fs", str(MAX_UPLOAD + 1), str(target)], timeout=120)
            if result.returncode or not target.is_file():
                raise validation_error("تعذرت تهيئة الملف للإرسال؛ جرّب صيغة أخرى")
            content = target.read_bytes()
            if len(content) > MAX_UPLOAD:
                raise CoreApiError("VALIDATION_ERROR", "حجم الملف بعد المعالجة كبير جداً", 413)
    target = root / f"{stem}{extension}"
    target.write_bytes(content)
    return {"index": 0, "kind": kind, "status": "stored", "mime_type": mime,
            "name": f"{Path(safe_name(name) or kind).stem[:100]}{extension}", "stored_path": target.name,
            "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "duration_seconds": duration}


def attachment(message, attachment_id: str) -> dict:
    for index, item in enumerate(message.get_media_metadata().get("attachments") or []):
        if str(item.get("index", index)) == attachment_id:
            return item
    raise not_found("المرفق غير موجود")


def stored_path(item: dict, slug: str) -> Path:
    root = Path(storage_root(slug)).resolve()
    path = (root / str(item.get("stored_path") or "")).resolve()
    if item.get("status") != "stored" or path == root or not path.is_relative_to(root) or not path.is_file():
        raise not_found("المرفق غير جاهز أو لم يعد متاحاً")
    return path


def signer():
    secret = current_app.config.get("SECRET_KEY")
    if not secret:
        raise CoreApiError("UNKNOWN_ERROR", "مفتاح أمان الخادم غير مضبوط", 503)
    return URLSafeTimedSerializer(secret, salt="finora-core-media-delivery")


def delivery_url(message, item: dict, slug: str) -> str:
    base = str(os.environ.get("FINORA_CORE_PUBLIC_URL") or current_app.config.get("BASE_URL") or "https://www.finora.company").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise validation_error("عنوان FINORA العام يجب أن يكون HTTPS صالحاً حتى تصل Meta للمرفقات")
    token = signer().dumps({"slug": slug, "cid": message.conversation_id, "mid": message.id,
                            "aid": str(item.get("index", 0)), "hash": item.get("sha256")})
    return base + url_for("finora_core.deliver_media", token=token)


def send_stored(message, slug: str) -> str:
    from modules.ai_sales.channels import channel_client, outbound_message_id
    from modules.ai_sales.meta_reliability import require_message_id
    from .transport import loopback_enabled
    item = attachment(message, "0")
    path = stored_path(item, slug)
    if loopback_enabled():
        return f"loopback-{uuid.uuid4().hex[:12]}"
    conv = message.conversation
    if conv.channel.channel_type == "telegram":
        result = channel_client(conv.channel).send_file(conv.external_contact_id, item["kind"], path, item.get("mime_type"))
        return require_message_id(outbound_message_id(result))
    result = channel_client(conv.channel).send_media(conv.external_contact_id, item["kind"], url=delivery_url(message, item, slug))
    return require_message_id(outbound_message_id(result))
