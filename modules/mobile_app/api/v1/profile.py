"""Profile, addresses, and unified search endpoints."""
from __future__ import annotations

from flask import g, request

from modules.mobile_app.api.v1.routes import (
    mobile_api_v1_bp,
    optional_mobile_auth,
    require_mobile_auth,
)
from modules.mobile_app.schemas import api_error, api_ok
from modules.mobile_app.services import catalog as catalog_service
from modules.mobile_app.services import profile as profile_service
from modules.mobile_app.services import unified_search as search_service
from modules.mobile_app.services.profile import ProfileError


@mobile_api_v1_bp.get("/profile")
@require_mobile_auth
def profile_get():
    try:
        return api_ok(profile_service.get_profile(g.mobile_user.id))
    except ProfileError as exc:
        return api_error(exc.message, 404, code=exc.code)


@mobile_api_v1_bp.patch("/profile")
@require_mobile_auth
def profile_patch():
    body = request.get_json(silent=True) or {}
    try:
        return api_ok(profile_service.update_profile(g.mobile_user.id, body))
    except ProfileError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)


@mobile_api_v1_bp.get("/profile/addresses")
@require_mobile_auth
def profile_addresses_list():
    return api_ok({"items": profile_service.list_addresses(g.mobile_user.id)})


@mobile_api_v1_bp.post("/profile/addresses")
@require_mobile_auth
def profile_addresses_create():
    body = request.get_json(silent=True) or {}
    try:
        return api_ok(
            {"address": profile_service.create_address(g.mobile_user.id, body)},
            status=201,
        )
    except ProfileError as exc:
        return api_error(exc.message, 400, code=exc.code)


@mobile_api_v1_bp.patch("/profile/addresses/<int:address_id>")
@require_mobile_auth
def profile_addresses_update(address_id: int):
    body = request.get_json(silent=True) or {}
    try:
        return api_ok(
            {"address": profile_service.update_address(g.mobile_user.id, address_id, body)}
        )
    except ProfileError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)


@mobile_api_v1_bp.delete("/profile/addresses/<int:address_id>")
@require_mobile_auth
def profile_addresses_delete(address_id: int):
    try:
        profile_service.delete_address(g.mobile_user.id, address_id)
        return api_ok({"deleted": True})
    except ProfileError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)


@mobile_api_v1_bp.get("/profile/favorites")
@require_mobile_auth
def profile_favorites():
    return api_ok(
        {"items": catalog_service.list_favorites(user_id=g.mobile_user.id)}
    )


@mobile_api_v1_bp.get("/profile/liked-videos")
@require_mobile_auth
def profile_liked_videos():
    limit = min(100, max(1, int(request.args.get("limit") or 40)))
    return api_ok(
        {"items": profile_service.liked_videos(g.mobile_user.id, limit=limit)}
    )


@mobile_api_v1_bp.get("/profile/saved-videos")
@require_mobile_auth
def profile_saved_videos():
    limit = min(100, max(1, int(request.args.get("limit") or 40)))
    return api_ok(
        {"items": profile_service.saved_videos(g.mobile_user.id, limit=limit)}
    )


@mobile_api_v1_bp.post("/profile/delete-account")
@require_mobile_auth
def profile_delete_account():
    body = request.get_json(silent=True) or {}
    try:
        profile_service.deactivate_account(
            g.mobile_user.id, reason=str(body.get("reason") or "")
        )
        return api_ok({"deleted": True})
    except ProfileError as exc:
        return api_error(exc.message, 400, code=exc.code)


@mobile_api_v1_bp.get("/search/unified")
@optional_mobile_auth
def search_unified():
    q = (request.args.get("q") or "").strip()
    limit = min(40, max(1, int(request.args.get("limit") or 20)))
    user_id = g.mobile_user.id if g.mobile_user else None
    return api_ok(search_service.unified_search(q, user_id=user_id, limit=limit))
