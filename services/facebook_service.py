# services/facebook_service.py — جلب التعليقات والرد عليها عبر Facebook Graph API
from __future__ import annotations

from typing import Any, List

import requests
from flask import current_app


def get_page_access_token() -> str:
    """رمز وصول الصفحة من الإعدادات أو المتغيرات."""
    return (
        getattr(current_app.config, "FACEBOOK_PAGE_ACCESS_TOKEN", None)
        or current_app.config.get("FACEBOOK_PAGE_ACCESS_TOKEN")
        or ""
    )


def fetch_comments(
    post_id: str,
    access_token: str | None = None,
    since: str | None = None,
    limit: int = 25,
) -> List[dict[str, Any]]:
    """
    جلب تعليقات منشور فيسبوك.
    GET /v19.0/{post-id}/comments
    """
    token = access_token or get_page_access_token()
    if not token:
        current_app.logger.warning("Facebook fetch_comments: no access token")
        return []

    url = f"https://graph.facebook.com/v19.0/{post_id}/comments"
    params: dict[str, Any] = {
        "access_token": token,
        "fields": "id,message,from,created_time",
        "order": "chronological",
        "limit": min(limit, 100),
    }
    if since:
        params["since"] = since

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data") or []
    except Exception as e:
        current_app.logger.exception("Facebook fetch_comments failed: %s", e)
        return []


def reply_comment(
    comment_id: str,
    message: str,
    access_token: str | None = None,
) -> bool:
    """
    نشر رد على تعليق فيسبوك.
    POST https://graph.facebook.com/v19.0/{comment-id}/comments
    """
    token = access_token or get_page_access_token()
    if not token:
        current_app.logger.warning("Facebook reply_comment: no access token")
        return False
    if not message or not comment_id:
        return False

    url = f"https://graph.facebook.com/v19.0/{comment_id}/comments"
    payload = {"message": message, "access_token": token}

    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code >= 400:
            current_app.logger.error(
                "Facebook reply_comment failed: %s %s", resp.status_code, resp.text
            )
            return False
        return True
    except Exception as e:
        current_app.logger.exception("Facebook reply_comment error: %s", e)
        return False
