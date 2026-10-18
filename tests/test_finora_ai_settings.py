"""Advanced settings: persistence, secret protection and feature policy."""
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from flask import Flask, g, session
from sqlalchemy import create_engine
from extensions import db
import models
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from modules.finora_ai import init_finora_ai
from modules.finora_ai.models import FinoraAISettings
from modules.finora_ai.providers import ModelRouter, BuiltinReadOnlyProvider


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config.update(SECRET_KEY="settings-isolated-test-secret", TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    db.init_app(app)
    init_finora_ai(app)
    engine = create_engine("sqlite:///:memory:")
    with app.app_context():
        db.Model.metadata.create_all(engine)
    with patch("extensions_tenant.get_tenant_engine", return_value=engine):
        with app.app_context():
            g.tenant = "settings-test"
            db.session.add(Employee(name="Admin", username="admin", password="pw", role="admin", is_active=True))
            db.session.add(FinoraAISettings(provider="builtin"))
            db.session.commit()
        test_client = app.test_client()
        with test_client.session_transaction() as state:
            state.update(user_id=1, tenant_slug="settings-test", role="admin")
        yield test_client
    engine.dispose()


def test_settings_features_roundtrip_and_secret_removal(client):
    response = client.put("/finora-ai/api/settings", json={"provider": "builtin", "timeout_seconds": 90,
        "context_size": 4096, "api_key": "synthetic-not-a-real-key", "endpoint": "http://localhost:1234/v1",
        "feature_flags": {"mcp_enabled": False, "ai_accounting_tools_enabled": False, "ai_write_tools_enabled": True}})
    assert response.status_code == 200
    data = client.get("/finora-ai/api/settings").get_json()["settings"]
    assert data["has_api_key"] and "synthetic-not-a-real-key" not in str(data)
    assert data["timeout_seconds"] == 90 and data["context_size"] == 4096
    assert data["feature_flags"]["mcp_enabled"] is False
    assert data["feature_flags"]["ai_write_tools_enabled"] is False
    assert client.put("/finora-ai/api/settings", json={"clear_api_key": True, "endpoint": ""}).status_code == 200
    data = client.get("/finora-ai/api/settings").get_json()["settings"]
    assert not data["has_api_key"] and data["endpoint"] == ""


@pytest.mark.parametrize("payload", [
    {"feature_flags": {"mcp_enabled": "false"}}, {"enabled": "false"},
    {"endpoint": "http://user:password@localhost/v1"}, {"endpoint": "http://[invalid"},
    {"timeout_seconds": "invalid"},
    {"provider": "ollama", "feature_flags": {"ai_local_provider_enabled": False}},
])
def test_invalid_settings_leave_saved_values_unchanged(client, payload):
    assert client.put("/finora-ai/api/settings", json=payload).status_code == 400
    assert client.get("/finora-ai/api/settings").get_json()["settings"]["provider"] == "builtin"


def test_settings_require_backend_permission(client):
    with patch("modules.finora_ai.context.FinoraAuthContext.allows", return_value=False):
        assert client.get("/finora-ai/api/settings").status_code == 403
        assert client.put("/finora-ai/api/settings", json={"enabled": False}).status_code == 403


def test_router_enforces_local_flag_and_automatic_fallback():
    settings = SimpleNamespace(provider="local", get_flags=lambda: {"ai_local_provider_enabled": False})
    with pytest.raises(ValueError):
        ModelRouter(settings).select()
    assert isinstance(ModelRouter(SimpleNamespace(provider="automatic")).select(), BuiltinReadOnlyProvider)


def test_disabled_assistant_settings_remain_accessible_for_reenable(client):
    assert client.put("/finora-ai/api/settings", json={"enabled": False, "feature_flags": {"finora_ai_enabled": False}}).status_code == 200
    assert client.get("/finora-ai/api/settings").status_code == 200
    assert client.post("/finora-ai/api/chat/stream", json={"message": "test"}).status_code == 404
    assert client.put("/finora-ai/api/settings", json={"enabled": True, "feature_flags": {"finora_ai_enabled": True}}).status_code == 200


def _seed_agent_report(client):
    import json
    from models.invoice import Invoice
    from models.customer import Customer
    from models.shipping_report import ShippingReport
    with client.application.app_context():
        g.tenant = "settings-test"
        customer = Customer(name="زبون اختبار", phone="07700000000")
        agent = DeliveryAgent(name="وسام رحيم")
        db.session.add_all([customer, agent])
        db.session.flush()
        invoice = Invoice(customer_id=customer.id, customer_name=customer.name, delivery_agent_id=agent.id, total=100000, paid_amount=25000, status="تم الطلب", payment_status="جزئي", employee_name="إيمان")
        db.session.add(invoice)
        db.session.flush()
        report = ShippingReport(report_number=f"AGT-{agent.id}-20260916-0011", shipping_company_name="كشف المندوب: وسام رحيم", orders_count=1, total_amount=100000, orders_data=json.dumps([{"id": invoice.id, "total": 100000, "paid_amount": 0, "remaining": 100000}]), order_status_selections=json.dumps({str(invoice.id): "Delivered"}), is_executed=False)
        db.session.add(report)
        db.session.commit()
        return agent.id, report.report_number, report.orders_data


def test_order_then_unnamed_agent_then_name_reads_reports_without_guessing(client):
    import json
    from modules.finora_ai.models import FinoraAIConversation, FinoraAIToolCall
    from models.shipping_report import ShippingReport
    agent_id, number, original_snapshot = _seed_agent_report(client)
    first = client.post("/finora-ai/api/chat/stream", json={"message": "شنو آخر طلب؟"}).get_data(as_text=True)
    assert "إيمان" in first
    with client.application.app_context():
        g.tenant = "settings-test"
        conversation_id = FinoraAIConversation.query.one().id
    question = client.post("/finora-ai/api/chat/stream", json={"message": "شكد باقي على المندوب", "conversation_id": conversation_id}).get_data(as_text=True)
    assert "أي مندوب" in question and '"tool": "get_order"' not in question
    answer = client.post("/finora-ai/api/chat/stream", json={"message": "وسام", "conversation_id": conversation_id}).get_data(as_text=True)
    assert number in answer and "75,000" in answer and "ليس رصيد ذمة" in answer
    with client.application.app_context():
        g.tenant = "settings-test"
        context = FinoraAIConversation.query.one().get_context()
        assert context["active_entity"] == "agent" and context["agent_id"] == agent_id
        assert [row.tool_name for row in FinoraAIToolCall.query.order_by(FinoraAIToolCall.id).all()] == ["get_latest_order", "search_delivery_agents", "get_delivery_agent_reports"]
        assert ShippingReport.query.one().orders_data == original_snapshot
        assert ShippingReport.query.one().total_amount == 100000


def test_agent_tools_use_existing_permission_for_discovery_and_execution(client):
    _seed_agent_report(client)
    with patch("modules.finora_ai.context.FinoraAuthContext.allows", side_effect=lambda *names: "view_agents" not in names):
        listing = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).get_json()
        assert "get_delivery_agent_reports" not in {row["name"] for row in listing["result"]["tools"]}
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_delivery_agent_reports", "arguments": {"agent_id": 1}}}).get_json()
        assert response["result"]["structuredContent"]["error"]["code"] == "PERMISSION_DENIED"


def test_runtime_mode_is_honest_and_excludes_secrets(client):
    limited = client.get("/finora-ai/api/runtime")
    assert limited.headers["Cache-Control"] == "no-store"
    assert limited.get_json()["language_model"] is False
    assert "محدود" in limited.get_json()["notice"]
    with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
        client.put("/finora-ai/api/settings", json={"provider": "openai"})
        info = client.get("/finora-ai/api/runtime").get_json()
        assert info["language_model"] is True and info["ready"] is False
        assert "api_key" not in info
        with patch("modules.finora_ai.providers.requests.post") as external_request:
            reply = client.post("/finora-ai/api/chat/stream", json={"message": "شكد باقي على المندوب؟"}).get_data(as_text=True)
            assert "مفتاح OpenAI غير مضبوط" in reply
            external_request.assert_not_called()


def test_report_snapshots_cannot_leak_hidden_branch_invoice_amounts(client):
    from models.branch import Branch
    from models.invoice import Invoice
    from models.shipping_report import ShippingReport
    from utils.branch_orm_scope import install_branch_orm_scope
    _seed_agent_report(client)
    install_branch_orm_scope()
    with client.application.app_context():
        g.tenant = "settings-test"
        db.session.add_all([Branch(id=1, code="one", name="One", is_default=False), Branch(id=2, code="two", name="Two", is_default=False)])
        DeliveryAgent.query.one().branch_id = 1
        ShippingReport.query.one().branch_id = 1
        Invoice.query.one().branch_id = 2
        db.session.commit()
    @client.application.before_request
    def isolate_branch():
        g.branch_scope_ready = True
        g.independent_branches_enabled = True
        g.branch = SimpleNamespace(id=1, is_default=False)
        g.view_all_branches = False
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_delivery_agent_reports", "arguments": {"agent_id": 1}}}).get_json()
    data = response["result"]["structuredContent"]
    assert data["success"] and data["data"]["reports"] == []


@pytest.mark.parametrize("tool,query,key", [("search_customer", "احمد", "customer_id"), ("search_supplier", "ابراهيم", "supplier_id"), ("search_delivery_agents", "اياد", "agent_id")])
def test_arabic_spelling_variations_are_searchable_without_guessing(client, tool, query, key):
    from models.customer import Customer
    from models.supplier import Supplier
    with client.application.app_context():
        g.tenant = "settings-test"
        db.session.add_all([Customer(name="أَحْمَد", phone="0770"), Supplier(name="إبراهيم", phone="0771"), DeliveryAgent(name="إياد")])
        db.session.commit()
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": {"query": query}}}).get_json()["result"]["structuredContent"]
    assert response["success"] and len(response["data"]["items"]) == 1
    assert response["data"]["items"][0][key] == 1


def test_context_budget_trims_old_history_but_retains_system_and_latest_input(client):
    from modules.finora_ai.models import FinoraAIConversation, FinoraAIMessage
    from modules.finora_ai.context import FinoraAuthContext
    from modules.finora_ai.orchestrator import FinoraAIOrchestrator
    with client.application.app_context():
        g.tenant = "settings-test"
        settings = FinoraAISettings.query.one()
        settings.context_size = 512
        conversation = FinoraAIConversation(tenant_slug="settings-test", user_id=1)
        conversation.set_context({})
        db.session.add(conversation)
        db.session.flush()
        for index in range(5):
            db.session.add(FinoraAIMessage(conversation_id=conversation.id, role="user" if index % 2 == 0 else "assistant", content=str(index)*1000))
        db.session.commit()
        orchestrator = FinoraAIOrchestrator(FinoraAuthContext("settings-test", 1, "admin", frozenset()))
        history = orchestrator._history(conversation)
        assert history[0]["role"] == "system"
        assert len(history) == 2 and history[-1]["content"] == "4"*1000


def test_connection_info_and_scoped_token_are_available_without_caching(client):
    import jwt
    info = client.get("/finora-ai/api/settings").get_json()["settings"]["mcp_connection"]
    assert info["url"] == "http://localhost/mcp" and info["transport"] == "Streamable HTTP"
    response = client.post("/finora-ai/api/mcp/token")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    data = response.get_json()
    assert data["expires_in"] == 900
    claims = jwt.decode(data["access_token"], client.application.secret_key, algorithms=["HS256"], audience="finora-mcp", issuer="finora")
    assert claims["sub"] == "1" and claims["tenant"] == "settings-test"
    assert claims["exp"] - claims["iat"] == 900


def test_token_generation_requires_mcp_and_strong_signing_configuration(client):
    from modules.finora_ai.context import AuthenticationRequired
    with patch("modules.finora_ai.tokens.issue_token", side_effect=AuthenticationRequired("Weak signing key")):
        response = client.post("/finora-ai/api/mcp/token")
        assert response.status_code == 503
        assert response.get_json()["error"]["code"] == "SIGNING_NOT_CONFIGURED"
    client.put("/finora-ai/api/settings", json={"feature_flags": {"mcp_enabled": False}})
    assert client.post("/finora-ai/api/mcp/token").status_code == 409


def test_connection_template_contains_easy_copy_controls():
    from pathlib import Path
    from jinja2 import Environment
    template = Path("templates/finora_ai_settings.html").read_text(encoding="utf-8")
    Environment().parse(template)
    assert 'id="aiCopyMcpUrl"' in template and 'id="aiGenerateMcpToken"' in template
    assert 'id="aiCopyMcpToken"' in template


def test_latest_order_followup_remembers_order_and_refetches_employee(client):
    from models.customer import Customer
    from models.invoice import Invoice
    from modules.finora_ai.models import FinoraAIConversation, FinoraAIToolCall
    with client.application.app_context():
        g.tenant = "settings-test"
        customer = Customer(name="عميل تجريبي", phone="0770")
        db.session.add(customer)
        db.session.flush()
        db.session.add(Invoice(customer_id=customer.id, customer_name=customer.name, total=300000,
                              paid_amount=0, status="تم الطلب", payment_status="غير مسدد", employee_name="إيمان اختبار"))
        db.session.commit()
    first = client.post("/finora-ai/api/chat/stream", json={"message": "شنو آخر طلب؟"})
    assert "طلب #1" in first.get_data(as_text=True)
    with client.application.app_context():
        g.tenant = "settings-test"
        conversation = FinoraAIConversation.query.one()
        conversation_id = conversation.id
        assert conversation.get_context()["order_id"] == 1
    second = client.post("/finora-ai/api/chat/stream", json={"message": "منو الموظف الي نزله؟", "conversation_id": conversation_id})
    assert "إيمان اختبار" in second.get_data(as_text=True)
    with client.application.app_context():
        g.tenant = "settings-test"
        assert [row.tool_name for row in FinoraAIToolCall.query.all()] == ["get_latest_order", "get_order"]


def test_profit_tool_is_hidden_without_profit_permission(client):
    from modules.finora_ai.tools import list_tools
    from modules.finora_ai.context import FinoraAuthContext
    with client.application.test_request_context("/mcp"):
        g.tenant = "settings-test"
        session.update(user_id=1, tenant_slug="settings-test")
        context = FinoraAuthContext("settings-test", 1, "employee", frozenset())
        with patch.object(FinoraAuthContext, "allows", side_effect=lambda *names: "view_reports" in names):
            assert "get_top_products" not in {item["name"] for item in list_tools(context)}
