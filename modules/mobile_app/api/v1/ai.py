"""Finora AI conversation endpoints (Phase 7)."""
from __future__ import annotations

from flask import g, request

from modules.mobile_app.api.v1.routes import mobile_api_v1_bp, require_mobile_auth
from modules.mobile_app.schemas import api_error, api_ok, require_json_fields
from modules.mobile_app.services import ai_assistant as ai_service
from modules.mobile_app.services.ai_assistant import AIError
from modules.mobile_app.services.feature_flags import is_flag_enabled
from modules.mobile_app.services.rate_limit import enforce_rate_limit


@mobile_api_v1_bp.post("/ai/conversations")
@require_mobile_auth
def ai_create_conversation():
    if not is_flag_enabled("ai_assistant_enabled", True):
        return api_error("Finora AI غير مفعّل", 403, code="ai_disabled")
    body = request.get_json(silent=True) or {}
    title = str(body.get("title") or "").strip() or None
    return api_ok(
        {"conversation": ai_service.create_conversation(g.mobile_user.id, title=title)},
        status=201,
    )


@mobile_api_v1_bp.get("/ai/conversations")
@require_mobile_auth
def ai_list_conversations():
    if not is_flag_enabled("ai_assistant_enabled", True):
        return api_error("Finora AI غير مفعّل", 403, code="ai_disabled")
    limit = min(50, max(1, int(request.args.get("limit") or 30)))
    return api_ok(
        {"items": ai_service.list_conversations(g.mobile_user.id, limit=limit)}
    )


@mobile_api_v1_bp.get("/ai/conversations/<int:conversation_id>")
@require_mobile_auth
def ai_get_conversation(conversation_id: int):
    conv = ai_service.get_conversation(g.mobile_user.id, conversation_id)
    if conv is None:
        return api_error("المحادثة غير موجودة", 404, code="not_found")
    return api_ok({"conversation": conv})


@mobile_api_v1_bp.post("/ai/conversations/<int:conversation_id>/messages")
@require_mobile_auth
def ai_send_message(conversation_id: int):
    limited = enforce_rate_limit("ai_messages", limit=40, window_seconds=60)
    if limited is not None:
        return limited
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "content")
    if missing:
        return api_error(missing, 400, code="validation_error")
    try:
        result = ai_service.send_message(
            user_id=g.mobile_user.id,
            conversation_id=conversation_id,
            content=str(body.get("content") or ""),
        )
        return api_ok(result)
    except AIError as exc:
        status = 404 if exc.code == "not_found" else 400
        if exc.code == "ai_disabled":
            status = 403
        return api_error(exc.message, status, code=exc.code)


@mobile_api_v1_bp.post("/ai/conversations/<int:conversation_id>/confirm-action")
@require_mobile_auth
def ai_confirm_action(conversation_id: int):
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if not isinstance(action, dict):
        return api_error("action مطلوب", 400, code="validation_error")
    try:
        result = ai_service.confirm_pending_action(
            user_id=g.mobile_user.id,
            conversation_id=conversation_id,
            action=action,
        )
        return api_ok(result)
    except AIError as exc:
        status = 404 if exc.code == "not_found" else 400
        return api_error(exc.message, status, code=exc.code)
