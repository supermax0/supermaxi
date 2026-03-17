"""نشر على صفحة فيسبوك عبر Graph API — يُستخدم من Autoposter و AI Agent."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger("facebook_publish")
GRAPH_BASE = "https://graph.facebook.com/v19.0"


def _published_flag(visibility: str | None) -> str:
    return "false" if (visibility or "public").strip().lower() == "hidden" else "true"


def _sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload or {})
    if "access_token" in out:
        out["access_token"] = "***"
    return out


def _safe_json(resp: requests.Response) -> tuple[Dict[str, Any], str | None]:
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data, None
        return {"raw": data}, None
    except Exception as exc:
        return {}, str(exc)


def _handle_graph_response(resp: requests.Response, *, page_id: str, endpoint: str) -> Dict[str, Any]:
    data, parse_err = _safe_json(resp)
    if parse_err:
        logger.error(
            "FB publish non-JSON response: page_id=%s endpoint=%s status=%s body=%s",
            page_id,
            endpoint,
            resp.status_code,
            (resp.text or "")[:500],
        )
        raise RuntimeError(f"Invalid response from Facebook: HTTP {resp.status_code}")

    logger.info(
        "FB publish response: page_id=%s endpoint=%s status=%s body=%s",
        page_id,
        endpoint,
        resp.status_code,
        data,
    )
    if resp.status_code == 200 and ("id" in data or "post_id" in data):
        return data

    err = data.get("error", {}) if isinstance(data, dict) else {}
    msg = (err.get("message") if isinstance(err, dict) else None) or f"HTTP {resp.status_code}"
    raise RuntimeError(msg)


def _get_media_bytes(media_url: str) -> Optional[Tuple[bytes, str, str]]:
    """
    إن كان الرابط يشير إلى ملف محلي على السيرفر يُرجع (المحتوى، اسم الملف، mime).
    وإلا يُرجع None.
    """
    try:
        from services.media_service import resolve_media_url_to_path
        res = resolve_media_url_to_path(media_url)
        if not res:
            return None
        path, name = res
        if not path.is_file():
            return None
        mime = "video/mp4" if name.lower().endswith((".mp4", ".mov")) else "image/jpeg"
        if any(name.lower().endswith(ext) for ext in (".png",)):
            mime = "image/png"
        if any(name.lower().endswith(ext) for ext in (".webp",)):
            mime = "image/webp"
        with open(path, "rb") as f:
            return (f.read(), name, mime)
    except Exception:
        return None


def publish_facebook_post(
    page_access_token: str,
    message: str,
    *,
    photo_url: str | None = None,
    video_url: str | None = None,
    page_id: str | None = None,
    visibility: str = "public",
) -> Dict[str, Any]:
    """نشر منشور على صفحة فيسبوك (نص فقط، صورة، أو فيديو). يرجع استجابة الـ API (يحتوي id أو post_id).
    يجب تمرير page_id لصفحة فيسبوك (Page) وليس الحساب الشخصي؛ وإلا النشر قد يظهر على غير الصفحة أو يفشل.
    ظهور المنشور للعامة يعتمد على إعدادات الجمهور الافتراضي للصفحة في فيسبوك."""
    page_access_token = (page_access_token or "").strip()
    if not page_access_token:
        raise ValueError("نشر فيسبوك يتطلب Page Access Token صالح.")

    if not (page_id and str(page_id).strip()):
        raise ValueError("نشر فيسبوك يتطلب page_id (معرف الصفحة). تأكد أن الحساب المرتبط هو صفحة وليس حساب شخصي.")
    me_or_page = str(page_id).strip()

    if video_url:
        endpoint = f"/{me_or_page}/videos"
        url = f"{GRAPH_BASE}{endpoint}"
        published = _published_flag(visibility)
        media_bytes = _get_media_bytes(video_url)
        if media_bytes:
            content, name, mime = media_bytes
            files = {"source": (name, content, mime)}
            data = {
                "access_token": page_access_token,
                "description": message or "",
                "published": published,
            }
            logger.info(
                "FB publish request: page_id=%s endpoint=%s mode=video_file payload=%s",
                me_or_page,
                endpoint,
                _sanitize_payload(data),
            )
            r = requests.post(url, data=data, files=files, timeout=300)
        else:
            payload: Dict[str, Any] = {
                "access_token": page_access_token,
                "file_url": video_url,
                "description": message or "",
                "published": published,
            }
            logger.info(
                "FB publish request: page_id=%s endpoint=%s mode=video_url payload=%s",
                me_or_page,
                endpoint,
                _sanitize_payload(payload),
            )
            r = requests.post(url, data=payload, timeout=120)
        return _handle_graph_response(r, page_id=me_or_page, endpoint=endpoint)

    if photo_url:
        endpoint = f"/{me_or_page}/photos"
        url = f"{GRAPH_BASE}{endpoint}"
        published = _published_flag(visibility)
        media_bytes = _get_media_bytes(photo_url)
        if media_bytes:
            content, name, mime = media_bytes
            files = {"source": (name, content, mime)}
            data = {
                "access_token": page_access_token,
                "caption": message or "",
                "published": published,
            }
            logger.info(
                "FB publish request: page_id=%s endpoint=%s mode=photo_file payload=%s",
                me_or_page,
                endpoint,
                _sanitize_payload(data),
            )
            r = requests.post(url, data=data, files=files, timeout=60)
        else:
            payload = {
                "access_token": page_access_token,
                "url": photo_url,
                "caption": message or "",
                "published": published,
            }
            logger.info(
                "FB publish request: page_id=%s endpoint=%s mode=photo_url payload=%s",
                me_or_page,
                endpoint,
                _sanitize_payload(payload),
            )
            r = requests.post(url, data=payload, timeout=30)
        return _handle_graph_response(r, page_id=me_or_page, endpoint=endpoint)

    endpoint = f"/{me_or_page}/feed"
    url = f"{GRAPH_BASE}{endpoint}"
    published = _published_flag(visibility)
    payload = {
        "access_token": page_access_token,
        "message": message or "",
        "published": published,
    }
    logger.info(
        "FB publish request: page_id=%s endpoint=%s mode=text payload=%s",
        me_or_page,
        endpoint,
        _sanitize_payload(payload),
    )
    r = requests.post(url, data=payload, timeout=30)
    return _handle_graph_response(r, page_id=me_or_page, endpoint=endpoint)
