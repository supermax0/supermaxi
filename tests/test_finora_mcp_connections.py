"""Persistent credentials: real tenant verifier, lifecycle and both transports."""
import base64
from datetime import datetime
from unittest.mock import patch
import pytest
from flask import Flask, g
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient
from extensions import db
import models
from models.employee import Employee
from models.delivery_agent import DeliveryAgent
from modules.finora_ai import init_finora_ai
from modules.finora_ai.context import AuthenticationRequired
from modules.finora_ai.models import FinoraMCPConnection, FinoraAISettings
from modules.finora_ai.sdk_server import create_mcp_asgi


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config.update(SECRET_KEY="persistent-isolated-long-test-secret", TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    db.init_app(app)
    init_finora_ai(app)
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with app.app_context():
        db.Model.metadata.create_all(engine)
    with patch("extensions_tenant.get_tenant_engine", return_value=engine), patch("modules.finora_ai.tokens.require_active_tenant"), patch("modules.finora_ai.sdk_server.require_active_tenant"), patch("utils.branch_context.init_branch_context"):
        with app.app_context():
            g.tenant = "persistent-test"
            db.session.add_all([Employee(name="Admin", username="admin", password="pw", role="admin", is_active=True), FinoraAISettings(provider="builtin")])
            db.session.commit()
        from modules.finora_ai.security import _windows, _lock
        with _lock:
            _windows.pop(("persistent-test", 1), None)
        issuer = app.test_client()
        with issuer.session_transaction() as state:
            state.update(user_id=1, tenant_slug="persistent-test", role="admin")
        yield issuer
    engine.dispose()


def issue(client):
    response = client.post("/finora-ai/api/mcp/connections", json={"name": "AI Helper", "acknowledge_persistent_access": True})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    return response.get_json()


def discover(client, token):
    return client.post("/mcp", headers={"Authorization": "Bearer " + token}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})


def test_connection_is_long_lived_hash_only_and_revocable_without_login_cookie(client):
    key = issue(client)
    assert key["expires_in"] is None
    with client.application.app_context():
        g.tenant = "persistent-test"
        row = FinoraMCPConnection.query.one()
        assert len(row.secret_hash) == 64 and key["access_token"].split(".")[-1] not in row.secret_hash
        row.created_at = datetime(2000, 1, 1)
        db.session.commit()
    external = client.application.test_client()
    response = discover(external, key["access_token"])
    assert response.status_code == 200 and "Set-Cookie" not in response.headers
    assert external.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).status_code == 401
    listing = client.get("/finora-ai/api/mcp/connections").get_json()
    assert listing["connections"][0]["id"] == key["id"]
    assert "secret_hash" not in str(listing) and key["access_token"] not in str(listing)
    assert client.post(f"/finora-ai/api/mcp/connections/{key['id']}/revoke").status_code == 200
    assert client.post(f"/finora-ai/api/mcp/connections/{key['id']}/revoke").status_code == 200
    assert discover(external, key["access_token"]).status_code == 401


@pytest.mark.parametrize("payload", [{}, {"name": "App"}, {"name": "App", "acknowledge_persistent_access": "true"}, {"name": " " , "acknowledge_persistent_access": True}, {"name": "x"*81, "acknowledge_persistent_access": True}])
def test_creation_requires_valid_name_and_explicit_consent(client, payload):
    assert client.post("/finora-ai/api/mcp/connections", json=payload).status_code == 400


def test_issuance_requires_settings_permission_and_secure_configuration(client):
    with patch("modules.finora_ai.context.FinoraAuthContext.allows", side_effect=lambda *names: "manage_settings" not in names):
        assert client.post("/finora-ai/api/mcp/connections", json={"name": "App", "acknowledge_persistent_access": True}).status_code == 403
    client.application.secret_key = "super-secret-key-change-in-production"
    with client.session_transaction() as state:
        state.update(user_id=1, tenant_slug="persistent-test", role="admin")
    assert client.post("/finora-ai/api/mcp/connections", json={"name": "App", "acknowledge_persistent_access": True}).status_code == 503


@pytest.mark.parametrize("change", ["disabled_employee", "assistant_permission", "disabled_ai", "disabled_mcp", "expired_tenant"])
def test_backend_changes_stop_persistent_access(client, change):
    key = issue(client)
    external = client.application.test_client()
    if change == "disabled_employee":
        with client.application.app_context():
            g.tenant = "persistent-test"
            Employee.query.one().is_active = False
            db.session.commit()
    elif change == "assistant_permission":
        with patch("modules.finora_ai.context.FinoraAuthContext.allows", side_effect=lambda *names: "use_ai_assistant" not in names):
            assert discover(external, key["access_token"]).status_code == 401
        return
    elif change == "expired_tenant":
        with patch("modules.finora_ai.tokens.require_active_tenant", side_effect=AuthenticationRequired("expired")):
            assert discover(external, key["access_token"]).status_code == 401
        return
    else:
        client.put("/finora-ai/api/settings", json={"enabled": False} if change == "disabled_ai" else {"feature_flags": {"mcp_enabled": False}})
    assert discover(external, key["access_token"]).status_code == 401


def test_owner_can_revoke_when_ai_or_permissions_are_disabled(client):
    key = issue(client)
    client.put("/finora-ai/api/settings", json={"enabled": False, "feature_flags": {"mcp_enabled": False}})
    with patch("modules.finora_ai.context.FinoraAuthContext.allows", return_value=False):
        assert client.get("/finora-ai/api/mcp/connections").status_code == 200
        assert client.post(f"/finora-ai/api/mcp/connections/{key['id']}/revoke").status_code == 200


def test_other_employee_cannot_list_or_revoke_owner_key(client):
    key = issue(client)
    with client.application.app_context():
        g.tenant = "persistent-test"
        db.session.add(Employee(name="Other", username="other", password="pw", role="admin", is_active=True))
        db.session.commit()
    with client.session_transaction() as state:
        state["user_id"] = 2
    assert client.get("/finora-ai/api/mcp/connections").get_json()["connections"] == []
    assert client.post(f"/finora-ai/api/mcp/connections/{key['id']}/revoke").status_code == 404


def test_tampered_secret_or_tenant_locator_is_rejected(client):
    key = issue(client)["access_token"]
    external = client.application.test_client()
    parts = key.split(".")
    parts[-1] = ("A" if parts[-1][0] != "A" else "B") + parts[-1][1:]
    assert discover(external, ".".join(parts)).status_code == 401
    parts = key.split(".")
    parts[1] = base64.urlsafe_b64encode(b"another-tenant").decode().rstrip("=")
    assert discover(external, ".".join(parts)).status_code == 401


def test_active_key_limit_is_ten_and_revocation_frees_slot(client):
    first = None
    for _ in range(10):
        key = issue(client)
        first = first or key["id"]
    assert client.post("/finora-ai/api/mcp/connections", json={"name": "Eleventh", "acknowledge_persistent_access": True}).status_code == 409
    client.post(f"/finora-ai/api/mcp/connections/{first}/revoke")
    issue(client)


def test_sdk_accepts_persistent_key_and_rejects_it_after_revocation(client):
    key = issue(client)
    headers = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer " + key["access_token"]}
    with TestClient(create_mcp_asgi(client.application)) as sdk:
        response = sdk.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
        assert response.status_code == 200
        client.post(f"/finora-ai/api/mcp/connections/{key['id']}/revoke")
        assert sdk.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).status_code == 401
