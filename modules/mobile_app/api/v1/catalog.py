"""Mobile store / catalog endpoints (Phase 4)."""
from __future__ import annotations

from flask import g, request

from modules.mobile_app.api.v1.routes import (
    mobile_api_v1_bp,
    optional_mobile_auth,
    require_mobile_auth,
)


def _viewer_id() -> int | None:
    return g.mobile_user.id if getattr(g, "mobile_user", None) else None
from modules.mobile_app.schemas import api_error, api_ok
from modules.mobile_app.services import catalog as catalog_service
from modules.mobile_app.services import shared_cache


def _cached_ok(payload: dict, state: str):
    response, status = api_ok(payload)
    response.headers["X-Finora-Cache"] = state
    return response, status


@mobile_api_v1_bp.get("/categories")
@optional_mobile_auth
def categories():
    cache_parts = {"version": 2}
    cached = shared_cache.get_json("catalog-categories", cache_parts)
    if isinstance(cached, dict):
        return _cached_ok(cached, "HIT")
    payload = {"items": catalog_service.list_categories()}
    shared_cache.set_json("catalog-categories", cache_parts, payload, ttl=60)
    return _cached_ok(payload, "MISS")


@mobile_api_v1_bp.get("/products")
@optional_mobile_auth
def products():
    limit = min(80, max(1, int(request.args.get("limit") or 24)))
    offset = max(0, int(request.args.get("offset") or 0))
    q = request.args.get("q") or ""
    category = request.args.get("category") or ""
    sort = request.args.get("sort") or "latest"
    availability = request.args.get("availability") or "all"
    cache_parts = {
        "version": 3,
        "q": q,
        "category": category,
        "sort": sort,
        "availability": availability,
        "limit": limit,
        "offset": offset,
    }
    if _viewer_id() is None:
        cached = shared_cache.get_json("catalog-products", cache_parts)
        if isinstance(cached, dict):
            return _cached_ok(cached, "HIT")

    items = catalog_service.list_products(
        q=q,
        category=category,
        sort=sort,
        availability=availability,
        limit=limit + 1,
        offset=offset,
        user_id=_viewer_id(),
    )
    has_more = len(items) > limit
    page = items[:limit]
    payload = {
        "items": page,
        "has_more": has_more,
        "next_offset": offset + len(page) if has_more else None,
    }
    if _viewer_id() is None:
        shared_cache.set_json("catalog-products", cache_parts, payload, ttl=20)
    return _cached_ok(payload, "MISS")


@mobile_api_v1_bp.get("/products/<int:product_id>")
@optional_mobile_auth
def product_detail(product_id: int):
    item = catalog_service.get_product(product_id, user_id=_viewer_id())
    if item is None:
        return api_error("المنتج غير موجود", 404, code="not_found")
    return api_ok({"product": item})


@mobile_api_v1_bp.get("/products/<int:product_id>/videos")
@optional_mobile_auth
def product_videos(product_id: int):
    item = catalog_service.get_product(product_id, user_id=_viewer_id())
    if item is None:
        return api_error("المنتج غير موجود", 404, code="not_found")
    return api_ok({"items": item.get("videos") or []})


@mobile_api_v1_bp.get("/offers")
@optional_mobile_auth
def offers():
    return api_ok(
        {
            "items": catalog_service.list_offers(
                user_id=_viewer_id(),
                limit=int(request.args.get("limit") or 30),
            )
        }
    )


@mobile_api_v1_bp.get("/search")
@optional_mobile_auth
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return api_ok({"items": []})
    return api_ok(
        {
            "items": catalog_service.search_products(
                q, user_id=_viewer_id(), limit=int(request.args.get("limit") or 40)
            )
        }
    )


@mobile_api_v1_bp.get("/favorites")
@require_mobile_auth
def favorites():
    return api_ok({"items": catalog_service.list_favorites(user_id=g.mobile_user.id)})


@mobile_api_v1_bp.post("/favorites/<int:product_id>")
@require_mobile_auth
def favorite_add(product_id: int):
    from modules.mobile_app.models import MobileFavorite

    existing = MobileFavorite.query.filter_by(
        user_id=g.mobile_user.id, product_id=product_id
    ).first()
    if existing:
        product = catalog_service.get_product(product_id, user_id=g.mobile_user.id)
        if product is None:
            return api_error("المنتج غير موجود", 404, code="not_found")
        return api_ok({"favorited": True, "product": product})
    favorited, product = catalog_service.toggle_favorite(
        user_id=g.mobile_user.id, product_id=product_id
    )
    if product is None:
        return api_error("المنتج غير موجود", 404, code="not_found")
    return api_ok({"favorited": favorited, "product": product})


@mobile_api_v1_bp.delete("/favorites/<int:product_id>")
@require_mobile_auth
def favorite_remove(product_id: int):
    from modules.mobile_app.models import MobileFavorite

    existing = MobileFavorite.query.filter_by(
        user_id=g.mobile_user.id, product_id=product_id
    ).first()
    if existing:
        catalog_service.toggle_favorite(user_id=g.mobile_user.id, product_id=product_id)
    return api_ok({"favorited": False})


@mobile_api_v1_bp.get("/videos/<int:video_id>/products")
@optional_mobile_auth
def video_products(video_id: int):
    return api_ok(
        {
            "items": catalog_service.products_for_video(
                video_id, user_id=_viewer_id()
            )
        }
    )
