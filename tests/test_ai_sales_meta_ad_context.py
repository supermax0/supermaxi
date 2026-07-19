from modules.ai_sales.agent import extract_budget
from modules.ai_sales.channels import (
    extract_meta_system_message_context,
    meta_attachment_details,
    parse_meta_messaging_payload,
)
from modules.ai_sales.engine import _direct_ad_price_result, _unsupported_brand_result
from modules.ai_sales.product_tools import _product_size


def test_messenger_referral_only_open_is_persistable():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE55",
            "messaging": [{
                "sender": {"id": "CUSTOMER1"},
                "recipient": {"id": "PAGE55"},
                "timestamp": 123456,
                "referral": {
                    "source": "ADS",
                    "type": "OPEN_THREAD",
                    "ad_id": "AD55",
                    "ads_context_data": {
                        "ad_title": "شاشة جنرال حجم 55",
                        "photo_url": "https://example.com/ad.jpg",
                    },
                },
            }],
        }],
    }

    event = parse_meta_messaging_payload(payload)[0]

    assert event["message_type"] == "referral"
    assert event["has_message"] is True
    assert event["ads_context_data"]["ad_title"] == "شاشة جنرال حجم 55"
    assert event["text"] == ""


def test_messenger_referral_and_ad_context_are_preserved():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE55",
            "messaging": [{
                "sender": {"id": "CUSTOMER1"},
                "recipient": {"id": "PAGE55"},
                "timestamp": 123456,
                "referral": {
                    "source": "ADS",
                    "type": "OPEN_THREAD",
                    "ad_id": "AD55",
                    "ref": "tv-55",
                    "ads_context_data": {
                        "ad_title": "شاشة جنرال حجم 55",
                        "ad_body": "سمارت 4K",
                        "photo_url": "https://example.com/ad.jpg",
                    },
                },
                "message": {"mid": "m-55", "text": "سعر"},
            }],
        }],
    }

    event = parse_meta_messaging_payload(payload)[0]

    assert event["external_message_id"] == "m-55"
    assert event["referral"]["ad_id"] == "AD55"
    assert event["ads_context_data"]["ad_title"] == "شاشة جنرال حجم 55"
    assert event["has_message"] is True


def test_graph_attachment_shape_is_imported_as_an_image():
    details = meta_attachment_details({
        "data": [{
            "mime_type": "image/jpeg",
            "image_data": {"url": "https://example.com/product.jpg"},
        }],
    })

    assert details["type"] == "image"
    assert details["url"] == "https://example.com/product.jpg"


def test_messenger_like_sticker_is_not_treated_as_image():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE1",
            "messaging": [{
                "sender": {"id": "CUSTOMER1"},
                "recipient": {"id": "PAGE1"},
                "timestamp": 123456,
                "message": {
                    "mid": "m-like",
                    "attachments": [{
                        "type": "sticker",
                        "payload": {
                            "sticker_id": "369239263222822",
                            "url": "https://example.com/like.png",
                        },
                    }],
                },
            }],
        }],
    }

    event = parse_meta_messaging_payload(payload)[0]

    assert event["message_type"] == "text"
    assert event["text"] == "لايك"
    assert event["attachment_url"] == ""
    assert event["is_like"] is True


def test_messenger_regular_sticker_is_not_treated_as_image():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE1",
            "messaging": [{
                "sender": {"id": "CUSTOMER1"},
                "recipient": {"id": "PAGE1"},
                "timestamp": 123456,
                "message": {
                    "mid": "m-sticker",
                    "attachments": [{
                        "type": "sticker",
                        "payload": {
                            "sticker_id": "12345",
                            "url": "https://example.com/sticker.png",
                        },
                    }],
                },
            }],
        }],
    }

    event = parse_meta_messaging_payload(payload)[0]

    assert event["message_type"] == "sticker"
    assert event["text"] == "[ملصق]"
    assert event["attachment_url"] == ""
    assert event["is_like"] is False


def test_meta_file_attachment_with_voice_url_is_audio():
    details = meta_attachment_details({
        "data": [{
            "type": "file",
            "file_url": "https://cdn.example.com/voice.ogg",
        }],
    })

    assert details["type"] == "audio"
    assert details["url"] == "https://cdn.example.com/voice.ogg"


def test_messenger_file_voice_payload_is_audio():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE1",
            "messaging": [{
                "sender": {"id": "CUSTOMER1"},
                "recipient": {"id": "PAGE1"},
                "timestamp": 123456,
                "message": {
                    "mid": "m-voice",
                    "attachments": [{
                        "type": "file",
                        "payload": {"url": "https://cdn.example.com/voice.ogg"},
                    }],
                },
            }],
        }],
    }

    event = parse_meta_messaging_payload(payload)[0]

    assert event["message_type"] == "audio"
    assert event["attachment_url"] == "https://cdn.example.com/voice.ogg"


def test_meta_comment_notice_is_structured_instead_of_rendered_as_a_raw_link():
    context = extract_meta_system_message_context(
        "أنت بصدد الرد على تعليق مستخدم على منشور على صفحتك. عرض التعليق."
        "(https://facebook.com/reel/1354824573504143/?comment_id=1332896605725923)"
    )

    assert context["type"] == "comment_reply"
    assert context["reel_id"] == "1354824573504143"
    assert context["comment_id"] == "1332896605725923"
    assert context["is_meta_system"] is True


def test_meta_marketing_permission_notice_is_structured():
    context = extract_meta_system_message_context(
        "تريد صفحة Finora إرسال رسائل إليك. تعرف على المزيد "
        "https://www.facebook.com/help/messenger-app/564030381383143"
    )

    assert context["type"] == "marketing_permission"


def test_tv_resolution_is_not_treated_as_customer_budget():
    assert extract_budget("4K") is None
    assert extract_budget("8k") is None
    assert extract_budget("ميزانيتي 300 الف") == 300_000


def test_model_number_can_supply_screen_size():
    assert _product_size("شاشة هيتاشي موديل 5500") == 55


def test_tcl_reply_is_direct_and_uses_live_alternatives():
    products = [
        {"product_id": 1, "name": "شاشة جنرال حجم 55", "price": 339_000},
        {"product_id": 2, "name": "شاشة هيتاشي موديل 5500", "price": 325_000},
        {"product_id": 3, "name": "شاشة ال جي حجم 55", "price": 349_000},
    ]

    result = _unsupported_brand_result("TCL", products, 55)

    assert "TCL غير متوفرة" in result["reply"]
    assert "جنرال" in result["reply"]
    assert "هيتاشي" in result["reply"]
    assert "المتوفر" not in result["reply"]
    assert result["product_ids"] == [1, 2, 3]


def test_ad_price_reply_answers_without_reasking_for_product():
    result = _direct_ad_price_result(
        {
            "product_id": 1,
            "name": "شاشة جنرال حجم 55",
            "price": 339_000,
            "warranty": "الضمان سنة",
            "delivery": "التوصيل مجاني",
        },
        {"title": "إعلان شاشة جنرال 55"},
    )

    assert "339,000 د.ع" in result["reply"]
    assert "أي منتج" not in result["reply"]
    assert result["sales_strategy"] == "answer_from_ad_context"
