"""
facebook_service.py
-------------------
Handles all Facebook Graph API interactions.
- Fetch pages for a user token
- Publish text / photo / video posts
- Exponential back-off retry on rate-limit errors
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger("publisher")

GRAPH_BASE = "https://graph.facebook.com/v19.0"
# FB rate-limit error codes
_RATE_LIMIT_CODES = {4, 17, 32, 613}
_MAX_RETRIES = 3


def _retry_post(url: str, **kwargs) -> dict:
    """POST with exponential back-off for rate-limit errors."""
    last_err = {}
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.post(url, timeout=60, **kwargs)
        except Exception as exc:
            logger.error("FB request error (attempt %d): %s", attempt + 1, exc)
            last_err = {"success": False, "message": str(exc), "error_code": None, "error_subcode": None}
            time.sleep(2 ** attempt)
            continue

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("FB response not JSON (attempt %d): %s", attempt + 1, exc)
            last_err = {
                "success": False,
                "message": f"Invalid response from Facebook: {resp.status_code}",
                "error_code": None,
                "error_subcode": None,
            }
            if resp.status_code != 200:
                return last_err
            time.sleep(2 ** attempt)
            continue

        # Success: 200 and response contains id (feed/photo/video) or post_id (photo)
        if resp.status_code == 200 and ("id" in data or "post_id" in data):
            return {"success": True, "data": data}

        error = data.get("error", {})
        code = error.get("code", 0)
        subcode = error.get("error_subcode")
        msg = error.get("message", "Unknown Facebook error")
        logger.warning("FB error code=%s message=%s (attempt %d)", code, msg, attempt + 1)

        if code in _RATE_LIMIT_CODES:
            wait = 2 ** attempt * 5   # 5s, 10s, 20s
            logger.info("Rate-limited — waiting %ds before retry", wait)
            time.sleep(wait)
            last_err = {
                "success": False,
                "message": f"Rate limited: {msg}",
                "error_code": code,
                "error_subcode": subcode,
            }
            continue

        # Non-retryable error
        return {"success": False, "message": msg, "error_code": code, "error_subcode": subcode}

    return last_err or {"success": False, "message": "Max retries exceeded", "error_code": None, "error_subcode": None}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_user_pages(user_token: str) -> dict:
    """Fetch all Facebook pages the user manages."""
    try:
        url = f"{GRAPH_BASE}/me/accounts"
        resp = requests.get(url, params={"access_token": user_token}, timeout=30)
        data = resp.json()
        if "data" in data:
            return {"success": True, "pages": data["data"]}
        err = data.get("error", {}) or {}
        error = err.get("message", "Could not fetch pages")
        return {
            "success": False,
            "message": error,
            "error_code": err.get("code"),
            "error_subcode": err.get("error_subcode"),
        }
    except Exception as exc:
        logger.error("get_user_pages error: %s", exc)
        return {"success": False, "message": str(exc), "error_code": None, "error_subcode": None}


def publish_text_post(page_id: str, page_token: str, text: str) -> dict:
    """Publish a plain-text post to a Facebook page."""
    url = f"{GRAPH_BASE}/{page_id}/feed"
    result = _retry_post(url, data={"message": text, "access_token": page_token})
    if result.get("success"):
        logger.info("Text post published to page %s: %s", page_id, result["data"].get("id"))
    return result


def publish_photo_post(page_id: str, page_token: str, text: str, image_path: str) -> dict:
    """Publish an image post to a Facebook page."""
    url = f"{GRAPH_BASE}/{page_id}/photos"
    try:
        with open(image_path, "rb") as f:
            result = _retry_post(
                url,
                data={"caption": text, "access_token": page_token},
                files={"source": f},
            )
    except FileNotFoundError:
        return {"success": False, "message": f"Image file not found: {image_path}"}
    if result.get("success"):
        logger.info("Photo post published to page %s", page_id)
    return result


def publish_video_post(page_id: str, page_token: str, text: str, video_path: str) -> dict:
    """Publish a video post to a Facebook page (simple upload)."""
    url = f"{GRAPH_BASE}/{page_id}/videos"
    try:
        with open(video_path, "rb") as f:
            result = _retry_post(
                url,
                data={"description": text, "access_token": page_token},
                files={"source": f},
            )
    except FileNotFoundError:
        return {"success": False, "message": f"Video file not found: {video_path}"}
    if result.get("success"):
        logger.info("Video post published to page %s", page_id)
    return result
