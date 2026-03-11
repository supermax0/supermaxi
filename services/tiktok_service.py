# services/tiktok_service.py — جلب تعليقات تيك توك والرد عليها (TikTok API)
from __future__ import annotations

from typing import Any, List

import requests
from flask import current_app


def get_tiktok_access_token() -> str:
    """رمز وصول تيك توك من الإعدادات."""
    return (
        getattr(current_app.config, "TIKTOK_ACCESS_TOKEN", None)
        or current_app.config.get("TIKTOK_ACCESS_TOKEN")
        or ""
    )


def fetch_comments(
    video_id: str,
    access_token: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> List[dict[str, Any]]:
    """
    جلب تعليقات فيديو تيك توك.
    يستخدم TikTok Research API أو Content Posting API حسب التوثيق المتاح.
    في حال عدم ضبط التوكن يُرجع قائمة فارغة.
    """
    token = access_token or get_tiktok_access_token()
    if not token:
        current_app.logger.warning("TikTok fetch_comments: no access token")
        return []

    # TikTok Comment List API (قد يختلف حسب الإصدار)
    url = "https://open.tiktokapis.com/v2/comment/list/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "video_id": video_id,
        "max_count": min(limit, 50),
    }
    if cursor:
        payload["cursor"] = cursor

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code >= 400:
            current_app.logger.error(
                "TikTok fetch_comments failed: %s %s", resp.status_code, resp.text
            )
            return []
        data = resp.json()
        return data.get("data", {}).get("comments") or []
    except Exception as e:
        current_app.logger.exception("TikTok fetch_comments failed: %s", e)
        return []


def reply_comment(
    comment_id: str,
    message: str,
    access_token: str | None = None,
) -> bool:
    """
    نشر رد على تعليق تيك توك.
    POST /tiktok/comment/reply أو حسب وثائق TikTok API.
    """
    token = access_token or get_tiktok_access_token()
    if not token:
        current_app.logger.warning("TikTok reply_comment: no access token")
        return False
    if not message or not comment_id:
        return False

    # مثال افتراضي — قد يتطلب TikTok endpoint مختلف
    url = "https://open.tiktokapis.com/v2/comment/reply/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"comment_id": comment_id, "text": message}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code >= 400:
            current_app.logger.error(
                "TikTok reply_comment failed: %s %s", resp.status_code, resp.text
            )
            return False
        return True
    except Exception as e:
        current_app.logger.exception("TikTok reply_comment error: %s", e)
        return False
