"""التكامل مع Nano Banana (أو أي خدمة مشابهة) لتوليد الصور."""

from __future__ import annotations

from typing import Any, Dict

import requests
from flask import current_app


def generate_image(prompt: str) -> str:
    """توليد صورة تسويقية وترجيع رابطها.

    يعتمد على إعدادات:
    - NANOBANANA_API_URL
    - NANOBANANA_API_KEY
    """
    base_url = current_app.config.get("NANOBANANA_API_URL", "").rstrip("/")
    api_key = current_app.config.get("NANOBANANA_API_KEY")
    if not base_url or not api_key:
        raise RuntimeError("إعدادات Nano Banana غير مكتملة (URL أو API KEY).")

    url = f"{base_url}/generate"
    payload: Dict[str, Any] = {
        "prompt": prompt,
        "style": "modern marketing",
        "size": "1024x1024",
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    image_url = data.get("image_url")
    if not image_url:
        raise RuntimeError("لم يتم إرجاع image_url من خدمة Nano Banana.")
    return image_url

