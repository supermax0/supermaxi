"""
validation_utils.py
-------------------
Shared parsing/validation helpers for Publisher API endpoints.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from flask import request


def parse_pagination(
    *,
    default_per_page: int = 20,
    max_per_page: int = 200,
) -> Tuple[int, int]:
    try:
        page = int(request.args.get("page", "1"))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page", str(default_per_page)))
    except Exception:
        per_page = default_per_page
    page = max(1, page)
    per_page = min(max(1, per_page), max_per_page)
    return page, per_page


def parse_publish_time_utc(payload: Dict) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Parse publish_time from request payload and normalize to naive UTC datetime.
    Supports:
      - ISO string with timezone (preferred)
      - ISO naive datetime + timezone_offset_minutes (JS Date.getTimezoneOffset())
    """
    publish_time_str = (payload.get("publish_time") or "").strip()
    if not publish_time_str:
        return None, "وقت النشر مطلوب"

    try:
        parsed = datetime.fromisoformat(publish_time_str.replace("Z", "+00:00"))
    except Exception:
        return None, "صيغة وقت النشر غير صحيحة"

    if parsed.tzinfo is not None:
        utc_dt = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return utc_dt, None

    # If datetime-local from browser is naive, allow timezone offset in minutes.
    raw_offset = payload.get("timezone_offset_minutes")
    if raw_offset is None:
        # Backward-compatible fallback: treat as server-local naive/UTC-naive behavior.
        return parsed.replace(tzinfo=None), None

    try:
        offset_minutes = int(raw_offset)
    except Exception:
        return None, "timezone_offset_minutes يجب أن يكون رقمًا صحيحًا"

    # JS offset is UTC - local, so UTC = local + offset.
    utc_dt = parsed + timedelta(minutes=offset_minutes)
    return utc_dt.replace(tzinfo=None), None
