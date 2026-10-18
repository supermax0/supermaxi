"""Official SDK transport and JWT negative tests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from flask import Flask
from starlette.testclient import TestClient

from modules.finora_ai.context import AuthenticationRequired
from modules.finora_ai.sdk_server import create_mcp_asgi
from modules.finora_ai.tokens import apply_bearer


def test_expired_mcp_token_is_rejected():
    app = Flask(__name__)
    app.secret_key = "token-test-secret-that-is-long-enough"
    token = jwt.encode({"sub": "1", "tenant": "a", "iss": "finora", "aud": "finora-mcp",
                        "iat": datetime.now(timezone.utc)-timedelta(hours=1),
                        "exp": datetime.now(timezone.utc)-timedelta(minutes=1)}, app.secret_key, algorithm="HS256")
    with app.test_request_context("/mcp"), pytest.raises(AuthenticationRequired):
        apply_bearer("Bearer " + token)


def test_sdk_http_requires_authentication():
    app = Flask(__name__)
    app.secret_key = "sdk-test-secret-that-is-long-enough"
    with TestClient(create_mcp_asgi(app)) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 401


def test_sdk_initializes_with_official_transport():
    app = Flask(__name__)
    app.secret_key = "sdk-test-secret-that-is-long-enough"
    with patch("modules.finora_ai.sdk_server.FinoraAuthContext.current", return_value=SimpleNamespace(role="admin", tenant_slug="sdk-test", user_id=1)), \
         patch("modules.finora_ai.sdk_server.ensure_finora_ai_schema"), \
         patch("modules.finora_ai.sdk_server.require_active_tenant"), \
         patch("modules.finora_ai.sdk_server.current_settings", return_value=SimpleNamespace(get_flags=lambda: {"mcp_enabled": True})), \
         patch("utils.branch_context.init_branch_context"):
        with TestClient(create_mcp_asgi(app)) as client:
            response = client.post("/mcp", headers={"Accept": "application/json, text/event-stream"}, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}
            })
            assert response.status_code == 200, response.text
            assert response.json()["result"]["serverInfo"]["name"] == "finora-mcp"


def test_sdk_rejects_inactive_tenant_before_transport():
    app = Flask(__name__)
    app.secret_key = "sdk-test-secret-that-is-long-enough"
    with patch("modules.finora_ai.sdk_server.FinoraAuthContext.current", return_value=SimpleNamespace(tenant_slug="expired")), \
         patch("modules.finora_ai.sdk_server.require_active_tenant", side_effect=AuthenticationRequired("Inactive tenant")):
        with TestClient(create_mcp_asgi(app)) as client:
            response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            assert response.status_code == 401
