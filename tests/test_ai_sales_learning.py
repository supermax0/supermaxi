"""Tests for tenant-local learning from sanitized employee replies."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_ai_sales_learning_{os.getpid()}"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_employee_history_is_sanitized_ranked_and_retrievable():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from modules.ai_sales.learning import refresh_employee_reply_examples, retrieve_reply_examples
    from modules.ai_sales.models import (
        AISalesChannelAccount,
        AISalesConversation,
        AISalesMessage,
        AISalesReplyExample,
    )
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_ai_sales_schema()
        channel = AISalesChannelAccount(name="Learning Test", channel_type="messenger", is_active=False)
        db.session.add(channel)
        db.session.flush()
        conversation = AISalesConversation(
            channel_account_id=channel.id,
            external_contact_id="customer-learning-1",
            contact_name="سجاد أحمد",
        )
        db.session.add(conversation)
        db.session.flush()
        now = datetime.utcnow()
        db.session.add_all([
            AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                direction="inbound",
                sender_type="customer",
                message_type="text",
                text_content="سجاد أحمد يسأل: شاشة 43 بكم؟ اتصلوا على 07734049148",
                status="received",
                created_at=now,
            ),
            AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                direction="outbound",
                sender_type="employee",
                message_type="text",
                text_content="هلا سجاد أحمد، سعرها 219,000 د.ع. تريد أعرف استخدامك حتى أحددلك إذا قياس 43 مناسب؟",
                status="sent",
                created_at=now + timedelta(seconds=1),
            ),
            AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                direction="inbound",
                sender_type="customer",
                message_type="text",
                text_content="أكو أرخص؟",
                status="received",
                created_at=now + timedelta(seconds=2),
            ),
            AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                direction="outbound",
                sender_type="ai",
                message_type="text",
                text_content="أبحث لك عن بديل.",
                status="sent",
                created_at=now + timedelta(seconds=3),
            ),
            AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                direction="outbound",
                sender_type="employee",
                message_type="text",
                text_content="هذا رد بعد الذكاء ولا يجب تعلمه.",
                status="sent",
                created_at=now + timedelta(seconds=4),
            ),
        ])
        db.session.commit()

        stats = refresh_employee_reply_examples(max_examples=300, minimum_quality=50)
        learned = AISalesReplyExample.query.all()
        assert stats["customer_messages"] == 2
        assert len(learned) == 1
        assert learned[0].intent == "price"
        assert "سجاد أحمد" not in learned[0].customer_example
        assert "07734049148" not in learned[0].customer_example
        assert "219,000" not in learned[0].employee_example
        assert "[اسم الزبون]" in learned[0].employee_example
        assert "[السعر الحالي]" in learned[0].employee_example

        matches = retrieve_reply_examples("شاشة 43 شكد سعرها؟", limit=3)
        assert len(matches) == 1
        assert matches[0]["intent"] == "price"

