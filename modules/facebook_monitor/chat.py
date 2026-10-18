"""Facebook Monitor conversation thread: fetch, reply, and media send via Graph."""
from __future__ import annotations

import mimetypes
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from modules.facebook_monitor.formatters import format_relative
from modules.facebook_monitor.service import _customer_avatar_url, _initials, _page_avatar_url, _parse_fb_time
from utils.meta_graph import GRAPH_BASE

GRAPH = GRAPH_BASE
ALLOWED_MEDIA = {
    "image/jpeg": ("image", ".jpg", 5 * 1024 * 1024),
    "image/png": ("image", ".png", 5 * 1024 * 1024),
    "image/webp": ("image", ".webp", 5 * 1024 * 1024),
    "image/gif": ("image", ".gif", 5 * 1024 * 1024),
    "video/mp4": ("video", ".mp4", 16 * 1024 * 1024),
    "video/quicktime": ("video", ".mov", 16 * 1024 * 1024),
    "audio/mpeg": ("audio", ".mp3", 16 * 1024 * 1024),
    "audio/mp4": ("audio", ".m4a", 16 * 1024 * 1024),
    "audio/ogg": ("audio", ".ogg", 16 * 1024 * 1024),
    "audio/aac": ("audio", ".aac", 16 * 1024 * 1024),
    "application/pdf": ("file", ".pdf", 25 * 1024 * 1024),
}
MEDIA_HOSTS = ("facebook.com", "fbcdn.net", "fbsbx.com", "cdninstagram.com", "instagram.com")


class ChatError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _digits(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def resolve_page_token(external_page_id: str) -> tuple[str, str]:
    """Return (page_id, page_token). Token never leaves the server."""
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.models.publisher_settings import PublisherSettings
    from modules.publisher.services.token_utils import decrypt_token

    page_id = _digits(external_page_id)
    if not page_id:
        raise ChatError("معرّف الصفحة مفقود", 400)

    row = PublisherPage.query.filter_by(page_id=page_id).first()
    if row and row.page_token:
        try:
            token = decrypt_token(row.page_token) or ""
        except Exception:
            token = ""
        if token:
            return page_id, token

    settings = PublisherSettings.get("default")
    # Prefer active tenant settings via PublisherSettings.get which already scopes when called with tenant key.
    try:
        from flask import session

        slug = session.get("tenant_slug") or "default"
        settings = PublisherSettings.get(slug) or settings
    except Exception:
        pass
    if settings and settings.fb_user_token:
        try:
            token = decrypt_token(settings.fb_user_token) or ""
        except Exception:
            token = ""
        if token:
            return page_id, token
    raise ChatError("ماكو توكن للصفحة. اربط الصفحات من الإعدادات أولاً.", 400)


def _graph_get(path: str, token: str, params: dict | None = None, timeout: int = 20) -> dict:
    payload = dict(params or {})
    payload["access_token"] = token
    response = requests.get(f"{GRAPH}/{path.lstrip('/')}", params=payload, timeout=timeout)
    try:
        body = response.json()
    except Exception as exc:
        raise ChatError(f"رد غير صالح من فيسبوك (HTTP {response.status_code})", 502) from exc
    err = body.get("error") or {}
    if err:
        from modules.facebook_monitor.service import _is_limit_error, _mark_graph_limit

        if _is_limit_error(err):
            _mark_graph_limit()
        raise ChatError(err.get("message") or "فشل طلب فيسبوك", 400)
    return body


def _graph_post(path: str, token: str, *, json_body: dict | None = None, files=None, data=None, timeout: int = 45) -> dict:
    url = f"{GRAPH}/{path.lstrip('/')}"
    if files:
        form = dict(data or {})
        form["access_token"] = token
        response = requests.post(url, data=form, files=files, timeout=timeout)
    else:
        payload = dict(json_body or {})
        payload["access_token"] = token
        response = requests.post(url, json=payload, timeout=timeout)
    try:
        body = response.json()
    except Exception as exc:
        raise ChatError(f"رد غير صالح من فيسبوك (HTTP {response.status_code})", 502) from exc
    err = body.get("error") or {}
    if err:
        from modules.facebook_monitor.service import _is_limit_error, _mark_graph_limit

        if _is_limit_error(err):
            _mark_graph_limit()
        raise ChatError(err.get("message") or "فشل إرسال الرسالة", 400)
    return body


def _participant_psid(participants: list[dict], page_id: str) -> tuple[str, str]:
    for person in participants or []:
        pid = str(person.get("id") or "")
        if pid and pid != page_id:
            return pid, str(person.get("name") or "") or "عميل فيسبوك"
    return "", "عميل فيسبوك"


_GENERIC_MEDIA_TEXT = {"صورة", "فيديو", "صوت", "ملف", "وسائط", "ملصق"}
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
_VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".webm")
_AUDIO_EXT = (".ogg", ".oga", ".opus", ".mp3", ".m4a", ".aac", ".wav")


def _allowed_media_host(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and any(host == item or host.endswith(f".{item}") for item in MEDIA_HOSTS)


def _kind_from_mime(mime: str) -> str:
    value = str(mime or "").split(";", 1)[0].strip().lower()
    if value.startswith("image/"):
        return "image"
    if value.startswith("video/"):
        return "video"
    if value.startswith("audio/"):
        return "audio"
    return ""


def _kind_from_hints(kind: str, mime: str, name: str = "", url: str = "") -> str:
    detected = _kind_from_mime(mime)
    if detected:
        return detected
    blob = f"{str(url or '').split('?', 1)[0]} {name}".lower()
    if any(blob.endswith(ext) for ext in _IMAGE_EXT):
        return "image"
    if any(blob.endswith(ext) for ext in _VIDEO_EXT):
        return "video"
    if any(blob.endswith(ext) for ext in _AUDIO_EXT):
        return "audio"
    if kind == "sticker":
        return "image"
    return kind if kind in {"image", "video", "audio", "file"} else "file"


def _magic_mime(sample: bytes) -> str:
    if sample.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if sample.startswith(b"\x89PNG"):
        return "image/png"
    if sample.startswith(b"GIF8"):
        return "image/gif"
    if sample.startswith(b"RIFF") and b"WEBP" in sample[:16]:
        return "image/webp"
    if sample.startswith(b"%PDF"):
        return "application/pdf"
    if sample.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if sample.startswith(b"ID3") or sample.startswith(b"\xff\xfb"):
        return "audio/mpeg"
    if sample.startswith(b"OggS"):
        return "audio/ogg"
    if len(sample) >= 12 and sample[4:8] == b"ftyp":
        brand = sample[8:12]
        if brand in {b"M4A ", b"M4B "}:
            return "audio/mp4"
        return "video/mp4"
    return ""


def _remote_media_url(row) -> str:
    meta = row.get_media_metadata() if hasattr(row, "get_media_metadata") else {}
    for candidate in (meta.get("external_url"), getattr(row, "external_media_id", ""), meta.get("preview_url")):
        value = str(candidate or "")
        if value.startswith("https://") and _allowed_media_host(value):
            return value
    return ""


def _attachment_payload(item: dict, page_id: str) -> dict | None:
    from modules.ai_sales.channels import meta_attachment_details

    details = meta_attachment_details(item.get("attachments"))
    raw = details.get("raw") or {}
    if not raw and not details.get("url"):
        return None
    mime = str(details.get("mime_type") or "")
    name = str(raw.get("name") or "")
    url = str(details.get("url") or "")
    kind = _kind_from_hints(str(details.get("type") or "file"), mime, name, url)
    proxy = ""
    if url and _allowed_media_host(url):
        proxy = f"/api/facebook-monitor/media-proxy?page_id={page_id}&url={quote(url, safe='')}"
    return {
        "kind": kind,
        "mime": mime,
        "name": name,
        "url": proxy,
        "raw_url": "",
    }


def _format_bubble(item: dict, page_id: str, now: datetime) -> dict:
    sender = item.get("from") or {}
    sender_id = str(sender.get("id") or "")
    outbound = sender_id == page_id
    moment = _parse_fb_time(item.get("created_time")) or now
    text = (item.get("message") or "").strip()
    attachment = _attachment_payload(item, page_id)
    if attachment and attachment.get("url") and (not text or text in _GENERIC_MEDIA_TEXT):
        if attachment.get("kind") in {"image", "video", "audio"}:
            text = ""
        elif not text:
            text = "ملف"
    elif not text and attachment:
        text = {"image": "صورة", "video": "فيديو", "audio": "صوت", "file": "ملف"}.get(attachment["kind"], "وسائط")
    return {
        "id": str(item.get("id") or ""),
        "direction": "out" if outbound else "in",
        "text": text,
        "time_label": format_relative(moment, now) if moment else "",
        "created_at": moment.isoformat() if moment else "",
        "sender_name": str(sender.get("name") or ("الصفحة" if outbound else "عميل")),
        "attachment": attachment,
    }


def fetch_thread(*, thread_id: str = "", external_page_id: str, customer_psid: str = "") -> dict[str, Any]:
    page_id, token = resolve_page_token(external_page_id)
    thread_id = str(thread_id or "").strip()
    psid_hint = str(customer_psid or "").strip()
    local = _local_thread(page_id=page_id, customer_psid=psid_hint) if psid_hint else None
    if local:
        _mark_thread_read(page_id, psid_hint)
        return local
    from modules.facebook_monitor.service import _graph_cooling

    if _graph_cooling():
        raise ChatError("فيسبوك محدود حالياً. الرسالة توصل من الويب هوك، جرّب بعد شوية.", 429)

    if not thread_id and psid_hint:
        lookup = _graph_get(
            f"{page_id}/conversations",
            token,
            {
                "platform": "messenger",
                "user_id": psid_hint,
                "fields": "id",
                "limit": 1,
            },
        )
        rows = lookup.get("data") or []
        if rows:
            thread_id = str(rows[0].get("id") or "")
    if not thread_id:
        # Fall back to local AI Sales history when Graph thread id is unknown.
        local = _local_thread(page_id=page_id, customer_psid=psid_hint)
        if local:
            _mark_thread_read(page_id, psid_hint)
            return local
        raise ChatError("ما لقينا المحادثة على فيسبوك. حدّث القائمة وافتح من جديد.", 404)

    fields = (
        "id,updated_time,snippet,participants,"
        "messages.limit(80){id,message,from,created_time,"
        "attachments{mime_type,name,size,image_data,video_data,file_url}}"
    )
    body = _graph_get(thread_id, token, {"fields": fields})
    participants = ((body.get("participants") or {}).get("data") or [])
    psid, customer_name = _participant_psid(participants, page_id)
    if psid_hint and not psid:
        psid = psid_hint
    messages_raw = ((body.get("messages") or {}).get("data") or [])
    now = datetime.utcnow()
    bubbles = [_format_bubble(item, page_id, now) for item in messages_raw]
    local = _local_thread(page_id=page_id, customer_psid=psid or psid_hint)
    if local:
        seen = {str(row.get("id") or "") for row in bubbles if row.get("id")}
        seen_out = {
            (row.get("direction"), (row.get("text") or "").strip())
            for row in bubbles
        }
        for row in local.get("messages") or []:
            rid = str(row.get("id") or "")
            if rid and rid in seen:
                continue
            key = (row.get("direction"), (row.get("text") or "").strip())
            if key[1] and key in seen_out and row.get("direction") == "out":
                continue
            bubbles.append(row)
            if rid:
                seen.add(rid)
    bubbles.sort(key=lambda row: row.get("created_at") or "")

    page_name = ""
    try:
        from modules.publisher.models.publisher_page import PublisherPage

        row = PublisherPage.query.filter_by(page_id=page_id).first()
        page_name = (row.page_name if row else "") or ""
    except Exception:
        page_name = ""

    payload = {
        "thread_id": body.get("id") or thread_id,
        "external_page_id": page_id,
        "customer_psid": psid,
        "customer_name": customer_name,
        "customer_initials": _initials(customer_name),
        "customer_avatar": _customer_avatar_url(page_id, psid or psid_hint, customer_name),
        "page_name": page_name or f"صفحة {page_id}",
        "page_avatar": _page_avatar_url(page_id),
        "can_reply": bool(psid),
        "messages": bubbles,
        "count": len(bubbles),
        **_assignment(page_id, psid or psid_hint),
    }
    _mark_thread_read(page_id, psid or psid_hint)
    return payload


def _mark_thread_read(page_id: str, customer_psid: str) -> None:
    try:
        from flask import session
        from extensions import db
        from modules.ai_sales.models import AISalesConversationRead, AISalesMessage
        from modules.facebook_routing.engine import conversation_for_psid

        employee_id = session.get("user_id")
        if not employee_id or not page_id or not customer_psid:
            return
        conversation = conversation_for_psid(str(page_id), str(customer_psid))
        if not conversation:
            return
        latest = (
            AISalesMessage.query.filter_by(conversation_id=conversation.id, direction="inbound")
            .order_by(AISalesMessage.id.desc())
            .first()
        )
        receipt = AISalesConversationRead.query.filter_by(
            conversation_id=conversation.id, employee_id=employee_id
        ).first()
        if not receipt:
            receipt = AISalesConversationRead(conversation_id=conversation.id, employee_id=employee_id)
            db.session.add(receipt)
        receipt.last_read_message_id = latest.id if latest else receipt.last_read_message_id
        receipt.last_read_at = datetime.utcnow()
        db.session.commit()
    except Exception:
        try:
            from extensions import db

            db.session.rollback()
        except Exception:
            pass


def _assignment(page_id: str, customer_psid: str, conversation=None) -> dict:
    if conversation is None and page_id and customer_psid:
        from modules.facebook_routing.engine import conversation_for_psid

        conversation = conversation_for_psid(page_id, customer_psid)
    employee_id = None
    employee_name = ""
    if conversation is not None and conversation.assigned_employee_id:
        employee_id = conversation.assigned_employee_id
        employee_name = conversation.assigned_employee.name if conversation.assigned_employee else ""
    return {
        "assigned_employee_id": employee_id,
        "assigned_employee_name": employee_name,
    }


def _page_token_or_blank(page_id: str) -> str:
    try:
        _page, token = resolve_page_token(page_id)
        return token
    except Exception:
        return ""


def _download_cdn(url: str, token: str = "", *, limit: int = 30 * 1024 * 1024) -> tuple[bytes, str]:
    if not _allowed_media_host(url):
        raise ChatError("رابط وسائط غير مسموح", 400)

    def _open(with_token: bool):
        params = {"access_token": token} if with_token and token and "access_token=" not in url else None
        return requests.get(url, params=params, timeout=30, stream=True, allow_redirects=True)

    response = _open(False)
    try:
        if response.status_code >= 400 and token:
            response.close()
            response = _open(True)
        if not _allowed_media_host(response.url):
            raise ChatError("إعادة توجيه وسائط غير مسموحة", 400)
        if response.status_code >= 400:
            raise ChatError("تعذر جلب الوسائط من فيسبوك", 502)
        content_type = (response.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].lower()
        if "text/" in content_type or "json" in content_type:
            raise ChatError("ملف الوسائط غير صالح", 502)
        chunks = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise ChatError("الملف كبير جداً", 413)
            chunks.append(chunk)
    finally:
        response.close()
    data = b"".join(chunks)
    sniffed = _magic_mime(data[:32])
    if sniffed:
        content_type = sniffed
    return data, content_type


def _sniff_cdn(url: str, token: str = "") -> str:
    if not _allowed_media_host(url):
        return ""

    def _open(with_token: bool):
        params = {"access_token": token} if with_token and token and "access_token=" not in url else None
        return requests.get(url, params=params, timeout=12, stream=True, allow_redirects=True)

    response = _open(False)
    try:
        if response.status_code >= 400 and token:
            response.close()
            response = _open(True)
        if response.status_code >= 400 or not _allowed_media_host(response.url):
            return ""
        content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
        sample = b""
        for chunk in response.iter_content(64):
            sample = chunk or b""
            break
    finally:
        response.close()
    if "text/" in content_type or "json" in content_type:
        return ""
    return _magic_mime(sample) or (_kind_from_mime(content_type) and content_type) or ""


def _save_media_bytes(data: bytes, mime: str) -> Path:
    from flask import current_app, g

    ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "application/pdf": ".pdf",
    }.get(str(mime or "").split(";", 1)[0].lower()) or ".bin"
    tenant = str(getattr(g, "tenant", None) or "core")
    folder = Path(current_app.root_path) / "uploads" / "ai_sales" / tenant / "inbound"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{uuid.uuid4().hex}{ext}"
    target.write_bytes(data)
    return target


def _stored_file(message) -> Path | None:
    raw = str(getattr(message, "media_path", "") or "")
    if not raw:
        return None
    try:
        from flask import current_app

        target = Path(raw).resolve()
        allowed = (Path(current_app.root_path) / "uploads" / "ai_sales").resolve()
        target.relative_to(allowed)
    except Exception:
        return None
    return target if target.is_file() else None


def _backfill_attachment_urls(page_id: str, customer_psid: str, rows: list) -> None:
    pending = []
    for row in rows:
        kind = str(row.message_type or "").lower()
        if kind not in {"image", "video", "audio", "file", "sticker"}:
            continue
        if _stored_file(row) or _remote_media_url(row):
            continue
        meta = row.get_media_metadata()
        if meta.get("media_graph_miss"):
            continue
        pending.append(row)
    if not pending:
        return
    try:
        from modules.facebook_monitor.service import _graph_cooling

        if _graph_cooling():
            return
        token = _page_token_or_blank(page_id)
        if not token:
            return
        lookup = _graph_get(
            f"{page_id}/conversations",
            token,
            {
                "platform": "messenger",
                "user_id": customer_psid,
                "fields": "messages.limit(30){id,attachments{mime_type,name,image_data,video_data,file_url}}",
                "limit": 1,
            },
        )
    except Exception:
        return
    found = {}
    for thread in lookup.get("data") or []:
        for item in ((thread.get("messages") or {}).get("data") or []):
            mid = str(item.get("id") or "")
            if mid:
                found[mid] = item
    for row in pending:
        item = found.get(str(row.external_message_id or ""))
        details_url = ""
        details_mime = ""
        details_type = ""
        if item:
            from modules.ai_sales.channels import meta_attachment_details

            details = meta_attachment_details(item.get("attachments"))
            details_url = str(details.get("url") or "")
            details_mime = str(details.get("mime_type") or "")
            details_type = str(details.get("type") or "")
            raw_name = str((details.get("raw") or {}).get("name") or "")
            details_type = _kind_from_hints(details_type, details_mime, raw_name, details_url)
        if details_url and _allowed_media_host(details_url):
            meta = row.get_media_metadata()
            meta["external_url"] = details_url
            row.set_media_metadata(meta)
            if len(details_url) <= 180:
                row.external_media_id = details_url
            if details_mime:
                row.mime_type = details_mime
            kind = _kind_from_hints(details_type or row.message_type, details_mime, "", details_url)
            if kind in {"image", "video", "audio"}:
                row.message_type = kind
        else:
            meta = row.get_media_metadata()
            meta["media_graph_miss"] = True
            row.set_media_metadata(meta)


def _refine_row_media(row, page_id: str, network_budget: int) -> int:
    """Classify a stored attachment. Returns remaining network sniff budget."""
    kind = str(row.message_type or "").lower()
    if kind not in {"image", "video", "audio", "file", "sticker"}:
        return network_budget
    stored = _stored_file(row)
    remote = _remote_media_url(row)
    mime = str(row.mime_type or "")
    meta = row.get_media_metadata()
    name = str(meta.get("original_filename") or "")
    detected = _kind_from_hints(kind, mime, name, remote)
    if stored and detected == "file" and network_budget >= 0:
        try:
            sniffed = _magic_mime(stored.read_bytes()[:32])
        except Exception:
            sniffed = ""
        if sniffed:
            row.mime_type = sniffed
            detected = _kind_from_mime(sniffed) or detected
    elif remote and detected == "file" and not meta.get("media_sniffed") and network_budget > 0:
        sniffed = _sniff_cdn(remote, _page_token_or_blank(page_id))
        network_budget -= 1
        if sniffed:
            meta["media_sniffed"] = True
            row.set_media_metadata(meta)
            row.mime_type = sniffed
            detected = _kind_from_mime(sniffed) or detected
    if detected in {"image", "video", "audio"} and row.message_type != detected:
        row.message_type = detected
    return network_budget


def resolve_message_media(message_id: int) -> tuple[Path | bytes, str]:
    """Return local bytes for a stored image, video, or file. Caches Facebook URLs on disk."""
    from extensions import db
    from modules.ai_sales.models import AISalesMessage

    message = AISalesMessage.query.get(message_id)
    if not message:
        raise ChatError("الرسالة غير موجودة", 404)
    stored = _stored_file(message)
    if stored:
        mime = str(message.mime_type or "") or _magic_mime(stored.read_bytes()[:32]) or "application/octet-stream"
        return stored, mime
    remote = _remote_media_url(message)
    if not remote:
        raise ChatError("الوسائط غير محفوظة. الصق توكن صفحة جديد ثم أعد فتح المحادثة.", 404)
    channel = message.conversation.channel if message.conversation else None
    page_id = str(getattr(channel, "page_id", "") or "")
    data, mime = _download_cdn(remote, _page_token_or_blank(page_id))
    target = _save_media_bytes(data, mime)
    message.media_path = str(target)
    message.mime_type = mime
    kind = _kind_from_mime(mime)
    if kind:
        message.message_type = kind
    db.session.commit()
    return target, mime


def _local_thread(*, page_id: str, customer_psid: str) -> dict | None:
    if not customer_psid:
        return None
    from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation, AISalesMessage

    channels = AISalesChannelAccount.query.filter(
        AISalesChannelAccount.channel_type.in_(("messenger", "facebook")),
        AISalesChannelAccount.page_id == page_id,
    ).all()
    if not channels:
        return None
    channel_ids = [row.id for row in channels]
    conversation = (
        AISalesConversation.query.filter(
            AISalesConversation.channel_account_id.in_(channel_ids),
            AISalesConversation.external_contact_id == customer_psid,
        )
        .order_by(AISalesConversation.updated_at.desc())
        .first()
    )
    if not conversation:
        return None
    rows = (
        AISalesMessage.query.filter_by(conversation_id=conversation.id)
        .order_by(AISalesMessage.created_at.asc(), AISalesMessage.id.asc())
        .limit(120)
        .all()
    )
    try:
        _backfill_attachment_urls(page_id, customer_psid, rows)
        budget = 6
        for row in rows:
            budget = _refine_row_media(row, page_id, budget)
        from extensions import db

        if db.session.dirty or db.session.new:
            db.session.commit()
    except Exception:
        try:
            from extensions import db

            db.session.rollback()
        except Exception:
            pass
    now = datetime.utcnow()
    bubbles = []
    for row in rows:
        text = (row.text_content or row.transcription or "").strip()
        kind = (row.message_type or "text").lower()
        meta = row.get_media_metadata()
        name = str(meta.get("original_filename") or "")
        remote = _remote_media_url(row)
        kind = _kind_from_hints(kind, row.mime_type or "", name, remote)
        attachment = None
        playable = bool(row.id and (_stored_file(row) or remote) and kind in {"image", "video", "audio", "file"})
        if playable:
            attachment = {
                "kind": kind,
                "mime": row.mime_type or "",
                "name": name,
                "url": f"/api/facebook-monitor/message-media/{row.id}",
            }
            if kind in {"image", "video", "audio"} and (not text or text in _GENERIC_MEDIA_TEXT):
                text = ""
            elif not text:
                text = "ملف"
        elif kind in {"image", "video", "audio", "file"} and row.id:
            attachment = {"kind": kind, "mime": row.mime_type or "", "name": name, "url": ""}
            if not text:
                text = {"image": "صورة", "video": "فيديو", "audio": "صوت", "file": "ملف"}.get(kind, "وسائط")
        bubbles.append({
            "id": str(row.external_message_id or row.id),
            "direction": "out" if row.direction == "outbound" else "in",
            "text": text or "رسالة بدون نص",
            "time_label": format_relative(row.created_at, now) if row.created_at else "",
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "sender_name": "الصفحة" if row.direction == "outbound" else (conversation.contact_name or "عميل"),
            "attachment": attachment,
        })
    channel = conversation.channel
    return {
        "thread_id": "",
        "external_page_id": page_id,
        "customer_psid": customer_psid,
        "customer_name": conversation.contact_name or "عميل فيسبوك",
        "customer_initials": _initials(conversation.contact_name),
        "customer_avatar": _customer_avatar_url(page_id, customer_psid, conversation.contact_name),
        "page_name": (channel.name if channel else "") or f"صفحة {page_id}",
        "page_avatar": _page_avatar_url(page_id),
        "can_reply": True,
        "messages": bubbles,
        "count": len(bubbles),
        "source": "local",
        **_assignment(page_id, customer_psid, conversation),
    }


def _store_outbound(
    *,
    page_id: str,
    customer_psid: str,
    text: str,
    message_id: str = "",
    message_type: str = "text",
    media_path: str = "",
    mime_type: str = "",
    filename: str = "",
) -> int | None:
    local_id = None
    try:
        from extensions import db
        from modules.ai_sales.engine import get_or_create_conversation
        from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
        from modules.facebook_monitor.service import clear_graph_cache

        channel = AISalesChannelAccount.query.filter(
            AISalesChannelAccount.page_id == str(page_id),
            AISalesChannelAccount.channel_type.in_(("messenger", "facebook")),
        ).first()
        if channel:
            conversation = get_or_create_conversation(
                channel,
                external_contact_id=str(customer_psid),
                phone="",
                contact_name="",
            )
            now = datetime.utcnow()
            existing = None
            if message_id:
                existing = AISalesMessage.query.filter_by(
                    channel_account_id=channel.id, external_message_id=message_id
                ).first()
            if existing:
                if media_path and not existing.media_path:
                    existing.media_path = media_path
                    existing.mime_type = mime_type or existing.mime_type
                    existing.message_type = message_type or existing.message_type
                local_id = existing.id
            else:
                message = AISalesMessage(
                    conversation_id=conversation.id,
                    channel_account_id=channel.id,
                    external_message_id=message_id or None,
                    direction="outbound",
                    sender_type="employee",
                    message_type=message_type or "text",
                    text_content=text,
                    mime_type=mime_type or None,
                    media_path=media_path or None,
                    status="sent",
                    sent_at=now,
                    created_at=now,
                )
                if filename:
                    message.set_media_metadata({"original_filename": str(filename)[:240]})
                db.session.add(message)
                db.session.flush()
                local_id = message.id
            conversation.last_business_message_at = now
            conversation.updated_at = now
            db.session.commit()
            try:
                from modules.facebook_routing.engine import refill_after_reply

                refill_after_reply(str(page_id))
            except Exception:
                pass
        clear_graph_cache()
    except Exception:
        try:
            from extensions import db

            db.session.rollback()
        except Exception:
            pass
        try:
            from modules.facebook_monitor.service import clear_graph_cache

            clear_graph_cache()
        except Exception:
            pass
    return local_id


def send_text(*, external_page_id: str, customer_psid: str, text: str) -> dict:
    page_id, token = resolve_page_token(external_page_id)
    psid = str(customer_psid or "").strip()
    body_text = str(text or "").strip()
    if not psid:
        raise ChatError("معرّف العميل مفقود — افتح المحادثة من جديد", 400)
    if not body_text:
        raise ChatError("اكتب رسالة قبل الإرسال", 400)
    if len(body_text) > 2000:
        raise ChatError("الرسالة طويلة جداً (حد أقصى 2000 حرف)", 400)

    result = _graph_post(
        f"{page_id}/messages",
        token,
        json_body={
            "recipient": {"id": psid},
            "messaging_type": "RESPONSE",
            "message": {"text": body_text},
        },
    )
    message_id = str(result.get("message_id") or "")
    _store_outbound(page_id=page_id, customer_psid=psid, text=body_text, message_id=message_id, message_type="text")
    return {
        "message_id": message_id,
        "text": body_text,
        "direction": "out",
        "time_label": "الآن",
        "created_at": datetime.utcnow().isoformat(),
        "attachment": None,
    }


def send_media(*, external_page_id: str, customer_psid: str, file_bytes: bytes, mime_type: str, filename: str = "") -> dict:
    page_id, token = resolve_page_token(external_page_id)
    psid = str(customer_psid or "").strip()
    mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if not psid:
        raise ChatError("معرّف العميل مفقود", 400)
    rule = ALLOWED_MEDIA.get(mime)
    if not rule:
        # fallback by extension
        guessed, _ = mimetypes.guess_type(filename or "")
        mime = (guessed or "").lower()
        rule = ALLOWED_MEDIA.get(mime)
    if not rule:
        raise ChatError("صيغة الملف غير مدعومة. استخدم صورة، فيديو، صوت، أو PDF.", 400)
    kind, _ext, max_bytes = rule
    if not file_bytes:
        raise ChatError("الملف فارغ", 400)
    if len(file_bytes) > max_bytes:
        raise ChatError(f"حجم الملف يتجاوز {max_bytes // (1024 * 1024)} MB", 413)

    upload = _graph_post(
        f"{page_id}/message_attachments",
        token,
        data={"message": f'{{"attachment":{{"type":"{kind}","payload":{{"is_reusable":true}}}}}}'},
        files={"filedata": (filename or f"upload{_ext}", file_bytes, mime)},
    )
    attachment_id = str(upload.get("attachment_id") or "")
    if not attachment_id:
        raise ChatError("فيسبوك ما رجّع معرّف المرفق", 502)

    result = _graph_post(
        f"{page_id}/messages",
        token,
        json_body={
            "recipient": {"id": psid},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": kind,
                    "payload": {"attachment_id": attachment_id},
                }
            },
        },
    )
    labels = {"image": "صورة", "video": "فيديو", "audio": "صوت", "file": "ملف"}
    message_id = str(result.get("message_id") or "")
    preview = labels.get(kind, "وسائط")
    target = _save_media_bytes(file_bytes, mime)
    local_id = _store_outbound(
        page_id=page_id,
        customer_psid=psid,
        text=preview,
        message_id=message_id,
        message_type=kind,
        media_path=str(target),
        mime_type=mime,
        filename=filename,
    )
    media_url = f"/api/facebook-monitor/message-media/{local_id}" if local_id else ""
    return {
        "message_id": message_id,
        "text": "" if kind in {"image", "video", "audio"} else preview,
        "direction": "out",
        "time_label": "الآن",
        "created_at": datetime.utcnow().isoformat(),
        "attachment": {"kind": kind, "mime": mime, "name": filename, "url": media_url},
    }


def proxy_media(*, external_page_id: str, media_url: str) -> tuple[bytes, str]:
    page_id, token = resolve_page_token(external_page_id)
    parsed = urlparse(str(media_url or ""))
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not any(host == h or host.endswith(f".{h}") for h in MEDIA_HOSTS):
        raise ChatError("رابط وسائط غير مسموح", 400)

    response = requests.get(
        media_url,
        params={"access_token": token} if "access_token=" not in media_url else None,
        timeout=30,
        stream=True,
        allow_redirects=True,
    )
    final = urlparse(response.url)
    final_host = (final.hostname or "").lower().rstrip(".")
    if not any(final_host == h or final_host.endswith(f".{h}") for h in MEDIA_HOSTS):
        raise ChatError("إعادة توجيه وسائط غير مسموحة", 400)
    if response.status_code >= 400:
        raise ChatError("تعذر جلب الوسائط من فيسبوك", 502)
    content_type = response.headers.get("Content-Type") or "application/octet-stream"
    if "text/" in content_type or "json" in content_type:
        raise ChatError("ملف الوسائط غير صالح", 502)
    data = response.content
    if len(data) > 30 * 1024 * 1024:
        raise ChatError("الملف كبير جداً", 413)
    return data, content_type
