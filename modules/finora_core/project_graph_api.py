"""Project maps and revocable, conversation-scoped read-only MCP access."""
import json
import secrets
from datetime import datetime, timedelta, timezone

import jsonschema
from flask import jsonify, request

from .api import _actor, _allowed_origins, _conv_id, _customer_for, _json, finora_core_bp
from .auth import authenticate_request, current_operator, hash_token, require, role_for
from .brain import project_consultation as project
from .brain.provider import ProviderError, get_provider
from .errors import CoreApiError, auth_error, conflict, not_found, permission_error, validation_error
from .models import FcSetting
from .permissions import permissions_for
from .project_graph import analyze_graph, load_graph, plan_hash, save_analysis
from .store import audit, core_session, get_setting, set_setting, use_house


def scoped_draft(s, cid):
    from .conversations import get_conversation
    with use_house():
        if not get_conversation(cid):
            raise not_found("المحادثة غير موجودة")
    customer = _customer_for(s, cid)
    draft = project.load(s, customer, str(cid)) if customer else None
    if not draft:
        raise not_found("لا توجد خطة لهذه المحادثة")
    return customer, draft


@finora_core_bp.get("/conversations/<conversation_id>/project/graph")
@require("settings.manage")
def project_graph(conversation_id):
    cid = _conv_id(conversation_id)
    with core_session() as s:
        customer, draft = scoped_draft(s, cid)
        return jsonify(load_graph(s, customer, cid, draft))


@finora_core_bp.post("/conversations/<conversation_id>/project/graph/analyze")
@require("settings.manage")
def project_graph_analysis(conversation_id):
    cid, payload = _conv_id(conversation_id), _json()
    if set(payload) != {"planHash"}:
        raise validation_error("أرسل إصدار المخطط الذي راجعته")
    with core_session() as s:
        customer, draft = scoped_draft(s, cid)
        graph = load_graph(s, customer, cid, draft)
        if graph["planHash"] != payload["planHash"]:
            raise conflict("الخطة تغيّرت؛ حدّث المخطط أولاً")
    provider = get_provider()
    if provider is None:
        raise validation_error("شغّل الذكاء المحلي أو السحابي لتحليل الترابطات")
    try:
        annotation = analyze_graph(provider, graph)
    except (ProviderError, jsonschema.ValidationError, ValueError, TypeError, KeyError):
        raise CoreApiError("VALIDATION_ERROR", "لم يكتمل تحليل موثوق للترابطات؛ المخطط والخطة الحاليان محفوظان", 422) from None
    with core_session() as s:
        customer = _customer_for(s, cid)
        draft = project.load(s, customer, str(cid), lock=True) if customer else None
        if not draft or plan_hash(draft) != payload["planHash"]:
            raise conflict("الخطة تغيّرت أثناء التحليل؛ لم تُطبق اقتراحات قديمة")
        save_analysis(s, customer, cid, annotation, _actor())
        audit(s, actor=_actor(), actor_type="human", category="finora", action="project.graph_analysis",
              title="تحليل ترابطات خطة العميل", customer=customer.display_name, conversation_ref=str(cid))
        s.commit()
        return jsonify(load_graph(s, customer, cid, draft))


TOKEN_PREFIX = "project_mcp:"
MCP_VERSIONS = {"2025-03-26", "2025-06-18", "2025-11-25"}


def _connection_key(raw):
    # FcSetting.key is VARCHAR(60); 192 hash bits fit without a schema migration.
    return TOKEN_PREFIX + hash_token(raw)[:48]


@finora_core_bp.post("/conversations/<conversation_id>/project/mcp-connection")
@require("settings.manage")
def create_project_connection(conversation_id):
    cid = _conv_id(conversation_id)
    if _json() != {}:
        raise validation_error("حقول اتصال غير معروفة")
    raw = "fpg_" + secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    with core_session() as s:
        customer, _ = scoped_draft(s, cid)
        # A new connection replaces older keys for this owner/conversation, without touching other clients.
        _revoke_connections(s, cid, current_operator().superadmin_id)
        value = {"conversationId": str(cid), "customerId": customer.id,
                 "ownerId": current_operator().superadmin_id, "expiresAt": expires.isoformat(), "revoked": False}
        set_setting(s, _connection_key(raw), json.dumps(value), _actor())
        audit(s, actor=_actor(), actor_type="human", category="finora", action="project.mcp_created",
              title="إنشاء اتصال قراءة لخطة العميل", conversation_ref=str(cid), customer=customer.display_name)
        s.commit()
    return jsonify({"endpointPath": f"/api/v1/finora-core/conversations/{cid}/project/mcp",
                    "token": raw, "expiresAt": expires.isoformat(), "readOnly": True})


def _revoke_connections(s, cid, owner):
    for row in s.query(FcSetting).filter(FcSetting.key.startswith(TOKEN_PREFIX)).all():
        value = json.loads(row.value)
        if value["conversationId"] == str(cid) and value["ownerId"] == owner and not value["revoked"]:
            value["revoked"] = True
            row.value = json.dumps(value)


@finora_core_bp.post("/conversations/<conversation_id>/project/mcp-connection/revoke")
@require("settings.manage")
def revoke_project_connection(conversation_id):
    cid = _conv_id(conversation_id)
    if _json() != {}:
        raise validation_error("حقول اتصال غير معروفة")
    with core_session() as s:
        scoped_draft(s, cid)
        _revoke_connections(s, cid, current_operator().superadmin_id)
        audit(s, actor=_actor(), actor_type="human", category="finora", action="project.mcp_revoked",
              title="إلغاء اتصال قراءة لخطة العميل", conversation_ref=str(cid))
        s.commit()
    return jsonify({"revoked": True})


def _mcp_authorize(s, cid):
    header = request.headers.get("Authorization", "")
    raw = header[7:].strip() if header.startswith("Bearer ") else ""
    if not raw.startswith("fpg_"):
        operator = authenticate_request()
        if "settings.manage" not in operator.permissions:
            raise permission_error()
        return None
    if len(raw) > 100:
        raise auth_error()
    stored = get_setting(s, _connection_key(raw))
    if not stored:
        raise auth_error()
    value = json.loads(stored)
    if value["revoked"] or datetime.fromisoformat(value["expiresAt"]) <= datetime.now(timezone.utc):
        raise auth_error("اتصال MCP منتهي أو ملغى")
    if value["conversationId"] != str(cid):
        raise CoreApiError("FORBIDDEN", "هذا الاتصال يخص خطة عميل آخر", 403)
    from models.core.super_admin import SuperAdmin
    if not s.get(SuperAdmin, value["ownerId"]) or "settings.manage" not in permissions_for(role_for(s, value["ownerId"])):
        raise permission_error()
    return value["customerId"]


def _rpc_error(request_id, code, message, status=200):
    return jsonify({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}), status


def _technical_plan(draft):
    return {"revision": draft["revision"], "phase": draft["phase"],
            "project": {key: value for key, value in draft["brief"].items() if key != "estimate"},
            "handoffReady": draft["phase"] == "execution_ready", "automaticExecutionEnabled": False}


@finora_core_bp.route("/conversations/<conversation_id>/project/mcp", methods=["GET", "POST", "DELETE"])
def project_mcp(conversation_id):
    cid = _conv_id(conversation_id)
    origin = request.headers.get("Origin")
    if origin and origin not in _allowed_origins() | {request.host_url.rstrip("/")}:
        return _rpc_error(None, -32000, "Origin denied", 403)
    if request.content_length and request.content_length > 65536:
        return _rpc_error(None, -32600, "Request too large", 413)
    version = request.headers.get("MCP-Protocol-Version", "2025-03-26")
    if version not in MCP_VERSIONS:
        return _rpc_error(None, -32600, "Unsupported MCP protocol version", 400)
    with core_session() as s:
        scoped_customer = _mcp_authorize(s, cid)
        customer, draft = scoped_draft(s, cid)
        if scoped_customer is not None and scoped_customer != customer.id:
            raise permission_error()
        if request.method != "POST":
            return ("", 405)  # Stateless JSON responses; no SSE stream or session deletion.
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
            return _rpc_error(None, -32600, "Invalid Request", 400)
        request_id, method, params = payload.get("id"), payload["method"], payload.get("params", {})
        if not isinstance(params, dict) or (request_id is not None and (isinstance(request_id, bool) or not isinstance(request_id, (str, int)))):
            return _rpc_error(request_id, -32602, "Invalid params", 400)
        if "id" not in payload:
            if method in {"notifications/initialized", "notifications/cancelled"}:
                return ("", 202)
            return _rpc_error(None, -32600, "Unsupported notification", 400)
        if method == "initialize":
            negotiated = params.get("protocolVersion")
            if not isinstance(negotiated, str):
                return _rpc_error(request_id, -32602, "Invalid protocolVersion")
            result = {"protocolVersion": negotiated if negotiated in MCP_VERSIONS else "2025-11-25",
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "finora-project", "version": "1.0.0"},
                      "instructions": "Read only this customer's technical plan. No quotes, payment, tenant changes or execution."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": name, "description": description,
                                 "inputSchema": {"type": "object", "additionalProperties": False,
                                                 "properties": {"nodeId": {"type": "string"}} if name == "get_project_node" else {},
                                                 "required": ["nodeId"] if name == "get_project_node" else []},
                                 "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}
                                for name, description in [("get_project_plan", "Read the scoped technical specification"),
                                                          ("get_project_graph", "Read pages, features, data, workflows and their links"),
                                                          ("get_project_node", "Read an element and all incoming/outgoing connections")]]}
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments", {})
            if not isinstance(name, str) or name not in {"get_project_plan", "get_project_graph", "get_project_node"} or not isinstance(args, dict):
                return _rpc_error(request_id, -32602, "Unknown tool or invalid arguments")
            if set(args) != ({"nodeId"} if name == "get_project_node" else set()):
                return _rpc_error(request_id, -32602, "Arguments outside project scope")
            if name == "get_project_node" and not isinstance(args["nodeId"], str):
                return _rpc_error(request_id, -32602, "Invalid nodeId")
            data = _technical_plan(draft) if name == "get_project_plan" else load_graph(s, customer, cid, draft)
            if name == "get_project_node":
                item = next((n for n in data["nodes"] if n["id"] == args["nodeId"]), None)
                if not item:
                    return _rpc_error(request_id, -32602, "Unknown project node")
                data = {"revision": data["revision"], "node": item,
                        "connections": [edge for edge in data["edges"] if item["id"] in {edge["source"], edge["target"]}]}
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                      "structuredContent": data, "isError": False}
        else:
            return _rpc_error(request_id, -32601, "Method not found")
        return jsonify({"jsonrpc": "2.0", "id": request_id, "result": result})
