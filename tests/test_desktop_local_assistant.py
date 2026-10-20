"""Local inference bridge: actual auth, ORM tools and audit, no model/network calls."""
from unittest.mock import patch

import pytest
from flask import Flask, g
from sqlalchemy import create_engine

from extensions import db
import models  # noqa: F401
from models.delivery_agent import DeliveryAgent  # noqa: F401
from models.customer import Customer
from models.employee import Employee
from modules.finora_ai import init_finora_ai
from modules.finora_ai.models import FinoraAISettings, FinoraAIToolCall


@pytest.fixture()
def local_ai():
    app = Flask(__name__)
    app.config.update(SECRET_KEY="local-assistant-test", TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    db.init_app(app)
    init_finora_ai(app)
    engine = create_engine("sqlite:///:memory:")
    with app.app_context():
        db.Model.metadata.create_all(engine)
    with patch("extensions_tenant.get_tenant_engine", return_value=engine):
        with app.app_context():
            g.tenant = "local-ai"
            db.session.add_all([Employee(name="Admin", username="admin", password="pw", role="admin", is_active=True),
                                Customer(name="عميل محلي", phone="07700000001"), FinoraAISettings(provider="builtin", enabled=True)])
            db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess.update(user_id=1, tenant_slug="local-ai", role="admin")
        yield app, client
    engine.dispose()


def test_local_catalog_is_read_only_and_authenticated(local_ai):
    app, client = local_ai
    assert app.test_client().get("/finora-ai/api/desktop/tools").status_code == 401
    response = client.get("/finora-ai/api/desktop/tools")
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["scope"]) == 64 and body["read_only"]
    assert "no-store" in response.headers["Cache-Control"]
    names = {tool["name"] for tool in body["tools"]}
    assert "search_customer" in names
    assert not any(word in name for name in names for word in ("delete", "create", "update", "post_", "execute_"))


def test_local_tools_reuse_orm_and_audit_without_mutating_customer(local_ai):
    app, client = local_ai
    scope = client.get("/finora-ai/api/desktop/tools").get_json()["scope"]
    response = client.post("/finora-ai/api/desktop/tool", json={"name": "search_customer", "arguments": {"query": "محلي"}, "scope": scope})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["success"]
    assert response.get_json()["data"]["items"][0]["name"] == "عميل محلي"
    with app.app_context():
        g.tenant = "local-ai"
        assert Customer.query.count() == 1
        audit = FinoraAIToolCall.query.one()
        assert audit.tool_name == "search_customer" and audit.provider == "desktop-local"


def test_local_tools_reject_identity_overrides_stale_scope_and_writes(local_ai):
    _, client = local_ai
    scope = client.get("/finora-ai/api/desktop/tools").get_json()["scope"]
    base = {"name": "get_customer", "arguments": {"customer_id": 1}, "scope": scope}
    assert client.post("/finora-ai/api/desktop/tool", json={**base, "scope": "stale"}).status_code == 409
    assert client.post("/finora-ai/api/desktop/tool", json={**base, "name": "create_customer"}).status_code == 403
    assert client.post("/finora-ai/api/desktop/tool", json={**base, "tenant_id": "other"}).status_code == 400
    result = client.post("/finora-ai/api/desktop/tool", json={**base, "arguments": {"customer_id": 1, "tenant_id": "other"}}).get_json()
    assert not result["success"] and result["error"]["code"] == "VALIDATION_ERROR"
    with client.session_transaction() as sess:
        sess["branch_id"] = 999
    assert client.post("/finora-ai/api/desktop/tool", json=base).status_code == 409


def test_local_bridge_respects_feature_and_origin(local_ai):
    app, client = local_ai
    assert client.get("/finora-ai/api/desktop/tools", headers={"Origin": "https://other.invalid"}).status_code == 403
    with app.app_context():
        g.tenant = "local-ai"
        FinoraAISettings.query.one().enabled = False
        db.session.commit()
    assert client.get("/finora-ai/api/desktop/tools").status_code == 404
