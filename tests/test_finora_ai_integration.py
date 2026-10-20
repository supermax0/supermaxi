"""Isolated real ORM conversation acceptance test (no production data)."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
import os
import pytest
from jsonschema import Draft202012Validator
from modules.finora_ai.services import TOOL_OUTPUT_SCHEMA

from flask import Flask
from sqlalchemy import create_engine

from extensions import db
import models
from models.delivery_agent import DeliveryAgent
from models.customer import Customer
from models.employee import Employee
from models.invoice import Invoice
from models.product import Product
from models.supplier import Supplier
from models.shipping_report import ShippingReport
from modules.finora_ai import init_finora_ai
from modules.finora_ai.models import FinoraAIConversation, FinoraAIToolCall, FinoraAISettings


def test_search_balance_sales_keeps_context_and_uses_real_orm():
    app = Flask(__name__)
    app.config.update(SECRET_KEY="isolated-e2e", TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    db.init_app(app)
    init_finora_ai(app)
    engine = create_engine("sqlite:///:memory:")
    with app.app_context():
        db.Model.metadata.create_all(engine)
    with patch("extensions_tenant.get_tenant_engine", return_value=engine):
        from flask import g
        with app.app_context():
            g.tenant = "ai-e2e"
            admin = Employee(name="Test Admin", username="admin", password="pw", role="admin", is_active=True)
            customer = Customer(name="أحمد اختبار", phone="07700000000")
            db.session.add_all([admin, customer])
            db.session.flush()
            db.session.add(Invoice(customer_id=customer.id, customer_name=customer.name, total=500000,
                                   paid_amount=200000, payment_status="جزئي", status="تم الطلب", created_at=datetime.utcnow()))
            db.session.add(FinoraAISettings(provider="builtin", enabled=True))
            db.session.add(Product(name="منتج اختبار", buy_price=100, sale_price=200, quantity=3, active=True))
            db.session.add(Supplier(name="مورد اختبار", phone="0771", total_debt=200000, total_paid=100000))
            db.session.add(DeliveryAgent(name="وسام اختبار"))
            db.session.add(ShippingReport(report_number="AGT-1-20260916-0011", shipping_company_name="كشف المندوب: وسام اختبار", orders_data="[]", orders_count=0, total_amount=0, is_executed=False))
            db.session.commit()
            user_id = admin.id
        client = app.test_client()
        with client.session_transaction() as sess:
            sess.update(user_id=user_id, tenant_slug="ai-e2e", role="admin")
        response = client.post("/finora-ai/api/chat/stream", json={"message": "دورلي زبون اسمه أحمد"})
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert "أحمد اختبار" in body
        with app.app_context():
            g.tenant = "ai-e2e"
            conversation = FinoraAIConversation.query.one()
            conversation_id = conversation.id
            assert conversation.get_context()["customer_id"] == 1
        second = client.post("/finora-ai/api/chat/stream", json={"message": "شكد عليه؟", "conversation_id": conversation_id})
        assert "300,000" in second.get_data(as_text=True)
        third = client.post("/finora-ai/api/chat/stream", json={"message": "وشكد مبيعات اليوم؟", "conversation_id": conversation_id})
        assert "500,000" in third.get_data(as_text=True)
        with app.app_context():
            g.tenant = "ai-e2e"
            assert [row.tool_name for row in FinoraAIToolCall.query.order_by(FinoraAIToolCall.id).all()] == [
                "search_customer", "get_customer_balance", "get_daily_sales"
            ]
            assert FinoraAIConversation.query.count() == 1
            assert len(FinoraAIConversation.query.one().messages) == 6
        tool_args = {
            "search_customer": {"query": "أحمد"}, "get_customer": {"customer_id": 1},
            "get_customer_balance": {"customer_id": 1}, "get_customer_statement": {"customer_id": 1},
            "search_orders": {"query": "أحمد"}, "get_order": {"invoice_id": 1},
            "search_products": {"query": "منتج"}, "get_product": {"product_id": 1},
            "get_product_stock": {"product_id": 1}, "get_low_stock": {},
            "search_supplier": {"query": "مورد"}, "get_supplier_balance": {"supplier_id": 1},
            "get_supplier_statement": {"supplier_id": 1}, "get_daily_sales": {},
            "get_sales_summary": {}, "get_cash_balance": {}, "get_receivables_summary": {}, "get_payables_summary": {},
            "get_latest_order": {}, "get_expenses": {}, "get_top_products": {}, "get_shipping_dues": {},
            "search_delivery_agents": {"query": "وسام"}, "get_delivery_agent_reports": {"agent_id": 1},
            "get_agent_report": {"report_number": "AGT-1-20260916-0011"}, "get_pending_agent_reports": {}
        }
        for name, args in tool_args.items():
            response = client.post("/mcp", json={"jsonrpc": "2.0", "id": name, "method": "tools/call",
                                                 "params": {"name": name, "arguments": args}})
            assert response.status_code == 200, (name, response.get_data(as_text=True))
            result = response.get_json()["result"]["structuredContent"]
            assert result["success"], (name, result)
            Draft202012Validator(TOOL_OUTPUT_SCHEMA).validate(result)
            assert result["meta"]["read_only"] is True
        runtime = client.get("/finora-ai/api/desktop/runtime")
        assert runtime.status_code == 200 and runtime.get_json()["read_only"] is True
        native = client.post("/finora-ai/api/desktop/chat", json={"message": "مبيعات اليوم"})
        assert native.status_code == 200, native.get_data(as_text=True)
        assert "500,000" in native.get_json()["message"]
        assert client.post("/finora-ai/api/desktop/chat", json={"message": "مبيعات اليوم", "tenant_slug": "other"}).status_code == 400
        assert client.post("/finora-ai/api/desktop/chat", json={"message": 42}).status_code == 400
        assert client.post("/finora-ai/api/desktop/chat", json={"message": " "}).status_code == 400
        with app.app_context():
            g.tenant = "ai-e2e"
            assert FinoraAIConversation.query.count() == 2
    engine.dispose()


@pytest.mark.skipif(os.environ.get("FINORA_AI_RUN_LIVE_TEST") != "1", reason="Explicit live-provider opt-in required")
def test_openai_search_balance_sales_on_synthetic_data():
    from dotenv import load_dotenv
    load_dotenv()
    settings = SimpleNamespace(provider="openai", encrypted_api_key=None, model="gpt-4.1-mini",
                               endpoint="https://api.openai.com/v1", timeout_seconds=90)
    with patch("modules.finora_ai.orchestrator.current_settings", return_value=settings):
        test_search_balance_sales_keeps_context_and_uses_real_orm()
