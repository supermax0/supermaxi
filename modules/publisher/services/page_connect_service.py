"""
page_connect_service.py
-----------------------
Shared service to fetch Facebook pages from user token and upsert into publisher_pages.
Used by both /api/pages/connect and /api/settings/connect-pages endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List

from extensions import db
from modules.publisher.models.publisher_page import PublisherPage
from modules.publisher.services import facebook_service as fb
from modules.publisher.services.token_utils import encrypt_token


def connect_and_store_pages(*, tenant_slug: str, user_token: str) -> Dict[str, Any]:
    token = (user_token or "").strip()
    if not token:
        return {
            "success": False,
            "error_code": "missing_user_token",
            "message": "user_token مطلوب",
        }

    result = fb.get_user_pages(token)
    if not result.get("success"):
        return {
            "success": False,
            "error_code": "facebook_pages_fetch_failed",
            "message": result.get("message") or "فشل جلب صفحات فيسبوك",
            "details": result,
        }

    pages_data: List[dict] = result.get("pages", []) or []
    saved = []
    for page in pages_data:
        page_id = page.get("id")
        page_name = page.get("name", "")
        page_token = page.get("access_token", "")
        if not page_id or not page_token:
            continue

        existing = PublisherPage.query.filter_by(
            tenant_slug=tenant_slug, page_id=page_id
        ).first()
        if existing:
            existing.page_name = page_name
            existing.page_token = encrypt_token(page_token)
        else:
            db.session.add(
                PublisherPage(
                    tenant_slug=tenant_slug,
                    page_id=page_id,
                    page_name=page_name,
                    page_token=encrypt_token(page_token),
                )
            )
        saved.append({"page_id": page_id, "page_name": page_name})

    db.session.commit()
    return {
        "success": True,
        "message": f"تم ربط {len(saved)} صفحة بنجاح",
        "pages": saved,
        "count": len(saved),
    }
