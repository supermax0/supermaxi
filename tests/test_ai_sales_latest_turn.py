from modules.ai_sales.engine import (
    _latest_message_needs_product_answer,
    _latest_turn_analysis_text,
)
from modules.ai_sales.agent import _quick_decline_reply
from modules.ai_sales.message_guard import classify_customer_message


def test_latest_greeting_breaks_old_product_burst():
    combined = "رسالة الزبون 1: اريد ثلاجة 7 قدم\nرسالة الزبون 2: مرحبا"

    text, continuation = _latest_turn_analysis_text("مرحبا", combined, 2)

    assert text == "مرحبا"
    assert continuation is False


def test_latest_address_question_breaks_old_product_burst():
    combined = "رسالة الزبون 1: اريد ثلاجة 7 قدم\nرسالة الزبون 2: العنوان وين"

    text, continuation = _latest_turn_analysis_text("العنوان وين", combined, 2)
    guard = classify_customer_message(text)
    needs_product = _latest_message_needs_product_answer(
        text,
        guard,
        current_product_family="refrigerator",
        direct_screen_size_price=None,
        requested_foot_size=7,
        requested_features=[],
        requested_media=None,
        purchase_intent=False,
        price_objection=False,
        price_flexibility_question=False,
        mid_range_preference=False,
        show_all_options=False,
        advertised_dollar_amount=None,
        visual_reference_active=False,
        previous_products=[{"product_id": 1, "name": "ثلاجة 7 قدم"}],
    )

    assert text == "العنوان وين"
    assert continuation is False
    assert needs_product is False


def test_decline_never_reuses_stale_product_context():
    text = "اعتذر"
    guard = classify_customer_message(text, context={"product_family": "refrigerator"})
    needs_product = _latest_message_needs_product_answer(
        text,
        guard,
        current_product_family="refrigerator",
        direct_screen_size_price=None,
        requested_foot_size=7,
        requested_features=[],
        requested_media=None,
        purchase_intent=False,
        price_objection=False,
        price_flexibility_question=False,
        mid_range_preference=False,
        show_all_options=False,
        advertised_dollar_amount=None,
        visual_reference_active=False,
        previous_products=[{"product_id": 1, "name": "ثلاجة 7 قدم"}],
    )

    assert guard.intent == "decline"
    assert guard.is_decline is True
    assert needs_product is False
    reply = _quick_decline_reply(text, {"lead_score": 35})
    assert reply is not None
    assert reply["customer_intent"] == "decline"
    assert reply["product_ids"] == []
    assert "ثلاج" not in reply["reply"]


def test_short_price_followup_keeps_product_burst_context():
    combined = "رسالة الزبون 1: شاشة 55\nرسالة الزبون 2: سعره"

    text, continuation = _latest_turn_analysis_text("سعره", combined, 2)

    assert text == combined
    assert continuation is True
