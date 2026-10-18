"""Load the full FINORA app against temporary databases, never production DBs."""
import os
import logging
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

from flask import Flask, g

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def main():
    with tempfile.TemporaryDirectory(prefix="finora-ai-runtime-", ignore_cleanup_errors=True) as sandbox:
        os.environ.update(DATABASE_URL="sqlite:///" + str(Path(sandbox) / "core.db"),
                          SERVER_SOFTWARE="gunicorn/isolated-verification", RUN_STARTUP_TENANT_MIGRATIONS="0",
                          LEADS_DISCOVERY_SCHEDULER_ENABLED="0", ORDER_INSTALLMENT_SCHEDULER_ENABLED="0",
                          FINORA_LOCAL_WORKSPACE="0")
        original = Flask.__init__
        def isolated_init(self, *args, **kwargs):
            original(self, *args, **kwargs)
            if args and args[0] == "app":
                self.root_path = sandbox
                self.template_folder = str(PROJECT / "templates")
                self.static_folder = str(PROJECT / "static")
                self.instance_path = str(Path(sandbox) / "instance")
        with patch.object(Flask, "__init__", isolated_init), patch("apscheduler.schedulers.background.BackgroundScheduler.start"):
            from app import app
        app.config["TESTING"] = True
        from extensions import db
        from extensions_tenant import get_tenant_engine
        from models.employee import Employee
        from models.customer import Customer
        from modules.finora_ai.models import FinoraAISettings
        from models.core.tenant import Tenant as CoreTenant
        from models.tenant import Tenant
        from models.invoice import Invoice
        from models.delivery_agent import DeliveryAgent
        from models.shipping_report import ShippingReport
        with app.app_context():
            db.session.add(CoreTenant(name="AI Runtime", slug="ai-runtime", db_path=str(Path(sandbox) / "tenants" / "ai-runtime.db"),
                                      is_active=True, subscription_end_date=datetime.utcnow()+timedelta(days=30)))
            db.session.commit()
            engine = get_tenant_engine("ai-runtime")
            db.Model.metadata.create_all(engine)
            g.tenant = "ai-runtime"
            db.session.add(Tenant(name="AI Runtime", plan_key="enterprise", is_active=True))
            db.session.flush()
            employee = Employee(name="Runtime Test", username="runtime", password=generate_password_hash("test-only"), role="admin", is_active=True, tenant_id=1)
            customer = Customer(name="أحمد اختبار", phone="07700000000")
            agent = DeliveryAgent(name="وسام اختبار")
            db.session.add_all([employee, customer, agent, FinoraAISettings(provider="builtin")])
            db.session.flush()
            invoice = Invoice(customer_id=customer.id, customer_name=customer.name, delivery_agent_id=agent.id, employee_name=employee.name, total=500000, paid_amount=200000,
                              status="تم الطلب", payment_status="جزئي", created_at=datetime.utcnow())
            db.session.add(invoice)
            db.session.flush()
            db.session.add(ShippingReport(report_number=f"AGT-{agent.id}-20260916-0011", shipping_company_name="كشف المندوب: وسام اختبار", orders_data=json.dumps([{"id": invoice.id, "total": 500000, "remaining": 300000, "paid_amount": 200000}]), order_status_selections=json.dumps({str(invoice.id): "Delivered"}), orders_count=1, total_amount=300000, is_executed=False))
            db.session.commit()
            user_id = employee.id
        assert "finora_ai" in app.blueprints
        assert "finora_mcp" in app.blueprints
        client = app.test_client()
        assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
        login = client.post("/login/ai-runtime", data={"username": "runtime", "password": "test-only"})
        assert login.status_code == 302, "Existing FINORA login failed"
        with client.session_transaction() as session:
            assert session.get("user_id") == user_id
            assert session.get("tenant_slug") == "ai-runtime"
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 200, response.status_code
        from modules.finora_ai.tools import TOOLS
        assert len(response.get_json()["result"]["tools"]) == len(TOOLS)
        settings_response = client.get("/finora-ai/settings")
        assert settings_response.status_code == 200, settings_response.status_code
        assert "finoraAiFab" in settings_response.get_data(as_text=True)
        assert "finoraAiSettingsForm" in settings_response.get_data(as_text=True)
        connection = client.post("/finora-ai/api/mcp/connections", json={"name": "Isolated runtime test", "acknowledge_persistent_access": True})
        assert connection.status_code == 200, connection.status_code
        credential = connection.get_json()
        assert credential["expires_in"] is None
        external = app.test_client()
        authorization = {"Authorization": "Bearer " + credential["access_token"]}
        discovery = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        connected = external.post("/mcp", headers=authorization, json=discovery)
        assert connected.status_code == 200, connected.status_code
        assert "Set-Cookie" not in connected.headers
        assert external.post("/mcp", json=discovery).status_code == 401
        assert client.post(f"/finora-ai/api/mcp/connections/{credential['id']}/revoke").status_code == 200
        assert external.post("/mcp", headers=authorization, json=discovery).status_code == 401
        first = client.post("/finora-ai/api/chat/stream", json={"message": "دورلي زبون اسمه أحمد"})
        assert "أحمد اختبار" in first.get_data(as_text=True)
        from modules.finora_ai.models import FinoraAIConversation
        with app.app_context():
            g.tenant = "ai-runtime"
            conversation_id = FinoraAIConversation.query.one().id
        second = client.post("/finora-ai/api/chat/stream", json={"message": "شكد عليه؟", "conversation_id": conversation_id})
        assert "300,000" in second.get_data(as_text=True)
        latest = client.post("/finora-ai/api/chat/stream", json={"message": "شنو آخر طلب؟", "conversation_id": conversation_id})
        assert "Runtime Test" in latest.get_data(as_text=True)
        unresolved = client.post("/finora-ai/api/chat/stream", json={"message": "شكد باقي على المندوب", "conversation_id": conversation_id})
        assert "أي مندوب" in unresolved.get_data(as_text=True)
        agent_answer = client.post("/finora-ai/api/chat/stream", json={"message": "وسام", "conversation_id": conversation_id})
        assert "AGT-1-20260916-0011" in agent_answer.get_data(as_text=True)
        assert "300,000" in agent_answer.get_data(as_text=True)
        print("Full FINORA app load: SUCCESS")
        print(f"Authenticated MCP discovery: {len(TOOLS)} read-only tools")
        print("Unauthenticated MCP: rejected (401)")
        print("Existing FINORA login: SUCCESS")
        print("Settings + floating chat template: SUCCESS")
        print("Persistent MCP key: issue, fresh-client authentication, no login cookie, revoke: SUCCESS")
        print("Full-app search and follow-up customer balance: SUCCESS")
        print("Full-app order -> unnamed agent clarification -> named agent report: SUCCESS")
        if "--serve-browser" in sys.argv:
            logging.getLogger("werkzeug").setLevel(logging.ERROR)
            print("Isolated browser verification: http://127.0.0.1:5089/login/ai-runtime", flush=True)
            app.run(host="127.0.0.1", port=5089, debug=False, use_reloader=False)
        engine.dispose()
        with app.app_context():
            db.session.remove()
            for core_engine in db.engines.values():
                core_engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
