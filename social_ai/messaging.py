from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from flask import current_app


def send_whatsapp_message(phone: str, message: str) -> None:
    """
    إرسال رسالة واتساب عبر WhatsApp Cloud API.

    تعتمد على:
    - WHATSAPP_ACCESS_TOKEN
    - WHATSAPP_PHONE_NUMBER_ID

    إذا لم تُضبط هذه الإعدادات لن يتم إرسال شيء (يتم فقط تسجيل تحذير في اللوج).
    """
    if not phone or not message:
        return

    access_token = current_app.config.get("WHATSAPP_ACCESS_TOKEN") or ""
    phone_number_id = current_app.config.get("WHATSAPP_PHONE_NUMBER_ID") or ""
    if not access_token or not phone_number_id:
        current_app.logger.warning(
            "WhatsApp send skipped: missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID"
        )
        return

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code >= 400:
            current_app.logger.error(
                "WhatsApp send failed: status=%s body=%s", resp.status_code, resp.text
            )
        else:
            current_app.logger.info("WhatsApp send OK: to=%s", phone)
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("WhatsApp send error: %s", exc)


def send_telegram_message(
    chat_id: str,
    message: str,
    bot_token: str | None = None,
    *,
    reply_markup: dict[str, Any] | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool | None = None,
) -> None:
    """
    إرسال رسالة تيليجرام عبر Bot API.

    يستخدم bot_token إذا مُرّر، وإلا TELEGRAM_BOT_TOKEN أو BOT_TOKEN من إعدادات التطبيق.
    """
    if not chat_id or not message:
        return

    token = (bot_token or "").strip()
    if not token:
        token = (
            (current_app.config.get("TELEGRAM_BOT_TOKEN") or "")
            or (current_app.config.get("BOT_TOKEN") or "")
        ).strip()
    if not token:
        current_app.logger.warning("Telegram send skipped: no bot token (set in عقدة تيليجرام Listener or TELEGRAM_BOT_TOKEN)")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": message,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if disable_web_page_preview is not None:
        payload["disable_web_page_preview"] = disable_web_page_preview

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code >= 400:
            current_app.logger.error(
                "Telegram send failed: status=%s body=%s", resp.status_code, resp.text
            )
        else:
            current_app.logger.info("Telegram send OK: chat_id=%s", chat_id)
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("Telegram send error: %s", exc)


def send_telegram_photo(
    chat_id: str,
    photo_url: str,
    bot_token: str | None = None,
    caption: str | None = None,
) -> bool:
    """
    إرسال صورة إلى تيليجرام عبر sendPhoto.

    يدعم:
    - رابط http/https مباشر
    - مسار ملف محلي (absolute/relative) مثل /static/uploads/products/x.jpg
    """
    photo_ref = (photo_url or "").strip()
    if not chat_id or not photo_ref:
        return False

    token = (bot_token or "").strip()
    if not token:
        token = (
            (current_app.config.get("TELEGRAM_BOT_TOKEN") or "")
            or (current_app.config.get("BOT_TOKEN") or "")
        ).strip()
    if not token:
        current_app.logger.warning("Telegram photo skipped: no bot token")
        return False

    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    try:
        # 1) URL مباشر
        if photo_ref.startswith(("http://", "https://")):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "photo": photo_ref,
            }
            if caption and caption.strip():
                payload["caption"] = caption[:1024]
            resp = requests.post(url, json=payload, timeout=20)
        else:
            # 2) ملف محلي
            local_file = _resolve_local_photo_file(photo_ref)
            if not local_file:
                current_app.logger.warning(
                    "Telegram photo skipped: invalid local file source=%s",
                    photo_ref[:180],
                )
                return False

            data: dict[str, Any] = {"chat_id": chat_id}
            if caption and caption.strip():
                data["caption"] = caption[:1024]
            mime = mimetypes.guess_type(local_file.name)[0] or "application/octet-stream"
            with local_file.open("rb") as fh:
                files = {"photo": (local_file.name, fh, mime)}
                resp = requests.post(url, data=data, files=files, timeout=30)

        if resp.status_code >= 400:
            current_app.logger.error(
                "Telegram sendPhoto failed: status=%s body=%s", resp.status_code, resp.text
            )
            return False
        current_app.logger.info("Telegram sendPhoto OK: chat_id=%s", chat_id)
        return True
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("Telegram sendPhoto error: %s", exc)
        return False


def _resolve_local_photo_file(photo_ref: str) -> Path | None:
    """
    يحوّل قيمة صورة من المخزون إلى ملف محلي إن أمكن.
    أمثلة مدعومة:
    - C:\\...\\img.jpg
    - /var/www/.../img.jpg
    - /static/uploads/products/img.jpg
    - static/uploads/products/img.jpg
    - /uploads/products/img.jpg
    - file:///C:/path/img.jpg
    """
    raw = (photo_ref or "").strip()
    if not raw:
        return None
    if raw.lower().startswith(("http://", "https://", "data:", "tg://")):
        return None

    parsed = urlparse(raw)
    value = raw
    if parsed.scheme == "file":
        value = unquote(parsed.path or "").strip()
        # file:///C:/x.jpg على ويندوز
        if len(value) >= 3 and value[0] == "/" and value[2] == ":" and value[1].isalpha():
            value = value[1:]
        value = value.replace("/", "\\") if "\\" in raw else value

    candidates: list[Path] = []
    p = Path(value)
    if p.is_absolute():
        candidates.append(p)

    root = Path(current_app.root_path)
    stripped = value.lstrip("/\\")
    if stripped:
        # تحت جذر التطبيق مباشرة
        candidates.append(root / stripped)
        # صيغ شائعة لمسارات مخزون الصور
        if stripped.startswith("uploads/"):
            candidates.append(root / "static" / stripped)
        if stripped.startswith("static/"):
            candidates.append(root / stripped)
        if stripped.startswith("autoposter/uploads/"):
            candidates.append(root / "static" / stripped.replace("autoposter/", "", 1))

    # /uploads/... في بيئات تستخدم مجلد uploads خارج static
    if value.startswith("/uploads/"):
        candidates.append(root / value.lstrip("/"))
        candidates.append(root / "static" / value.lstrip("/"))

    seen: set[str] = set()
    for cand in candidates:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        try:
            if cand.exists() and cand.is_file():
                return cand
        except Exception:
            continue
    return None

