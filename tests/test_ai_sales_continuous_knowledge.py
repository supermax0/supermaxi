"""Continuous employee learning and multi-source knowledge tests."""
import os
import sys
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_ai_sales_continuous_{os.getpid()}"


def test_future_employee_reply_and_excel_knowledge_are_retrievable():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from modules.ai_sales.knowledge import (
        build_learning_template,
        import_learning_workbook,
        retrieve_business_knowledge,
    )
    from modules.ai_sales.learning import capture_employee_reply_example
    from modules.ai_sales.models import (
        AISalesAgentProfile,
        AISalesChannelAccount,
        AISalesConversation,
        AISalesKnowledgeEntry,
        AISalesMessage,
        AISalesProductProfile,
        AISalesReplyExample,
    )
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_ai_sales_schema()
        profile = AISalesAgentProfile.query.first()
        profile.continuous_learning_enabled = True
        profile.learn_from_employee_replies = True
        profile.learning_min_quality = 60
        product = Product(
            name="شاشة اختبار 50",
            sku="TV-TEST-50",
            barcode="TEST50001",
            buy_price=200000,
            sale_price=270000,
            quantity=5,
        )
        channel = AISalesChannelAccount(name="Learning", channel_type="messenger", is_active=False)
        db.session.add_all([product, channel])
        db.session.flush()
        conversation = AISalesConversation(
            channel_account_id=channel.id,
            external_contact_id="future-customer",
            contact_name="أحمد الاختبار",
        )
        db.session.add(conversation)
        db.session.flush()
        now = datetime.utcnow()
        customer = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="شاشة 50 شكد سعرها؟ رقمي 07734049148",
            status="received",
            created_at=now,
        )
        employee = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            direction="outbound",
            sender_type="employee",
            message_type="text",
            text_content="سعرها 270,000 د.ع. استخدامك إلها للبيت لو للمحل حتى أحددلك إذا القياس مناسب؟",
            status="sent",
            created_at=now + timedelta(seconds=1),
        )
        db.session.add_all([customer, employee])
        db.session.commit()

        captured = capture_employee_reply_example(employee.id)
        learned = AISalesReplyExample.query.filter_by(source_employee_message_id=employee.id).one()
        assert captured["captured"] is True
        assert captured["approved"] is True
        assert "07734049148" not in learned.customer_example
        assert "270,000" not in learned.employee_example
        assert learned.source_type == "employee_continuous"

        template = build_learning_template()
        workbook = load_workbook(template)
        workbook["المنتجات"].append([
            product.id,
            product.sku,
            product.barcode,
            product.name,
            "شاشة البيت 50",
            "تلفزيون خمسين، شاشة 50",
            "دقة 4K ونظام سمارت",
            "صورة واضحة\nتشغيل التطبيقات",
            "غرفة معيشة متوسطة",
            "ضمان سنة",
            "حسب المنطقة",
            "غالية: وضح الفرق المسجل فقط",
            "لا تخمن معدل التحديث",
            "نعم",
        ])
        workbook["المشاكل والحلول"].append([
            product.id,
            product.name,
            "يوتيوب لا يفتح رغم اتصال الشاشة بالواي فاي",
            "يوتيوب، واي فاي، لا يفتح",
            "هل تعمل بقية التطبيقات؟",
            "أعد تشغيل الشاشة والراوتر ثم امسح ذاكرة تطبيق يوتيوب المؤقتة.",
            "إذا لم تعمل بقية التطبيقات أيضاً",
            "نعم",
        ])
        stream = BytesIO()
        workbook.save(stream)
        result = import_learning_workbook(stream.getvalue(), "training.xlsx")

        product_profile = AISalesProductProfile.query.filter_by(product_id=product.id).one()
        assert result["product_rows"] == 1
        assert result["problem_rows"] == 1
        assert product_profile.marketing_name == "شاشة البيت 50"
        assert "4K" in product.description
        assert AISalesKnowledgeEntry.query.count() == 1
        matches = retrieve_business_knowledge("الشاشة متصلة واي فاي بس اليوتيوب ما يفتح", product_ids=[product.id])
        assert len(matches) == 1
        assert "أعد تشغيل" in matches[0]["approved_solution"]
