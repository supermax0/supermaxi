"""Telegram Bot API transport. Credential-bearing URLs never leave this module."""
from __future__ import annotations

import re

import requests

from .security import decrypt_secret

TOKEN_PATTERN = re.compile(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,200}\Z")


class TelegramError(RuntimeError):
    provider = "telegram"

    def __init__(self, status=0, retry_after=None):
        self.status_code = status or None
        self.response_body = {}
        self.response_headers = {"Retry-After": str(retry_after)} if retry_after else {}
        super().__init__({401: "رمز بوت تلگرام غير صالح", 403: "تعذر الإرسال: المستخدم حظر البوت أو لم يبدأ المحادثة",
                          429: "تلگرام طلب تأجيل الإرسال"}.get(status, "تعذر الاتصال ببوت تلگرام؛ حاول مرة أخرى"))


class TelegramBotClient:
    def __init__(self, channel=None, *, token=None):
        self.channel = channel
        self.token = token if token is not None else decrypt_secret(channel.access_token_encrypted)
        if not TOKEN_PATTERN.fullmatch(self.token or ""):
            raise TelegramError(401)

    def call(self, method, body=None, *, files=None):
        # No provider descriptions/response URLs in errors: they may contain the token.
        try:
            kwargs = {"data": body or {}, "files": files} if files else {"json": body or {}}
            response = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", timeout=(10, 45), **kwargs)
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise TelegramError() from None
        if not isinstance(payload, dict) or not payload.get("ok") or response.status_code != 200:
            code = payload.get("error_code", response.status_code) if isinstance(payload, dict) else response.status_code
            parameters = payload.get("parameters") if isinstance(payload, dict) else None
            retry = parameters.get("retry_after") if isinstance(parameters, dict) else None
            raise TelegramError(401 if code == 404 else code, retry)
        return payload.get("result")

    def _recipient(self, recipient):
        if self.channel is not None and not self.channel.is_active:
            raise TelegramError(403)
        if not re.fullmatch(r"[1-9][0-9]{0,19}", str(recipient)):
            raise TelegramError(400)
        return str(recipient)

    @staticmethod
    def _sent(result, recipient):
        if not isinstance(result, dict) or not isinstance(result.get("message_id"), int) or result["message_id"] <= 0:
            raise TelegramError(502)
        if str((result.get("chat") or {}).get("id")) != str(recipient):
            raise TelegramError(502)
        # Telegram message ids are unique inside a chat, not across the bot's chats.
        return {"message_id": f"tg:{recipient}:{result['message_id']}"}

    def send_text(self, recipient, text):
        recipient = self._recipient(recipient)
        result = self.call("sendMessage", {"chat_id": recipient, "text": text})
        return self._sent(result, recipient)

    def send_file(self, recipient, kind, path, mime):
        recipient = self._recipient(recipient)
        method, field = {"image": ("sendPhoto", "photo"), "video": ("sendVideo", "video"),
                         "audio": ("sendVoice", "voice"), "document": ("sendDocument", "document")}[kind]
        with path.open("rb") as stream:
            result = self.call(method, {"chat_id": recipient}, files={field: (path.name, stream, mime)})
        return self._sent(result, recipient)

    def download_file(self, file_id, *, max_bytes):
        cap = min(max_bytes, 20 * 1024 * 1024)
        info = self.call("getFile", {"file_id": file_id})
        path = str(info.get("file_path") or "") if isinstance(info, dict) else ""
        if not re.fullmatch(r"[A-Za-z0-9_/.-]+", path) or any(p in ("", ".", "..") for p in path.split("/")):
            raise TelegramError(400)
        if info.get("file_size", 0) > cap:
            raise TelegramError(413)
        try:
            with requests.get(f"https://api.telegram.org/file/bot{self.token}/{path}",
                              stream=True, allow_redirects=False, timeout=(10, 45)) as response:
                if response.status_code != 200:
                    raise TelegramError(response.status_code)
                content = bytearray()
                for block in response.iter_content(64 * 1024):
                    content.extend(block)
                    if len(content) > cap:
                        raise TelegramError(413)
                return bytes(content), response.headers.get("Content-Type", "").split(";", 1)[0]
        except requests.RequestException:
            raise TelegramError() from None


def message_attachments(message):
    """Store opaque Telegram file ids, never token-bearing download URLs."""
    rows = []
    if isinstance(message.get("photo"), list) and message["photo"] and isinstance(message["photo"][-1], dict):
        rows.append(("image", message["photo"][-1], "image/jpeg", "photo.jpg"))
    for field, kind, mime, name in (("video", "video", "video/mp4", "video.mp4"),
                                   ("voice", "audio", "audio/ogg", "voice.ogg"),
                                   ("audio", "audio", "audio/mpeg", "audio.mp3"),
                                   ("document", "document", "application/octet-stream", "document")):
        if isinstance(message.get(field), dict):
            rows.append((kind, message[field], mime, name))
    from .attachments import MAX_BYTES, safe_name
    return [{"index": i, "kind": kind, "telegram_file_id": str(row.get("file_id") or "")[:512],
             "mime_type": str(row.get("mime_type") or mime)[:100],
             "name": safe_name(str(row.get("file_name") or name)), "size_bytes": row.get("file_size"),
             "status": "pending" if row.get("file_id") and isinstance(row.get("file_size", 0), int)
             and row.get("file_size", 0) <= min(MAX_BYTES[kind], 20 * 1024 * 1024) else "unsupported",
             "stored_path": None, "sha256": None, "source_url": None}
            for i, (kind, row, mime, name) in enumerate(rows)]
