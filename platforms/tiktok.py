from __future__ import annotations

"""تكامل أساسي مع TikTok Business API لنشر فيديو."""

from typing import Any, Dict

import requests


def publish_tiktok_video(video_url: str, caption: str, access_token: str) -> str:
    """نشر فيديو على تيك توك باستخدام API.

    ملاحظة: قد تحتاج هذه الدالة لتعديل لتوافق مخطط حسابات TikTok لديك
    (upload session, video_id، إلخ) حسب وثائق API الفعلية.
    """
    url = "https://open.tiktokapis.com/v2/post/publish/"
    payload: Dict[str, Any] = {
        "video_url": video_url,
        "text": caption,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    post_id = data.get("data", {}).get("id") or data.get("id")
    if not post_id:
        raise RuntimeError("فشل نشر فيديو تيك توك.")
    return post_id

