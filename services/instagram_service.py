# services/instagram_service.py - Instagram comments via Graph API
from __future__ import annotations

from typing import Any, List

import requests
from flask import current_app


def get_instagram_access_token() -> str:
    token = getattr(current_app.config, "INSTAGRAM_ACCESS_TOKEN", None)
    return token or current_app.config.get("INSTAGRAM_ACCESS_TOKEN") or ""


def fetch_comments(
    media_id: str,
    access_token: str | None = None,
    since: str | None = None,
    limit: int = 25,
) -> List[dict[str, Any]]:
    token = access_token or get_instagram_access_token()
    if not token:
        current_app.logger.warning("Instagram fetch_comments: no access token")
        return []
    url = f"https://graph.facebook.com/v19.0/{media_id}/comments"
    params: dict[str, Any] = {
        "access_token": token,
        "fields": "id,text,username,timestamp",
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
        current_app.logger.exception("Instagram fetch_comments failed: %s", e)
        return []


def reply_comment(
    comment_id: str,
    message: str,
    access_token: str | None = None,
) -> bool:
    token = access_token or get_instagram_access_token()
    if not token:
        current_app.logger.warning("Instagram reply_comment: no access token")
        return False
    if not message or not comment_id:
        return False
    url = f"https://graph.facebook.com/v19.0/{comment_id}/replies"
    payload = {"message": message, "access_token": token}
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code >= 400:
            current_app.logger.error("Instagram reply_comment failed: %s %s", resp.status_code, resp.text)
            return False
        return True
    except Exception as e:
        current_app.logger.exception("Instagram reply_comment error: %s", e)
        return False
