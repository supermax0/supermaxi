"""Employee inbox isolation by registered channel/page."""
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_ai_sales_employee_scope_{os.getpid()}"


def test_employee_only_sees_conversations_from_registered_pages():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.employee import Employee
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.routes import (
        _can_view,
        api_conversations,
        api_message_media,
        api_messages,
        api_overview,
    )
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_ai_sales_schema()
        first = Employee(name="First Page Employee", username="page-first", password="test", role="cashier", is_active=True)
        second = Employee(name="Second Page Employee", username="page-second", password="test", role="cashier", is_active=True)
        db.session.add_all([first, second])
        db.session.flush()
        first_page = AISalesChannelAccount(
            name="First Page",
            channel_type="messenger",
            external_account_id="page-first",
            reply_mode="ai",
            default_employee_id=first.id,
            connection_status="connected",
            is_active=True,
        )
        second_page = AISalesChannelAccount(
            name="Second Page",
            channel_type="messenger",
            external_account_id="page-second",
            reply_mode="inbox",
            default_employee_id=second.id,
            connection_status="connected",
            is_active=True,
        )
        db.session.add_all([first_page, second_page])
        db.session.flush()
        first_conversation = get_or_create_conversation(
            first_page,
            external_contact_id="customer-first",
            phone="",
            contact_name="First Customer",
        )
        second_conversation = get_or_create_conversation(
            second_page,
            external_contact_id="customer-second",
            phone="",
            contact_name="Second Customer",
        )
        first_message = AISalesMessage(
            conversation_id=first_conversation.id,
            channel_account_id=first_page.id,
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="first message",
            status="received",
        )
        second_message = AISalesMessage(
            conversation_id=second_conversation.id,
            channel_account_id=second_page.id,
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="second message",
            status="received",
        )
        db.session.add_all([first_message, second_message])
        db.session.commit()
        first_id = first.id
        first_conversation_id = first_conversation.id
        second_conversation_id = second_conversation.id
        second_message_id = second_message.id

        with app.test_request_context("/ai-sales/api/conversations"):
            g.tenant = TENANT
            session["user_id"] = first_id
            session["role"] = "cashier"
            assert _can_view() is True
            response = api_conversations()
            payload = response.get_json()
            assert [row["id"] for row in payload["conversations"]] == [first_conversation_id]

        with app.test_request_context("/ai-sales/api/overview"):
            g.tenant = TENANT
            session["user_id"] = first_id
            session["role"] = "cashier"
            payload = api_overview().get_json()["overview"]
            assert payload["open_conversations"] == 1
            assert payload["messages_today"] == 1

        with app.test_request_context(f"/ai-sales/api/conversations/{second_conversation_id}/messages"):
            g.tenant = TENANT
            session["user_id"] = first_id
            session["role"] = "cashier"
            response = app.make_response(api_messages(second_conversation_id))
            assert response.status_code == 403

        with app.test_request_context(f"/ai-sales/api/messages/{second_message_id}/media"):
            g.tenant = TENANT
            session["user_id"] = first_id
            session["role"] = "cashier"
            response = app.make_response(api_message_media(second_message_id))
            assert response.status_code == 403
