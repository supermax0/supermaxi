"""نشر على صفحة فيسبوك عبر Graph API — يُستخدم من Autoposter و AI Agent."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import requests


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
) -> Dict[str, Any]:
    """نشر منشور على صفحة فيسبوك (نص فقط، صورة، أو فيديو). يرجع استجابة الـ API (يحتوي id أو post_id)."""
    version = "v21.0"
    base = f"https://graph.facebook.com/{version}"
    me_or_page = page_id if page_id else "me"

    if video_url:
        url = f"{base}/{me_or_page}/videos"
        media_bytes = _get_media_bytes(video_url)
        if media_bytes:
            content, name, mime = media_bytes
            files = {"source": (name, content, mime)}
            data = {
                "access_token": page_access_token,
                "description": message or "",
            }
            r = requests.post(url, data=data, files=files, timeout=300)
        else:
            payload: Dict[str, Any] = {
                "access_token": page_access_token,
                "file_url": video_url,
                "description": message or "",
            }
            r = requests.post(url, data=payload, timeout=120)
        if r.status_code != 200:
            err = r.json() if r.text else {}
            msg = (err.get("error") or {}).get("message", r.text)
            raise RuntimeError(msg or f"HTTP {r.status_code}")
        return r.json()

    if photo_url:
        url = f"{base}/{me_or_page}/photos"
        media_bytes = _get_media_bytes(photo_url)
        if media_bytes:
            content, name, mime = media_bytes
            files = {"source": (name, content, mime)}
            data = {
                "access_token": page_access_token,
                "message": message or "",
            }
            r = requests.post(url, data=data, files=files, timeout=60)
        else:
            payload = {
                "access_token": page_access_token,
                "url": photo_url,
                "message": message or "",
            }
            r = requests.post(url, data=payload, timeout=30)
        if r.status_code != 200:
            err = r.json() if r.text else {}
            msg = (err.get("error") or {}).get("message", r.text)
            raise RuntimeError(msg or f"HTTP {r.status_code}")
        return r.json()

    url = f"{base}/{me_or_page}/feed"
    payload = {
        "access_token": page_access_token,
        "message": message or "",
    }
    r = requests.post(url, data=payload, timeout=30)
    if r.status_code != 200:
        err = r.json() if r.text else {}
        msg = (err.get("error") or {}).get("message", r.text)
        raise RuntimeError(msg or f"HTTP {r.status_code}")
    return r.json()
