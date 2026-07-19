"""Meta channel clients and webhook payload parsers."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from flask import current_app

from .models import AISalesChannelAccount
from .security import decrypt_secret


def _redact_log_value(value: Any) -> Any:
    """Remove credentials from structured Graph API logs."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(marker in str(key).lower() for marker in ("token", "secret", "authorization")) else _redact_log_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_log_value(item) for item in value]
    return value


class WhatsAppClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, meta_code: int | None = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.meta_code = meta_code
        self.response_body = response_body


class WhatsAppClient:
    def __init__(self, channel: AISalesChannelAccount):
        self.channel = channel
        self.access_token = decrypt_secret(channel.access_token_encrypted)
        if not self.access_token or not channel.phone_number_id:
            raise WhatsAppClientError("قناة واتساب غير مكتملة: التوكن وPhone Number ID مطلوبان")
        version = (channel.api_version or "v23.0").strip()
        self.graph_root = f"https://graph.facebook.com/{version}"
        self.base_url = f"{self.graph_root}/{channel.phone_number_id}"

    def _post(self, path: str, payload: dict) -> dict:
        endpoint = f"{self.base_url}/{path.lstrip('/')}"
        current_app.logger.warning(
            "AI_SALES_OUTBOUND %s",
            json.dumps(
                {
                    "event": "graph_request",
                    "method": "POST",
                    "endpoint": endpoint,
                    "phone_number_id": self.channel.phone_number_id,
                    "graph_version": self.channel.api_version or "v23.0",
                    "headers": {"Authorization": "Bearer [REDACTED]", "Content-Type": "application/json"},
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
        )
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text[:500]}
        error = body.get("error", {}) if isinstance(body, dict) else {}
        current_app.logger.warning(
            "AI_SALES_OUTBOUND %s",
            json.dumps(
                {
                    "event": "graph_response",
                    "endpoint": endpoint,
                    "http_status": response.status_code,
                    "meta_error_code": error.get("code"),
                    "meta_error_message": error.get("message"),
                    "response_body": body,
                },
                ensure_ascii=False,
                default=str,
            ),
        )
        if response.status_code >= 400:
            raise WhatsAppClientError(
                error.get("message") or f"WhatsApp HTTP {response.status_code}",
                status_code=response.status_code,
                meta_code=error.get("code"),
                response_body=body,
            )
        return body

    def _get(self, path: str, *, params: dict | None = None) -> dict:
        endpoint = f"{self.base_url}/{path.lstrip('/')}"
        response = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {self.access_token}"},
            params=params,
            timeout=30,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text[:500]}
        if response.status_code >= 400:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            raise WhatsAppClientError(
                error.get("message") or f"WhatsApp HTTP {response.status_code}",
                status_code=response.status_code,
                meta_code=error.get("code"),
                response_body=body,
            )
        return body

    def get_calling_settings(self) -> dict:
        return self._get("settings")

    def update_calling_settings(self, calling: dict) -> dict:
        return self._post("settings", {"calling": calling})

    def call_action(self, call_id: str, action: str, *, session: dict | None = None) -> dict:
        if action not in {"pre_accept", "accept", "reject", "terminate"}:
            raise WhatsAppClientError("Unsupported WhatsApp call action")
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "call_id": str(call_id or "").strip(),
            "action": action,
        }
        if not payload["call_id"]:
            raise WhatsAppClientError("Call ID is required")
        if session:
            payload["session"] = session
        return self._post("calls", payload)

    def send_text(self, to_phone: str, text: str) -> dict:
        return self._post(
            "messages",
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_phone,
                "type": "text",
                "text": {"preview_url": False, "body": text[:4096]},
            },
        )

    def send_media(self, to_phone: str, media_type: str, *, media_id: str | None = None, link: str | None = None, caption: str = "") -> dict:
        media_type = media_type.lower()
        if media_type not in {"image", "video", "audio", "document"}:
            raise WhatsAppClientError("نوع الوسائط غير مدعوم")
        media: dict[str, Any] = {"id": media_id} if media_id else {"link": link}
        if not media.get("id") and not media.get("link"):
            raise WhatsAppClientError("Media ID أو رابط الوسائط مطلوب")
        if caption and media_type in {"image", "video", "document"}:
            media["caption"] = caption[:1024]
        return self._post(
            "messages",
            {"messaging_product": "whatsapp", "to": to_phone, "type": media_type, media_type: media},
        )

    def get_media_info(self, media_id: str) -> dict:
        response = requests.get(
            f"{self.graph_root}/{media_id}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=20,
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not body.get("url"):
            raise WhatsAppClientError((body.get("error") or {}).get("message") or "تعذر جلب معلومات الوسائط")
        return body

    def download_media(self, media_id: str, *, max_bytes: int) -> tuple[bytes, str]:
        info = self.get_media_info(media_id)
        response = requests.get(
            info["url"],
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=45,
            stream=True,
        )
        if response.status_code >= 400:
            raise WhatsAppClientError("تعذر تنزيل وسائط واتساب")
        content = bytearray()
        for chunk in response.iter_content(64 * 1024):
            content.extend(chunk)
            if len(content) > max_bytes:
                raise WhatsAppClientError("حجم الوسائط أكبر من الحد المسموح")
        return bytes(content), str(info.get("mime_type") or response.headers.get("Content-Type") or "application/octet-stream")

    def upload_media(self, file_path: str, mime_type: str) -> str:
        with open(file_path, "rb") as handle:
            response = requests.post(
                f"{self.base_url}/media",
                headers={"Authorization": f"Bearer {self.access_token}"},
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1], handle, mime_type)},
                timeout=45,
            )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not body.get("id"):
            raise WhatsAppClientError((body.get("error") or {}).get("message") or "تعذر رفع الوسائط إلى واتساب")
        return str(body["id"])


class MetaMessagingClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, meta_code: int | None = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.meta_code = meta_code
        self.response_body = response_body


class MetaMessagingClient:
    """Graph API client for a Meta connector, Messenger page, or Instagram account."""

    def __init__(self, channel: AISalesChannelAccount, *, access_token: str | None = None):
        self.channel = channel
        self.access_token = str(access_token or "").strip() or decrypt_secret(channel.access_token_encrypted)
        if not self.access_token:
            raise MetaMessagingClientError("رمز وصول Meta غير محفوظ لهذه القناة")
        version = (channel.api_version or "v23.0").strip()
        self.graph_root = f"https://graph.facebook.com/{version}"

    def _request(self, method: str, path: str, *, params: dict | None = None, payload: dict | None = None) -> dict:
        endpoint = path if path.startswith("https://") else f"{self.graph_root}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        current_app.logger.info(
            "AI_SALES_META %s",
            json.dumps({
                "event": "graph_request",
                "method": method,
                "endpoint": endpoint,
                "channel_type": self.channel.channel_type,
                "account_id": self.channel.external_account_id,
                "params": _redact_log_value(params or {}),
                "payload": _redact_log_value(payload or {}),
            }, ensure_ascii=False, default=str),
        )
        response = requests.request(method, endpoint, headers=headers, params=params, json=payload, timeout=30)
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text[:1000]}
        error = body.get("error", {}) if isinstance(body, dict) else {}
        current_app.logger.info(
            "AI_SALES_META %s",
            json.dumps({
                "event": "graph_response",
                "endpoint": endpoint,
                "http_status": response.status_code,
                "meta_error_code": error.get("code"),
                "meta_error_message": error.get("message"),
            }, ensure_ascii=False, default=str),
        )
        if response.status_code >= 400:
            raise MetaMessagingClientError(
                error.get("message") or f"Meta HTTP {response.status_code}",
                status_code=response.status_code,
                meta_code=error.get("code"),
                response_body=body,
            )
        return body

    def list_pages(self) -> list[dict]:
        fields = "id,name,access_token,tasks,picture{url},instagram_business_account{id,username,name,profile_picture_url}"
        path = "me/accounts"
        params = {"fields": fields, "limit": 100}
        pages: list[dict] = []
        while path:
            body = self._request("GET", path, params=params)
            pages.extend(body.get("data") or [])
            path = ((body.get("paging") or {}).get("next") or "")
            params = None
        return pages

    def token_info(self) -> dict:
        response = requests.get(
            f"{self.graph_root}/debug_token",
            params={"input_token": self.access_token},
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=30,
        )
        body = response.json() if response.content else {}
        if response.status_code >= 400:
            error = body.get("error", {})
            raise MetaMessagingClientError(
                error.get("message") or "تعذر التحقق من Meta App ID",
                status_code=response.status_code,
                meta_code=error.get("code"),
                response_body=body,
            )
        return body.get("data") or {}

    def account_profile(self) -> dict:
        """Resolve the Facebook Page represented by a Page Access Token."""
        return self._request("GET", "me", params={"fields": "id,name,picture{url}"})

    def configure_app_webhook(self, object_name: str, callback_url: str, verify_token: str, fields: str) -> dict:
        app_id = str(self.channel.external_account_id or "")
        app_secret = decrypt_secret(self.channel.app_secret_encrypted)
        if not app_id or not app_secret:
            raise MetaMessagingClientError("App ID وApp Secret مطلوبان لتسجيل Webhook تلقائياً")
        endpoint = f"{self.graph_root}/{app_id}/subscriptions"
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {app_id}|{app_secret}"},
            data={
                "object": object_name,
                "callback_url": callback_url,
                "verify_token": verify_token,
                "fields": fields,
                "include_values": "true",
            },
            timeout=30,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text[:1000]}
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if response.status_code >= 400 or body.get("success") is False:
            raise MetaMessagingClientError(
                error.get("message") or f"Meta Webhook HTTP {response.status_code}",
                status_code=response.status_code,
                meta_code=error.get("code"),
                response_body=body,
            )
        return body

    def subscribe_page(self, page_id: str, *, fields: str | None = None) -> dict:
        subscribed_fields = fields or (
            "messages,messaging_postbacks,messaging_optins,messaging_referrals,"
            "message_deliveries,message_reads,feed"
        )
        return self._request(
            "POST",
            f"{page_id}/subscribed_apps",
            params={"subscribed_fields": subscribed_fields},
        )

    def list_page_posts(self, *, limit: int = 30) -> list[dict]:
        page_id = self.channel.external_account_id or self.channel.page_id
        if not page_id:
            return []
        fields = (
            "id,message,story,created_time,permalink_url,full_picture,status_type,"
            "attachments.limit(5){media,type,target,url,subattachments},comments.limit(0).summary(true)"
        )
        body = self._request(
            "GET",
            f"{page_id}/published_posts",
            params={"fields": fields, "limit": min(max(int(limit or 30), 1), 100)},
        )
        return body.get("data") or []

    def get_post(self, post_id: str) -> dict:
        fields = (
            "id,message,story,created_time,permalink_url,full_picture,status_type,"
            "attachments.limit(5){media,type,target,url,subattachments},comments.limit(0).summary(true)"
        )
        return self._request("GET", post_id, params={"fields": fields})

    def list_post_comments(self, post_id: str, *, limit: int = 100) -> list[dict]:
        fields = (
            "id,message,created_time,from{id,name,picture},parent{id},permalink_url,"
            "attachment,can_reply_privately,private_reply_conversation"
        )
        body = self._request(
            "GET",
            f"{post_id}/comments",
            params={
                "fields": fields,
                "filter": "stream",
                "order": "reverse_chronological",
                "limit": min(max(int(limit or 100), 1), 100),
            },
        )
        return body.get("data") or []

    def get_comment(self, comment_id: str) -> dict:
        fields = (
            "id,message,created_time,from{id,name,picture},parent{id},permalink_url,"
            "attachment,can_reply_privately,private_reply_conversation"
        )
        return self._request("GET", comment_id, params={"fields": fields})

    def reply_to_comment(self, comment_id: str, message: str) -> dict:
        return self._request(
            "POST",
            f"{comment_id}/comments",
            payload={"message": str(message or "").strip()[:8000]},
        )

    def private_reply_to_comment(self, comment_id: str, message: str) -> dict:
        page_id = self.channel.external_account_id or self.channel.page_id
        if not page_id:
            raise MetaMessagingClientError("Page ID غير محفوظ لهذه القناة")
        return self._request(
            "POST",
            f"{page_id}/messages",
            payload={
                "recipient": {"comment_id": str(comment_id)},
                "message": {"text": str(message or "").strip()[:2000]},
            },
        )

    def subscribe_instagram(self, instagram_id: str) -> dict:
        return self._request(
            "POST",
            f"{instagram_id}/subscribed_apps",
            params={"subscribed_fields": "messages,messaging_postbacks"},
        )

    def send_text(self, recipient_id: str, text: str) -> dict:
        account_id = self.channel.external_account_id
        if not account_id:
            raise MetaMessagingClientError("معرف صفحة Meta غير موجود")
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text[:2000]},
        }
        if self.channel.channel_type == "messenger":
            payload["messaging_type"] = "RESPONSE"
        return self._request("POST", f"{account_id}/messages", payload=payload)

    def send_media(self, recipient_id: str, media_type: str, *, url: str) -> dict:
        account_id = self.channel.external_account_id
        if not account_id:
            raise MetaMessagingClientError("معرف صفحة Meta غير موجود")
        media_type = (media_type or "").lower()
        if self.channel.channel_type == "instagram" and media_type != "image":
            raise MetaMessagingClientError("إنستغرام يدعم إرسال الصور فقط من صندوق Finora حالياً")
        if media_type not in {"image", "video", "audio", "file"}:
            raise MetaMessagingClientError("نوع الوسائط غير مدعوم في Meta")
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": media_type,
                    "payload": {"url": url, "is_reusable": True},
                }
            },
        }
        if self.channel.channel_type == "messenger":
            payload["messaging_type"] = "RESPONSE"
        return self._request("POST", f"{account_id}/messages", payload=payload)

    def download_media(self, media_url: str, *, max_bytes: int) -> tuple[bytes, str]:
        """Download a signed Messenger/Instagram attachment without exposing the page token."""
        allowed_hosts = (
            "facebook.com",
            "fbcdn.net",
            "fbsbx.com",
            "instagram.com",
            "cdninstagram.com",
        )

        def validate_url(value: str) -> None:
            parsed = urlparse(value)
            host = (parsed.hostname or "").lower().rstrip(".")
            if parsed.scheme != "https" or not any(host == suffix or host.endswith(f".{suffix}") for suffix in allowed_hosts):
                raise MetaMessagingClientError("رابط وسائط Meta غير صالح")

        validate_url(media_url)
        response = requests.get(media_url, timeout=45, stream=True, allow_redirects=True)
        validate_url(response.url)
        if response.status_code >= 400:
            raise MetaMessagingClientError(
                "تعذر تنزيل وسائط Meta",
                status_code=response.status_code,
                response_body={"url_host": urlparse(response.url).hostname or ""},
            )
        content = bytearray()
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > max_bytes:
                raise MetaMessagingClientError("حجم وسائط Meta أكبر من الحد المسموح")
        mime_type = str(response.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].lower()
        if mime_type == "application/octet-stream":
            path = urlparse(response.url).path.lower()
            extension_mimes = {
                ".ogg": "audio/ogg",
                ".oga": "audio/ogg",
                ".mp3": "audio/mpeg",
                ".m4a": "audio/mp4",
                ".aac": "audio/aac",
                ".webm": "audio/webm",
                ".mp4": "video/mp4",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
            }
            mime_type = next((value for extension, value in extension_mimes.items() if extension in path), mime_type)
        return bytes(content), mime_type

    def contact_profile(self, contact_id: str) -> dict:
        fields = "name,username,first_name,last_name,profile_pic,profile_picture_url"
        try:
            return self._request("GET", contact_id, params={"fields": fields})
        except MetaMessagingClientError:
            return {}

    def list_conversations(self, *, limit: int = 50) -> list[dict]:
        page_id = self.channel.page_id or self.channel.external_account_id
        if not page_id:
            return []
        params = {
            "fields": "id,updated_time,participants{id,name,username,picture},messages.limit(50){id,created_time,from,to,message,attachments}",
            "limit": min(max(limit, 1), 100),
        }
        if self.channel.channel_type == "instagram":
            params["platform"] = "instagram"
        body = self._request("GET", f"{page_id}/conversations", params=params)
        return body.get("data") or []


def channel_client(channel: AISalesChannelAccount):
    if channel.channel_type == "whatsapp":
        return WhatsAppClient(channel)
    if channel.channel_type in {"messenger", "instagram", "meta"}:
        return MetaMessagingClient(channel)
    raise ValueError(f"قناة غير مدعومة: {channel.channel_type}")


def outbound_message_id(body: dict | None) -> str:
    body = body or {}
    if body.get("messages"):
        return str(body["messages"][0].get("id") or "")
    return str(body.get("message_id") or body.get("id") or "")


def meta_attachment_details(attachments) -> dict:
    """Normalize webhook and Graph conversation attachment shapes."""
    if isinstance(attachments, dict):
        rows = attachments.get("data") or []
    else:
        rows = attachments or []
    first = rows[0] if rows else {}
    payload = first.get("payload") or {}
    mime_type = str(first.get("mime_type") or payload.get("mime_type") or "").lower()
    attachment_type = str(first.get("type") or "").lower()
    sticker_id = str(
        first.get("sticker_id")
        or payload.get("sticker_id")
        or first.get("stickerId")
        or payload.get("stickerId")
        or ""
    ).strip()
    is_like = attachment_type == "sticker" and sticker_id == "369239263222822"
    raw_url = str(
        payload.get("url")
        or first.get("url")
        # Graph conversation-sync audio/file attachments expose the link as file_url
        or first.get("file_url")
        or payload.get("file_url")
        or ""
    )
    if attachment_type not in {"image", "video", "audio", "file"}:
        if mime_type.startswith("image/") or first.get("image_data"):
            attachment_type = "image"
        elif mime_type.startswith("video/") or first.get("video_data"):
            attachment_type = "video"
        elif mime_type.startswith("audio/") or first.get("audio_data"):
            attachment_type = "audio"
        elif attachment_type == "sticker":
            attachment_type = "sticker"
        elif first:
            attachment_type = "file"
    if attachment_type == "file":
        url_without_query = raw_url.split("?", 1)[0].lower()
        if mime_type.startswith("audio/") or url_without_query.endswith((".ogg", ".oga", ".opus", ".mp3", ".m4a", ".aac", ".wav", ".webm")):
            attachment_type = "audio"
        elif mime_type.startswith("video/") or url_without_query.endswith((".mp4", ".mov", ".m4v", ".avi", ".webm")):
            attachment_type = "video"
        elif mime_type.startswith("image/") or url_without_query.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")):
            attachment_type = "image"
    media_data = (
        first.get(f"{attachment_type}_data")
        or first.get("image_data")
        or first.get("video_data")
        or first.get("audio_data")
        or {}
    )
    url = str(
        raw_url
        or media_data.get("url")
        or ""
    )
    if attachment_type == "sticker":
        url = ""
    preview_url = str(media_data.get("preview_url") or payload.get("preview_url") or "")
    return {
        "type": attachment_type,
        "url": url,
        "preview_url": preview_url,
        "mime_type": mime_type,
        "sticker_id": sticker_id,
        "is_like": is_like,
        "raw": first,
    }


def extract_meta_system_message_context(text: str) -> dict:
    """Turn Meta's generated Messenger notices into structured origin data."""
    value = str(text or "").replace("\u200e", "").replace("\u200f", "").strip()
    url_match = re.search(r"https?://[^\s)]+", value, flags=re.IGNORECASE)
    url = (url_match.group(0).rstrip(".,،؛") if url_match else "")
    lowered = value.lower()

    context_type = ""
    title = ""
    description = ""
    if "أنت بصدد الرد على تعليق" in value or "replying to a comment" in lowered:
        context_type = "comment_reply"
        title = "رد خاص مرتبط بتعليق"
        description = "بدأت هذه المحادثة من تعليق على منشور الصفحة."
    elif "أنشأ فيسبوك هذه الدردشة" in value or "created this chat" in lowered:
        context_type = "comment_thread"
        title = "محادثة بدأت من تعليق"
        description = "فتح الزبون هذه المحادثة من تعليق على منشور الصفحة."
    elif (
        "564030381383143" in value
        or "إرسال رسائل إليك" in value
        or "send you messages" in lowered
    ):
        context_type = "marketing_permission"
        title = "إذن مراسلة من Meta"
        description = "سمح الزبون للصفحة بإرسال رسائل إليه."
    if not context_type:
        return {}

    parsed = urlparse(url) if url else None
    query = parse_qs(parsed.query) if parsed else {}
    reel_match = re.search(r"/(?:reel|videos?)/(\d+)", parsed.path if parsed else "")
    return {
        "type": context_type,
        "title": title,
        "description": description,
        "url": url,
        "reel_id": reel_match.group(1) if reel_match else "",
        "post_id": str((query.get("post_id") or [""])[0]),
        "comment_id": str((query.get("comment_id") or [""])[0]),
        "is_meta_system": True,
    }


def parse_meta_messaging_payload(payload: dict) -> list[dict]:
    """Normalize Messenger and Instagram webhook messaging events."""
    platform = "instagram" if str(payload.get("object") or "").lower() == "instagram" else "messenger"
    events: list[dict] = []
    for entry in payload.get("entry") or []:
        account_id = str(entry.get("id") or "")
        for event in entry.get("messaging") or []:
            message = event.get("message") or {}
            referral = event.get("referral") or message.get("referral") or {}
            ads_context = (
                referral.get("ads_context_data")
                or event.get("ads_context_data")
                or message.get("ads_context_data")
                or {}
            )
            if not message and not referral:
                continue
            sender_id = str((event.get("sender") or {}).get("id") or "")
            recipient_id = str((event.get("recipient") or {}).get("id") or "")
            is_echo = bool(message.get("is_echo"))
            contact_id = recipient_id if is_echo else sender_id
            attachment = meta_attachment_details(message.get("attachments"))
            attachment_type = attachment["type"]
            text_content = str(message.get("text") or "")
            if attachment_type == "sticker":
                text_content = text_content or ("لايك" if attachment.get("is_like") else "[ملصق]")
                message_type = "text" if attachment.get("is_like") else "sticker"
            else:
                message_type = attachment_type if attachment_type in {"image", "video", "audio", "file"} else "text"
            has_body = bool(text_content.strip() or attachment_type in {"image", "video", "audio", "file", "sticker"})
            # Click-to-Messenger ads often open the thread with referral only (no typed text).
            if referral and not has_body:
                message_type = "referral"
            attachment_url = attachment["url"]
            external_message_id = str(message.get("mid") or "")
            if not external_message_id and referral:
                external_message_id = ":".join((
                    "referral",
                    account_id,
                    sender_id,
                    str(event.get("timestamp") or ""),
                    str(referral.get("ad_id") or referral.get("ref") or ""),
                ))
            events.append({
                "platform": platform,
                "account_id": account_id or (sender_id if is_echo else recipient_id),
                "external_message_id": external_message_id,
                "from": contact_id,
                "sender_id": sender_id,
                "is_echo": is_echo,
                "app_id": str(message.get("app_id") or ""),
                "timestamp": str(event.get("timestamp") or ""),
                "message_type": message_type,
                "text": text_content,
                "attachment_url": attachment_url,
                "attachment_preview_url": attachment["preview_url"],
                "attachment_mime_type": attachment["mime_type"],
                "sticker_id": attachment.get("sticker_id") or "",
                "is_like": bool(attachment.get("is_like")),
                "reply_to_external_id": str(((message.get("reply_to") or {}).get("mid") or "")),
                "referral": referral,
                "ads_context_data": ads_context,
                # Treat referral-only ad opens as persistable inbox events.
                "has_message": bool(message) or bool(referral),
                "raw": event,
            })
    return events


def parse_meta_comment_payload(payload: dict) -> list[dict]:
    """Normalize Page feed comment events without mixing them with inbox messages."""
    if str(payload.get("object") or "").lower() != "page":
        return []
    events: list[dict] = []
    for entry in payload.get("entry") or []:
        page_id = str(entry.get("id") or "")
        for change in entry.get("changes") or []:
            if str(change.get("field") or "").lower() != "feed":
                continue
            value = change.get("value") or {}
            if str(value.get("item") or "").lower() != "comment":
                continue
            if str(value.get("verb") or "").lower() not in {"add", "edited"}:
                continue
            author = value.get("from") or {}
            comment_id = str(value.get("comment_id") or value.get("id") or "")
            post_id = str(value.get("post_id") or "")
            if not page_id or not comment_id or not post_id:
                continue
            events.append({
                "page_id": page_id,
                "external_post_id": post_id,
                "external_comment_id": comment_id,
                "parent_external_comment_id": str(value.get("parent_id") or ""),
                "external_user_id": str(author.get("id") or ""),
                "user_name": str(author.get("name") or ""),
                "message": str(value.get("message") or ""),
                "attachment_url": str(((value.get("photo") or {}).get("url") or value.get("video_id") or "")),
                "created_time": value.get("created_time") or entry.get("time"),
                "verb": str(value.get("verb") or "add").lower(),
                "raw": change,
            })
    return events


def _redact_call_payload(call: dict) -> dict:
    redacted = json.loads(json.dumps(call or {}, ensure_ascii=False, default=str))
    session = redacted.get("session")
    if isinstance(session, dict) and session.get("sdp"):
        session["sdp"] = "[REDACTED_SDP]"
    return redacted


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def parse_whatsapp_payload(payload: dict) -> dict:
    result = {"phone_number_id": "", "messages": [], "statuses": [], "calls": []}
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            result["phone_number_id"] = str(metadata.get("phone_number_id") or result["phone_number_id"])
            contacts = {
                str(contact.get("wa_id") or ""): ((contact.get("profile") or {}).get("name") or "")
                for contact in value.get("contacts") or []
            }
            contact_objects = value.get("contacts") or []
            for message in value.get("messages") or []:
                msg_type = str(message.get("type") or "unknown")
                content = message.get(msg_type) or {}
                text = content.get("body") if msg_type == "text" else ""
                if msg_type == "button":
                    text = content.get("text") or content.get("payload") or ""
                elif msg_type == "interactive":
                    choice = content.get("button_reply") or content.get("list_reply") or {}
                    text = choice.get("title") or choice.get("id") or ""
                sender = str(message.get("from") or "")
                context = message.get("context") or {}
                result["messages"].append(
                    {
                        "external_message_id": str(message.get("id") or ""),
                        "from": sender,
                        "contact_name": contacts.get(sender, ""),
                        "timestamp": str(message.get("timestamp") or ""),
                        "message_type": msg_type,
                        "text": str(text or ""),
                        "media_id": str(content.get("id") or ""),
                        "mime_type": str(content.get("mime_type") or ""),
                        "caption": str(content.get("caption") or ""),
                        "reply_to_external_id": str(context.get("id") or ""),
                        "raw": message,
                    }
                )
            for status in value.get("statuses") or []:
                result["statuses"].append(
                    {
                        "external_message_id": str(status.get("id") or ""),
                        "status": str(status.get("status") or ""),
                        "timestamp": str(status.get("timestamp") or ""),
                        "errors": status.get("errors") or [],
                    }
                )
            for call in value.get("calls") or []:
                errors = value.get("errors") or []
                first_error = errors[0] if errors else {}
                contact = contact_objects[0] if contact_objects else {}
                contact_profile = contact.get("profile") or {}
                external_contact_id = str(
                    call.get("from_user_id")
                    or contact.get("user_id")
                    or call.get("from")
                    or contact.get("wa_id")
                    or ""
                )
                result["calls"].append({
                    "external_call_id": str(call.get("id") or ""),
                    "external_contact_id": external_contact_id,
                    "contact_name": str(contact_profile.get("name") or contact_profile.get("username") or ""),
                    "from": str(call.get("from") or ""),
                    "to": str(call.get("to") or ""),
                    "event": str(call.get("event") or "unknown").lower(),
                    "direction": str(call.get("direction") or "USER_INITIATED").upper(),
                    "timestamp": str(call.get("timestamp") or ""),
                    "start_time": str(call.get("start_time") or ""),
                    "end_time": str(call.get("end_time") or ""),
                    "duration": _safe_int(call.get("duration")),
                    "status": str(call.get("status") or "").lower(),
                    "sdp_type": str((call.get("session") or {}).get("sdp_type") or ""),
                    "failure_code": str(first_error.get("code") or ""),
                    "failure_message": str(first_error.get("message") or ((first_error.get("error_data") or {}).get("details") or "")),
                    "raw": _redact_call_payload(call),
                })
    return result


def external_timestamp(value: str | None) -> datetime | None:
    try:
        timestamp = int(value or 0)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return datetime.utcfromtimestamp(timestamp)
    except (TypeError, ValueError, OSError):
        return None
