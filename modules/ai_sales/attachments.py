"""Attachment pipeline for Meta (Messenger / Instagram) messages.

Stage 1 (webhook, synchronous, never raises): normalize EVERY attachment of a message into safe metadata stored on the
message (``media_metadata_json["attachments"]``). Unsupported types are kept with ``status="unsupported"`` so the
conversation never breaks.
Stage 2 (background): download each supported attachment from Meta's CDN (host allow-list, size cap, page token never
sent), store it under ``uploads/ai_sales_media/<tenant>/`` with a content hash, and record ``stored`` / ``failed``.
Content analysis (vision / transcription / document parsing) is a later phase and is not done here.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MAX_ATTACHMENTS = 10
MAX_BYTES = {"image": 15 * 1024 * 1024, "audio": 25 * 1024 * 1024, "video": 50 * 1024 * 1024, "document": 25 * 1024 * 1024}
ALLOWED_HOSTS = ("facebook.com", "fbcdn.net", "fbsbx.com", "instagram.com", "cdninstagram.com")
DOCUMENT_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/csv",
}
_EXT_KIND = {
    "image": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"),
    "audio": (".ogg", ".oga", ".opus", ".mp3", ".m4a", ".aac", ".wav", ".mp4a"),
    "video": (".mp4", ".mov", ".m4v", ".webm"),
    "document": (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv"),
}
_SAFE_NAME = re.compile(r"[^\w.\- ()؀-ۿ]+")
LABELS = {
    "image": "[صورة]",
    "audio": "[رسالة صوتية]",
    "video": "[فيديو]",
    "document": "[ملف]",
    "sticker": "[ملصق]",
    "unsupported": "[مرفق غير مدعوم]",
}


def _allowed_url(url: str) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and any(host == h or host.endswith(f".{h}") for h in ALLOWED_HOSTS)


def _kind(meta_type: str, mime: str, name: str, url: str) -> str:
    meta_type = (meta_type or "").lower()
    if meta_type in {"image", "audio", "video"}:
        return meta_type
    if meta_type == "sticker":
        return "sticker"
    mime = (mime or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime in DOCUMENT_MIMES:
        return "document"
    probe = f"{name} {url.split('?', 1)[0]}".lower()
    for kind, exts in _EXT_KIND.items():
        if any(probe.endswith(e) or f"{e} " in probe for e in exts):
            return kind
    if meta_type == "file":
        return "document"
    return "unsupported"


def safe_name(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", os.path.basename(name or "")).strip(" ._")
    return cleaned[:120]


def normalize(attachments: Any) -> list[dict[str, Any]]:
    """Webhook/Graph attachment list → safe metadata. Never raises."""
    rows = attachments.get("data") if isinstance(attachments, dict) else attachments
    result: list[dict[str, Any]] = []
    for index, row in enumerate((rows or [])[:MAX_ATTACHMENTS]):
        if not isinstance(row, dict):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        url = str(payload.get("url") or row.get("url") or row.get("file_url") or "")
        name = safe_name(str(row.get("name") or payload.get("name") or payload.get("title") or ""))
        mime = str(row.get("mime_type") or payload.get("mime_type") or "").lower()[:100]
        kind = _kind(str(row.get("type") or ""), mime, name, url)
        downloadable = kind in MAX_BYTES and _allowed_url(url)
        result.append(
            {
                "index": index,
                "kind": kind,
                "meta_type": str(row.get("type") or "")[:40],
                "mime_type": mime or None,
                "name": name or None,
                # Signed Meta CDN URL: server-side only, never sent to the desktop or an LLM prompt.
                "source_url": url if downloadable else None,
                "source_host": (urlparse(url).hostname or "")[:120] if url else None,
                "status": "pending" if downloadable else ("unsupported" if kind in {"unsupported"} else "not_downloadable"),
                "size_bytes": None,
                "sha256": None,
                "stored_path": None,
            }
        )
    return result


def label_for(attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return ""
    first = attachments[0]["kind"]
    label = LABELS.get(first, LABELS["unsupported"])
    return label if len(attachments) == 1 else f"{label} +{len(attachments) - 1}"


def public_view(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the desktop may see: no URLs, no storage paths."""
    return [
        {
            "id": str(a.get("index", i)),
            "kind": a.get("kind", "unsupported"),
            "mimeType": a.get("mime_type"),
            "name": a.get("name"),
            "sizeBytes": a.get("size_bytes"),
            "status": a.get("status", "pending"),
        }
        for i, a in enumerate(attachments or [])
    ]


def storage_root(tenant_slug: str) -> str:
    from flask import current_app

    root = os.path.join(current_app.root_path, "uploads", "ai_sales_media", tenant_slug)
    os.makedirs(root, exist_ok=True)
    return root


def store_message_attachments(message, channel, tenant_slug: str, *, downloader=None) -> int:
    """Stage 2: download pending attachments. Returns the number stored. Never raises; caller commits."""
    from .channels import MetaMessagingClient, MetaMessagingClientError

    meta = message.get_media_metadata()
    items = meta.get("attachments") or []
    stored = 0
    for item in items:
        telegram = channel.channel_type == "telegram" and bool(item.get("telegram_file_id"))
        if item.get("status") != "pending" or not (item.get("source_url") or telegram):
            continue
        cap = MAX_BYTES.get(item.get("kind"), 0)
        try:
            if telegram:
                from .telegram import TelegramBotClient
                fetch = downloader or TelegramBotClient(channel).download_file
                source = item["telegram_file_id"]
            else:
                fetch = downloader or MetaMessagingClient(channel).download_media
                source = item["source_url"]
            content, mime = fetch(source, max_bytes=cap)
            digest = hashlib.sha256(content).hexdigest()
            ext = os.path.splitext(item.get("name") or "")[1].lower()[:8] or _ext_for(mime)
            filename = f"m{message.id}-{item['index']}-{digest[:16]}{ext}"
            path = os.path.join(storage_root(tenant_slug), filename)
            with open(path, "wb") as fh:
                fh.write(content)
            item.update(
                status="stored",
                size_bytes=len(content),
                sha256=digest,
                mime_type=(mime or item.get("mime_type") or None),
                stored_path=os.path.relpath(path, storage_root(tenant_slug)),
                source_url=None,  # signed URL no longer needed once stored
                stored_at=datetime.utcnow().isoformat(),
            )
            stored += 1
        except MetaMessagingClientError as exc:
            item.update(status="failed", error=str(exc)[:200])
            logger.warning("attachment %s/%s download failed: %s", message.id, item.get("index"), exc)
        except Exception as exc:  # network, disk — recorded, never breaks the conversation
            item.update(status="failed", error=type(exc).__name__)
            logger.exception("attachment %s/%s storage failed", message.id, item.get("index"))
    meta["attachments"] = items
    message.set_media_metadata(meta)
    return stored


def _ext_for(mime: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "video/mp4": ".mp4",
        "application/pdf": ".pdf",
    }.get((mime or "").lower(), ".bin")


def dispatch_storage_async(app, tenant_slug: str, message_ids: list[int]) -> None:
    """Stage 2 in a background thread so the webhook answers Meta immediately."""
    from threading import Thread

    from flask import g

    from extensions import db

    from .models import AISalesMessage

    def runner() -> None:
        with app.app_context():
            g.tenant = tenant_slug
            try:
                for message_id in message_ids:
                    message = AISalesMessage.query.get(message_id)
                    if message is None or message.conversation is None:
                        continue
                    store_message_attachments(message, message.conversation.channel, tenant_slug)
                    db.session.commit()
            except Exception:
                app.logger.exception("attachment storage worker failed")
                db.session.rollback()
            finally:
                db.session.remove()

    Thread(target=runner, name=f"ai-sales-attachments-{tenant_slug}", daemon=True).start()
