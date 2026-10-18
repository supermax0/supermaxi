"""MCP transport and client abstractions for FINORA."""
from __future__ import annotations

import itertools
from typing import Protocol

import requests
from flask import Blueprint, jsonify, request, session
from modules.finora_ai.schema import ensure_finora_ai_schema

from modules.finora_ai.context import AuthenticationRequired, FinoraAuthContext
from modules.finora_ai.tools import execute_tool, list_tools


class MCPClient(Protocol):
    def list_tools(self) -> list[dict]: ...
    def call_tool(self, name: str, arguments: dict, **metadata) -> dict: ...


class InProcessMCPClient:
    """Uses the exact same policy/executor as the remote MCP endpoint."""

    def __init__(self, context: FinoraAuthContext):
        self.context = context

    def list_tools(self) -> list[dict]:
        return list_tools(self.context)

    def call_tool(self, name: str, arguments: dict, **metadata) -> dict:
        return execute_tool(self.context, name, arguments, **metadata)


class RemoteMCPClient:
    """Streamable-HTTP-ready JSON-RPC client for future separated deployment."""

    def __init__(self, endpoint: str, token: str, timeout: int = 30):
        self.endpoint = endpoint
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
        self.timeout = timeout
        self._ids = itertools.count(1)

    def _rpc(self, method: str, params: dict | None = None):
        response = requests.post(
            self.endpoint,
            headers=self.headers,
            json={"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"].get("message") or "MCP request failed")
        return payload.get("result")

    def list_tools(self) -> list[dict]:
        return (self._rpc("tools/list") or {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict, **_metadata) -> dict:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments}) or {}
        return result.get("structuredContent") or {}


mcp_bp = Blueprint("finora_mcp", __name__, url_prefix="/mcp")


@mcp_bp.before_request
def protect_mcp():
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return jsonify({"success": False, "error": {"code": "ORIGIN_DENIED"}}), 403
    if request.content_length and request.content_length > 65536:
        return jsonify({"success": False, "error": {"code": "REQUEST_TOO_LARGE"}}), 413
    if request.path.endswith("/health"):
        return None
    try:
        from modules.finora_ai.tokens import apply_bearer
        apply_bearer(request.headers.get("Authorization", ""))
        context = FinoraAuthContext.current()
    except AuthenticationRequired:
        return _rpc_error(None, -32001, "Authentication required", http=401)
    ensure_finora_ai_schema()
    if request.headers.get("Authorization"):
        session["role"] = context.role
        from utils.branch_context import init_branch_context
        init_branch_context()
    from modules.finora_ai.security import rate_limit as _rate_limit
    denied = _rate_limit(context, maximum=120)
    if denied:
        return denied
    from modules.finora_ai.settings import current_settings
    if not current_settings().get_flags().get("mcp_enabled", True):
        return jsonify({"success": False, "error": {"code": "FEATURE_DISABLED"}}), 404


@mcp_bp.after_request
def no_bearer_session_cookie(response):
    # Bearer authentication is request-local. Never turn a revocable key (or
    # expiring JWT) into a reusable browser login that bypasses its lifecycle.
    if request.headers.get("Authorization"):
        session.modified = False
    return response


def _rpc_error(request_id, code: int, message: str, *, http=200):
    return jsonify({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}), http


@mcp_bp.route("", methods=["GET", "POST"], strict_slashes=False)
def mcp_endpoint():
    if request.method == "GET":
        try:
            context = FinoraAuthContext.current()
        except AuthenticationRequired:
            return jsonify({"success": False, "error": {"code": "UNAUTHENTICATED"}}), 401
        return jsonify({"name": "finora-mcp", "protocol": "2025-03-26", "transport": "streamable-http", "tools": len(list_tools(context))})

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _rpc_error(None, -32600, "Invalid Request", http=400)
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        return _rpc_error(request_id, -32600, "Invalid Request", http=400)
    try:
        context = FinoraAuthContext.current()
    except AuthenticationRequired:
        return _rpc_error(request_id, -32001, "Authentication required", http=401)

    method, params = payload["method"], payload.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(request_id, -32602, "Invalid params", http=400)
    if method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "finora-mcp", "version": "1.0.0"},
        }
    elif method == "notifications/initialized":
        return ("", 204)
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": list_tools(context)}
    elif method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments") or {}
        normalized = execute_tool(context, name, arguments)
        result = {
            "content": [{"type": "text", "text": __import__("json").dumps(normalized, ensure_ascii=False, default=str)}],
            "structuredContent": normalized,
            "isError": not normalized.get("success", False),
        }
    else:
        return _rpc_error(request_id, -32601, "Method not found")
    return jsonify({"jsonrpc": "2.0", "id": request_id, "result": result})


@mcp_bp.get("/health")
def mcp_health():
    return jsonify({"status": "ok", "service": "finora-mcp", "write_tools": False})


@mcp_bp.get("/ready")
def mcp_ready():
    try:
        FinoraAuthContext.current()
    except AuthenticationRequired:
        return jsonify({"status": "not_ready", "reason": "authentication_required"}), 401
    return jsonify({"status": "ready", "service": "finora-mcp"})
