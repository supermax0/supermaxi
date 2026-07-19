from modules.ai_sales.agent import _is_gratitude_message, _quick_gratitude_reply


def test_short_thanks_is_a_closing_message():
    assert _is_gratitude_message("تمام شكرا الكم")
    reply = _quick_gratitude_reply("تمام شكرا الكم", {"current_sales_stage": "product_selection"})
    assert reply is not None
    assert reply["customer_intent"] == "gratitude"
    assert reply["product_ids"] == []
    assert "شكراً" not in reply["reply"]


def test_thanks_with_a_request_is_not_swallowed():
    assert not _is_gratitude_message("شكرا، شكد سعر شاشة 55؟")
    assert _quick_gratitude_reply("شكرا، شكد سعر شاشة 55؟", {}) is None


def test_plain_order_confirmation_is_preserved():
    context = {"current_sales_stage": "waiting_confirmation", "pending_order": {"id": 1}}
    assert _quick_gratitude_reply("تمام", context) is None


def test_thanks_after_waiting_confirmation_closes_without_repeating_data():
    context = {"current_sales_stage": "waiting_confirmation", "pending_order": {"id": 1}}
    reply = _quick_gratitude_reply("تمام شكرا", context)

    assert reply is not None
    assert reply["customer_intent"] == "gratitude"
    assert reply["product_ids"] == []


def test_plain_arabic_thanks_returns_only_a_short_closing():
    reply = _quick_gratitude_reply("شكرا", {"current_sales_stage": "product_selection"})
    assert reply is not None
    assert reply["reply"] == "العفو حبيبي، بالخدمة."
    assert reply["product_ids"] == []
