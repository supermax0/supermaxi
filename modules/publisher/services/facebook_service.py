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
import time
from typing import Optional

import requests

logger = logging.getLogger("publisher")

GRAPH_BASE = "https://graph.facebook.com/v19.0"
# FB rate-limit error codes
_RATE_LIMIT_CODES = {4, 17, 32, 613}
_MAX_RETRIES = 3


def _published_flag(visibility: str | None) -> str:
    return "false" if (visibility or "public").strip().lower() == "hidden" else "true"


def _log_payload(page_id: str, endpoint: str, payload: dict) -> None:
    sanitized = dict(payload or {})
    if "access_token" in sanitized:
        sanitized["access_token"] = "***"
    logger.info("FB publish payload: page_id=%s endpoint=%s payload=%s", page_id, endpoint, sanitized)


def _safe_json(resp: requests.Response) -> tuple[dict, str | None]:
    try:
        return resp.json(), None
    except Exception as exc:
        return {}, str(exc)


def _retry_post(url: str, *, page_id: str | None = None, **kwargs) -> dict:
    """POST with exponential back-off for rate-limit errors."""
    last_err = {}
    endpoint = url.split("graph.facebook.com/")[-1]
    for attempt in range(_MAX_RETRIES):
        logger.info("FB publish request: page_id=%s endpoint=%s attempt=%d", page_id or "-", endpoint, attempt + 1)
        try:
            resp = requests.post(url, timeout=60, **kwargs)
        except Exception as exc:
            logger.error("FB request error (attempt %d): %s", attempt + 1, exc)
            last_err = {"success": False, "message": str(exc), "error_code": None, "error_subcode": None}
            time.sleep(2 ** attempt)
            continue

        data, parse_err = _safe_json(resp)
        if parse_err:
            logger.warning("FB response not JSON (attempt %d): %s", attempt + 1, parse_err)
            last_err = {
                "success": False,
                "message": f"Invalid response from Facebook: {resp.status_code}",
                "error_code": None,
                "error_subcode": None,
            }
            logger.warning(
                "FB publish response (non-JSON): page_id=%s endpoint=%s status=%s body=%s",
                page_id or "-",
                endpoint,
                resp.status_code,
                (resp.text or "")[:500],
            )
            if resp.status_code != 200:
                return last_err
            time.sleep(2 ** attempt)
            continue

        logger.info(
            "FB publish response: page_id=%s endpoint=%s status=%s body=%s",
            page_id or "-",
            endpoint,
            resp.status_code,
            data,
        )

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


def publish_text_post(page_id: str, page_token: str, text: str, visibility: str = "public") -> dict:
    """Publish a plain-text post to a Facebook page."""
    page_id = (page_id or "").strip()
    page_token = (page_token or "").strip()
    if not page_id:
        return {"success": False, "message": "Missing page_id", "error_code": None, "error_subcode": None}
    if not page_token:
        return {"success": False, "message": "Missing page access token", "error_code": None, "error_subcode": None}

    url = f"{GRAPH_BASE}/{page_id}/feed"
    payload = {"message": text, "access_token": page_token, "published": _published_flag(visibility)}
    _log_payload(page_id, f"/{page_id}/feed", payload)
    result = _retry_post(
        url,
        page_id=page_id,
        data=payload,
    )
    if result.get("success"):
        logger.info("Text post published to page %s: %s", page_id, result["data"].get("id"))
    return result


def publish_photo_post(page_id: str, page_token: str, text: str, image_path: str, visibility: str = "public") -> dict:
    """Publish an image post to a Facebook page."""
    page_id = (page_id or "").strip()
    page_token = (page_token or "").strip()
    if not page_id:
        return {"success": False, "message": "Missing page_id", "error_code": None, "error_subcode": None}
    if not page_token:
        return {"success": False, "message": "Missing page access token", "error_code": None, "error_subcode": None}

    url = f"{GRAPH_BASE}/{page_id}/photos"
    payload = {"caption": text, "access_token": page_token, "published": _published_flag(visibility)}
    _log_payload(page_id, f"/{page_id}/photos", payload)
    try:
        with open(image_path, "rb") as f:
            result = _retry_post(
                url,
                page_id=page_id,
                data=payload,
                files={"source": f},
            )
    except FileNotFoundError:
        return {"success": False, "message": f"Image file not found: {image_path}"}
    if result.get("success"):
        logger.info("Photo post published to page %s", page_id)
    return result


def publish_video_post(page_id: str, page_token: str, text: str, video_path: str, visibility: str = "public") -> dict:
    """Publish a video post to a Facebook page (simple upload)."""
    page_id = (page_id or "").strip()
    page_token = (page_token or "").strip()
    if not page_id:
        return {"success": False, "message": "Missing page_id", "error_code": None, "error_subcode": None}
    if not page_token:
        return {"success": False, "message": "Missing page access token", "error_code": None, "error_subcode": None}

    url = f"{GRAPH_BASE}/{page_id}/videos"
    payload = {"description": text, "access_token": page_token, "published": _published_flag(visibility)}
    _log_payload(page_id, f"/{page_id}/videos", payload)
    try:
        with open(video_path, "rb") as f:
            result = _retry_post(
                url,
                page_id=page_id,
                data=payload,
                files={"source": f},
            )
    except FileNotFoundError:
        return {"success": False, "message": f"Video file not found: {video_path}"}
    if result.get("success"):
        logger.info("Video post published to page %s", page_id)
    return result
