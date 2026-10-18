"""Two tenant databases with overlapping IDs must never cross reads."""
from unittest.mock import patch
import pytest

from flask import Flask, g, session
from sqlalchemy import create_engine

from extensions import db
import models
from models.delivery_agent import DeliveryAgent
from models.customer import Customer
from models.employee import Employee
from modules.finora_ai.context import AuthenticationRequired, FinoraAuthContext
from modules.finora_ai.tools import execute_tool
from modules.finora_ai.tokens import apply_bearer, issue_connection, issue_token
from modules.finora_ai.models import FinoraAISettings


def test_two_tenants_with_overlapping_ids_are_isolated():
    app = Flask(__name__)
    app.config.update(SECRET_KEY="tenant-test-long-secret", TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    db.init_app(app)
    engines = {name: create_engine("sqlite:///:memory:") for name in ("a", "b")}
    with app.app_context():
        for engine in engines.values():
            db.Model.metadata.create_all(engine)
    with patch("extensions_tenant.get_tenant_engine", side_effect=lambda slug: engines[slug]):
        for tenant in engines:
            with app.test_request_context("/mcp"):
                g.tenant = tenant
                session.update(tenant_slug=tenant, user_id=1)
                db.session.add(Employee(name="Admin", username="admin", password="pw", role="admin", is_active=True))
                db.session.add(Customer(name=f"Customer {tenant}", phone="0770"))
                db.session.commit()
        with app.test_request_context("/mcp"):
            g.tenant = "a"
            session.update(tenant_slug="a", user_id=1)
            context = FinoraAuthContext.current()
            result = execute_tool(context, "get_customer", {"customer_id": 1})
            assert result["data"]["name"] == "Customer a"
            override = execute_tool(context, "get_customer", {"customer_id": 1, "tenant_id": "b"})
            assert override["error"]["code"] == "VALIDATION_ERROR"
            db.session.remove()
            g.tenant = "b"
            assert execute_tool(context, "get_customer", {"customer_id": 1})["error"]["code"] == "TENANT_CONTEXT_MISMATCH"
        with app.test_request_context("/mcp"):
            g.tenant = "b"
            session.update(tenant_slug="b", user_id=1)
            context = FinoraAuthContext.current()
            assert execute_tool(context, "get_customer", {"customer_id": 1})["data"]["name"] == "Customer b"
    for engine in engines.values():
        engine.dispose()


@pytest.mark.parametrize("persistent", [True, False])
def test_bearer_discards_cookie_tenant_employee_identity_map(persistent):
    app = Flask(__name__)
    app.config.update(SECRET_KEY="tenant-test-long-secret", TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    db.init_app(app)
    engines = {name: create_engine("sqlite:///:memory:") for name in ("a", "b")}
    with app.app_context():
        for engine in engines.values():
            db.Model.metadata.create_all(engine)
    with patch("extensions_tenant.get_tenant_engine", side_effect=lambda slug: engines[slug]), patch("modules.finora_ai.tokens.require_active_tenant"):
        for tenant in engines:
            with app.test_request_context("/mcp"):
                g.tenant = tenant
                session.update(tenant_slug=tenant, user_id=1)
                db.session.add_all([Employee(name=tenant, username="admin", password="pw", role="admin", is_active=True), FinoraAISettings(provider="builtin")])
                db.session.commit()
        with app.test_request_context("/mcp"):
            g.tenant = "b"
            session.update(tenant_slug="b", user_id=1)
            context = FinoraAuthContext.current()
            token = issue_connection(context, "Test")[1] if persistent else issue_token(context)
            Employee.query.get(1).is_active = False
            db.session.commit()
        with app.test_request_context("/mcp"):
            g.tenant = "a"
            session.update(tenant_slug="a", user_id=1, role="admin", view_all_branches=True)
            cached_cookie_employee = Employee.query.get(1)
            assert cached_cookie_employee.is_active
            with pytest.raises(AuthenticationRequired):
                apply_bearer("Bearer " + token)
                FinoraAuthContext.current()
            assert session.get("role") is None
            assert session.get("view_all_branches") is None
    for engine in engines.values():
        engine.dispose()
