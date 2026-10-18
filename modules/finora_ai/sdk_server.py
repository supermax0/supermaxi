"""Official MCP SDK Streamable HTTP service using FINORA services and auth.

Run through an ASGI process using create_mcp_asgi(flask_app). Deployment may
route /mcp to this service; the existing Flask JSON-RPC endpoint is additive.
"""
from contextlib import asynccontextmanager
import json

from flask import session
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp import types
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from werkzeug.test import EnvironBuilder

from modules.finora_ai.context import AuthenticationRequired, FinoraAuthContext
from modules.finora_ai.schema import ensure_finora_ai_schema
from modules.finora_ai.settings import current_settings
from modules.finora_ai.tokens import apply_bearer, require_active_tenant
from modules.finora_ai.tools import list_tools, execute_tool


def create_mcp_asgi(flask_app):
    server = Server("finora-mcp", version="1.0.0")

    @server.list_tools()
    async def discover():
        return [types.Tool(**tool) for tool in list_tools(FinoraAuthContext.current())]

    @server.call_tool(validate_input=False)
    async def call(name: str, arguments: dict):
        result = execute_tool(FinoraAuthContext.current(), name, arguments)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result, isError=not result.get("success", False),
        )

    hosts = flask_app.config.get("FINORA_MCP_ALLOWED_HOSTS", ["localhost:*", "127.0.0.1:*", "testserver"])
    origins = flask_app.config.get("FINORA_MCP_ALLOWED_ORIGINS", ["http://localhost:*", "http://127.0.0.1:*"])
    manager = StreamableHTTPSessionManager(
        server, json_response=True, stateless=True, max_request_body_size=65536,
        security_settings=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins),
    )

    class AuthenticatedTransport:
        async def __call__(self, scope, receive, send):
            headers = {k.decode("latin1"): v.decode("latin1") for k, v in scope.get("headers", [])}
            builder = EnvironBuilder(path="/mcp", method=scope["method"], headers=headers)
            with flask_app.request_context(builder.get_environ()):
                try:
                    apply_bearer(headers.get("authorization", ""))
                    context = FinoraAuthContext.current()
                    require_active_tenant(context.tenant_slug)
                    # Reload the role from the authenticated employee, never token claims.
                    session["role"] = context.role
                    from modules.finora_ai.security import rate_limit as _rate_limit
                    if _rate_limit(context, maximum=120) is not None:
                        await JSONResponse({"error": "RATE_LIMITED"}, status_code=429)(scope, receive, send)
                        return
                    ensure_finora_ai_schema()
                    if not current_settings().get_flags().get("mcp_enabled", True):
                        await JSONResponse({"error": "FEATURE_DISABLED"}, status_code=404)(scope, receive, send)
                        return
                    from utils.branch_context import init_branch_context
                    init_branch_context()
                    await manager.handle_request(scope, receive, send)
                except AuthenticationRequired:
                    await JSONResponse({"error": "UNAUTHENTICATED"}, status_code=401)(scope, receive, send)

    @asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    async def health(_request):
        return JSONResponse({"status": "ok", "service": "finora-mcp", "sdk": True, "read_only": True})

    return Starlette(routes=[Route("/health", health), Mount("/", app=AuthenticatedTransport())], lifespan=lifespan)
