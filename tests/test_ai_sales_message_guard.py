from modules.ai_sales.message_guard import classify_customer_message


def test_message_guard_screen_size_not_model():
    guard = classify_customer_message("55")

    assert guard.family == "screen"
    assert guard.screen_size == 55


def test_message_guard_fridge_preferred_size():
    guard = classify_customer_message("ثلاجه 6 قدم")

    assert guard.family == "refrigerator"
    assert guard.foot_size == 6
    assert guard.preferred_foot_size == 7


def test_message_guard_large_fridge_preferred_size():
    guard = classify_customer_message("اريد ثلاجه 10 قدم")

    assert guard.family == "refrigerator"
    assert guard.foot_size == 10
    assert guard.preferred_foot_size == 12


def test_message_guard_cooler_not_refrigerator():
    guard = classify_customer_message("براد ماء حار بارد")

    assert guard.family == "cooler"


def test_message_guard_ad_price_reference():
    guard = classify_customer_message("انت ناشرها ب128")

    assert guard.is_ad_price_reference
    assert guard.mentioned_price is not None
    assert guard.mentioned_price.amount_iqd == 128000


def test_message_guard_gratitude_closing():
    guard = classify_customer_message("تمام شكرا الكم")

    assert guard.intent == "gratitude"
    assert guard.is_gratitude


def test_message_guard_gratitude_with_pending_order_stays_gratitude():
    guard = classify_customer_message("شكرا", {"pending_order": {"id": 1}})

    assert guard.intent == "gratitude"
    assert guard.is_gratitude
    assert guard.family == ""


def test_message_guard_bare_fridge_size_from_context():
    guard = classify_customer_message("7", {"product_family": "refrigerator"})

    assert guard.family == "refrigerator"
    assert guard.foot_size == 7
    assert guard.preferred_foot_size == 7


def test_message_guard_bare_screen_size_not_fridge_with_fridge_context():
    guard = classify_customer_message("55", {"product_family": "refrigerator"})

    assert guard.family == "screen"
    assert guard.screen_size == 55
    assert guard.foot_size is None
