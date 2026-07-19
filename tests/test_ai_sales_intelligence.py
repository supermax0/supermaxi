"""Behavior tests for intelligence levels and consultative sales replies."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT_REASONING = f"test_ai_sales_reasoning_{os.getpid()}"
TENANT_OBJECTION = f"test_ai_sales_objection_{os.getpid()}"
TENANT_KNOWLEDGE = f"test_ai_sales_knowledge_{os.getpid()}"
TENANT_GREETING = f"test_ai_sales_greeting_{os.getpid()}"
TENANT_REPAIR = f"test_ai_sales_repair_{os.getpid()}"
TENANT_LINKS = f"test_ai_sales_links_{os.getpid()}"
TENANT_ORDER = f"test_ai_sales_order_{os.getpid()}"
TENANT_ORDER_CONTINUITY = f"test_ai_sales_order_continuity_{os.getpid()}"
TENANT_PRODUCT_SWITCH = f"test_ai_sales_product_switch_{os.getpid()}"
TENANT_BURST = f"test_ai_sales_burst_{os.getpid()}"


def _fresh_tenant_db(tenant):
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_sales_reply_layout_rejects_newspaper_paragraphs():
    from modules.ai_sales.agent import _reply_layout_is_readable

    dense = (
        "المواصفات المسجلة لهذا المنتج مناسبة للاستخدام اليومي في الغرف والمساحات الصغيرة والمتوسطة "
        "وضمانها سنة واحدة وتفاصيل الدقة والسمارت والمداخل موجودة عندي، لذلك ما أذكر أكثر من المؤكد "
        "حتى تكون المعلومة دقيقة وواضحة قبل إكمال الطلب واختيار المنتج المناسب للزبون."
    )
    arranged = (
        "شاشة هيتاشي 42 موديل 4300\n"
        "• السعر: 195,000 د.ع\n"
        "• الضمان: سنة واحدة\n"
        "• التوصيل: مجاني\n"
        "تريد أكمل وياك الطلب؟"
    )

    assert not _reply_layout_is_readable(dense)
    assert _reply_layout_is_readable(arranged)


def test_structured_reply_can_be_sent_as_ordered_message_bubbles():
    from modules.ai_sales.engine import _split_outbound_reply

    reply = (
        "شاشة هيتاشي 42 موديل 4300\n"
        "• السعر: 195,000 د.ع\n"
        "• الضمان: سنة واحدة\n\n"
        "يناسبك السعر حتى نكمل الطلب؟"
    )

    assert _split_outbound_reply(reply) == [
        "شاشة هيتاشي 42 موديل 4300\n• السعر: 195,000 د.ع\n• الضمان: سنة واحدة",
        "يناسبك السعر حتى نكمل الطلب؟",
    ]


def test_newer_customer_message_supersedes_an_inflight_reply():
    tenant = TENANT_BURST
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from modules.ai_sales.engine import _newer_customer_message, get_or_create_conversation
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        channel = AISalesChannelAccount(name="Burst", channel_type="messenger", is_active=False)
        db.session.add(channel)
        db.session.flush()
        conversation = get_or_create_conversation(channel, external_contact_id="burst-customer", phone="")
        first = AISalesMessage(
            conversation_id=conversation.id, channel_account_id=channel.id, direction="inbound",
            sender_type="customer", message_type="text", text_content="شاشة 43 عدك", status="processing",
        )
        second = AISalesMessage(
            conversation_id=conversation.id, channel_account_id=channel.id, direction="inbound",
            sender_type="customer", message_type="text", text_content="شكد السعر والضمان", status="received",
        )
        db.session.add_all([first, second])
        db.session.commit()

        assert _newer_customer_message(first).id == second.id


def test_map_link_is_previewed_and_saved_as_optional_delivery_data():
    tenant = TENANT_LINKS
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.customer import Customer
    from models.product import Product
    from modules.ai_sales import agent
    from modules.ai_sales.engine import get_or_create_conversation, process_inbound_message
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema

    map_url = "https://maps.google.com/?q=33.3152,44.3661"
    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        product = Product(name="سبلت جنرال 1طن", buy_price=350000, sale_price=399000, quantity=4, active=True)
        channel = AISalesChannelAccount(name="Links Test", channel_type="whatsapp", connection_status="simulator", is_active=False)
        db.session.add_all([product, channel])
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="9647700004555",
            phone="9647700004555",
            contact_name="عميل الخريطة",
        )
        conversation.set_context({"last_product_ids": [product.id], "focus_product_id": product.id})
        inbound = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="map-link-1",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content=f"هذا موقعي {map_url}",
            status="received",
        )
        db.session.add(inbound)
        db.session.commit()

        original_key = agent._openai_key
        agent._openai_key = lambda: ""
        try:
            outbound = process_inbound_message(inbound.id, send_external=False)
        finally:
            agent._openai_key = original_key

        context = conversation.get_context()
        previews = inbound.to_dict()["link_previews"]
        customer = Customer.query.get(conversation.customer_id)
        assert previews[0]["type"] == "map"
        assert context["order_customer_data"]["location_url"] == map_url
        assert context["order_customer_data"]["location_latitude"] == 33.3152
        assert map_url in (customer.address or "")
        assert "وصلني موقع التوصيل" in outbound.text_content
        assert "الاسم" in outbound.text_content
        assert "المحافظة" not in outbound.text_content


def test_confirmed_ai_booking_creates_one_linked_order_in_orders_page():
    tenant = TENANT_ORDER
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.page import Page
    from models.product import Product
    from modules.ai_sales import agent
    from modules.ai_sales.engine import get_or_create_conversation, process_inbound_message
    from modules.ai_sales.models import AISalesChannelAccount, AISalesLead, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        product = Product(
            name="سبلت جنرال 1طن",
            buy_price=350000,
            sale_price=399000,
            quantity=4,
            active=True,
        )
        channel = AISalesChannelAccount(
            name="صفحة طلبات الذكاء",
            channel_type="messenger",
            connection_status="simulator",
            is_active=False,
        )
        db.session.add_all([product, channel])
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="ai-order-customer",
            phone="07734049148",
            contact_name="سجاد أحمد",
        )
        conversation.set_context({
            "last_product_ids": [product.id],
            "focus_product_id": product.id,
            "order_customer_data": {
                "name": "سجاد أحمد",
                "phone": "07734049148",
                "city": "بغداد",
                "area": "الأمين الثانية",
            },
        })
        booking = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="ai-order-booking",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="حجزلي هذا",
            status="received",
        )
        db.session.add(booking)
        db.session.commit()

        original_key = agent._openai_key
        agent._openai_key = lambda: ""
        try:
            summary_reply = process_inbound_message(booking.id, send_external=False)
            assert Invoice.query.count() == 0
            assert conversation.sales_stage == "waiting_confirmation"
            assert conversation.get_context()["pending_order"]["product_id"] == product.id
            assert "أأكد وياك ملخص الطلب" in summary_reply.text_content
            assert "أكد الطلب" in summary_reply.text_content

            confirmation = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                external_message_id="ai-order-confirmation",
                direction="inbound",
                sender_type="customer",
                message_type="text",
                text_content="أكد الطلب",
                status="received",
            )
            db.session.add(confirmation)
            db.session.commit()
            created_reply = process_inbound_message(confirmation.id, send_external=False)

            invoice = Invoice.query.one()
            item = OrderItem.query.filter_by(invoice_id=invoice.id).one()
            lead = AISalesLead.query.filter_by(conversation_id=conversation.id).one()
            assert invoice.status == "تم الطلب"
            assert invoice.payment_status == "غير مسدد"
            assert invoice.customer_name == "سجاد أحمد"
            assert invoice.total == 399000
            assert invoice.page_name == "صفحة طلبات الذكاء"
            assert Page.query.filter_by(name="صفحة طلبات الذكاء").one().id == invoice.page_id
            assert item.product_id == product.id
            assert item.quantity == 1
            assert item.price == 399000
            assert lead.status == "won"
            assert lead.won_order_id == invoice.id
            assert conversation.sales_stage == "won"
            assert conversation.get_context()["created_order_id"] == invoice.id
            assert "تم تسجيل طلبك بنجاح" in created_reply.text_content
            assert f"#{invoice.id}" in created_reply.text_content

            repeated = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                external_message_id="ai-order-confirmation-repeat",
                direction="inbound",
                sender_type="customer",
                message_type="text",
                text_content="أكد الطلب",
                status="received",
            )
            db.session.add(repeated)
            db.session.commit()
            repeated_reply = process_inbound_message(repeated.id, send_external=False)
            assert Invoice.query.count() == 1
            assert conversation.sales_stage == "won"
            assert "مسجل فعلاً" in repeated_reply.text_content
        finally:
            agent._openai_key = original_key


def test_order_summary_recovers_price_updates_quantity_and_ignores_bare_image_drift():
    tenant = TENANT_ORDER_CONTINUITY
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from modules.ai_sales import agent, engine
    from modules.ai_sales.engine import get_or_create_conversation, process_inbound_message
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        screen = Product(
            name="شاشة جنرال حجم 43",
            buy_price=180000,
            sale_price=219000,
            quantity=37,
            active=True,
        )
        unrelated = Product(
            name="سبلت جنرال فلاك 2طن حار بارد",
            buy_price=420000,
            sale_price=490000,
            quantity=3,
            active=True,
        )
        channel = AISalesChannelAccount(
            name="Order continuity",
            channel_type="messenger",
            connection_status="simulator",
            is_active=False,
        )
        db.session.add_all([screen, unrelated, channel])
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="order-continuity-customer",
            phone="07734049148",
            contact_name="سجاد أحمد",
        )
        conversation.sales_stage = "waiting_confirmation"
        conversation.set_context({
            "product_family": "screen",
            "last_product_ids": [screen.id],
            "focus_product_id": screen.id,
            "main_need": "شاشة جنرال حجم 43",
            "order_customer_data": {
                "name": "سجاد أحمد",
                "phone": "07734049148",
                "city": "بغداد",
                "area": "الأمينة الثانية",
                "landmark": "قرب مطعم الرياضي",
            },
        })
        quantity_message = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="order-quantity-two",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="عدل اريد عدد 2",
            status="received",
        )
        db.session.add(quantity_message)
        db.session.commit()

        original_key = agent._openai_key
        original_download = engine.download_inbound_media
        agent._openai_key = lambda: ""
        engine.download_inbound_media = lambda message: message
        try:
            quantity_reply = process_inbound_message(quantity_message.id, send_external=False)
            context = conversation.get_context()
            assert context["pending_order"]["product_id"] == screen.id
            assert context["pending_order"]["quantity"] == 2
            assert context["pending_order"]["unit_price"] == 219000
            assert context["pending_order"]["total"] == 438000
            assert "سعر الوحدة: 219,000 د.ع" in quantity_reply.text_content
            assert "المجموع: 438,000 د.ع" in quantity_reply.text_content

            summary_message = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                external_message_id="order-show-summary",
                direction="inbound",
                sender_type="customer",
                message_type="text",
                text_content="اعرض الملخص",
                status="received",
            )
            db.session.add(summary_message)
            db.session.commit()
            summary_reply = process_inbound_message(summary_message.id, send_external=False)
            assert "شاشة جنرال حجم 43" in summary_reply.text_content
            assert "سعر الوحدة: 219,000 د.ع" in summary_reply.text_content
            assert "المجموع: 438,000 د.ع" in summary_reply.text_content

            image_message = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                external_message_id="order-bare-image",
                external_media_id="thumbs-up-image",
                direction="inbound",
                sender_type="customer",
                message_type="image",
                text_content="",
                status="received",
            )
            db.session.add(image_message)
            db.session.commit()
            image_reply = process_inbound_message(image_message.id, send_external=False)
        finally:
            agent._openai_key = original_key
            engine.download_inbound_media = original_download

        final_context = conversation.get_context()
        assert final_context["pending_order"]["product_id"] == screen.id
        assert final_context["pending_order"]["quantity"] == 2
        assert final_context["focus_product_id"] == screen.id
        assert conversation.human_takeover is False
        assert conversation.ai_enabled is True
        assert "نفس المنتج والسعر" in image_reply.text_content
        assert unrelated.name not in (conversation.summary or "")


def test_product_switch_and_price_flexibility_never_book_stale_product():
    tenant = TENANT_PRODUCT_SWITCH
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from modules.ai_sales import agent
    from modules.ai_sales.engine import get_or_create_conversation, process_inbound_message
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        screen = Product(name="شاشة 55", buy_price=250000, sale_price=300000, quantity=4, active=True)
        washer = Product(name="غسالة دنكا 16 كيلو أبيض", buy_price=150000, sale_price=199000, quantity=3, active=True)
        cooler = Product(name="براد كهرمانه", buy_price=90000, sale_price=115000, quantity=8, active=True)
        channel = AISalesChannelAccount(
            name="Product switch regression",
            channel_type="messenger",
            connection_status="simulator",
            is_active=False,
        )
        db.session.add_all([screen, washer, cooler, channel])
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="product-switch-customer",
            phone="07734049148",
            contact_name="سجاد أحمد",
        )
        conversation.sales_stage = "waiting_confirmation"
        conversation.set_context({
            "product_family": "screen",
            "last_product_ids": [screen.id],
            "focus_product_id": screen.id,
            "pending_order": {
                "product_id": washer.id,
                "product_name": washer.name,
                "unit_price": 199000,
            },
            "order_customer_data": {
                "name": "سجاد أحمد",
                "phone": "07734049148",
                "city": "بغداد",
                "area": "الأمين الثانية",
            },
        })
        product_message = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="switch-to-cooler",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="براد كهرمانه",
            status="received",
        )
        db.session.add(product_message)
        db.session.commit()

        original_key = agent._openai_key
        agent._openai_key = lambda: ""
        try:
            process_inbound_message(product_message.id, send_external=False)
            after_switch = conversation.get_context()
            assert after_switch["product_family"] == "air_cooler"
            assert after_switch["focus_product_id"] == cooler.id
            assert "pending_order" not in after_switch
            assert "purchase_selection" not in after_switch

            price_message = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                external_message_id="cooler-price-flexibility",
                direction="inbound",
                sender_type="customer",
                message_type="text",
                text_content="سعره بي مجال",
                status="received",
            )
            db.session.add(price_message)
            db.session.commit()
            reply = process_inbound_message(price_message.id, send_external=False)
        finally:
            agent._openai_key = original_key

        final_context = conversation.get_context()
        assert final_context["focus_product_id"] == cooler.id
        assert final_context["last_product_ids"] == [cooler.id]
        assert "pending_order" not in final_context
        assert "purchase_selection" not in final_context
        assert "براد كهرمانه" in reply.text_content
        assert "115,000" in reply.text_content
        assert "غسالة" not in reply.text_content


def test_budget_language_and_intelligence_policies():
    from modules.ai_sales.agent import (
        _fallback_reply,
        _grounded_reply,
        _known_customer_facts,
        extract_budget,
        intelligence_policy,
        is_purchase_intent,
    )
    from modules.ai_sales.product_tools import has_product_query
    from modules.ai_sales.links import extract_link_previews

    assert extract_budget("ميزانيتي 270") == 270_000
    assert extract_budget("حدود ٣٠٠ ألف") == 300_000
    assert extract_budget("ثلاثمية") == 300_000
    assert extract_budget("أريد راوتر سعره مية وخمسة وعشرين ألف") == 125_000
    assert extract_budget("ميزانيتي ثلاثمية وخمسين ألف") == 350_000
    assert has_product_query("أريد شاشة 50")
    assert not has_product_query("الغرفة متوسطة والمسافة 3 متر")
    assert not has_product_query("إي قارنلي بالحجم والسعر")
    assert extract_budget("ربع مليون") == 250_000
    assert extract_budget("أريد شاشة 55") is None
    assert intelligence_policy("fast")["reasoning_effort"] == "minimal"
    assert intelligence_policy("expert")["reasoning_effort"] == "medium"
    assert intelligence_policy("elite")["reasoning_effort"] == "medium"
    assert intelligence_policy("unknown")["history_limit"] == intelligence_policy("expert")["history_limit"]
    assert intelligence_policy("expert")["max_output_tokens"] >= 3000
    assert is_purchase_intent("حجزلي هذا")
    assert is_purchase_intent("بس توصيل أريد")
    facts = _known_customer_facts(
        "أريد شاشة للبيت وميزانيتي 300 ألف وأهم شي الصورة تكون زينة",
        [],
        {},
    )
    assert facts["الميزانية"] == 300_000
    assert facts["الاستخدام"] == "البيت"
    assert facts["الأولوية"] == "جودة الصورة"
    fallback = _fallback_reply(
        "أريد شاشة للبيت وأهم شي الصورة تكون زينة",
        [{"product_id": 1, "name": "شاشة 50", "price": 270_000, "stock": 3}],
        known_facts=facts,
    )
    assert "للبيت لو للمحل" not in fallback["reply"]
    assert fallback["missing_information"] == ["الخيار المفضل"]
    maps = extract_link_previews("هذا موقعي https://maps.google.com/?q=33.3152,44.3661")
    assert maps[0]["type"] == "map"
    assert maps[0]["latitude"] == 33.3152
    assert extract_link_previews("شوف https://example.com/item")[0]["title"] == "example.com"
    fridge_reply = _fallback_reply(
        "أريد ثلاجة 5 قدم",
        [{"product_id": 9, "name": "ثلاجة شارب 5 قدم لون أبيض", "price": 145_000, "stock": 3}],
    )["reply"]
    assert "ثلاجة شارب 5 قدم" in fridge_reply
    assert "7 قدم" not in fridge_reply
    assert "متوفر 3" not in fridge_reply
    assert "گلي أريده" in fridge_reply
    assert "رقم الهاتف" not in fridge_reply
    products = [{"price": 270_000, "stock": 33, "warranty": "سنة", "delivery": "حسب المنطقة"}]
    assert _grounded_reply("السعر 270,000 د.ع", "ميزانيتي 300 ألف", products)
    assert not _grounded_reply("السعر 270,000 د.ع، الكمية المتوفرة 33", "ميزانيتي 300 ألف", products)
    assert not _grounded_reply("السعر 280,000 د.ع، الكمية المتوفرة 33", "ميزانيتي 300 ألف", products)
    assert not _grounded_reply("السعر 270,000 د.ع، الكمية المتوفرة 99", "ميزانيتي 300 ألف", products)
    bare_products = [{"price": 270_000, "stock": 3}]
    assert _grounded_reply("أكيد، نخليها توصيل. بقي الاسم.", "بس توصيل أريد", bare_products)
    assert not _grounded_reply("التوصيل مجاني اليوم.", "أريد توصيل", bare_products)
    assert not _grounded_reply("هذا براند قوي وسعره 270,000 د.ع", "ميزانيتي 300 ألف", bare_products)
    assert not _grounded_reply("جودته أفضل وسعره 270,000 د.ع", "ميزانيتي 300 ألف", bare_products)
    assert not _grounded_reply("مناسب للاستخدام اليومي وسعره 270,000 د.ع", "ميزانيتي 300 ألف", bare_products)
    assert not _grounded_reply(
        "استخدامك للبيت لو للمحل؟",
        "أريدها للبيت",
        bare_products,
        {"الاستخدام": "البيت"},
    )
    order_fallback = _fallback_reply(
        "حجزلي",
        [{"product_id": 7, "name": "سبلت جنرال 1طن", "price": 399_000, "stock": 4}],
        known_facts={
            "اسم الزبون": "سجاد أحمد",
            "رقم الهاتف": "07734049148",
            "المحافظة": "بغداد",
            "المنطقة": "الأمين الثانية",
        },
    )
    assert order_fallback["sales_stage"] == "collecting_order_data"
    assert order_fallback["missing_information"] == []
    assert "بيانات الطلب كاملة" in order_fallback["reply"]
    assert "لقيتلك" not in order_fallback["reply"]
    assert "رقم الهاتف" not in order_fallback["reply"]

    continued = _fallback_reply(
        "للبيت",
        [{"product_id": 7, "name": "سبلت جنرال 1طن", "price": 399_000, "stock": 4}],
        known_facts={"الاستخدام": "البيت"},
        history=[{"role": "assistant", "content": "الموجود المناسب: سبلت جنرال 1طن بسعر 399,000 د.ع"}],
    )
    assert "نفس الخيارات" not in continued["reply"]
    assert "ثبت عندي نوع الاستخدام" in continued["reply"]


def test_decision_engine_remembers_facts_ranks_products_and_adapts_reasoning():
    from modules.ai_sales.decision_engine import (
        adaptive_reasoning_effort,
        calculate_lead_state,
        classify_objection,
        facts_for_prompt,
        next_best_action,
        rank_products_for_customer,
        update_customer_facts,
    )

    history = [{"role": "user", "content": "أريد شاشة للبيت وميزانيتي 300 ألف"}]
    facts = update_customer_facts(
        "أهم شي الصورة تكون واضحة",
        history,
        {},
        budget=300_000,
    )
    assert facts["usage"] == "home"
    assert facts["budget"] == 300_000
    assert facts["priority"] == "picture_quality"
    assert classify_objection("غالية أريد أرخص") == "price"
    assert classify_objection("أريد أحجي ويا موظف") == "human_request"

    ranked = rank_products_for_customer([
        {
            "product_id": 1, "name": "شاشة 42", "price": 195_000, "stock": 150,
            "description": "", "selling_points": [], "ideal_for": [], "warranty": "", "delivery": "",
        },
        {
            "product_id": 2, "name": "شاشة 50 4K", "price": 285_000, "stock": 4,
            "description": "دقة 4K ووضوح صورة عالي", "selling_points": ["صورة 4K"],
            "ideal_for": ["غرف المعيشة"], "warranty": "سنة", "delivery": "حسب المنطقة",
        },
    ], facts)
    assert ranked[0]["product_id"] == 2
    assert ranked[0]["knowledge_score"] > ranked[1]["knowledge_score"]
    assert any("جودة الصورة" in reason for reason in ranked[0]["recommendation_reasons"])
    assert next_best_action(facts, "price", purchase_intent=False, products=ranked) == "عرض بديل أوفر حقيقي وشرح الفرق باختصار"
    score, temperature = calculate_lead_state(20, facts, ranked, objection="price", purchase_intent=False)
    assert score >= 50
    assert temperature == "warm"
    assert adaptive_reasoning_effort("expert", "عندكم شاشة 50؟") == "low"
    assert adaptive_reasoning_effort("expert", "أريد شاشة للبيت", fact_count=3) == "medium"
    assert adaptive_reasoning_effort("expert", "غالية أريد أرخص", objection="price") == "medium"
    assert adaptive_reasoning_effort("elite", "عندكم شاشة 50؟") == "low"
    assert adaptive_reasoning_effort("elite", "قارن بينهم", history_count=3) == "medium"
    fridge_facts = update_customer_facts("أريد ثلاجة 5 قدم", [], {"requested_size": 50})
    assert fridge_facts["requested_foot_size"] == 5
    assert "requested_size" not in fridge_facts
    fridge_ranked = rank_products_for_customer([
        {"product_id": 21, "name": "ثلاجة شارب 5 قدم", "price": 145000, "stock": 3},
        {"product_id": 22, "name": "ثلاجة إيفولي 7 قدم", "price": 169000, "stock": 3},
    ], fridge_facts)
    assert fridge_ranked[0]["product_id"] == 21
    assert "جمع الاسم ورقم الهاتف" in next_best_action(
        fridge_facts,
        "none",
        purchase_intent=False,
        products=fridge_ranked[:1],
    )
    assert next_best_action(
        facts,
        "none",
        purchase_intent=False,
        products=ranked,
    ) == "معرفة حجم الغرفة أو مسافة المشاهدة قبل التوصية النهائية"

    from modules.ai_sales.agent import _fallback_reply, _grounded_reply

    action = "معرفة حجم الغرفة أو مسافة المشاهدة قبل التوصية النهائية"
    fallback = _fallback_reply(
        "أريد شاشة للبيت بحدود 300 ألف وأهم شي وضوح الصورة",
        ranked,
        known_facts={"الاستخدام": "البيت", "الميزانية": 300_000, "الأولوية": "جودة الصورة"},
        recommended_next_action=action,
    )
    assert "أقرب الخيارات الموجودة" in fallback["reply"]
    assert "أفضل الخيارات" not in fallback["reply"]
    assert "غرفتك صغيرة، متوسطة لو كبيرة؟" in fallback["reply"]
    assert fallback["next_action"] == action
    assert not _grounded_reply(
        "أنصحك بشاشة 50 لأنها قيمة ممتازة. تريد تستلمها لمقارنة الصورة بالمتجر؟",
        "أريد شاشة للبيت بحدود 300 ألف",
        ranked,
        {"الاستخدام": "البيت", "الميزانية": 300_000},
        action,
    )

    room_facts = update_customer_facts(
        "الغرفة متوسطة والمسافة تقريباً 3 متر",
        history,
        facts,
        budget=300_000,
    )
    assert room_facts["room_size"] == "medium"
    assert room_facts["viewing_distance_m"] == 3
    unprofiled = [
        {"product_id": 11, "name": "شاشة هيتاشي حجم 42", "price": 195_000, "stock": 152, "description": "", "selling_points": [], "ideal_for": []},
        {"product_id": 12, "name": "شاشة الحي حجم 50", "price": 285_000, "stock": 4, "description": "", "selling_points": [], "ideal_for": []},
        {"product_id": 13, "name": "شاشة جنرال حجم 50", "price": 270_000, "stock": 33, "description": "", "selling_points": [], "ideal_for": []},
    ]
    room_ranked = rank_products_for_customer(unprofiled, room_facts)
    assert room_ranked[0]["product_id"] == 13
    missing_quality_action = next_best_action(
        room_facts,
        "none",
        purchase_intent=False,
        products=room_ranked,
    )
    assert missing_quality_action == "توضيح أن مواصفات جودة الصورة غير مسجلة والمقارنة بالحجم والسعر فقط"
    missing_quality_reply = _fallback_reply(
        "الغرفة متوسطة والمسافة تقريباً 3 متر",
        room_ranked,
        known_facts={"الاستخدام": "البيت", "الميزانية": 300_000, "الأولوية": "جودة الصورة", "حجم المكان": "غرفة متوسطة"},
        recommended_next_action=missing_quality_action,
    )
    assert "جودة الصورة مو مسجلة" in missing_quality_reply["reply"]
    assert "أقارنلك بالحجم والسعر فقط" in missing_quality_reply["reply"]
    assert _grounded_reply(
        missing_quality_reply["reply"],
        "الغرفة متوسطة والمسافة تقريباً 3 متر",
        room_ranked,
        {"الاستخدام": "البيت", "الميزانية": 300_000, "الأولوية": "جودة الصورة"},
        missing_quality_action,
    )

    basis_facts = update_customer_facts(
        "قارنلي بالحجم والسعر",
        history,
        room_facts,
        budget=300_000,
    )
    assert basis_facts["decision_basis"] == "size_price"
    comparison_action = next_best_action(
        basis_facts,
        "none",
        purchase_intent=False,
        products=room_ranked,
    )
    assert comparison_action == "مقارنة أفضل خيارين وتقديم توصية مبررة"
    comparison_reply = _fallback_reply(
        "قارنلي بالحجم والسعر",
        room_ranked,
        known_facts=facts_for_prompt(basis_facts),
        recommended_next_action=comparison_action,
    )
    assert "شاشة جنرال حجم 50 هو الأقرب لطلبك" in comparison_reply["reply"]
    assert "نكمل بيانات الطلب؟" in comparison_reply["reply"]


def test_product_knowledge_api_persists_grounded_sales_data():
    tenant = TENANT_KNOWLEDGE
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.product import Product
    from modules.ai_sales.models import AISalesProductProfile
    from modules.ai_sales.routes import api_product_knowledge
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        product = Product(name="شاشة اختبار 50", sale_price=285000, buy_price=220000, quantity=5, active=True)
        db.session.add(product)
        db.session.commit()
        product_id = product.id

        payload = {
            "marketing_name": "شاشة البيت 50",
            "aliases": "شاشة خمسين\nتلفزيون 50",
            "description": "شاشة بدقة 4K للاستخدام المنزلي",
            "selling_points": "دقة 4K\nصورة واضحة",
            "ideal_for": "غرفة متوسطة\nغرفة معيشة",
            "warranty": "ضمان سنة",
            "delivery": "حسب المنطقة",
            "objections": "غالية: اشرح القيمة واعرض بديلاً أوفر",
            "sales_notes": "لا تذكر أي ميزة غير مسجلة",
            "allow_price": True,
            "allow_recommendation": True,
            "is_active": True,
        }
        with app.test_request_context(
            f"/ai-sales/api/product-knowledge/{product_id}",
            method="PUT",
            json=payload,
        ):
            g.tenant = tenant
            session["user_id"] = 1
            session["role"] = "admin"
            response = api_product_knowledge(product_id).get_json()
        assert response["success"] is True
        assert response["knowledge"]["knowledge_score"] >= 90
        assert response["knowledge"]["selling_points"] == ["دقة 4K", "صورة واضحة"]
        assert response["knowledge"]["objection_guidance"]["غالية"].startswith("اشرح القيمة")
        profile = AISalesProductProfile.query.filter_by(product_id=product_id).one()
        assert profile.marketing_name == "شاشة البيت 50"

        with app.test_request_context(f"/ai-sales/api/product-knowledge/{product_id}"):
            g.tenant = tenant
            session["user_id"] = 1
            session["role"] = "admin"
            loaded = api_product_knowledge(product_id).get_json()["knowledge"]
        assert loaded["warranty"] == "ضمان سنة"
        assert loaded["missing"] == ["صورة المنتج"]


def test_product_grounded_openai_reply_is_kept_and_level_controls_reasoning():
    tenant = TENANT_REASONING
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from modules.ai_sales import agent
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesAgentProfile, AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema

    captured = {}

    def fake_response(_api_key, **kwargs):
        captured.update(kwargs)
        payload = {
            "reply": "أنصحك بشاشة جنرال 50 لأن سعرها 270,000 د.ع وتناسب ميزانيتك، والمتوفر منها فعلياً. تريد أثبتلك هذا الخيار؟",
            "sales_stage": "product_selection",
            "lead_score": 61,
            "lead_temperature": "warm",
            "should_handoff": False,
            "handoff_reason": "",
            "product_ids": [101],
            "main_need": "شاشة ضمن ميزانية 300 ألف",
            "primary_objection": "",
            "next_action": "تأكيد الخيار",
            "customer_intent": "product_search",
            "customer_sentiment": "interested",
            "sales_strategy": "recommend",
            "missing_information": ["تأكيد الخيار"],
            "confidence": 94,
        }
        return SimpleNamespace(
            output_text=json.dumps(payload, ensure_ascii=False),
            usage=SimpleNamespace(input_tokens=120, output_tokens=80),
        )

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        profile = AISalesAgentProfile.query.first()
        profile.intelligence_level = "elite"
        profile.persuasion_style = "balanced"
        channel = AISalesChannelAccount(name="Reasoning Test", connection_status="simulator", is_active=False)
        db.session.add(channel)
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="9647700001001",
            phone="9647700001001",
            contact_name="زبون التفكير",
        )
        inbound = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            direction="inbound",
            sender_type="customer",
            text_content="ميزانيتي 300 ألف",
            status="received",
        )
        db.session.add(inbound)
        db.session.flush()

        original_key = agent._openai_key
        original_create = agent._create_openai_response
        agent._openai_key = lambda: "existing-test-key"
        agent._create_openai_response = fake_response
        try:
            result = agent.generate_sales_reply(
                conversation_id=conversation.id,
                message_id=inbound.id,
                customer_message="ميزانيتي 300 ألف",
                history=[{"role": "user", "content": "أريد شاشة للبيت"}],
                products=[{
                    "product_id": 101,
                    "name": "شاشة جنرال 50",
                    "official_name": "شاشة جنرال 50",
                    "price": 270_000,
                    "stock": 33,
                    "description": "",
                    "selling_points": ["حجم مناسب للغرف المتوسطة"],
                    "ideal_for": ["المنزل"],
                    "warranty": "",
                    "delivery": "",
                    "image_url": "",
                }],
                conversation_context={"last_budget": 300_000},
            )
        finally:
            agent._openai_key = original_key
            agent._create_openai_response = original_create

        assert result["reply"].startswith("أنصحك بشاشة جنرال 50")
        assert "حسب ميزانيتك" not in result["reply"], "The model reply must not be replaced by the fallback template"
        assert result["product_ids"] == [101]
        assert captured["reasoning"] == {"effort": "medium"}
        assert captured["text"]["verbosity"] == "medium"
        assert captured["max_output_tokens"] >= 3000
        final_input = captured["input"][-1]["content"]
        assert "KNOWN_CUSTOMER_FACTS" in final_input
        assert "HUMAN_STYLE_EXAMPLES" in final_input
        assert '"الاستخدام": "البيت"' in final_input
        assert '"الميزانية": 300000' in final_input
        assert profile.to_dict()["intelligence_level"] == "elite"


def test_price_objection_uses_remembered_product_and_offers_cheaper_live_alternative():
    tenant = TENANT_OBJECTION
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from modules.ai_sales import agent
    from modules.ai_sales.engine import get_or_create_conversation, process_inbound_message
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        db.session.add_all([
            Product(name="شاشة Super Max حجم 55", buy_price=260000, sale_price=325000, quantity=7, active=True),
            Product(name="شاشة جنرال حجم 50", buy_price=220000, sale_price=270000, quantity=33, active=True),
            Product(name="شاشة جيسون حجم 43", buy_price=205000, sale_price=250000, quantity=4, active=True),
            Product(name="راوتر Super Max 5G", buy_price=90000, sale_price=125000, quantity=8, active=True),
        ])
        channel = AISalesChannelAccount(name="Objection Test", connection_status="simulator", is_active=False)
        db.session.add(channel)
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="9647700001002",
            phone="9647700001002",
            contact_name="زبون الاعتراض",
        )
        first = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="objection-first",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="أريد شاشة 55",
            status="received",
        )
        db.session.add(first)
        db.session.commit()

        original_key = agent._openai_key
        agent._openai_key = lambda: ""
        try:
            first_reply = process_inbound_message(first.id, send_external=False)
            assert "325,000" in first_reply.text_content

            second = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                external_message_id="objection-second",
                direction="inbound",
                sender_type="customer",
                message_type="text",
                text_content="غالية، أريد أرخص",
                status="received",
            )
            db.session.add(second)
            db.session.commit()
            second_reply = process_inbound_message(second.id, send_external=False)
            second_stage = conversation.sales_stage
            second_context = dict(conversation.get_context())

            third = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=channel.id,
                external_message_id="category-switch",
                direction="inbound",
                sender_type="customer",
                message_type="text",
                text_content="أريد راوتر",
                status="received",
            )
            db.session.add(third)
            db.session.commit()
            third_reply = process_inbound_message(third.id, send_external=False)
        finally:
            agent._openai_key = original_key

        assert second_reply is not None
        assert any(
            phrase in second_reply.text_content
            for phrase in ("أوفر", "ننزل بالسعر", "أقل بالسعر")
        )
        assert "270,000" in second_reply.text_content
        assert "325,000" not in second_reply.text_content
        assert second_context["primary_objection"] == "السعر"
        assert second_stage == "objection"
        assert "راوتر Super Max 5G" in third_reply.text_content
        assert "شاشة" not in third_reply.text_content
        assert conversation.get_context()["primary_objection"] == ""


def test_greeting_does_not_replay_products_or_reset_existing_sales_context():
    tenant = TENANT_GREETING
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from modules.ai_sales import agent
    from modules.ai_sales.engine import get_or_create_conversation, process_inbound_message
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage, AISalesToolCall
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        product = Product(name="شاشة جنرال حجم 50", buy_price=220000, sale_price=270000, quantity=33, active=True)
        fridge_5 = Product(name="ثلاجة شارب 5 قدم", buy_price=110000, sale_price=145000, quantity=3, active=True)
        fridge_7 = Product(name="ثلاجة إيفولي 7 قدم", buy_price=130000, sale_price=169000, quantity=3, active=True)
        channel = AISalesChannelAccount(name="Greeting Test", connection_status="simulator", is_active=False)
        db.session.add_all([product, fridge_5, fridge_7, channel])
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="greeting-customer",
            phone="9647700001099",
            contact_name="زبون التحية",
        )
        conversation.sales_stage = "product_selection"
        conversation.lead_score = 48
        conversation.lead_temperature = "warm"
        conversation.summary = "الاحتياج: شاشة 50 | الميزانية: 270,000 د.ع"
        conversation.set_context({
            "last_product_ids": [product.id],
            "last_budget": 270000,
            "main_need": "شاشة 50",
            "next_action": "معرفة مكان أو نوع الاستخدام",
            "customer_facts": {"budget": 270000, "requested_size": 50},
        })
        original_context = dict(conversation.get_context())
        original_summary = conversation.summary
        inbound = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="greeting-1",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="مرحبا",
            status="received",
        )
        db.session.add(inbound)
        db.session.commit()

        outbound = process_inbound_message(inbound.id, send_external=False)

        assert outbound is not None
        assert outbound.text_content == "هلا بيك، نورت.\nنكمل على الخيارات السابقة لو عندك طلب جديد؟"
        assert "270,000" not in outbound.text_content
        assert "شاشة جنرال" not in outbound.text_content
        assert conversation.sales_stage == "product_selection"
        assert conversation.lead_score == 48
        assert conversation.lead_temperature == "warm"
        assert conversation.summary == original_summary
        assert conversation.get_context() == original_context
        assert AISalesToolCall.query.filter_by(message_id=inbound.id, tool_name="search_products").count() == 0

        fridge_inbound = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            external_message_id="category-fridge-1",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="أريد ثلاجة 5 قدم",
            status="received",
        )
        db.session.add(fridge_inbound)
        db.session.commit()
        original_key = agent._openai_key
        agent._openai_key = lambda: ""
        try:
            fridge_outbound = process_inbound_message(fridge_inbound.id, send_external=False)
        finally:
            agent._openai_key = original_key

        assert "ثلاجة شارب 5 قدم" in fridge_outbound.text_content
        assert "7 قدم" not in fridge_outbound.text_content
        assert "متوفر 3" not in fridge_outbound.text_content
        assert "گلي أريده" in fridge_outbound.text_content
        assert "رقم الهاتف" not in fridge_outbound.text_content
        switched_context = conversation.get_context()
        assert switched_context["product_family"] == "refrigerator"
        assert switched_context["customer_facts"]["requested_foot_size"] == 5
        assert "requested_size" not in switched_context["customer_facts"]
        assert "last_budget" not in switched_context


def test_invalid_model_json_is_repaired_before_using_fallback():
    tenant = TENANT_REPAIR
    _fresh_tenant_db(tenant)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from modules.ai_sales import agent
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_ai_sales_schema()
        channel = AISalesChannelAccount(name="Repair Test", connection_status="simulator", is_active=False)
        db.session.add(channel)
        db.session.flush()
        conversation = get_or_create_conversation(
            channel,
            external_contact_id="repair-customer",
            phone="9647700001098",
            contact_name="زبون الإصلاح",
        )
        inbound = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=channel.id,
            direction="inbound",
            sender_type="customer",
            text_content="أريد شاشة 50",
            status="received",
        )
        db.session.add(inbound)
        db.session.flush()
        calls = []

        valid_result = {
            "reply": "موجودة شاشة جنرال حجم 50 بسعر 270,000 د.ع.\nتريد أعرفك على تفاصيلها؟",
            "sales_stage": "product_selection",
            "lead_score": 45,
            "lead_temperature": "warm",
            "should_handoff": False,
            "handoff_reason": "",
            "product_ids": [101],
            "main_need": "شاشة 50",
            "primary_objection": "",
            "next_action": "تأكيد ملاءمة الخيار",
            "customer_intent": "product_search",
            "customer_sentiment": "interested",
            "sales_strategy": "recommend",
            "missing_information": ["الاستخدام"],
            "confidence": 92,
        }

        def fake_response(**kwargs):
            calls.append(kwargs)
            output = '{"reply":"رد ناقص' if len(calls) == 1 else json.dumps(valid_result, ensure_ascii=False)
            return SimpleNamespace(
                output_text=output,
                usage=SimpleNamespace(input_tokens=10, output_tokens=20),
            )

        original_key = agent._openai_key
        original_create = agent._create_openai_response
        agent._openai_key = lambda: "existing-test-key"
        agent._create_openai_response = lambda _key, **kwargs: fake_response(**kwargs)
        try:
            result = agent.generate_sales_reply(
                conversation_id=conversation.id,
                message_id=inbound.id,
                customer_message="أريد شاشة 50",
                history=[],
                products=[{
                    "product_id": 101,
                    "name": "شاشة جنرال حجم 50",
                    "official_name": "شاشة جنرال حجم 50",
                    "price": 270000,
                    "stock": 33,
                    "description": "",
                    "selling_points": [],
                    "ideal_for": [],
                    "warranty": "",
                    "delivery": "",
                    "image_url": "",
                }],
                conversation_context={},
            )
        finally:
            agent._openai_key = original_key
            agent._create_openai_response = original_create

        assert len(calls) == 2
        assert result["reply"].startswith("موجودة شاشة جنرال")
        assert result["product_ids"] == [101]
        assert calls[1]["reasoning"] == {"effort": "low"}

