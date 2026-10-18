"""Unified search endpoint for Finora Phone."""

from __future__ import annotations

from flask import g, request

from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.schemas import api_ok
from modules.phone_app.services.feature_flags import require_feature
from modules.phone_app.services.search import search_all


@phone_api_v1_bp.get("/search")
@require_phone_auth
def phone_search():
    blocked = require_feature("phone_advanced_search_enabled")
    if blocked is not None:
        return blocked
    q = request.args.get("q") or ""
    types_raw = (request.args.get("types") or "").strip()
    types = [t.strip() for t in types_raw.split(",") if t.strip()] if types_raw else None
    cursor = request.args.get("cursor")
    try:
        limit = int(request.args.get("limit") or 20)
    except ValueError:
        limit = 20
    branch_id = None
    if request.args.get("branch_id"):
        try:
            branch_id = int(request.args.get("branch_id"))
        except ValueError:
            branch_id = None
    result = search_all(
        q=q,
        types=types,
        cursor=cursor,
        limit=limit,
        employee=g.phone_employee,
        branch_id=branch_id,
    )
    return api_ok(result)
