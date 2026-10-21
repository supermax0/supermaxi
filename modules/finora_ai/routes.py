"""Finora AI HTTP/SSE API."""
from __future__ import annotations

import json
import time
import hashlib
from collections import defaultdict, deque
from datetime import datetime
from types import SimpleNamespace

from flask import Blueprint, Response, jsonify, request, session, stream_with_context, render_template, current_app, g

from extensions import db
from modules.finora_ai.context import AuthenticationRequired, FinoraAuthContext
from modules.finora_ai.models import FinoraAIConversation, FinoraAIMessage, FinoraMCPConnection
from modules.finora_ai.orchestrator import FinoraAIOrchestrator
from modules.finora_ai.schema import ensure_finora_ai_schema
from modules.finora_ai.settings import current_settings, encrypt_secret
from utils.permission_checks import check_permission


finora_ai_bp = Blueprint("finora_ai", __name__, url_prefix="/finora-ai")
from modules.finora_ai.security import rate_limit as _rate_limit
_TOOL_LABELS = {
    "search_customer": "جاري البحث عن العميل...",
    "get_customer_balance": "جاري قراءة رصيد العميل...",
    "get_customer_statement": "جاري قراءة كشف الحساب...",
    "search_orders": "جاري البحث في الطلبات...",
    "get_order": "جاري قراءة الطلب...",
    "search_products": "جاري البحث في المنتجات...",
    "get_product_stock": "جاري قراءة المخزون...",
    "get_low_stock": "جاري فحص المخزون المنخفض...",
    "search_supplier": "جاري البحث عن المورد...",
    "get_supplier_balance": "جاري قراءة رصيد المورد...",
    "get_supplier_statement": "جاري قراءة كشف المورد...",
    "get_daily_sales": "جاري احتساب مبيعات اليوم...",
    "get_sales_summary": "جاري إعداد ملخص المبيعات...",
    "get_cash_balance": "جاري قراءة رصيد الصندوق...",
    "get_receivables_summary": "جاري احتساب ذمم العملاء...",
    "get_payables_summary": "جاري احتساب ذمم الموردين...",
    "get_latest_order": "جاري قراءة آخر طلب مصرح لك...",
    "get_expenses": "جاري تلخيص المصاريف...",
    "get_top_products": "جاري ترتيب المنتجات الأكثر مبيعًا...",
    "get_shipping_dues": "جاري قراءة ذمم شركات النقل...",
    "search_delivery_agents": "جاري البحث عن المندوب...",
    "get_delivery_agent_reports": "جاري قراءة كشوف المندوب ومبالغها...",
    "get_agent_report": "جاري قراءة الكشف المحدد...",
    "get_pending_agent_reports": "جاري قراءة طابور كشوف المندوب...",
    "get_period_comparison": "جاري مقارنة الفترتين...",
    "get_sales_breakdown": "جاري تقسيم المبيعات...",
    "get_purchases_summary": "جاري قراءة المشتريات...",
    "get_receivables_aging": "جاري قراءة أعمار الذمم...",
    "get_sales_returns": "جاري قراءة المرتجعات...",
    "get_overdue_installments": "جاري قراءة الأقساط المتأخرة...",
    "get_stagnant_products": "جاري فحص المنتجات الراكدة...",
    "get_product_movements": "جاري قراءة حركة المنتج...",
    "get_expense_anomalies": "جاري فحص المصاريف غير الطبيعية...",
    "get_duplicate_customers": "جاري البحث عن عملاء مكررين...",
}


@finora_ai_bp.before_request
def _protect():
    try:
        context = FinoraAuthContext.current()
    except AuthenticationRequired:
        return jsonify({"success": False, "error": {"code": "UNAUTHENTICATED", "message": "Authentication required"}}), 401
    if request.endpoint not in {"finora_ai.provider_settings", "finora_ai.settings_page", "finora_ai.mcp_connections", "finora_ai.revoke_mcp_connection"} and not context.allows("use_ai_assistant"):
        return jsonify({"success": False, "error": {"code": "PERMISSION_DENIED", "message": "AI assistant permission required"}}), 403
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return jsonify({"success": False, "error": {"code": "ORIGIN_DENIED"}}), 403
    ensure_finora_ai_schema()
    settings = current_settings()
    if request.endpoint not in {"finora_ai.provider_settings", "finora_ai.settings_page", "finora_ai.mcp_connections", "finora_ai.revoke_mcp_connection"} and (not settings.enabled or not settings.get_flags().get("finora_ai_enabled", True)):
        return jsonify({"success": False, "error": {"code": "FEATURE_DISABLED"}}), 404
    if request.content_length and request.content_length > 64 * 1024:
        return jsonify({"success": False, "error": {"code": "REQUEST_TOO_LARGE"}}), 413


def _context() -> FinoraAuthContext:
    return FinoraAuthContext.current()


@finora_ai_bp.post("/api/mcp/token")
def mcp_access_token():
    from modules.finora_ai.tokens import issue_token
    denied = _rate_limit(_context())
    if denied:
        return denied
    if not current_settings().get_flags().get("mcp_enabled", True):
        return jsonify({"error": {"code": "FEATURE_DISABLED", "message": "فعّل ربط MCP واحفظ الإعدادات أولًا."}}), 409
    try:
        token = issue_token(_context())
    except AuthenticationRequired:
        return jsonify({"error": {"code": "SIGNING_NOT_CONFIGURED", "message": "يجب تهيئة مفتاح توقيع آمن على الخادم قبل إصدار رمز الاتصال."}}), 503
    response = jsonify({"access_token": token, "token_type": "Bearer", "expires_in": 900})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@finora_ai_bp.route("/api/mcp/connections", methods=["GET", "POST"])
def mcp_connections():
    context = _context()
    if request.method == "GET":
        rows = FinoraMCPConnection.query.filter_by(tenant_slug=context.tenant_slug, user_id=context.user_id).order_by(FinoraMCPConnection.created_at.desc()).limit(100).all()
        response = jsonify({"connections": [{"id": row.id, "name": row.name, "created_at": row.created_at.isoformat(), "revoked": row.revoked_at is not None} for row in rows]})
    else:
        if not context.allows("manage_settings") or not context.allows("use_ai_assistant"):
            return jsonify({"error": {"code": "PERMISSION_DENIED"}}), 403
        denied = _rate_limit(context)
        if denied:
            return denied
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("acknowledge_persistent_access") is not True or not isinstance(payload.get("name"), str) or not 1 <= len(payload["name"].strip()) <= 80:
            return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "اذكر اسم التطبيق ووافق على منحه وصولًا مستمرًا بصلاحيات حسابك."}}), 400
        settings = current_settings()
        if not settings.enabled or not settings.get_flags().get("finora_ai_enabled", True) or not settings.get_flags().get("mcp_enabled", True):
            return jsonify({"error": {"code": "FEATURE_DISABLED", "message": "فعّل ربط MCP أولًا."}}), 409
        from modules.finora_ai.tokens import issue_connection
        try:
            connection_id, token = issue_connection(context, payload["name"].strip())
        except AuthenticationRequired:
            return jsonify({"error": {"code": "SIGNING_NOT_CONFIGURED", "message": "هيّئ مفتاح توقيع آمن للخادم أولًا."}}), 503
        except ValueError as exc:
            return jsonify({"error": {"code": "CONNECTION_LIMIT", "message": str(exc)}}), 409
        response = jsonify({"id": connection_id, "access_token": token, "token_type": "Bearer", "expires_in": None})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@finora_ai_bp.post("/api/mcp/connections/<string:connection_id>/revoke")
def revoke_mcp_connection(connection_id):
    context = _context()
    row = FinoraMCPConnection.query.filter_by(id=connection_id, tenant_slug=context.tenant_slug, user_id=context.user_id).first()
    if not row:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.session.commit()
    response = jsonify({"success": True})
    response.headers["Cache-Control"] = "no-store"
    return response


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@finora_ai_bp.post("/api/chat/stream")
def chat_stream():
    context = _context()
    denied = _rate_limit(context)
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR"}}), 400
    message = str(payload.get("message") or "").strip()
    if not message or len(message) > 4000:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Message must contain 1-4000 characters"}}), 400
    conversation_id = payload.get("conversation_id")
    if conversation_id is not None and (not isinstance(conversation_id, int) or isinstance(conversation_id, bool) or conversation_id <= 0):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR"}}), 400
    page_context = payload.get("page_context") if isinstance(payload.get("page_context"), dict) else {}
    # Streaming resumes after the original request's ORM session is removed.
    # Keep the already-authorized branch scope, but not expired ORM objects.
    def branch_snapshot(branch):
        return SimpleNamespace(id=int(branch.id), name=branch.name,
                               is_default=bool(branch.is_default)) if branch is not None else None
    stream_branch = branch_snapshot(getattr(g, "branch", None))
    stream_branches = [branch_snapshot(branch) for branch in (getattr(g, "branches", []) or [])]

    @stream_with_context
    def generate():
        active_conversation_id = conversation_id
        try:
            yield _sse("start", {"conversation_id": conversation_id})
            g.branch = stream_branch
            g.branches = stream_branches
            for event, data in FinoraAIOrchestrator(context).run_events(
                message, conversation_id=conversation_id, page_context=page_context
            ):
                if event == "tool":
                    name = data["tool"]
                    yield _sse("tool", {"tool": name, "status": _TOOL_LABELS.get(name, "جاري قراءة بيانات FINORA...")})
                elif event == "delta":
                    yield _sse("delta", data)
                elif event == "conversation":
                    active_conversation_id = data["conversation_id"]
                    yield _sse("conversation", data)
                elif event == "mode":
                    yield _sse("mode", data)
                elif event == "done":
                    yield _sse("done", data)
        except Exception as error:
            db.session.rollback()
            current_app.logger.warning("Finora AI request failed: %s", type(error).__name__)
            if current_app.testing:
                current_app.logger.exception("Finora AI test-environment traceback")
            if active_conversation_id:
                error_message = FinoraAIMessage(conversation_id=active_conversation_id, role="assistant", content="تعذر إكمال الطلب. حاول مرة أخرى.")
                error_message.set_metadata({"error_code": "AI_REQUEST_FAILED", "error_type": type(error).__name__})
                db.session.add(error_message)
                db.session.commit()
            yield _sse("error", {"code": "AI_REQUEST_FAILED", "message": "تعذر إكمال الطلب. حاول مرة أخرى."})
    return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@finora_ai_bp.get("/api/desktop/runtime")
@finora_ai_bp.get("/api/runtime")
def runtime_info():
    response = jsonify({"success": True, **FinoraAIOrchestrator(_context()).runtime_info()})
    response.headers["Cache-Control"] = "no-store"
    return response


def _desktop_local_scope(context):
    from utils.branch_scope import allowed_branch_ids, viewing_all_branches
    scope = [context.tenant_slug, context.user_id, context.role, sorted(context.permissions),
             sorted(allowed_branch_ids()), viewing_all_branches(), session.get("branch_id")]
    return hashlib.sha256(json.dumps(scope, sort_keys=True, default=str).encode()).hexdigest()


@finora_ai_bp.get("/api/desktop/tools")
def desktop_local_tools():
    """Read-only tools for a local model; credentials and language inference stay on the PC."""
    from modules.finora_ai.services import list_tools
    context = _context()
    response = jsonify(success=True, scope=_desktop_local_scope(context), read_only=True,
                       tools=[{"name": tool["name"], "description": tool["description"],
                               "parameters": tool["inputSchema"]} for tool in list_tools(context)])
    response.headers["Cache-Control"] = "no-store"
    return response


@finora_ai_bp.post("/api/desktop/tool")
def desktop_local_tool():
    from modules.finora_ai.services import execute_tool, list_tools
    context = _context()
    payload = request.get_json(silent=True)
    if (not isinstance(payload, dict) or set(payload) != {"name", "arguments", "scope"}
            or not isinstance(payload["name"], str) or not isinstance(payload["arguments"], dict)
            or not isinstance(payload["scope"], str)):
        return jsonify(success=False, error={"code": "VALIDATION_ERROR"}), 400
    if payload["scope"] != _desktop_local_scope(context):
        return jsonify(success=False, error={"code": "SCOPE_CHANGED", "message": "تغير الحساب أو نطاق الفروع. أعد السؤال ضمن النطاق الحالي."}), 409
    if payload["name"] not in {tool["name"] for tool in list_tools(context)}:
        return jsonify(success=False, error={"code": "PERMISSION_DENIED"}), 403
    denied = _rate_limit(context)
    if denied:
        return denied
    response = jsonify(execute_tool(context, payload["name"], payload["arguments"], provider="desktop-local"))
    response.headers["Cache-Control"] = "no-store"
    return response


@finora_ai_bp.post("/api/desktop/chat")
def desktop_chat():
    """JSON adapter for the existing read-only assistant, using its existing provider/settings.

    Electron's validated JSON transport does not consume SSE. Keep authentication,
    feature/permission guards, tool authorization and rate limits identical to chat_stream.
    A fresh conversation prevents previous-branch context being replayed after a scope switch.
    """
    context = _context()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"message"}:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR"}), 400
    message = payload.get("message")
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
        return jsonify(success=False, error={"code": "VALIDATION_ERROR"}), 400
    denied = _rate_limit(context)
    if denied:
        return denied
    try:
        for event, data in FinoraAIOrchestrator(context).run_events(
            message.strip(), page_context={"page": "desktop-workspace"}
        ):
            if event == "done":
                return jsonify(success=True, message=data["message"])
        return jsonify(success=False, error={"code": "AI_REQUEST_FAILED"}), 502
    except Exception as error:
        db.session.rollback()
        current_app.logger.warning("Finora desktop assistant failed: %s", type(error).__name__)
        return jsonify(success=False, error={"code": "AI_REQUEST_FAILED", "message": "تعذر إكمال الطلب. حاول مرة أخرى."}), 502


@finora_ai_bp.get("/api/conversations")
def conversations():
    context = _context()
    rows = FinoraAIConversation.query.filter_by(
        tenant_slug=context.tenant_slug, user_id=context.user_id
    ).order_by(FinoraAIConversation.updated_at.desc()).limit(30).all()
    return jsonify({"success": True, "conversations": [
        {"id": row.id, "title": row.title, "updated_at": row.updated_at.isoformat() if row.updated_at else None}
        for row in rows
    ]})


@finora_ai_bp.get("/api/conversations/<int:conversation_id>/messages")
def conversation_messages(conversation_id):
    context = _context()
    conversation = FinoraAIConversation.query.filter_by(
        id=conversation_id, tenant_slug=context.tenant_slug, user_id=context.user_id
    ).first()
    if not conversation:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND"}}), 404
    rows = FinoraAIMessage.query.filter_by(conversation_id=conversation.id).order_by(FinoraAIMessage.id.asc()).all()
    return jsonify({"success": True, "conversation_id": conversation.id, "messages": [
        {"id": row.id, "role": row.role, "content": row.content, "created_at": row.created_at.isoformat() if row.created_at else None}
        for row in rows if row.role in {"user", "assistant"}
    ]})


@finora_ai_bp.route("/api/settings", methods=["GET", "PUT"])
def provider_settings():
    if not _context().allows("manage_settings"):
        return jsonify({"success": False, "error": {"code": "PERMISSION_DENIED"}}), 403
    settings = current_settings()
    if request.method == "GET":
        return jsonify({"success": True, "settings": {
            "enabled": bool(settings.enabled), "provider": settings.provider, "model": settings.model or "",
            "endpoint": settings.endpoint or "", "has_api_key": bool(settings.encrypted_api_key),
            "timeout_seconds": settings.timeout_seconds, "context_size": settings.context_size,
            "feature_flags": settings.get_flags(),
            "mcp_connection": {"url": current_app.config.get("FINORA_MCP_PUBLIC_URL") or request.host_url.rstrip("/") + "/mcp",
                               "transport": "Streamable HTTP", "expires_in": 900},
        }})
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR"}}), 400
    allowed = {"builtin", "openai", "local", "ollama", "lmstudio", "vllm", "openai_compatible", "automatic"}
    provider = str(payload.get("provider") or settings.provider or "builtin").lower()
    if provider not in allowed:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Unsupported provider"}}), 400
    flags_payload = payload.get("feature_flags", {})
    if not isinstance(flags_payload, dict) or any(not isinstance(value, bool) for value in flags_payload.values()) or ("enabled" in payload and not isinstance(payload["enabled"], bool)):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR"}}), 400
    flags = settings.get_flags()
    flags.update({key: value for key, value in flags_payload.items() if key in flags})
    flags["ai_write_tools_enabled"] = False
    if provider in {"local", "ollama", "lmstudio", "vllm"} and not flags.get("ai_local_provider_enabled", True):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Local providers are disabled"}}), 400
    settings.enabled = bool(payload.get("enabled", settings.enabled))
    settings.provider = provider
    settings.model = str(payload.get("model", settings.model) or "").strip()[:120] or None
    settings.endpoint = str(payload.get("endpoint", settings.endpoint) or "").strip()[:500] or None
    if settings.endpoint:
        from urllib.parse import urlsplit
        try:
            endpoint = urlsplit(settings.endpoint)
            valid_endpoint = endpoint.scheme in {"http", "https"} and endpoint.hostname and not endpoint.username and not endpoint.password
            endpoint.port
        except ValueError:
            valid_endpoint = False
        if not valid_endpoint:
            db.session.rollback()
            return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Endpoint must be an HTTP(S) URL without credentials"}}), 400
    try:
        settings.timeout_seconds = max(5, min(int(payload.get("timeout_seconds") or settings.timeout_seconds or 60), 180))
        if "context_size" in payload:
            settings.context_size = max(512, min(int(payload.get("context_size") or 8192), 1000000))
    except (ValueError, TypeError, OverflowError):
        db.session.rollback()
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid numeric settings"}}), 400
    if payload.get("api_key"):
        settings.encrypted_api_key = encrypt_secret(str(payload["api_key"]))
    if payload.get("clear_api_key") is True:
        settings.encrypted_api_key = None
    settings.set_flags(flags)
    settings.updated_by_id = _context().user_id
    db.session.add(settings)
    db.session.commit()
    return jsonify({"success": True, "message": "AI settings saved", "has_api_key": bool(settings.encrypted_api_key)})


@finora_ai_bp.get("/settings")
def settings_page():
    if not _context().allows("manage_settings"):
        return jsonify({"success": False, "error": {"code": "PERMISSION_DENIED"}}), 403
    return render_template("finora_ai_settings.html")


@finora_ai_bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "finora-ai", "phase": 1, "write_tools": False})


@finora_ai_bp.get("/ready")
def ready():
    settings = current_settings()
    return jsonify({"status": "ready", "provider": settings.provider, "mcp": settings.get_flags().get("mcp_enabled", True)})


@finora_ai_bp.get("/api/metrics")
def metrics():
    context = _context()
    if not context.allows("view_ai_audit_logs", "manage_settings"):
        return jsonify({"success": False, "error": {"code": "PERMISSION_DENIED"}}), 403
    from sqlalchemy import func
    from modules.finora_ai.models import FinoraAIToolCall
    query = FinoraAIToolCall.query.filter_by(tenant_slug=context.tenant_slug)
    conversations_query = FinoraAIConversation.query.filter_by(tenant_slug=context.tenant_slug)
    requests_count = db.session.query(func.count(FinoraAIMessage.id)).join(FinoraAIConversation).filter(
        FinoraAIConversation.tenant_slug == context.tenant_slug, FinoraAIMessage.role == "user"
    ).scalar()
    return jsonify({"success": True, "metrics": {"ai_requests": requests_count,
        "conversations": conversations_query.count(), "tool_calls": query.count(),
        "tool_failures": query.filter(FinoraAIToolCall.result_status.in_(["failed", "denied"])).count(),
        "average_tool_latency_ms": query.with_entities(func.avg(FinoraAIToolCall.duration_ms)).scalar(),
        "estimated_cost": None, "confirmation_acceptance_rate": None, "write_tools": False}})
