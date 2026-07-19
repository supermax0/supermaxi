"""Unified mobile search across products, categories, and videos."""
from __future__ import annotations

from sqlalchemy import or_

from modules.mobile_app.models import MobileVideo
from modules.mobile_app.services import catalog as catalog_service


def unified_search(q: str, *, user_id: int | None = None, limit: int = 20) -> dict:
    query = (q or "").strip()
    if len(query) < 2:
        return {"query": query, "products": [], "categories": [], "videos": [], "offers": []}

    products = catalog_service.search_products(query, user_id=user_id, limit=limit)
    q_lower = query.lower()
    categories = [
        c
        for c in catalog_service.list_categories()
        if q_lower in str(c.get("name") or "").lower()
    ]
    offers = [
        p
        for p in catalog_service.list_offers(user_id=user_id, limit=limit)
        if q_lower in str(p.get("name") or "").lower()
        or q_lower in str(p.get("category") or "").lower()
    ]

    like = f"%{query}%"
    video_rows = (
        MobileVideo.query.filter(
            MobileVideo.deleted_at.is_(None),
            MobileVideo.status.in_(["published", "ready"]),
            MobileVideo.processing_status == "ready",
            MobileVideo.visibility == "public",
        )
        .filter(or_(MobileVideo.title.ilike(like), MobileVideo.description.ilike(like)))
        .order_by(MobileVideo.published_at.desc(), MobileVideo.id.desc())
        .limit(min(limit, 15))
        .all()
    )
    videos = [v.to_feed_dict(liked=False, saved=False) for v in video_rows]

    return {
        "query": query,
        "products": products,
        "categories": categories,
        "videos": videos,
        "offers": offers,
    }
