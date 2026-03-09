from __future__ import annotations

"""تكامل أساسي مع Instagram Graph API لنشر صورة مع كابشن."""

from typing import Any, Dict

import requests


def publish_instagram_image(ig_user_id: str, access_token: str, image_url: str, caption: str) -> str:
    """إنشاء وسائط ثم نشرها على إنستجرام، وإرجاع post_id."""
    create_url = f"https://graph.facebook.com/v19.0/{ig_user_id}/media"
    payload: Dict[str, Any] = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token,
    }
    r = requests.post(create_url, data=payload, timeout=60)
    r.raise_for_status()
    creation_id = r.json().get("id")
    if not creation_id:
        raise RuntimeError("فشل إنشاء وسائط إنستجرام.")

    publish_url = f"https://graph.facebook.com/v19.0/{ig_user_id}/media_publish"
    payload = {
        "creation_id": creation_id,
        "access_token": access_token,
    }
    r2 = requests.post(publish_url, data=payload, timeout=60)
    r2.raise_for_status()
    data = r2.json()
    post_id = data.get("id")
    if not post_id:
        raise RuntimeError("فشل نشر منشور إنستجرام.")
    return post_id

