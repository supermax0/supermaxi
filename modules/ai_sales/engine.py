"""Inbound persistence, background processing, lead updates, and outbound delivery."""
from __future__ import annotations

import os
import re
import secrets
import time
from datetime import datetime, timedelta
from threading import Thread

from flask import current_app, g

from extensions import db
from models.customer import Customer
from .agent import (
    extract_budget,
    generate_sales_reply,
    intelligence_policy,
    _quick_greeting_reply,
    _quick_gratitude_reply,
    is_affirmative_to_specs_offer,
    is_greeting_message,
    is_mid_range_preference,
    is_positive_ack,
    is_price_objection,
    is_purchase_intent,
    is_show_all_options_request,
    is_spec_request,
)
from .channels import WhatsAppClient, channel_client, outbound_message_id
from .decision_engine import (
    OBJECTION_LABELS,
    PRIORITY_LABELS,
    calculate_lead_state,
    classify_objection,
    next_best_action,
    rank_products_for_customer,
    update_customer_facts,
)
from .media import analyze_image, download_inbound_media, generate_speech, transcribe_audio
from .links import extract_link_previews, first_map_preview
from .message_guard import classify_customer_message, normalize_arabic
from .models import AISalesAgentProfile, AISalesConversation, AISalesLead, AISalesMessage
from .order_service import (
    build_pending_order,
    create_confirmed_order,
    extract_order_quantity,
    find_existing_ai_order,
    is_explicit_order_confirmation,
    is_order_revision_or_cancellation,
    is_order_summary_request,
    order_data_complete,
    pending_order_summary,
    refresh_pending_order,
    update_pending_order_quantity,
)
from .product_tools import (
    filter_products_by_features,
    filter_products_by_manager_instructions,
    find_nearest_smaller_foot_products,
    get_available_screen_products,
    get_fridge_products,
    get_product_media,
    get_products_by_ids,
    has_product_query,
    is_redundant_spec_point,
    log_product_search,
    parse_foot_size,
    relevant_selling_point,
    requested_product_features,
    search_products,
    unique_selling_points,
)
from .schema import ensure_ai_sales_schema


def get_or_create_conversation(
    channel,
    *,
    external_contact_id: str,
    phone: str,
    contact_name: str = "",
    contact_profile_picture_url: str = "",
):
    conversation = AISalesConversation.query.filter_by(
        channel_account_id=channel.id,
        external_contact_id=external_contact_id,
    ).first()
    if conversation:
        if contact_name and (not conversation.contact_name or conversation.contact_name == external_contact_id):
            conversation.contact_name = contact_name
        if contact_profile_picture_url:
            conversation.contact_profile_picture_url = contact_profile_picture_url
        if conversation.status == "closed":
            reply_mode = (channel.reply_mode or "ai").strip().lower()
            use_ai = reply_mode == "ai"
            use_employee = reply_mode == "employee"
            conversation.status = "waiting_employee" if use_employee else "open"
            conversation.ai_enabled = use_ai
            conversation.human_takeover = use_employee
            conversation.assigned_employee_id = channel.default_employee_id
            conversation.ai_paused_until = None
            conversation.handoff_reason = None
            conversation.closed_at = None
        return conversation
    customer = Customer.query.filter_by(phone=phone).first() if phone else None
    if not customer and phone:
        customer = Customer(name=contact_name or f"WhatsApp {phone[-4:]}", phone=phone)
        db.session.add(customer)
        db.session.flush()
    reply_mode = (channel.reply_mode or "ai").strip().lower()
    use_ai = reply_mode == "ai"
    use_employee = reply_mode == "employee"
    conversation = AISalesConversation(
        channel_account_id=channel.id,
        customer_id=customer.id if customer else None,
        external_contact_id=external_contact_id,
        external_phone=phone,
        contact_name=contact_name,
        contact_profile_picture_url=contact_profile_picture_url or None,
        sales_stage="new",
        ai_enabled=use_ai,
        human_takeover=use_employee,
        assigned_employee_id=channel.default_employee_id,
        status="waiting_employee" if use_employee else "open",
    )
    db.session.add(conversation)
    db.session.flush()
    db.session.add(AISalesLead(conversation_id=conversation.id, customer_id=conversation.customer_id))
    return conversation


def recent_history(conversation_id: int, limit: int = 12, *, before_message_id: int | None = None) -> list[dict]:
    query = AISalesMessage.query.filter_by(conversation_id=conversation_id)
    if before_message_id:
        query = query.filter(AISalesMessage.id < int(before_message_id))
    rows = query.order_by(AISalesMessage.id.desc()).limit(limit).all()
    return [
        {
            "role": "assistant" if row.sender_type in {"ai", "employee"} else "user",
            "content": row.text_content or row.transcription or "",
        }
        for row in reversed(rows)
        if (row.text_content or row.transcription)
    ]


def pause_conversation_for_human(
    conversation: AISalesConversation,
    *,
    employee_id: int | None = None,
    reason: str = "رد موظف",
    minutes: int | None = None,
    indefinite: bool = False,
) -> None:
    """Pause AI after a human reply without permanently disabling an AI channel."""
    profile = AISalesAgentProfile.query.order_by(AISalesAgentProfile.id.asc()).first()
    pause_minutes = max(1, min(int(minutes or getattr(profile, "human_takeover_minutes", 30) or 30), 1440))
    channel_uses_ai = str(conversation.channel.reply_mode or "ai").strip().lower() == "ai"
    conversation.human_takeover = True
    conversation.ai_enabled = False if indefinite else channel_uses_ai
    conversation.ai_paused_until = None if indefinite else datetime.utcnow() + timedelta(minutes=pause_minutes)
    conversation.handoff_reason = str(reason or "رد موظف")[:300]
    conversation.status = "human_active"
    if employee_id:
        conversation.assigned_employee_id = employee_id


def resume_conversation_ai_if_due(conversation: AISalesConversation) -> bool:
    if not conversation.ai_paused_until or conversation.ai_paused_until > datetime.utcnow():
        return False
    conversation.ai_paused_until = None
    conversation.handoff_reason = None
    if str(conversation.channel.reply_mode or "ai").strip().lower() == "ai":
        conversation.human_takeover = False
        conversation.ai_enabled = True
        conversation.status = "open"
        conversation.assigned_employee_id = conversation.channel.default_employee_id
        return True
    return False


def _history_budget(history: list[dict]) -> int | None:
    for row in reversed(history):
        if row.get("role") != "user":
            continue
        value = extract_budget(str(row.get("content") or ""))
        if value:
            return value
    return None


def _history_anchor(history: list[dict]) -> str:
    ignored = {"هلا", "هلو", "هاي", "السلام عليكم", "شكرا", "شكراً", "تمام", "زين"}
    for row in reversed(history):
        if row.get("role") != "user":
            continue
        value = str(row.get("content") or "").strip()
        if value and value.lower() not in ignored and not is_price_objection(value) and has_product_query(value):
            return value[:500]
    return ""


def _product_family(value: str) -> str:
    normalized = (value or "").translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})).lower()
    if re.search(r"ثلاجه|ثلاجات|فريزر|براد\s*(?:كهرب|كهرباء|كمبرسر|\d|قدم|ft)", normalized):
        return "refrigerator"
    if re.search(r"مبرد|كولر|براد\s*(?:ماء|هواء)", normalized):
        return "air_cooler"
    families = (
        # شاسة / شاسه are common typos for شاشة
        ("screen", r"شاشه|شاسة|شاسه|شاشات|تلفزيون|تلفاز|\btv\b"),
        ("refrigerator", r"ثلاجه|ثلاجات|فريزر"),
        ("air_cooler", r"مبرد|كولر"),
        ("washer", r"غساله|غسالات"),
        ("air_conditioner", r"سبلت|مكيف|تكييف"),
        ("router", r"راوتر|مودم|واي\s*فاي|wifi"),
    )
    return next((family for family, pattern in families if re.search(pattern, normalized)), "")


def _product_matches_family(product: dict, family: str) -> bool:
    if not family:
        return True
    product_text = " ".join(
        str(product.get(key) or "")
        for key in ("official_name", "name", "category", "catalog_category", "brand", "model", "description")
    )
    normalized = product_text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})).lower()
    english_family_patterns = {
        "screen": r"\b(?:screen|smart\s*tv|television|tv|display)\b",
        "refrigerator": r"\b(?:refrigerator|fridge|freezer)\b",
        "air_cooler": r"\b(?:air\s*cooler|cooler)\b",
        "washer": r"\b(?:washer|washing\s*machine)\b",
        "air_conditioner": r"\b(?:split|air\s*conditioner|ac)\b",
        "router": r"\b(?:router|modem|wifi)\b",
    }
    detected = _product_family(product_text)
    if not detected:
        for candidate, pattern in english_family_patterns.items():
            if re.search(pattern, normalized, re.IGNORECASE):
                detected = candidate
                break
    if detected:
        return detected == family
    family_patterns = {
        "screen": r"شاشه|شاشة|شاسة|شاسه|شاشات|تلفزيون|تلفاز",
        "refrigerator": r"ثلاجه|ثلاجة|ثلاجات|فريزر|براد\s*(?:كهرب|كهرباء|كمبرسر|\d|قدم|ft)",
        "air_cooler": r"مبرد|كولر|براد\s*(?:ماء|هواء)",
        "washer": r"غساله|غسالة|غسالات",
        "air_conditioner": r"سبلت|مكيف|تكييف",
        "router": r"راوتر|مودم|واي\s*فاي|wifi",
    }
    return bool(family_patterns.get(family) and re.search(family_patterns[family], normalized, re.IGNORECASE))


def _is_price_flexibility_question(value: str) -> bool:
    normalized = (value or "").translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})).lower()
    return bool(re.search(
        r"بي(?:ه)?\s+مجال|اكو\s+مجال|مجال\s+بالسعر|اخر\s+سعر|سعر(?:ه|ها)?\s+نهائي|"
        r"يصير\s+اقل|ينقص|تنقص|تخفض|تراعي",
        normalized,
    ))


def _direct_screen_size_price(value: str) -> int | None:
    translated = (value or "").translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    ))
    normalized = translated.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه"})).lower()
    has_price_word = bool(re.search(r"(?:سعر|سعره|سعرها|بكم|بشكد|شكد|بيش|كم)", normalized, re.IGNORECASE))
    has_screen_word = bool(re.search(r"شاشه|شاسة|شاسه|شاشات|تلفزيون|تلفاز|\btv\b", normalized, re.IGNORECASE))
    if not has_price_word and not has_screen_word:
        return None
    values = [int(raw) for raw in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", translated)]
    return next((size for size in values if 20 <= size <= 100), None)


def _bare_screen_size(value: str) -> int | None:
    translated = (value or "").translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    ))
    compact = re.sub(r"[^\d]+", " ", translated).strip()
    values = [int(raw) for raw in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", compact)]
    if len(values) == 1 and 20 <= values[0] <= 100:
        return values[0]
    return None


def _loose_fridge_foot_size(value: str, *, require_fridge_word: bool = True) -> int | None:
    normalized = (value or "").translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    ))
    if require_fridge_word and not re.search(r"ثلاجه|ثلاجة|ثلاجات|براد|فريزر", normalized):
        return None
    explicit = parse_foot_size(normalized)
    if explicit is not None:
        return explicit
    if not re.search(r"(?:سعر|سعره|سعرها|بكم|بشكد|شكد|بيش|كم)", normalized, re.IGNORECASE):
        return None
    values = [int(raw) for raw in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", normalized)]
    return next((size for size in values if 3 <= size <= 20), None)


def _bare_fridge_foot_size(value: str) -> int | None:
    normalized = normalize_arabic(value or "")
    match = re.fullmatch(r"(?:حجم|قياس|مقاس)?\s*(\d{1,2})\s*", normalized)
    if not match:
        return None
    size = int(match.group(1))
    if 3 <= size <= 25:
        return size
    return None


def _direct_size_price_result(products: list[dict], requested_size: int) -> dict:
    choices = sorted(
        products,
        key=lambda row: (int(row.get("price") or 0), str(row.get("name") or "")),
    )[:1]
    selected = choices[0]
    price = int(selected.get("price") or 0)
    warranty = str(selected.get("warranty") or "ضمان سنة")
    delivery = str(selected.get("delivery") or "توصيل مجاني")
    lines = [
        f"إي، موجود حجم {requested_size}:",
        f"• {selected.get('name')}",
        f"• السعر: {price:,} د.ع",
        f"• {warranty}",
        f"• {delivery}",
        "",
        "تحب أدزلك صورته أو أثبته إلك؟",
    ]
    return {
        "reply": "\n".join(lines),
        "product_ids": [int(row.get("product_id") or 0) for row in choices],
        "customer_intent": "price_inquiry",
        "customer_sentiment": "neutral",
        "sales_stage": "product_selection",
        "sales_strategy": "direct_price_answer",
        "main_need": f"شاشة حجم {requested_size}",
        "primary_objection": "",
        "next_action": "معرفة الماركة التي يفضلها الزبون",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _screen_size_from_text(value: str) -> int | None:
    translated = (value or "").translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    ))
    values = [int(raw) for raw in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", translated)]
    return next((size for size in values if 20 <= size <= 100), None)


def _unsupported_screen_brand(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", (value or "").lower()).strip()
    if re.search(r"\bt\s*c\s*l\b|تي\s*سي\s*ال|تيسيال", normalized, re.IGNORECASE):
        return "TCL"
    return ""


def _screen_brand_labels(products: list[dict]) -> list[str]:
    joined = " ".join(str(row.get("name") or "") for row in products).lower()
    known = (
        ("جنرال", ("جنرال",)),
        ("هيتاشي", ("هيتاشي",)),
        ("LG", ("ال جي", "الجي", "ال جي بابل", "الجي بابل")),
        ("سامسونگ", ("سامسونك", "سامسونگ", "سامسونج")),
        ("برو ماكس", ("برو ماكس", "بروماكس")),
        ("كراون", ("كراون",)),
    )
    return [label for label, aliases in known if any(alias in joined for alias in aliases)]


def _unsupported_brand_result(brand: str, products: list[dict], requested_size: int | None) -> dict:
    choices = products[:3]
    if requested_size and choices:
        lines = [f"ماركة {brand} غير متوفرة حالياً. الموجود عندنا بحجم {requested_size}:"]
        lines.extend(
            f"• {row.get('name')} — {int(row.get('price') or 0):,} د.ع"
            for row in choices
        )
        lines.extend(["", "أي خيار تريد أعطيك مواصفاته؟"])
        product_ids = [int(row.get("product_id") or 0) for row in choices]
        next_action = "اختيار أحد البدائل المتوفرة"
        missing = []
    else:
        brands = _screen_brand_labels(products)
        brand_text = "، ".join(brands[:4]) if brands else "ماركات ثانية متوفرة"
        lines = [
            f"ماركة {brand} غير متوفرة حالياً، وعدنا بدائل من {brand_text}.",
            "شكد الحجم اللي تريده؟",
        ]
        product_ids = []
        next_action = "معرفة حجم الشاشة المطلوب"
        missing = ["حجم الشاشة"]
    return {
        "reply": "\n".join(lines),
        "product_ids": product_ids,
        "customer_intent": "product_search",
        "customer_sentiment": "neutral",
        "sales_stage": "product_selection" if requested_size else "discovery",
        "sales_strategy": "offer_live_alternatives",
        "main_need": f"بديل متوفر عن {brand}",
        "primary_objection": "",
        "next_action": next_action,
        "missing_information": missing,
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _ad_context_search_text(context: dict) -> str:
    ad = context.get("ad_context") or {}
    return " ".join(
        str(ad.get(key) or "").strip()
        for key in ("title", "body", "ref")
        if str(ad.get(key) or "").strip()
    )[:1800]


def _is_generic_price_request(value: str) -> bool:
    normalized = re.sub(r"[^\w\u0600-\u06ff]+", " ", value or "").strip().lower()
    return bool(re.fullmatch(r"(?:سعر|السعر|بكم|بشكد|شكد السعر)", normalized))


def _direct_ad_price_result(product: dict, ad_context: dict) -> dict:
    name = str(product.get("name") or "المنتج")
    price = int(product.get("price") or 0)
    warranty = str(product.get("warranty") or "الضمان سنة").strip()
    delivery = str(product.get("delivery") or "التوصيل مجاني").strip()
    reply = f"سعر {name}: {price:,} د.ع\n{warranty}، و{delivery}.\nتريد تثبته؟"
    return {
        "reply": reply,
        "product_ids": [int(product.get("product_id") or 0)],
        "customer_intent": "price_inquiry",
        "customer_sentiment": "interested",
        "sales_stage": "product_selection",
        "sales_strategy": "answer_from_ad_context",
        "main_need": str(ad_context.get("title") or name),
        "primary_objection": "",
        "next_action": "تأكيد اختيار المنتج",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _dollar_amount_in_text(value: str) -> int | None:
    translated = (value or "").translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    ))
    if re.search(r"د\.ع|دينار", translated, re.IGNORECASE):
        return None
    values = []
    for raw in re.findall(r"(?<!\d)(\d[\d,\.]{1,8})(?!\d)", translated):
        number = int(re.sub(r"[^\d]", "", raw) or 0)
        if number >= 1000 and number % 1000 == 0:
            number //= 1000
        values.append(number)
    return next((amount for amount in values if 20 <= amount <= 999), None)


def _history_requested_foot_size(
    history: list[dict] | None,
    text: str = "",
    facts: dict | None = None,
) -> int | None:
    facts = facts or {}
    current = str(text or "").strip()
    burst_parts: list[str] = []
    if "\n" in current and ":" in current:
        for line in current.splitlines():
            part = line.split(":", 1)[1].strip() if ":" in line else line.strip()
            if part:
                burst_parts.append(part)

    direct = None if burst_parts else parse_foot_size(current)
    if direct:
        return direct

    fridge_pattern = r"ثلاجه|ثلاجة|ثلاجات|براد|فريزر"
    if burst_parts:
        normalized_parts = [normalize_arabic(part) for part in burst_parts if str(part or "").strip()]
        joined_burst = " ".join(normalized_parts)
        has_burst_fridge = bool(
            str(facts.get("product_family") or "").strip().lower() == "refrigerator"
            or re.search(fridge_pattern, joined_burst)
        )
        if has_burst_fridge:
            parsed = parse_foot_size(joined_burst)
            if parsed:
                return parsed

            # Some channels deliver a single request as separate messages:
            # "fridge" / "7" / "foot". Rebuild that intent before using old facts.
            foot_indexes = [
                idx for idx, part in enumerate(normalized_parts)
                if re.search(r"(?:قدم|قدام|فوت|ft|feet)", part, re.IGNORECASE)
            ]
            for foot_index in foot_indexes:
                start = max(0, foot_index - 3)
                for idx in range(foot_index, start - 1, -1):
                    bare = _bare_fridge_foot_size(normalized_parts[idx])
                    if bare:
                        return bare
                parsed = parse_foot_size(" ".join(normalized_parts[start:foot_index + 1]))
                if parsed:
                    return parsed

    recent_user_texts: list[str] = []
    for row in history or []:
        if row.get("role") != "user":
            continue
        content = str(row.get("content") or "").strip()
        if content:
            recent_user_texts.append(content)

    # Customers often send one request as short bursts: "ثلاجه" then "7" then "قدم".
    # Treat the latest customer burst as one sentence before falling back to old facts.
    window = recent_user_texts[-8:]
    for part in burst_parts:
        if part and (not window or window[-1] != part):
            window.append(part)
    if current and not burst_parts and (not window or window[-1] != current):
        window.append(current)
    combined = " ".join(window[-6:])

    has_fridge_context = bool(
        str(facts.get("product_family") or "").strip().lower() == "refrigerator"
        or facts.get("requested_foot_size")
        or re.search(fridge_pattern, combined)
    )
    combined_size = parse_foot_size(combined)
    if has_fridge_context and combined_size:
        return combined_size

    if has_fridge_context:
        bare = _bare_fridge_foot_size(current)
        if bare:
            return bare
        for content in reversed(window):
            bare = _bare_fridge_foot_size(content)
            if bare:
                return bare

    if facts.get("requested_foot_size"):
        try:
            return int(facts["requested_foot_size"])
        except (TypeError, ValueError):
            pass
    return None


def _is_facebook_ad_reference(value: str) -> bool:
    normalized = (value or "").translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه"})).lower()
    return bool(re.search(r"اعلان|ناشر|ناشرين|منشور|مكتوب|حاط|بالصوره|بالصورة|بوست|فيس\s*بوك|فيسبوك", normalized))


def _advertised_dollar_amount(value: str, history: list[dict] | None = None) -> int | None:
    """Detect an ad price the customer thinks is in IQD but is actually USD.

    Triggers on ad-publish words (ناشر/اعلان/فيس بوك/...) or an explicit dollar mention.
    When the current message only asks about the currency (e.g. "لو دولار") the
    number is recovered from the recent customer history.
    """
    normalized = (value or "").translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه"})).lower()
    has_publish_word = _is_facebook_ad_reference(normalized)
    has_dollar_word = bool(re.search(r"دولار|\$|بالدولار", normalized))
    if not has_publish_word and not has_dollar_word:
        return None
    amount = _dollar_amount_in_text(value)
    if amount is not None:
        return amount
    for row in reversed(history or []):
        if row.get("role") != "user":
            continue
        recovered = _dollar_amount_in_text(str(row.get("content") or ""))
        if recovered is not None:
            return recovered
    return None


def _pick_advertised_dollar_product(
    *,
    amount: int,
    products: list[dict],
    focused_products: list[dict],
    previous_products: list[dict],
    history: list[dict],
    customer_facts: dict,
    text: str,
    context: dict,
) -> dict | None:
    """Bind an advertised USD amount to the fridge size the customer already asked for."""
    mapped = dict(context.get("advertised_dollar") or {})
    if int(mapped.get("amount") or 0) == int(amount) and mapped.get("product_id"):
        rows = get_products_by_ids([int(mapped["product_id"])], in_stock_only=False)
        if rows:
            return rows[0]

    foot = _history_requested_foot_size(history, text, customer_facts)
    # Common Meta fridge ads for this shop: 128 USD maps to the 7ft unit.
    if not foot and int(amount) == 128:
        foot = 7
    if foot:
        features = requested_product_features(text)
        if not features:
            for row in reversed(history or []):
                if row.get("role") != "user":
                    continue
                features = requested_product_features(str(row.get("content") or ""))
                if features:
                    break
        fridge = get_fridge_products(foot_size=foot, in_stock_only=False, limit=8)
        fridge = filter_products_by_features(fridge, features) if features else fridge
        if fridge:
            return fridge[0]

    candidates: list[dict] = []
    seen: set[int] = set()
    for row in list(products or []) + list(focused_products or []) + list(previous_products or []):
        product_id = int(row.get("product_id") or 0)
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        candidates.append(row)
    if foot:
        matching = [row for row in candidates if _foot_size_from_product(row) == foot]
        if matching:
            return matching[0]
    return candidates[0] if candidates else None


def _advertised_dollar_price_result(product: dict, amount: int) -> dict:
    name = str(product.get("official_name") or product.get("name") or "المنتج").strip()
    price = int(product.get("price") or 0)
    foot = _foot_size_from_product(product)
    size_note = f" بقياس {foot} قدم" if foot else ""
    return {
        "reply": (
            f"الـ{amount} المذكورة بالإعلان هي بالدولار، مو بالدينار العراقي.\n"
            f"السعر الحالي المسجل لـ{name}{size_note}: {price:,} د.ع."
        ),
        "product_ids": [int(product.get("product_id") or 0)],
        "customer_intent": "price_inquiry",
        "customer_sentiment": "neutral",
        "sales_stage": "product_selection",
        "sales_strategy": "clarify_ad_currency",
        "main_need": name,
        "primary_objection": "السعر",
        "next_action": "تأكيد مناسبة السعر الحالي للزبون",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
        "advertised_dollar_amount": int(amount),
        "advertised_foot_size": foot,
    }


def _latest_message_mentions_current_product(text: str) -> bool:
    normalized = normalize_arabic(text or "")
    if not normalized:
        return False
    return bool(re.search(
        r"(?:هذا|هاذا|هاي|هذه|هذي|بي|بيه|بيها|عليه|عليها|سعره|سعرها|شكد|بيش|بكم|"
        r"ضمان|كفاله|كفالة|مواصفات|مميزاته|صورته|صورتها|فيديو|الوان|ألوان|قياس|حجم|"
        r"توصيل|يوصل|متوفر|متوفرة|اخذه|آخذه|احجز|اطلب|يناسب|تنصح)",
        normalized,
    ))


def _latest_message_needs_product_answer(
    text: str,
    message_guard,
    *,
    current_product_family: str,
    direct_screen_size_price: int | None,
    requested_foot_size: int | None,
    requested_features: list[str] | None,
    requested_media: str | None,
    purchase_intent: bool,
    price_objection: bool,
    price_flexibility_question: bool,
    mid_range_preference: bool,
    show_all_options: bool,
    advertised_dollar_amount: int | None,
    visual_reference_active: bool,
    previous_products: list[dict],
) -> bool:
    """Decide whether the latest customer message should pull product context.

    The reply may still use conversation history for tone and pronouns, but stale
    products must not drive answers to greetings, thanks, or general chat.
    """
    if getattr(message_guard, "is_greeting", False) or getattr(message_guard, "is_gratitude", False):
        return False
    if visual_reference_active or requested_media or purchase_intent or price_objection or price_flexibility_question:
        return True
    if mid_range_preference or show_all_options or advertised_dollar_amount:
        return True
    if current_product_family or direct_screen_size_price or requested_foot_size or requested_features:
        return True
    if getattr(message_guard, "family", "") or getattr(message_guard, "needs_product_context", False):
        return True
    if getattr(message_guard, "intent", "") in {"product_search", "price_inquiry"}:
        return True
    if previous_products and _latest_message_mentions_current_product(text):
        return True
    return False


def _pending_has_explicit_selection(pending: dict) -> bool:
    product_id = int(pending.get("product_id") or 0)
    return bool(
        int(pending.get("selection_message_id") or 0)
        and int(pending.get("selection_product_id") or 0) == product_id
    )


_BURST_WAIT_SECONDS = 1.8
_BURST_LOOKBACK_SECONDS = 12
_BATCHABLE_MESSAGE_TYPES = {"text", "button", "interactive"}

_VISUAL_REFERENCE_RE = re.compile(
    r"(?:هاي|هذي|هذه|الصورة|الصوره|صورتها|مثلها|منها|نفسها|نفس هذا|نفس هاي)",
    re.IGNORECASE,
)


def _is_visual_reference_followup(value: str) -> bool:
    return bool(_VISUAL_REFERENCE_RE.search(value or ""))


def _latest_visual_reference(conversation_id: int, before_message_id: int) -> dict:
    """Return the latest analyzed customer image before a deictic follow-up."""
    rows = (
        AISalesMessage.query.filter(
            AISalesMessage.conversation_id == conversation_id,
            AISalesMessage.direction == "inbound",
            AISalesMessage.message_type == "image",
            AISalesMessage.id < before_message_id,
        )
        .order_by(AISalesMessage.id.desc())
        .limit(3)
        .all()
    )
    for row in rows:
        analysis = str(row.get_media_metadata().get("vision_analysis") or "").strip()
        if analysis:
            return {
                "message_id": row.id,
                "analysis": analysis,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
    return {}


def _matches_requested_screen_size(product: dict, requested_size: int) -> bool:
    values = [
        int(value)
        for value in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", str(product.get("name") or ""))
    ]
    return requested_size in values


def _defer_to_newer_burst_message(inbound: AISalesMessage) -> bool:
    """Let the newest text message in a short customer burst own the AI reply."""
    if inbound.message_type not in _BATCHABLE_MESSAGE_TYPES:
        return False
    time.sleep(_BURST_WAIT_SECONDS)
    db.session.expire_all()
    refreshed = AISalesMessage.query.get(inbound.id)
    if not refreshed or refreshed.status not in {"received", "queued"}:
        return True
    newer = (
        AISalesMessage.query.filter(
            AISalesMessage.conversation_id == refreshed.conversation_id,
            AISalesMessage.direction == "inbound",
            AISalesMessage.id > refreshed.id,
            AISalesMessage.message_type.in_(_BATCHABLE_MESSAGE_TYPES),
            AISalesMessage.status.in_(("received", "queued", "processing")),
        )
        .order_by(AISalesMessage.id.desc())
        .first()
    )
    if not newer:
        return False
    refreshed.status = "batched"
    db.session.commit()
    current_app.logger.info(
        "AI_SALES_BURST deferred conversation_id=%s message_id=%s leader_id=%s",
        refreshed.conversation_id,
        refreshed.id,
        newer.id,
    )
    return True


def _claim_burst_messages(inbound: AISalesMessage) -> list[AISalesMessage]:
    """Attach recent unsent text messages to the claimed leader in chronological order."""
    if inbound.message_type not in _BATCHABLE_MESSAGE_TYPES:
        return [inbound]
    last_outbound = (
        AISalesMessage.query.filter_by(conversation_id=inbound.conversation_id, direction="outbound")
        .order_by(AISalesMessage.id.desc())
        .first()
    )
    cutoff_time = (inbound.created_at or datetime.utcnow()) - timedelta(seconds=_BURST_LOOKBACK_SECONDS)
    query = AISalesMessage.query.filter(
        AISalesMessage.conversation_id == inbound.conversation_id,
        AISalesMessage.direction == "inbound",
        AISalesMessage.id <= inbound.id,
        AISalesMessage.created_at >= cutoff_time,
        AISalesMessage.message_type.in_(_BATCHABLE_MESSAGE_TYPES),
        AISalesMessage.status.in_(("received", "queued", "batched", "processing")),
    )
    if last_outbound:
        query = query.filter(AISalesMessage.id > last_outbound.id)
    rows = query.order_by(AISalesMessage.id.asc()).all()

    # Include recent processed text that never got an outbound reply (stale-suppressed
    # leaders), so a follow-up like "سعر" still sees "شاشه 65".
    orphan_cutoff = (inbound.created_at or datetime.utcnow()) - timedelta(seconds=max(_BURST_LOOKBACK_SECONDS, 45))
    orphan_query = AISalesMessage.query.filter(
        AISalesMessage.conversation_id == inbound.conversation_id,
        AISalesMessage.direction == "inbound",
        AISalesMessage.id < inbound.id,
        AISalesMessage.created_at >= orphan_cutoff,
        AISalesMessage.message_type.in_(_BATCHABLE_MESSAGE_TYPES),
        AISalesMessage.status == "processed",
    )
    if last_outbound:
        orphan_query = orphan_query.filter(AISalesMessage.id > last_outbound.id)
    for orphan in orphan_query.order_by(AISalesMessage.id.asc()).all():
        has_reply = AISalesMessage.query.filter(
            AISalesMessage.conversation_id == inbound.conversation_id,
            AISalesMessage.direction == "outbound",
            AISalesMessage.id > orphan.id,
            AISalesMessage.id < inbound.id,
        ).first()
        if not has_reply and orphan not in rows:
            rows.append(orphan)
    if inbound not in rows:
        rows.append(inbound)
    rows.sort(key=lambda row: row.id)
    for row in rows:
        row.status = "processing"
    db.session.commit()
    if len(rows) > 1:
        current_app.logger.info(
            "AI_SALES_BURST claimed conversation_id=%s leader_id=%s message_ids=%s",
            inbound.conversation_id,
            inbound.id,
            [row.id for row in rows],
        )
    return rows


def _newer_customer_message(inbound: AISalesMessage) -> AISalesMessage | None:
    """Return a message that made the current AI result stale while it was thinking."""
    db.session.expire_all()
    return (
        AISalesMessage.query.filter(
            AISalesMessage.conversation_id == inbound.conversation_id,
            AISalesMessage.direction == "inbound",
            AISalesMessage.id > inbound.id,
        )
        .order_by(AISalesMessage.id.desc())
        .first()
    )


def _split_outbound_reply(reply: str, *, max_parts: int = 3) -> list[str]:
    """Turn a structured answer into a few ordered message bubbles."""
    cleaned = re.sub(r"\n{3,}", "\n\n", str(reply or "").strip())
    if not cleaned:
        return []
    blocks = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if len(blocks) == 1:
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if len(lines) >= 4 and lines[-1].endswith(("?", "؟")):
            blocks = ["\n".join(lines[:-1]), lines[-1]]
    if len(blocks) <= max_parts:
        return blocks
    return blocks[: max_parts - 1] + ["\n\n".join(blocks[max_parts - 1 :])]


def _requested_product_media(text: str) -> str | None:
    """Detect when the customer asks us to SEND product media, not when they send a photo."""
    normalized = str(text or "").strip().lower()
    if re.search(
        r"(?:دز|دزلي|ارسل|أرسل|ابعت|ابعث|عطني|عطيني|اريد|أريد|اكو|عندكم|عندك).{0,24}(?:صورة|صوره|صور)"
        r"|(?:صورة|صوره|صور).{0,16}(?:المنتج|اللي|حق|مال|لها|له|الالوان|الألوان)"
        r"|صوره?\s*(?:لو\s*)?سمحت",
        normalized,
    ):
        return "image"
    if re.search(
        r"(?:دز|دزلي|ارسل|أرسل|ابعت|ابعث|عطني|عطيني|اريد|أريد|اكو|عندكم|عندك).{0,24}(?:فيديو|فديو|مقطع)"
        r"|(?:فيديو|فديو|مقطع).{0,16}(?:المنتج|اللي|حق|مال|لها|له)",
        normalized,
    ):
        return "video"
    return None


def _vision_unavailable_result() -> dict:
    return {
        "reply": (
            "وصلتني الصورة، بس تحليل الصور متوقف حالياً من خدمة الذكاء. "
            "اكتبلي اسم المنتج والحجم (مثلاً: شاشة جنرال 55) وأطلعلك السعر والمواصفات فوراً."
        ),
        "product_ids": [],
        "customer_intent": "product_search",
        "customer_sentiment": "interested",
        "sales_stage": "product_selection",
        "sales_strategy": "clarify_visual_reference",
        "main_need": "توضيح المنتج من الصورة",
        "primary_objection": "",
        "next_action": "طلب اسم المنتج والحجم لأن تحليل الصورة غير متاح",
        "missing_information": ["اسم المنتج أو الحجم"],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _media_request_result(
    product: dict,
    media_type: str,
    assets: list[dict],
    customer_message: str,
) -> dict:
    product_id = int(product.get("product_id") or 0)
    product_name = str(product.get("official_name") or product.get("name") or "المنتج").strip()
    color_match = re.search(
        r"(?:لون|اللون)\s+([^\s،,.؟?]+)",
        str(customer_message or ""),
        re.IGNORECASE,
    )
    requested_color = color_match.group(1).strip() if color_match else ""
    media_label = "الصورة" if media_type == "image" else "الفيديو"
    if assets:
        detail = f" للون {requested_color}" if requested_color else ""
        reply = f"أكيد، هاي {media_label}{detail} المتوفرة لـ{product_name}."
        confidence = 100
    else:
        reply = f"حالياً ما عندي {media_label} مسجلة لـ{product_name}. إذا تحب أحوّلك للموظف حتى يوفرها إلك."
        confidence = 100
    return {
        "reply": reply,
        "product_ids": [product_id] if product_id else [],
        "customer_intent": "media_request",
        "customer_sentiment": "interested",
        "sales_stage": "product_selection",
        "sales_strategy": "grounded_product_media",
        "main_need": product_name,
        "primary_objection": "",
        "next_action": "إرسال وسائط المنتج" if assets else "توفير وسائط المنتج عبر الموظف",
        "missing_information": [],
        "customer_data": {},
        "confidence": confidence,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _deterministic_pending_result(context: dict, pending: dict, reply: str) -> dict:
    return {
        "reply": reply,
        "product_ids": [int(pending.get("product_id") or 0)],
        "customer_intent": "order_details",
        "customer_sentiment": "ready",
        "sales_stage": "waiting_confirmation",
        "sales_strategy": "close",
        "main_need": str(context.get("main_need") or pending.get("product_name") or "تأكيد الطلب"),
        "primary_objection": str(context.get("primary_objection") or ""),
        "next_action": "انتظار تأكيد صريح لإنشاء الطلب",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _foot_size_from_product(product: dict) -> int | None:
    value = str(product.get("official_name") or product.get("name") or "")
    return parse_foot_size(value)


def _product_detail_lines(
    product: dict,
    *,
    include_dimensions: bool = False,
    customer_message: str = "",
    requested_features: list[str] | None = None,
) -> list[str]:
    lines = [f"• السعر: {int(product.get('price') or 0):,} د.ع"]
    warranty = str(product.get("warranty") or "ضمان سنة").strip()
    delivery = str(product.get("delivery") or "توصيل مجاني").strip()
    if warranty and warranty not in "\n".join(lines):
        lines.append(f"• {warranty}")
    if delivery and delivery not in "\n".join(lines):
        lines.append(f"• {delivery}")
    highlight = relevant_selling_point(product, customer_message, requested_features)
    if highlight:
        lines.append(f"• يفيدك بـ: {highlight}")
    colors = [str(value).strip() for value in product.get("colors") or [] if str(value).strip()]
    if colors:
        lines.append(f"• الألوان: {'، '.join(colors)}")
    if include_dimensions:
        dimensions = product.get("dimensions") or {}
        labels = (
            ("العرض", dimensions.get("width_cm")),
            ("الارتفاع", dimensions.get("height_cm")),
            ("العمق", dimensions.get("depth_cm")),
        )
        available = [f"{label} {value:g} سم" for label, value in labels if value is not None]
        if available:
            lines.append(f"• الأبعاد: {'، '.join(available)}")
    return lines


def _direct_foot_size_result(
    products: list[dict],
    requested_size: int,
    customer_message: str,
    *,
    requested_features: list[str] | None = None,
) -> dict:
    if requested_features:
        products = filter_products_by_features(products, requested_features)
    selected_size = _foot_size_from_product(products[0]) if products else None
    exact = selected_size == requested_size
    selected_stock = int((products[0] or {}).get("stock") or 0) if products else 0
    choices = sorted(
        [row for row in products if _foot_size_from_product(row) == selected_size],
        key=lambda row: (int(row.get("price") or 0), str(row.get("name") or "")),
    )[:2]
    if exact and selected_stock <= 0:
        lines = [f"إي، قياس {requested_size} قدم مسجل ونكدر نحجزه:"]
    elif exact:
        lines = [f"إي، موجود قياس {requested_size} قدم:"]
    else:
        lines = [
            f"قياس {requested_size} قدم غير متوفر حالياً.",
            f"أقرب حجم موجود هو {selected_size} قدم:",
        ]
    include_dimensions = bool(re.search(r"عرض|ارتفاع|عمق|ابعاد|أبعاد|قياساته", customer_message or ""))
    for index, product in enumerate(choices):
        if index:
            lines.append("")
        lines.append(f"• {product.get('name')}")
        lines.extend(_product_detail_lines(
            product,
            include_dimensions=include_dimensions,
            customer_message=customer_message,
            requested_features=requested_features,
        ))
    lines.extend([
        "",
        "إذا يناسبك گلي أريده وأكمل وياك الطلب." if exact else "يناسبك هذا الحجم البديل؟",
    ])
    return {
        "reply": "\n".join(lines),
        "product_ids": [int(row.get("product_id") or 0) for row in choices],
        "customer_intent": "price_inquiry" if re.search(r"سعر|بكم|بشكد|شكد|بيش|كم", customer_message or "") else "product_search",
        "customer_sentiment": "interested",
        "sales_stage": "product_selection",
        "sales_strategy": "exact_or_nearest_live_size",
        "main_need": f"منتج قياس {requested_size} قدم",
        "primary_objection": "",
        "next_action": "تأكيد مناسبة القياس البديل" if not exact else "تأكيد مناسبة المنتج",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _fridge_recommendation_result(products: list[dict], customer_message: str) -> dict:
    choices = sorted(
        products[:3],
        key=lambda row: (int(row.get("price") or 0), str(row.get("name") or "")),
    )
    if not choices:
        return {}
    requested_size = _loose_fridge_foot_size(customer_message or "")
    if not requested_size:
        lines = ["هذني بعض الثلاجات المتوفرة حالياً:"]
        for product in choices:
            lines.append(f"• {product.get('name')} — {int(product.get('price') or 0):,} د.ع")
        lines.append("تحب أي قياس بالقدم أو شكد ميزانيتك حتى أرشحلك الأنسب؟")
        return {
            "reply": "\n".join(lines),
            "product_ids": [int(row.get("product_id") or 0) for row in choices if int(row.get("product_id") or 0)],
            "customer_intent": "product_search",
            "customer_sentiment": "interested",
            "sales_stage": "product_selection",
            "sales_strategy": "fridge_catalog_options",
            "main_need": "ثلاجة",
            "primary_objection": "",
            "next_action": "معرفة القياس أو الميزانية لاختيار ثلاجة مناسبة",
            "missing_information": ["القياس أو الميزانية"],
            "customer_data": {},
            "confidence": 100,
            "should_handoff": False,
            "handoff_reason": "",
        }
    lead = choices[0]
    lead_size = _foot_size_from_product(lead)
    lines = [f"أرشحلك {lead_size} قدم كبداية:" if lead_size else "أرشحلك هذا الخيار:"]
    lines.append(f"• {lead.get('name')}")
    lines.extend(_product_detail_lines(
        lead,
        include_dimensions=bool(re.search(r"عرض|ارتفاع|عمق|ابعاد|أبعاد|قياساته", customer_message or "")),
        customer_message=customer_message,
    ))
    lines.extend(["", "إذا يناسبك أدزلك فيديو أو أكمل وياك الحجز؟"])
    return {
        "reply": "\n".join(lines),
        "product_ids": [int(lead.get("product_id") or 0)],
        "customer_intent": "product_search",
        "customer_sentiment": "interested",
        "sales_stage": "product_selection",
        "sales_strategy": "fridge_best_value_recommendation",
        "main_need": "ثلاجة",
        "primary_objection": "",
        "next_action": "إرسال فيديو أو تأكيد الحجز",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _price_flexibility_reply(product: dict, smaller_products: list[dict] | None = None) -> str:
    name = str(product.get("official_name") or product.get("name") or "هذا المنتج").strip()
    price = int(product.get("price") or 0)
    lines = [f"سعر {name} ثابت حالياً: {price:,} د.ع."]
    smaller = (smaller_products or [])[:1]
    if smaller:
        alternative = smaller[0]
        alternative_size = _foot_size_from_product(alternative)
        lines.extend([
            "",
            f"إذا تريد أوفر، عندي حجم {alternative_size} قدم:",
            f"• {alternative.get('name')} — {int(alternative.get('price') or 0):,} د.ع",
        ])
        colors = [str(value).strip() for value in alternative.get("colors") or [] if str(value).strip()]
        if colors:
            lines.append(f"• الألوان: {'، '.join(colors)}")
        lines.extend(["", "تحب أبقى على هذا لو أعتمد الأصغر؟"])
    else:
        lines.append("إذا أعلى من ميزانيتك، گلي شكد حاط حتى أطلعلك بديل أوفر حقيقي.")
    return "\n".join(lines)


def _price_fixed_ack_result(product: dict) -> dict:
    name = str(product.get("official_name") or product.get("name") or "هذا المنتج").strip()
    price = int(product.get("price") or 0)
    return {
        "reply": f"تمام، السعر ثابت: {price:,} د.ع.\n• {name}\n\nتحب أكمل وياك الطلب؟",
        "product_ids": [int(product.get("product_id") or 0)] if int(product.get("product_id") or 0) else [],
        "customer_intent": "price_confirmation",
        "customer_sentiment": "interested",
        "sales_stage": "product_selection",
        "sales_strategy": "confirm_fixed_price",
        "main_need": name,
        "primary_objection": "",
        "next_action": "تأكيد إكمال الطلب بعد موافقة الزبون على السعر",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _product_specs_result(product: dict) -> dict:
    name = str(product.get("name") or product.get("official_name") or "المنتج").strip()
    lines = [f"مواصفات {name}:", f"• السعر: {int(product.get('price') or 0):,} د.ع"]
    colors = [str(value).strip() for value in product.get("colors") or [] if str(value).strip()]
    if colors:
        lines.append(f"• الألوان: {'، '.join(colors)}")
    for point in unique_selling_points(product, limit=5):
        lines.append(f"• {point}")
    description = str(product.get("description") or "").strip()
    if description and description not in "\n".join(lines) and not is_redundant_spec_point(description, name):
        lines.append(f"• {description[:220]}")
    warranty = str(product.get("warranty") or "").strip()
    if warranty:
        lines.append(f"• الضمان: {warranty}")
    delivery = str(product.get("delivery") or "").strip()
    if delivery:
        lines.append(f"• التوصيل: {delivery}")
    dimensions = product.get("dimensions") or {}
    dim_bits = [
        f"{label} {value:g} سم"
        for label, value in (
            ("العرض", dimensions.get("width_cm")),
            ("الارتفاع", dimensions.get("height_cm")),
            ("العمق", dimensions.get("depth_cm")),
        )
        if value is not None
    ]
    if dim_bits:
        lines.append(f"• الأبعاد: {'، '.join(dim_bits)}")
    if len(lines) <= 2:
        lines.append("• باقي التفاصيل الدقيقة مو مسجلة عندي حالياً.")
    lines.extend(["", "يناسبك؟ لو تريده گلي أكمّل وياك الطلب."])
    return {
        "reply": "\n".join(lines),
        "product_ids": [int(product.get("product_id") or 0)] if int(product.get("product_id") or 0) else [],
        "customer_intent": "product_question",
        "customer_sentiment": "interested",
        "sales_stage": "product_selection",
        "sales_strategy": "answer_specs",
        "main_need": name,
        "primary_objection": "",
        "next_action": "سؤال هل يناسب الزبون بعد عرض المواصفات",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _browse_catalog_options(
    *,
    family: str,
    preferred_foot_size: int | None = None,
    preferred_screen_size: int | None = None,
    limit: int = 3,
) -> list[dict]:
    """Return up to 3 browse options, preferring size diversity for fridges."""
    cap = max(1, min(int(limit or 3), 3))
    if family == "screen":
        return get_available_screen_products(size=preferred_screen_size, limit=cap, in_stock_only=True)
    if family == "refrigerator":
        rows = get_fridge_products(foot_size=None, in_stock_only=False, limit=20)
        if not rows:
            return []
        selected: list[dict] = []
        seen_sizes: set[int] = set()
        if preferred_foot_size:
            for row in rows:
                size = _foot_size_from_product(row)
                if size == preferred_foot_size:
                    selected.append(row)
                    if size:
                        seen_sizes.add(size)
                    break
        for row in rows:
            if len(selected) >= cap:
                break
            product_id = int(row.get("product_id") or 0)
            if any(int(item.get("product_id") or 0) == product_id for item in selected):
                continue
            size = _foot_size_from_product(row)
            if size and size in seen_sizes and len(selected) < cap:
                # Prefer one option per foot size when browsing "all available".
                continue
            selected.append(row)
            if size:
                seen_sizes.add(size)
        if len(selected) < cap:
            for row in rows:
                if len(selected) >= cap:
                    break
                product_id = int(row.get("product_id") or 0)
                if any(int(item.get("product_id") or 0) == product_id for item in selected):
                    continue
                selected.append(row)
        return selected[:cap]
    return []


def _catalog_options_result(products: list[dict], customer_message: str = "") -> dict:
    choices = [row for row in products or [] if int(row.get("product_id") or 0)][:3]
    if not choices:
        return {
            "reply": "حالياً ما طلعلي خيارات جاهزة. گلي شنو المنتج أو القياس اللي تبيه حتى أطلعلك الموجود.",
            "product_ids": [],
            "customer_intent": "product_search",
            "customer_sentiment": "interested",
            "sales_stage": "product_selection",
            "sales_strategy": "browse_catalog",
            "main_need": "عرض الموجود",
            "primary_objection": "",
            "next_action": "معرفة المنتج أو القياس المطلوب",
            "missing_information": ["المنتج المطلوب"],
            "customer_data": {},
            "confidence": 100,
            "should_handoff": False,
            "handoff_reason": "",
        }
    lines = ["هذني الخيارات الموجودة حالياً (حد أقصى 3):", ""]
    for product in choices:
        lines.extend([
            f"• {product.get('name')}",
            f"  السعر: {int(product.get('price') or 0):,} د.ع",
        ])
        for point in unique_selling_points(product, limit=2):
            lines.append(f"  • {point}")
        lines.append("")
    lines.append("أي واحد يناسبك حتى نكمل عليه؟")
    return {
        "reply": "\n".join(lines).strip(),
        "product_ids": [int(row.get("product_id") or 0) for row in choices],
        "customer_intent": "product_search",
        "customer_sentiment": "interested",
        "sales_stage": "product_selection",
        "sales_strategy": "browse_catalog",
        "main_need": str(customer_message or "عرض الموجود")[:220],
        "primary_objection": "",
        "next_action": "اختيار واحد من الخيارات المعروضة",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _available_specs_result(products: list[dict]) -> dict:
    """Show currently discussed product specs when the customer asks for mid-range options."""
    choices = [row for row in products or [] if int(row.get("product_id") or 0)][:2]
    if not choices:
        return {
            "reply": "هاي المواصفات المتوفرة حالياً مو مثبتة عندي بعد. گلي اسم المنتج أو الحجم حتى أطلعلك التفاصيل.",
            "product_ids": [],
            "customer_intent": "product_question",
            "customer_sentiment": "interested",
            "sales_stage": "product_selection",
            "sales_strategy": "answer_specs",
            "main_need": "المواصفات المتوفرة حالياً",
            "primary_objection": "",
            "next_action": "معرفة المنتج أو الحجم المطلوب",
            "missing_information": ["المنتج المطلوب"],
            "customer_data": {},
            "confidence": 100,
            "should_handoff": False,
            "handoff_reason": "",
        }
    lines = ["هاي المواصفات المتوفرة حالياً:"]
    for product in choices:
        name = str(product.get("name") or product.get("official_name") or "المنتج").strip()
        lines.extend(["", f"• {name}", f"  السعر: {int(product.get('price') or 0):,} د.ع"])
        for point in unique_selling_points(product, limit=4):
            lines.append(f"  • {point}")
        warranty = str(product.get("warranty") or "").strip()
        if warranty:
            lines.append(f"  • الضمان: {warranty}")
    lines.extend(["", "يناسبك واحد من هذني؟"])
    return {
        "reply": "\n".join(lines),
        "product_ids": [int(row.get("product_id") or 0) for row in choices],
        "customer_intent": "product_question",
        "customer_sentiment": "interested",
        "sales_stage": "product_selection",
        "sales_strategy": "answer_available_specs",
        "main_need": "المواصفات المتوفرة حالياً",
        "primary_objection": "",
        "next_action": "سؤال هل تناسب المواصفات المعروضة",
        "missing_information": [],
        "customer_data": {},
        "confidence": 100,
        "should_handoff": False,
        "handoff_reason": "",
    }


def _merge_products(*groups: list[dict], limit: int = 3) -> list[dict]:
    rows = []
    seen = set()
    for group in groups:
        for row in group or []:
            product_id = int(row.get("product_id") or 0)
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def _instruction_filtered_products(products: list[dict], message: str, profile: AISalesAgentProfile | None) -> list[dict]:
    return filter_products_by_manager_instructions(
        products or [],
        message,
        getattr(profile, "system_instructions", "") if profile else "",
    )


def _conversation_summary(context: dict, result: dict, products: list[dict]) -> str:
    parts = []
    need = str(result.get("main_need") or context.get("main_need") or "").strip()
    if need:
        parts.append(f"الاحتياج: {need[:180]}")
    budget = context.get("last_budget")
    if budget:
        parts.append(f"الميزانية: {int(budget):,} د.ع")
    facts = context.get("customer_facts") or {}
    usage = {"home": "البيت", "business": "المحل"}.get(str(facts.get("usage") or ""), "")
    if usage:
        parts.append(f"الاستخدام: {usage}")
    if facts.get("requested_size"):
        parts.append(f"الحجم المطلوب: {int(facts['requested_size'])}")
    if facts.get("requested_foot_size"):
        parts.append(f"القياس المطلوب: {int(facts['requested_foot_size'])} قدم")
    if facts.get("room_size"):
        room = {"small": "صغيرة", "medium": "متوسطة", "large": "كبيرة"}.get(str(facts["room_size"]), str(facts["room_size"]))
        parts.append(f"حجم الغرفة: {room}")
    if facts.get("viewing_distance_m"):
        parts.append(f"مسافة المشاهدة: {facts['viewing_distance_m']} متر")
    if facts.get("decision_basis") == "size_price":
        parts.append("أساس القرار: الحجم والسعر")
    if facts.get("priority"):
        priority = str(facts["priority"])
        parts.append(f"الأولوية: {PRIORITY_LABELS.get(priority, priority)[:60]}")
    order_data = context.get("order_customer_data") or {}
    if order_data.get("location_url"):
        parts.append("موقع التوصيل: محفوظ كرابط خريطة")
    pending_order = context.get("pending_order") or {}
    if pending_order.get("product_id"):
        parts.append(
            "الطلب الحالي: "
            f"{pending_order.get('product_name') or 'المنتج'} × {int(pending_order.get('quantity') or 1)} "
            f"بمجموع {int(pending_order.get('total') or 0):,} د.ع"
        )
    elif products:
        parts.append("الخيارات الحالية: " + "، ".join(str(row.get("name") or "") for row in products[:3]))
    objection = str(result.get("primary_objection") or context.get("primary_objection") or "").strip()
    if objection:
        parts.append(f"الاعتراض: {objection[:100]}")
    next_action = str(result.get("next_action") or "").strip()
    if next_action:
        parts.append(f"الخطوة التالية: {next_action[:120]}")
    return " | ".join(parts)[:900]


def _sync_customer_from_order_data(conversation: AISalesConversation, order_data: dict) -> Customer | None:
    phone = re.sub(r"[^\d+]", "", str(order_data.get("phone") or conversation.external_phone or ""))[:20]
    customer = Customer.query.get(conversation.customer_id) if conversation.customer_id else None
    if not customer and phone:
        customer = Customer.query.filter_by(phone=phone).first()
    if not customer and phone:
        customer = Customer(
            name=str(order_data.get("name") or conversation.contact_name or f"عميل {phone[-4:]}")[:150],
            phone=phone,
        )
        db.session.add(customer)
        db.session.flush()
    if not customer:
        return None
    conversation.customer_id = customer.id
    if order_data.get("name"):
        customer.name = str(order_data["name"])[:150]
    if order_data.get("city"):
        customer.city = str(order_data["city"])[:100]
    address_parts = [
        order_data.get("area"), order_data.get("landmark"), order_data.get("location_url"),
    ]
    address = " / ".join(str(part).strip() for part in address_parts if str(part or "").strip())
    if address:
        customer.address = address[:255]
    return customer


def _order_created_reply(invoice) -> str:
    item = invoice.items[0] if invoice.items else None
    product_name = item.product_name if item else "الطلب"
    quantity = int(item.quantity or 1) if item else 1
    return (
        "تم تسجيل طلبك بنجاح.\n\n"
        f"• رقم الطلب: #{invoice.id}\n"
        f"• المنتج: {product_name}\n"
        f"• العدد: {quantity}\n"
        f"• المبلغ: {int(invoice.total or 0):,} د.ع\n\n"
        "وصل الطلب لفريق التجهيز، وراح يتواصلون وياك حسب بيانات التوصيل المسجلة."
    )


def _media_failure_reply(
    inbound: AISalesMessage,
    exc: Exception,
    *,
    send_external: bool,
) -> AISalesMessage:
    """Record a media failure and keep the AI available for the next customer message."""
    conversation = inbound.conversation
    inbound.status = "media_failed"
    inbound.failure_message = str(exc)
    media_kind = str(inbound.message_type or "").lower()
    if media_kind == "image":
        fallback_text = (
            "وصلتني الصورة، بس ما كدرت أحللها هالمرة. "
            "دزها مرة ثانية، أو اكتبلي شنو المنتج اللي تبيه وأكمل وياك مباشرة."
        )
    elif media_kind == "video":
        fallback_text = (
            "وصلتني الفيديو، بس ما كدرت أفتحه هالمرة. "
            "دزه مرة ثانية، أو اكتبلي طلبك برسالة وأكمل وياك مباشرة."
        )
    else:
        fallback_text = (
            "ما كدرت أفتح التسجيل الصوتي هالمرة. دزه مرة ثانية، "
            "أو اكتبلي طلبك برسالة وأكمل وياك مباشرة."
        )
    outbound = AISalesMessage(
        conversation_id=conversation.id,
        channel_account_id=conversation.channel_account_id,
        direction="outbound",
        sender_type="ai",
        message_type="text",
        text_content=fallback_text,
        status="queued" if send_external else "sent",
        sent_at=None if send_external else datetime.utcnow(),
    )
    db.session.add(outbound)
    db.session.flush()
    if send_external:
        try:
            recipient = conversation.external_phone if conversation.channel.channel_type == "whatsapp" else conversation.external_contact_id
            body = channel_client(conversation.channel).send_text(recipient, fallback_text)
            outbound.external_message_id = outbound_message_id(body) or None
            outbound.status = "sent"
            outbound.sent_at = datetime.utcnow()
            conversation.last_business_message_at = outbound.sent_at
        except Exception as send_exc:
            outbound.status = "failed"
            outbound.failure_message = str(send_exc)
            outbound.failure_code = str(getattr(send_exc, "meta_code", "") or "") or None
            conversation.channel.last_error = str(send_exc)
            current_app.logger.exception(
                "AI_SALES_MEDIA_FALLBACK failed inbound_message_id=%s outbound_message_id=%s",
                inbound.id,
                outbound.id,
            )
    db.session.commit()
    return outbound


def process_inbound_message(message_id: int, *, send_external: bool = True) -> AISalesMessage | None:
    started_at = time.monotonic()
    inbound = AISalesMessage.query.get(message_id)
    if not inbound or inbound.direction != "inbound":
        return None
    claimable_statuses = {"received", "queued", "needs_media_processing", "media_failed"}
    original_status = str(inbound.status or "")
    if original_status not in claimable_statuses:
        return None
    if send_external:
        inbound.status = "handled_by_human"
        conversation = inbound.conversation
        if conversation:
            conversation.ai_enabled = False
            conversation.human_takeover = True
            conversation.status = "waiting_employee"
            conversation.handoff_reason = "Sales AI reset: training-only mode"
        db.session.commit()
        current_app.logger.info("AI_SALES_TRAINING_ONLY skipped auto reply message_id=%s", message_id)
        return None
    if send_external and _defer_to_newer_burst_message(inbound):
        return None
    db.session.expire_all()
    inbound = AISalesMessage.query.get(message_id)
    if not inbound:
        return None
    original_status = str(inbound.status or "")
    if original_status not in claimable_statuses:
        return None
    claimed = AISalesMessage.query.filter_by(
        id=inbound.id,
        direction="inbound",
        status=original_status,
    ).update({"status": "processing"}, synchronize_session=False)
    db.session.commit()
    if not claimed:
        return None
    db.session.refresh(inbound)
    burst_messages = _claim_burst_messages(inbound)
    burst_start_id = min(row.id for row in burst_messages)
    conversation = inbound.conversation
    context = conversation.get_context()
    order_state_active = bool(
        context.get("pending_order")
        or (
            conversation.sales_stage in {"collecting_order_data", "waiting_confirmation"}
            and context.get("focus_product_id")
            and order_data_complete(context.get("order_customer_data") or {})
        )
    )
    bare_order_attachment = False
    visual_reference_active = False
    visual_reference_analysis = ""
    vision_failed = False
    profile = AISalesAgentProfile.query.filter_by(is_active=True).order_by(AISalesAgentProfile.id.asc()).first()
    resume_conversation_ai_if_due(conversation)
    if conversation.human_takeover or not conversation.ai_enabled:
        inbound.status = "handled_by_human"
        db.session.commit()
        return None
    text = (inbound.text_content or inbound.transcription or "").strip()
    try:
        if inbound.message_type in {"audio", "voice"} and not inbound.transcription:
            text = transcribe_audio(inbound)
        elif inbound.message_type == "image" and inbound.external_media_id:
            download_inbound_media(inbound)
            if not (inbound.text_content or "").strip() and order_state_active:
                bare_order_attachment = True
                text = "أرسل الزبون صورة مرفقة للطلب بدون طلب جديد."
            else:
                try:
                    vision = analyze_image(inbound)
                    visual_reference_active = True
                    visual_reference_analysis = vision
                    text = " | ".join(part for part in (inbound.text_content, vision) if part)
                except Exception as vision_exc:
                    # Image download succeeded; keep chatting even if vision quota/API fails.
                    current_app.logger.warning(
                        "AI_SALES_VISION_FALLBACK message_id=%s error=%s",
                        inbound.id,
                        vision_exc,
                    )
                    inbound.failure_message = str(vision_exc)[:700]
                    vision_failed = True
                    visual_reference_active = True
                    caption = (inbound.text_content or "").strip()
                    text = caption or (
                        "أرسل الزبون صورة منتج لكن تحليل الصورة غير متاح حالياً. "
                        "اطلب منه يوضح اسم المنتج أو القياس بدون الاعتماد على المنتج السابق."
                    )
        elif inbound.message_type == "video" and inbound.external_media_id:
            download_inbound_media(inbound)
            inbound.status = "needs_human_review"
            conversation.human_takeover = True
            conversation.ai_enabled = False
            conversation.status = "waiting_employee"
            db.session.commit()
            return None
    except Exception as exc:
        return _media_failure_reply(inbound, exc, send_external=send_external)
    if not text:
        inbound.status = "needs_media_processing"
        db.session.commit()
        return None

    if inbound.message_type != "image" and _is_visual_reference_followup(text):
        visual_reference = dict(context.get("last_visual_reference") or {})
        if not str(visual_reference.get("analysis") or "").strip():
            visual_reference = _latest_visual_reference(conversation.id, inbound.id)
        visual_reference_analysis = str(visual_reference.get("analysis") or "").strip()
        if visual_reference_analysis:
            visual_reference_active = True
            text = f"{text}\nمرجع الصورة الأخيرة المؤكد: {visual_reference_analysis}"

    if visual_reference_active:
        context["last_visual_reference"] = {
            "message_id": inbound.id,
            "analysis": visual_reference_analysis,
            "updated_at": datetime.utcnow().isoformat(),
        }
        for stale_key in (
            "last_budget", "last_product_ids", "focus_product_id", "recommendation_snapshot",
            "active_product_snapshot", "pending_order", "purchase_selection", "created_order_id",
            "product_family",
        ):
            context.pop(stale_key, None)
        conversation.set_context(context)
        db.session.commit()

    if len(burst_messages) > 1:
        burst_parts = [
            (row.text_content or row.transcription or "").strip()
            for row in burst_messages
            if (row.text_content or row.transcription or "").strip()
        ]
        if burst_parts:
            text = "\n".join(
                f"رسالة الزبون {index}: {part}"
                for index, part in enumerate(burst_parts, start=1)
            )
    latest_customer_text = (
        (burst_messages[-1].text_content or burst_messages[-1].transcription or "").strip()
        if burst_messages
        else str(text or "").strip()
    )

    greeting_only = is_greeting_message(text)
    policy = intelligence_policy(profile.intelligence_level if profile else "expert")
    product_limit = max(1, min(int(profile.max_products or 3) if profile else 3, int(policy["product_limit"]), 3))
    history_limit = max(6, min(int(getattr(profile, "max_context_messages", 18) or 18), 30))
    history = recent_history(conversation.id, limit=history_limit, before_message_id=burst_start_id)
    gratitude_reply = (
        _quick_gratitude_reply(
            latest_customer_text or text,
            {**context, "current_sales_stage": conversation.sales_stage},
        )
        if burst_messages
        else None
    )
    ad_search_anchor = _ad_context_search_text(context)
    link_previews = extract_link_previews(text)
    if link_previews:
        metadata = inbound.get_media_metadata()
        metadata["link_previews"] = link_previews
        inbound.set_media_metadata(metadata)
        order_data = dict(context.get("order_customer_data") or {})
        previous_links = [str(url) for url in order_data.get("shared_links") or [] if str(url).strip()]
        for preview in link_previews:
            url = str(preview.get("url") or "").strip()
            if url and url not in previous_links:
                previous_links.append(url)
        order_data["shared_links"] = previous_links[-5:]
        map_preview = first_map_preview(link_previews)
        if map_preview:
            order_data["location_url"] = str(map_preview["url"])[:1000]
            if map_preview.get("latitude") is not None:
                order_data["location_latitude"] = map_preview["latitude"]
                order_data["location_longitude"] = map_preview["longitude"]
        context["order_customer_data"] = order_data
    requested_quantity = extract_order_quantity(text)
    summary_requested = is_order_summary_request(text)
    pending_order = dict(context.get("pending_order") or {})
    order_customer_data = dict(context.get("order_customer_data") or {})
    should_recover_pending = bool(
        not pending_order
        and conversation.sales_stage in {"collecting_order_data", "waiting_confirmation"}
        and order_data_complete(order_customer_data)
        and (requested_quantity is not None or summary_requested or bare_order_attachment)
    )
    if should_recover_pending:
        active_snapshot = dict(context.get("active_product_snapshot") or {})
        selected_product_id = int(
            active_snapshot.get("product_id")
            or context.get("focus_product_id")
            or ((context.get("last_product_ids") or [0])[0])
            or 0
        )
        selected_products = get_products_by_ids([selected_product_id], in_stock_only=False) if selected_product_id else []
        if selected_products:
            purchase_selection = dict(context.get("purchase_selection") or {})
            selection_message_id = int(
                purchase_selection.get("selected_from_message_id")
                or active_snapshot.get("selected_from_message_id")
                or inbound.id
            )
            pending_order = build_pending_order(
                selected_products[0],
                order_customer_data,
                message_id=inbound.id,
                selection_message_id=selection_message_id,
                quantity=requested_quantity or 1,
            )
            context["purchase_selection"] = {
                "product_id": selected_product_id,
                "selected_from_message_id": selection_message_id,
                "selected_at": datetime.utcnow().isoformat(),
            }
            context["pending_order"] = pending_order
    pending_live_products = []
    if pending_order:
        pending_product_id = int(pending_order.get("product_id") or 0)
        pending_live_products = get_products_by_ids([pending_product_id], in_stock_only=False) if pending_product_id else []
        if pending_live_products:
            pending_order = refresh_pending_order(pending_order, pending_live_products[0])
        if requested_quantity is not None:
            pending_order = update_pending_order_quantity(pending_order, requested_quantity)
        context["pending_order"] = pending_order
    deterministic_order_action = bool(
        pending_order
        and pending_live_products
        and (requested_quantity is not None or summary_requested or bare_order_attachment)
    )
    raw_message_guard = classify_customer_message(text, context=context)
    if raw_message_guard.is_gratitude and not gratitude_reply:
        gratitude_reply = {
            "reply": "العفو حبيبي، بالخدمة.",
            "sales_stage": conversation.sales_stage or "discovery",
            "lead_score": int(context.get("lead_score") or conversation.lead_score or 0),
            "lead_temperature": str(context.get("lead_temperature") or conversation.lead_temperature or "cold"),
            "should_handoff": False,
            "handoff_reason": "",
            "product_ids": [],
            "main_need": str(context.get("main_need") or "إغلاق المحادثة بالشكر")[:220],
            "primary_objection": "",
            "next_action": "انتظار طلب جديد من الزبون",
            "customer_intent": "gratitude",
            "customer_sentiment": "positive",
            "sales_strategy": "retain",
            "missing_information": [],
            "customer_data": {},
            "confidence": 100,
        }
    effective_customer_text = " ".join(part for part in (ad_search_anchor, text) if part).strip()
    message_guard = raw_message_guard if gratitude_reply else classify_customer_message(effective_customer_text, context=context)
    context["last_message_guard"] = message_guard.as_dict()
    current_product_family = message_guard.family or _product_family(effective_customer_text)
    if not current_product_family and re.search(r"\u062a\u0644\u0627\u062c(?:\u0647|\u0629|\u0627\u062a)", effective_customer_text or ""):
        current_product_family = "refrigerator"
    previous_product_family = str(context.get("product_family") or "") or _product_family(
        " ".join((str(context.get("main_need") or ""), conversation.summary or ""))
    )
    product_family_changed = bool(
        current_product_family
        and previous_product_family
        and current_product_family != previous_product_family
    )
    if product_family_changed:
        for stale_key in (
            "last_budget", "last_product_ids", "focus_product_id", "recommendation_snapshot",
            "active_product_snapshot", "primary_objection", "pending_order", "purchase_selection", "created_order_id",
        ):
            context.pop(stale_key, None)
        if conversation.sales_stage in {
            "purchase_intent", "collecting_order_data", "waiting_confirmation", "won",
        }:
            conversation.sales_stage = "product_selection"
    current_budget = extract_budget(text)
    remembered_budget = None if (product_family_changed or visual_reference_active) else (context.get("last_budget") or _history_budget(history))
    budget = current_budget or remembered_budget
    customer_facts = update_customer_facts(
        effective_customer_text,
        [] if product_family_changed else history,
        {} if product_family_changed else (context.get("customer_facts") or {}),
        budget=int(budget) if budget else None,
    )
    previous_ids = [] if (product_family_changed or visual_reference_active) else (context.get("last_product_ids") or [])
    previous_products = [] if greeting_only else get_products_by_ids(previous_ids, in_stock_only=True)
    focus_product_id = int(context.get("focus_product_id") or (previous_ids[0] if previous_ids else 0) or 0)
    focused_products = [row for row in previous_products if int(row.get("product_id") or 0) == focus_product_id]
    if is_purchase_intent(text) and focused_products:
        previous_products = focused_products
    for row in previous_products:
        row["context_role"] = "current_selection"

    objection_type = classify_objection(text)
    price_objection = objection_type == "price" or is_price_objection(text)
    price_flexibility_question = _is_price_flexibility_question(text)
    history_screen_size = next(
        (
            size
            for row in reversed(history or [])
            if row.get("role") == "user"
            for size in [_screen_size_from_text(str(row.get("content") or ""))]
            if size
        ),
        None,
    )
    direct_screen_size_price = (
        message_guard.screen_size
        if message_guard.family == "screen" and message_guard.screen_size
        else _direct_screen_size_price(text)
    )
    if not direct_screen_size_price and not current_product_family:
        direct_screen_size_price = _bare_screen_size(text)
    # Follow-ups like "سعر" after "شاشه 65" / "شاسة٦٥" should keep the size.
    if not direct_screen_size_price and history_screen_size and (
        _is_generic_price_request(text)
        or current_product_family == "screen"
        or previous_product_family == "screen"
    ):
        direct_screen_size_price = history_screen_size
    if direct_screen_size_price and current_product_family not in {
        "refrigerator", "air_cooler", "washer", "air_conditioner", "router",
    }:
        current_product_family = "screen"
    active_product_family = current_product_family or ("" if visual_reference_active else previous_product_family)
    requested_foot_size = None
    if current_product_family != "screen" and not direct_screen_size_price:
        history_foot_size = _history_requested_foot_size(history, text, customer_facts)
        requested_foot_size = (
            history_foot_size
            or message_guard.foot_size
            or parse_foot_size(text)
            or _foot_size_from_product({"name": text})
        )
    requested_features = requested_product_features(text) or list(customer_facts.get("requested_features") or [])
    if not requested_features:
        for row in reversed(history or []):
            if row.get("role") != "user":
                continue
            prior_features = requested_product_features(str(row.get("content") or ""))
            if prior_features:
                requested_features = prior_features
                break
    if requested_foot_size:
        requested_foot_size = int(requested_foot_size)
        if customer_facts.get("requested_foot_size") != requested_foot_size:
            customer_facts["requested_foot_size"] = requested_foot_size
    if requested_features and not customer_facts.get("requested_features"):
        customer_facts["requested_features"] = list(requested_features)
    if requested_foot_size is None and active_product_family == "refrigerator":
        # Follow-up price questions often omit "ثلاجة" and may typo قدم as قدام.
        requested_foot_size = _loose_fridge_foot_size(text, require_fridge_word=False)
    elif current_product_family == "refrigerator" and requested_foot_size is None:
        requested_foot_size = _loose_fridge_foot_size(text)
    advertised_dollar_amount = _advertised_dollar_amount(text, history)
    # An inbound customer photo is a visual reference, not a request for our product media.
    requested_media = None if inbound.message_type in {"image", "video"} else _requested_product_media(text)
    if conversation.channel.channel_type == "instagram" and requested_media == "video":
        requested_media = None
    auto_media_type = None
    purchase_intent = is_purchase_intent(text)
    mid_range_preference = is_mid_range_preference(text)
    show_all_options = is_show_all_options_request(text)
    specific_product_query = has_product_query(text) and not mid_range_preference and not show_all_options
    latest_message_needs_product_answer = _latest_message_needs_product_answer(
        text,
        message_guard,
        current_product_family=current_product_family,
        direct_screen_size_price=direct_screen_size_price,
        requested_foot_size=requested_foot_size,
        requested_features=requested_features,
        requested_media=requested_media,
        purchase_intent=purchase_intent,
        price_objection=price_objection,
        price_flexibility_question=price_flexibility_question,
        mid_range_preference=mid_range_preference,
        show_all_options=show_all_options,
        advertised_dollar_amount=advertised_dollar_amount,
        visual_reference_active=visual_reference_active,
        previous_products=previous_products,
    )
    context["latest_message_priority"] = {
        "text": latest_customer_text or text,
        "needs_product_answer": latest_message_needs_product_answer,
        "intent": message_guard.intent,
        "family": message_guard.family or current_product_family or "",
    }
    if (
        specific_product_query
        and not deterministic_order_action
        and not purchase_intent
        and not is_explicit_order_confirmation(text)
    ):
        context.pop("pending_order", None)
        context.pop("purchase_selection", None)
        if conversation.sales_stage in {"purchase_intent", "collecting_order_data", "waiting_confirmation"}:
            conversation.sales_stage = "product_selection"
    anchor = _history_anchor(history)
    search_query = text
    unavailable_requested_brand = ""
    unavailable_requested_size = None
    if gratitude_reply:
        result = gratitude_reply
    elif deterministic_order_action:
        products = pending_live_products
        recommended_next_action = "انتظار تأكيد صريح لإنشاء الطلب"
    elif greeting_only:
        products = []
        recommended_next_action = str(
            context.get("recommended_next_action")
            or context.get("next_action")
            or "معرفة المنتج المطلوب"
        )
    elif not latest_message_needs_product_answer:
        products = []
        focused_products = []
        previous_products = []
        active_product_family = ""
        requested_media = None
        recommended_next_action = (
            "جاوب آخر رسالة للزبون مباشرة وبأسلوب طبيعي، ولا تعرض منتجاً أو سعراً إلا إذا طلبه في آخر رسالة."
        )
    elif mid_range_preference and (focused_products or previous_products or active_product_family == "screen"):
        products = (focused_products or previous_products)[:product_limit]
        if active_product_family:
            family_products = [row for row in products if _product_matches_family(row, active_product_family)]
            if family_products:
                products = family_products
            elif active_product_family == "screen":
                size = (
                    int(customer_facts.get("requested_size") or 0)
                    or history_screen_size
                    or _screen_size_from_text(anchor)
                    or None
                )
                products = get_available_screen_products(size=size, limit=product_limit)
        recommended_next_action = "عرض المواصفات المتوفرة حالياً للمنتجات قيد النقاش"
    elif show_all_options:
        browse_family = active_product_family or previous_product_family or "refrigerator"
        products = _browse_catalog_options(
            family=browse_family,
            preferred_foot_size=requested_foot_size,
            preferred_screen_size=(
                int(customer_facts.get("requested_size") or 0)
                or history_screen_size
                or _screen_size_from_text(anchor)
                or None
            ),
            limit=3,
        )
        if not products and previous_products:
            products = previous_products[:3]
        recommended_next_action = "عرض حتى 3 خيارات موجودة ثم سؤال أيهم يناسب"
    else:
        if advertised_dollar_amount or objection_type != "none" or purchase_intent or not specific_product_query:
            search_query = " ".join(part for part in (ad_search_anchor, anchor, text) if part).strip()
        if price_flexibility_question and previous_products:
            products = (focused_products or previous_products[:1])[:1]
            recommended_next_action = "الإجابة عن السعر لنفس المنتج بدون تبديل الاختيار أو اختراع خصم"
        else:
            search_max_price = current_budget if visual_reference_active else budget
            excluded_ids: list[int] = []
            if price_objection and previous_products:
                current_reference = focused_products or previous_products[:1]
                current_prices = [int(row.get("price") or 0) for row in current_reference if row.get("price")]
                if current_prices:
                    cheaper_than = max(min(current_prices) - 1, 1)
                    search_max_price = min(int(budget), cheaper_than) if budget else cheaper_than
                excluded_ids = [int(row["product_id"]) for row in current_reference]
            searched_candidates = search_products(
                search_query,
                max_price=search_max_price,
                in_stock_only=(active_product_family != "refrigerator"),
                limit=10,
                exclude_ids=excluded_ids,
            )
            if requested_features:
                feature_filtered = filter_products_by_features(searched_candidates, requested_features)
                if feature_filtered:
                    searched_candidates = feature_filtered
            if active_product_family == "refrigerator":
                fridge_candidates = get_fridge_products(
                    foot_size=requested_foot_size,
                    in_stock_only=False,
                    limit=10,
                )
                if fridge_candidates:
                    searched_candidates = filter_products_by_features(fridge_candidates, requested_features)
            unavailable_requested_brand = _unsupported_screen_brand(search_query)
            if unavailable_requested_brand and not searched_candidates:
                unavailable_requested_size = (
                    _screen_size_from_text(search_query)
                    or int(customer_facts.get("requested_size") or 0)
                    or None
                )
                searched_candidates = get_available_screen_products(
                    size=unavailable_requested_size,
                    limit=12,
                )
            if visual_reference_active and customer_facts.get("requested_size"):
                requested_visual_size = int(customer_facts["requested_size"])
                searched_candidates = [
                    row for row in searched_candidates
                    if _matches_requested_screen_size(row, requested_visual_size)
                ]
            if active_product_family:
                family_filtered = [
                    row for row in searched_candidates
                    if _product_matches_family(row, active_product_family)
                ]
                searched_candidates = family_filtered
            searched_products = rank_products_for_customer(searched_candidates, customer_facts)[:product_limit]
            if requested_features:
                feature_matches = filter_products_by_features(searched_products, requested_features)
                if feature_matches:
                    searched_products = feature_matches[:product_limit]
            for row in searched_products:
                row["context_role"] = "alternative" if (unavailable_requested_brand or price_objection) else "candidate"
            if price_objection:
                products = _merge_products(previous_products[:1], searched_products, limit=product_limit)
            elif previous_products and (not specific_product_query or not searched_products):
                products = _merge_products(previous_products, searched_products, limit=product_limit)
            else:
                products = searched_products
            if not price_objection and not purchase_intent:
                products = rank_products_for_customer(products, customer_facts)[:product_limit]
            recommended_next_action = next_best_action(
                customer_facts,
                objection_type,
                purchase_intent=purchase_intent,
                products=products,
            )
            if specific_product_query and not purchase_intent:
                recommended_next_action = (
                    "الإجابة عن أسئلة المنتج الحالية فقط ثم سؤال هل يناسب الزبون، "
                    "بدون افتراض كمية أو إكمال طلب سابق"
                )
        products = _instruction_filtered_products(products, text, profile)
        focused_products = _instruction_filtered_products(focused_products, text, profile)
        previous_products = _instruction_filtered_products(previous_products, text, profile)
        log_product_search(conversation.id, inbound.id, search_query, products)
    requested_media_product = products[0] if requested_media and products else None
    requested_media_product_id = int((requested_media_product or {}).get("product_id") or 0)
    requested_media_assets = (
        get_product_media(requested_media_product_id, requested_media, limit=2)
        if requested_media_product_id and requested_media
        else []
    )
    # Persist media, link and product-search work before the network call. This
    # keeps SQLite free while OpenAI is thinking and avoids blocking webhooks.
    db.session.commit()
    response_delay_ms = max(0, min(int(getattr(profile, "ai_response_delay_ms", 0) or 0), 3000))
    if response_delay_ms:
        time.sleep(response_delay_ms / 1000)
    ai_started_at = time.monotonic()
    if gratitude_reply:
        result = gratitude_reply
    elif greeting_only:
        result = _quick_greeting_reply(
            latest_customer_text or text,
            {**context, "current_sales_stage": conversation.sales_stage},
        ) or {
            "reply": "هلا بيك، شنو المنتج اللي تحب تعرف عنه؟",
            "sales_stage": "discovery",
            "lead_score": 15,
            "lead_temperature": "cold",
            "should_handoff": False,
            "handoff_reason": "",
            "product_ids": [],
            "main_need": "ترحيب",
            "primary_objection": "",
            "next_action": "معرفة المنتج المطلوب",
            "customer_intent": "greeting",
            "customer_sentiment": "neutral",
            "sales_strategy": "discover",
            "missing_information": ["المنتج المطلوب"],
            "customer_data": {},
            "confidence": 100,
        }
    elif deterministic_order_action:
        deterministic_reply = (
            "وصلتني الصورة وضفتها للمحادثة. الطلب بعده محفوظ بنفس المنتج والسعر. "
            "لعرضه اكتب: اعرض الملخص، ولتثبيته بعد المراجعة اكتب: أكد الطلب."
            if bare_order_attachment
            else pending_order_summary(pending_order)
        )
        result = _deterministic_pending_result(context, pending_order, deterministic_reply)
    elif vision_failed and inbound.message_type == "image" and not bare_order_attachment:
        result = _vision_unavailable_result()
    elif requested_media and requested_media_product:
        result = _media_request_result(
            requested_media_product,
            requested_media,
            requested_media_assets,
            text,
        )
    elif unavailable_requested_brand:
        result = _unsupported_brand_result(
            unavailable_requested_brand,
            products,
            unavailable_requested_size,
        )
    elif advertised_dollar_amount:
        dollar_product = _pick_advertised_dollar_product(
            amount=advertised_dollar_amount,
            products=products,
            focused_products=focused_products,
            previous_products=previous_products,
            history=history,
            customer_facts=customer_facts,
            text=text,
            context=context,
        )
        if dollar_product:
            result = _advertised_dollar_price_result(dollar_product, advertised_dollar_amount)
        else:
            result = generate_sales_reply(
                conversation_id=conversation.id,
                message_id=inbound.id,
                customer_message=text,
                history=[] if product_family_changed else history,
                products=products,
                conversation_context={**context, "current_sales_stage": conversation.sales_stage},
                profile=profile,
                product_limit=product_limit,
            )
    elif ad_search_anchor and _is_generic_price_request(text) and products:
        result = _direct_ad_price_result(products[0], context.get("ad_context") or {})
    elif mid_range_preference and (products or focused_products or previous_products):
        result = _available_specs_result(products or focused_products or previous_products)
    elif show_all_options:
        result = _catalog_options_result(products or focused_products or previous_products, text)
    elif (is_spec_request(text) or is_affirmative_to_specs_offer(text, history)) and (
        focused_products or previous_products or products
    ):
        result = _product_specs_result((focused_products or previous_products or products)[0])
    elif is_positive_ack(text) and not is_affirmative_to_specs_offer(text, history) and (
        focused_products or previous_products or products
    ):
        ack_product = (focused_products or previous_products or products)[0]
        result = _price_fixed_ack_result(ack_product)
    elif direct_screen_size_price:
        exact_screen_products = get_available_screen_products(size=direct_screen_size_price, limit=12)
        screen_products = _instruction_filtered_products(exact_screen_products, text, profile)
        if screen_products:
            result = _direct_size_price_result(screen_products, direct_screen_size_price)
        else:
            result = generate_sales_reply(
                conversation_id=conversation.id,
                message_id=inbound.id,
                customer_message=text,
                history=[] if product_family_changed else history,
                products=[],
                conversation_context={**context, "current_sales_stage": conversation.sales_stage},
                profile=profile,
                product_limit=product_limit,
            )
    elif requested_foot_size and active_product_family in {"", "refrigerator"}:
        fridge_products = get_fridge_products(foot_size=requested_foot_size, in_stock_only=False, limit=10)
        fridge_products = filter_products_by_features(fridge_products, requested_features)
        fridge_products = _instruction_filtered_products(fridge_products, text, profile)
        result = _direct_foot_size_result(
            fridge_products,
            requested_foot_size,
            text,
            requested_features=requested_features,
        ) if fridge_products else generate_sales_reply(
            conversation_id=conversation.id,
            message_id=inbound.id,
            customer_message=text,
            history=[] if product_family_changed else history,
            products=[],
            conversation_context={**context, "current_sales_stage": conversation.sales_stage},
            profile=profile,
            product_limit=product_limit,
        )
        auto_media_type = "video"
    elif active_product_family == "refrigerator" and products and re.search(r"ثلاجه|ثلاجة|ثلاجات|براد|قدم|قدام", text):
        result = _fridge_recommendation_result(products, text)
        if requested_foot_size:
            auto_media_type = "video"
    elif current_product_family == "refrigerator" and products:
        result = _fridge_recommendation_result(products, text)
        if requested_foot_size:
            auto_media_type = "video"
    elif requested_foot_size and products:
        filtered_products = filter_products_by_features(products, requested_features)
        result = _direct_foot_size_result(
            filtered_products or products,
            requested_foot_size,
            text,
            requested_features=requested_features,
        )
    elif price_flexibility_question and products:
        selected_product = products[0]
        smaller_products = find_nearest_smaller_foot_products(selected_product, limit=2)
        result = {
            "reply": _price_flexibility_reply(selected_product, smaller_products),
            "product_ids": [
                int(row.get("product_id") or 0)
                for row in [selected_product, *smaller_products[:1]]
                if int(row.get("product_id") or 0)
            ],
            "customer_intent": "price_objection",
            "customer_sentiment": "neutral",
            "sales_stage": "objection",
            "sales_strategy": "price_transparency",
            "main_need": str(context.get("main_need") or text),
            "primary_objection": "السعر",
            "next_action": "معرفة ميزانية الزبون إذا كان السعر الحالي غير مناسب",
            "missing_information": [],
            "customer_data": {},
            "confidence": 100,
            "should_handoff": False,
            "handoff_reason": "",
        }
    else:
        result = generate_sales_reply(
            conversation_id=conversation.id,
            message_id=inbound.id,
            customer_message=text,
            history=[] if product_family_changed else history,
            products=products,
            conversation_context={
                **context,
                "current_sales_stage": conversation.sales_stage,
                "current_lead_score": int(conversation.lead_score or 0),
                "remembered_budget": budget,
                "conversation_summary": conversation.summary or "",
                "customer_facts": customer_facts,
                "detected_objection": objection_type,
                "recommended_next_action": recommended_next_action,
                "visual_reference_analysis": visual_reference_analysis,
                "visual_reference_active": visual_reference_active,
            },
        )
    current_app.logger.info(
        "AI_SALES_TIMING message_id=%s stage=ai duration_ms=%s",
        inbound.id,
        round((time.monotonic() - ai_started_at) * 1000),
    )
    if send_external:
        newer_message = _newer_customer_message(inbound)
        if newer_message:
            for burst_message in burst_messages:
                burst_message.status = "processed"
            db.session.commit()
            current_app.logger.info(
                "AI_SALES_BURST suppressed_stale_reply conversation_id=%s stale_leader_id=%s newer_message_id=%s",
                inbound.conversation_id,
                inbound.id,
                newer_message.id,
            )
            return None
    previous_sales_stage = conversation.sales_stage
    if greeting_only:
        result["sales_stage"] = "discovery" if previous_sales_stage == "new" else previous_sales_stage
        result["next_action"] = str(context.get("next_action") or recommended_next_action)
        lead_score = max(int(conversation.lead_score or 0), 15 if previous_sales_stage == "new" else 0)
        lead_temperature = conversation.lead_temperature or ("cold" if lead_score < 35 else "warm")
    else:
        if purchase_intent and result.get("sales_stage") not in {"collecting_order_data", "waiting_confirmation"}:
            result["sales_stage"] = "purchase_intent"
        elif objection_type not in {"none", "human_request", "complaint"}:
            result["sales_stage"] = "objection"
        if objection_type != "none":
            result["primary_objection"] = OBJECTION_LABELS.get(objection_type, objection_type)
        result["next_action"] = recommended_next_action
        if objection_type in {"human_request", "complaint"}:
            result["should_handoff"] = True
            result["handoff_reason"] = OBJECTION_LABELS[objection_type]
        lead_score, lead_temperature = calculate_lead_state(
            int(conversation.lead_score or 0),
            customer_facts,
            products,
            objection=objection_type,
            purchase_intent=purchase_intent,
            model_intent=str(result.get("customer_intent") or ""),
        )
        if result.get("sales_stage") == "lost":
            lead_score = min(lead_score, 10)
            lead_temperature = "cold"
    conversation.sales_stage = result.get("sales_stage") or conversation.sales_stage
    result["lead_score"] = lead_score
    result["lead_temperature"] = lead_temperature
    conversation.lead_score = lead_score
    conversation.lead_temperature = lead_temperature
    low_confidence_handoff = bool(getattr(profile, "auto_escalation", True)) and (
        int(result.get("confidence") or 0) < int(profile.handoff_threshold or 45)
        and result.get("customer_intent") in {"complaint", "human_request", "other"}
    ) if profile else False
    if result.get("should_handoff") or low_confidence_handoff:
        conversation.human_takeover = True
        conversation.ai_enabled = False
        conversation.status = "waiting_employee"
    if not greeting_only:
        order_customer_data = dict(context.get("order_customer_data") or {})
        if conversation.channel.channel_type == "whatsapp" and conversation.external_phone:
            order_customer_data.setdefault("phone", conversation.external_phone)
        customer_data_limits = {
            "name": 150, "phone": 40, "city": 100, "area": 150,
            "landmark": 250, "location_url": 1000,
        }
        for key, limit in customer_data_limits.items():
            value = str((result.get("customer_data") or {}).get(key) or "").strip()
            if key == "phone" and value:
                value = "".join(character for character in value if character.isdigit() or character == "+")
            if key == "location_url" and value:
                value = str((first_map_preview(extract_link_previews(value)) or {}).get("url") or "")
            if value:
                order_customer_data[key] = value[:limit]
        context.update({
            "last_handoff_reason": result.get("handoff_reason") or "",
            "main_need": result.get("main_need") or context.get("main_need") or "",
            "last_intent": result.get("customer_intent") or "",
            "last_sentiment": result.get("customer_sentiment") or "",
            "last_strategy": result.get("sales_strategy") or "",
            "next_action": result.get("next_action") or "",
            "missing_information": result.get("missing_information") or [],
            "confidence": int(result.get("confidence") or 0),
            "customer_facts": customer_facts,
            "detected_objection": objection_type,
            "recommended_next_action": recommended_next_action,
            "order_customer_data": order_customer_data,
            "product_family": current_product_family or previous_product_family,
            "recommendation_snapshot": [
                {
                    "product_id": int(row.get("product_id") or 0),
                    "score": float(row.get("recommendation_score") or 0),
                    "reasons": row.get("recommendation_reasons") or [],
                }
                for row in products
            ],
        })
        if result.get("primary_objection"):
            context["primary_objection"] = result.get("primary_objection")
        elif objection_type == "none" and result.get("customer_intent") in {"product_search", "discovery", "purchase", "order_details"}:
            context["primary_objection"] = ""
        if budget:
            context["last_budget"] = int(budget)
        if result.get("product_ids"):
            context["last_product_ids"] = result.get("product_ids")
            context["focus_product_id"] = int(result.get("product_ids")[0])
            focused_result = next(
                (
                    row for row in products
                    if int(row.get("product_id") or 0) == int(result.get("product_ids")[0])
                ),
                None,
            )
            if not focused_result and result.get("sales_strategy") == "clarify_ad_currency":
                focused_result = get_products_by_ids([int(result.get("product_ids")[0])], in_stock_only=False)
                focused_result = focused_result[0] if focused_result else None
            if focused_result:
                context["active_product_snapshot"] = {
                    "product_id": int(focused_result.get("product_id") or 0),
                    "product_name": str(focused_result.get("official_name") or focused_result.get("name") or "")[:150],
                    "unit_price": int(focused_result.get("price") or 0),
                    "warranty": str(focused_result.get("warranty") or "")[:200],
                    "selected_from_message_id": int(inbound.id),
                    "selected_at": datetime.utcnow().isoformat(),
                }
            if result.get("sales_strategy") == "clarify_ad_currency":
                context["advertised_dollar"] = {
                    "amount": int(result.get("advertised_dollar_amount") or advertised_dollar_amount or 0),
                    "product_id": int(result.get("product_ids")[0]),
                    "foot_size": result.get("advertised_foot_size"),
                }
                if result.get("advertised_foot_size"):
                    customer_facts["requested_foot_size"] = int(result["advertised_foot_size"])
                    context["customer_facts"] = customer_facts
                    context["product_family"] = "refrigerator"
        if purchase_intent:
            selected_product_id = int(
                ((result.get("product_ids") or [0])[0])
                or context.get("focus_product_id")
                or 0
            )
            live_product_ids = {int(row.get("product_id") or 0) for row in products}
            if selected_product_id and selected_product_id in live_product_ids:
                context["purchase_selection"] = {
                    "product_id": selected_product_id,
                    "selected_from_message_id": int(inbound.id),
                    "selected_at": datetime.utcnow().isoformat(),
                }
        conversation.set_context(context)
        conversation.summary = _conversation_summary(context, result, products)
        customer = _sync_customer_from_order_data(conversation, order_customer_data)

        pending_order = dict(context.get("pending_order") or {})
        if pending_order and not _pending_has_explicit_selection(pending_order):
            context.pop("pending_order", None)
            pending_order = {}
            if conversation.sales_stage == "waiting_confirmation":
                conversation.sales_stage = "product_selection"
        created_order_id = int(context.get("created_order_id") or 0)
        starting_another_order = bool(
            (purchase_intent or specific_product_query)
            and not is_explicit_order_confirmation(text)
        )
        if created_order_id and previous_sales_stage == "won" and not starting_another_order:
            context.pop("pending_order", None)
            conversation.sales_stage = "won"
            result["sales_stage"] = "won"
            result["next_action"] = f"متابعة تجهيز الطلب #{created_order_id}"
            if is_explicit_order_confirmation(text):
                existing_invoice = find_existing_ai_order(conversation.id)
                result["reply"] = (
                    f"طلبك مسجل فعلاً برقم #{existing_invoice.id}. فريق التجهيز استلمه وراح يتابع وياك."
                    if existing_invoice
                    else f"طلبك مسجل فعلاً برقم #{created_order_id}. فريق التجهيز راح يتابع وياك."
                )
        elif pending_order:
            refreshed_customer_data = {
                key: order_customer_data.get(key)
                for key in ("name", "phone", "city", "area", "landmark", "location_url")
                if order_customer_data.get(key)
            }
            pending_changed = refreshed_customer_data != (pending_order.get("customer_data") or {})
            if refreshed_customer_data:
                pending_order["customer_data"] = refreshed_customer_data

            if is_order_revision_or_cancellation(text):
                context.pop("pending_order", None)
                context.pop("purchase_selection", None)
                conversation.sales_stage = "product_selection"
                result["sales_stage"] = "product_selection"
                result["reply"] = "تمام، ما سجلت الطلب. گلي شنو تريد نغيّر بالمنتج أو بيانات التوصيل؟"
                result["next_action"] = "تعديل اختيار المنتج أو بيانات الطلب"
            elif is_explicit_order_confirmation(text):
                order_result = create_confirmed_order(conversation, customer, pending_order)
                if order_result.status in {"created", "already_created"} and order_result.invoice:
                    invoice = order_result.invoice
                    context.pop("pending_order", None)
                    context.pop("purchase_selection", None)
                    context["created_order_id"] = invoice.id
                    conversation.sales_stage = "won"
                    result["sales_stage"] = "won"
                    result["reply"] = _order_created_reply(invoice)
                    result["next_action"] = f"متابعة تجهيز الطلب #{invoice.id}"
                    result["product_ids"] = [int(item.product_id) for item in invoice.items[:1]]
                    conversation.lead_score = max(int(conversation.lead_score or 0), 95)
                    conversation.lead_temperature = "hot"
                elif order_result.status == "reconfirm" and order_result.pending_order:
                    context["pending_order"] = order_result.pending_order
                    conversation.sales_stage = "waiting_confirmation"
                    result["sales_stage"] = "waiting_confirmation"
                    result["reply"] = order_result.message
                    result["next_action"] = "انتظار تأكيد السعر المحدث"
                else:
                    if order_result.status in {"unavailable", "invalid_selection"}:
                        context.pop("pending_order", None)
                        context.pop("purchase_selection", None)
                        conversation.sales_stage = "product_selection"
                    result["reply"] = order_result.message or "تعذر تثبيت الطلب حالياً، حولتك للموظف حتى يكمله بدقة."
                    result["next_action"] = "مراجعة الطلب مع الموظف"
                    if order_result.status not in {"unavailable", "invalid_customer", "invalid_selection"}:
                        conversation.human_takeover = True
                        conversation.ai_enabled = False
                        conversation.status = "waiting_employee"
            else:
                context["pending_order"] = pending_order
                conversation.sales_stage = "waiting_confirmation"
                result["sales_stage"] = "waiting_confirmation"
                if pending_changed:
                    result["reply"] = pending_order_summary(pending_order)
                    result["next_action"] = "انتظار تأكيد الطلب بعد تحديث البيانات"
        else:
            if created_order_id and starting_another_order:
                context.pop("created_order_id", None)
            purchase_selection = dict(context.get("purchase_selection") or {})
            selected_product_id = int(purchase_selection.get("product_id") or 0)
            selected_products = get_products_by_ids([selected_product_id], in_stock_only=False) if selected_product_id else []
            if purchase_selection and order_data_complete(order_customer_data) and selected_products:
                pending_order = build_pending_order(
                    selected_products[0],
                    order_customer_data,
                    message_id=inbound.id,
                    selection_message_id=int(purchase_selection.get("selected_from_message_id") or 0),
                )
                context["pending_order"] = pending_order
                conversation.sales_stage = "waiting_confirmation"
                result["sales_stage"] = "waiting_confirmation"
                result["reply"] = pending_order_summary(pending_order)
                result["next_action"] = "انتظار تأكيد صريح لإنشاء الطلب"

        conversation.set_context(context)
        conversation.summary = _conversation_summary(context, result, products)
    lead = AISalesLead.query.filter_by(conversation_id=conversation.id).first()
    if lead and not greeting_only:
        lead.customer_id = conversation.customer_id
        created_order_id = context.get("created_order_id")
        lead.status = "won" if created_order_id else "ready_to_order" if (
            purchase_intent or conversation.sales_stage == "waiting_confirmation"
        ) else "interested" if conversation.lead_score >= 35 else "qualifying"
        lead.temperature = conversation.lead_temperature
        lead.score = conversation.lead_score
        lead.purchase_probability = min(max(conversation.lead_score, 0), 100)
        lead.estimated_budget = budget or lead.estimated_budget
        lead.main_need = result.get("main_need") or lead.main_need
        lead.primary_objection = context.get("primary_objection") or ""
        lead.next_action = result.get("next_action") or lead.next_action
        if created_order_id:
            lead.won_order_id = int(created_order_id)
            lead.purchase_probability = 100
        product_ids = result.get("product_ids") or []
        if product_ids:
            lead.product_id = int(product_ids[0])

    voice_mode = profile.voice_reply_mode if profile else "text_only"
    explicit_voice = any(phrase in text for phrase in ("رد صوت", "جاوب صوت", "فويس"))
    wants_voice = (
        voice_mode in {"voice_only", "text_and_voice"}
        or (voice_mode == "match_customer" and inbound.message_type in {"audio", "voice"})
        or explicit_voice
    )
    voice_supported = bool(
        profile
        and profile.voice_enabled
        and wants_voice
        and conversation.channel.channel_type in {"whatsapp", "messenger"}
    )
    voice_only_external = bool(send_external and voice_supported and voice_mode == "voice_only")
    reply_parts = (
        [str(result["reply"] or "").strip()]
        if voice_only_external or not send_external
        else _split_outbound_reply(result["reply"])
    )
    if not reply_parts:
        reply_parts = [str(result["reply"] or "").strip()]
    outbound_messages = []
    for reply_part in reply_parts:
        message = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=conversation.channel_account_id,
            direction="outbound",
            sender_type="ai",
            message_type="text",
            text_content=reply_part,
            status="generated" if voice_only_external else "queued" if send_external else "sent",
            sent_at=None if send_external else datetime.utcnow(),
        )
        db.session.add(message)
        outbound_messages.append(message)
    for burst_message in burst_messages:
        burst_message.status = "processed"
    db.session.flush()
    outbound = outbound_messages[0]
    current_app.logger.warning(
        "AI_SALES_OUTBOUND queue_ready conversation_id=%s inbound_message_ids=%s outbound_message_ids=%s recipient=%s reply_parts=%r",
        conversation.id,
        [row.id for row in burst_messages],
        [row.id for row in outbound_messages],
        conversation.external_phone,
        reply_parts,
    )
    if send_external and not voice_only_external:
        recipient = conversation.external_phone if conversation.channel.channel_type == "whatsapp" else conversation.external_contact_id
        for index, message in enumerate(outbound_messages):
            try:
                body = channel_client(conversation.channel).send_text(recipient, message.text_content)
                external_id = outbound_message_id(body)
                message.external_message_id = external_id or None
                message.status = "sent"
                message.sent_at = datetime.utcnow()
                conversation.last_business_message_at = message.sent_at
                conversation.channel.connection_status = "connected"
                conversation.channel.last_error = None
                current_app.logger.warning(
                    "AI_SALES_OUTBOUND accepted part=%s/%s outbound_message_id=%s external_message_id=%s graph_body=%r",
                    index + 1,
                    len(outbound_messages),
                    message.id,
                    message.external_message_id,
                    body,
                )
                if index + 1 < len(outbound_messages):
                    time.sleep(0.12)
            except Exception as exc:
                message.status = "failed"
                message.failure_message = str(exc)
                conversation.channel.last_error = str(exc)
                message.failure_code = str(getattr(exc, "meta_code", "") or "") or None
                current_app.logger.exception(
                    "AI_SALES_OUTBOUND failed part=%s/%s outbound_message_id=%s meta_code=%s response_body=%r",
                    index + 1,
                    len(outbound_messages),
                    message.id,
                    getattr(exc, "meta_code", None),
                    getattr(exc, "response_body", None),
                )
    elif not send_external:
        conversation.last_business_message_at = outbound_messages[-1].sent_at

    if voice_supported:
        voice_message = None
        try:
            has_prior_voice_reply = (
                AISalesMessage.query.filter(
                    AISalesMessage.conversation_id == conversation.id,
                    AISalesMessage.direction == "outbound",
                    AISalesMessage.message_type.in_(("audio", "voice")),
                    AISalesMessage.status.in_(("sent", "delivered", "read")),
                ).first()
                is not None
            )
            speech_path = generate_speech(
                str(result["reply"] or "").strip(),
                voice=profile.voice_name or "marin",
                conversation_id=conversation.id,
                message_id=outbound.id,
                profile=profile,
                disclose_ai=not has_prior_voice_reply,
            )
            audio_format = str(profile.audio_format or "opus").lower()
            audio_mime = {
                "mp3": "audio/mpeg", "opus": "audio/ogg", "aac": "audio/aac",
                "flac": "audio/flac", "wav": "audio/wav", "pcm": "application/octet-stream",
            }.get(audio_format, "audio/mpeg")
            public_token = secrets.token_urlsafe(24) if conversation.channel.channel_type == "messenger" else ""
            voice_message = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=conversation.channel_account_id,
                direction="outbound",
                sender_type="ai",
                message_type="audio",
                text_content="رد صوتي",
                media_path=speech_path,
                mime_type=audio_mime,
                status="sent" if not send_external else "queued",
                sent_at=datetime.utcnow() if not send_external else None,
            )
            if public_token:
                voice_message.set_media_metadata({
                    "public_token": public_token,
                    "voice_note": True,
                    "ai_disclosure_included": not has_prior_voice_reply,
                    "audio_quality": profile.audio_quality or "professional",
                    "voice_speed": float(profile.voice_speed or 0.96),
                })
            db.session.add(voice_message)
            db.session.flush()
            if send_external and conversation.channel.channel_type == "messenger":
                # Meta fetches the public attachment URL during the send request.
                db.session.commit()
            if send_external:
                if conversation.channel.channel_type == "whatsapp":
                    client = WhatsAppClient(conversation.channel)
                    media_id = client.upload_media(speech_path, audio_mime)
                    body = client.send_media(conversation.external_phone, "audio", media_id=media_id)
                    voice_message.external_media_id = media_id
                else:
                    base_url = str(current_app.config.get("BASE_URL") or "https://www.finora.company").strip().rstrip("/")
                    if base_url == "https://finora.company":
                        base_url = "https://www.finora.company"
                    tenant_slug = str(getattr(g, "tenant", "") or "").strip()
                    public_url = f"{base_url}/ai-sales/public/media/{tenant_slug}/{voice_message.id}/{public_token}"
                    body = channel_client(conversation.channel).send_media(
                        conversation.external_contact_id,
                        "audio",
                        url=public_url,
                    )
                voice_message.external_message_id = outbound_message_id(body) or None
                voice_message.status = "sent"
                voice_message.sent_at = datetime.utcnow()
                conversation.last_business_message_at = voice_message.sent_at
        except Exception as exc:
            conversation.channel.last_error = f"voice reply: {exc}"
            if voice_message:
                voice_message.status = "failed"
                voice_message.failure_message = str(exc)
                voice_message.failure_code = str(getattr(exc, "code", "") or "") or None
            if voice_only_external:
                try:
                    recipient = conversation.external_phone if conversation.channel.channel_type == "whatsapp" else conversation.external_contact_id
                    body = channel_client(conversation.channel).send_text(recipient, outbound.text_content)
                    outbound.external_message_id = outbound_message_id(body) or None
                    outbound.status = "sent"
                    outbound.sent_at = datetime.utcnow()
                    conversation.last_business_message_at = outbound.sent_at
                except Exception as fallback_exc:
                    outbound.status = "failed"
                    outbound.failure_message = str(fallback_exc)

    product_ids = result.get("product_ids") or []
    supported_media_channel = conversation.channel.channel_type in {"whatsapp", "messenger", "instagram"}
    outbound_media_type = requested_media or auto_media_type
    if outbound_media_type and product_ids and supported_media_channel:
        selected_product_id = int(product_ids[0])
        assets = (
            requested_media_assets
            if requested_media and selected_product_id == requested_media_product_id
            else get_product_media(selected_product_id, outbound_media_type, limit=2)
        )
        for asset in assets:
            public_url = asset.get("public_url") or ""
            media_path = asset.get("storage_path") or ""
            public_token = secrets.token_urlsafe(24) if conversation.channel.channel_type != "whatsapp" and not public_url else ""
            media_message = AISalesMessage(
                conversation_id=conversation.id,
                channel_account_id=conversation.channel_account_id,
                direction="outbound",
                sender_type="ai",
                message_type=outbound_media_type,
                text_content=asset.get("title") or "",
                media_path=media_path,
                mime_type=asset.get("mime_type") or None,
                status="sent" if not send_external else "queued",
                sent_at=datetime.utcnow() if not send_external else None,
            )
            if public_token:
                media_message.set_media_metadata({"public_token": public_token, "product_media": True})
            db.session.add(media_message)
            db.session.flush()
            if send_external:
                try:
                    if conversation.channel.channel_type == "whatsapp":
                        client = WhatsAppClient(conversation.channel)
                        if public_url:
                            body = client.send_media(conversation.external_phone, outbound_media_type, link=public_url, caption=asset.get("title") or "")
                        elif media_path and os.path.exists(media_path):
                            media_id = client.upload_media(media_path, asset.get("mime_type") or "application/octet-stream")
                            body = client.send_media(conversation.external_phone, outbound_media_type, media_id=media_id, caption=asset.get("title") or "")
                            media_message.external_media_id = media_id
                        else:
                            raise ValueError("ملف الوسائط غير متوفر للإرسال")
                    else:
                        base_url = str(current_app.config.get("BASE_URL") or "https://www.finora.company").strip().rstrip("/")
                        if base_url == "https://finora.company":
                            base_url = "https://www.finora.company"
                        if public_url:
                            media_url = public_url if public_url.startswith("https://") else f"{base_url}/{public_url.lstrip('/')}"
                        elif media_path and os.path.exists(media_path):
                            tenant_slug = str(getattr(g, "tenant", "") or "").strip()
                            db.session.commit()
                            media_url = f"{base_url}/ai-sales/public/media/{tenant_slug}/{media_message.id}/{public_token}"
                        else:
                            raise ValueError("ملف الوسائط غير متوفر للإرسال")
                        body = channel_client(conversation.channel).send_media(
                            conversation.external_contact_id,
                            outbound_media_type,
                            url=media_url,
                        )
                    media_message.external_message_id = outbound_message_id(body) or None
                    media_message.status = "sent"
                    media_message.sent_at = datetime.utcnow()
                except Exception as exc:
                    media_message.status = "failed"
                    media_message.failure_message = str(exc)
    db.session.commit()
    current_app.logger.info(
        "AI_SALES_TIMING message_id=%s stage=complete duration_ms=%s status=%s",
        inbound.id,
        round((time.monotonic() - started_at) * 1000),
        outbound.status,
    )
    return outbound


def dispatch_inbound_async(app, tenant_slug: str, message_id: int, *, send_external: bool = True) -> None:
    def runner():
        with app.app_context():
            g.tenant = tenant_slug
            ensure_ai_sales_schema()
            try:
                process_inbound_message(message_id, send_external=send_external)
            except Exception:
                app.logger.exception("Finora Sales AI background message failed")
                db.session.rollback()
            finally:
                db.session.remove()

    Thread(target=runner, name=f"ai-sales-{tenant_slug}-{message_id}", daemon=True).start()


def mark_customer_activity(conversation: AISalesConversation, timestamp: datetime | None = None) -> None:
    now = timestamp or datetime.utcnow()
    conversation.last_customer_message_at = now
    conversation.service_window_expires_at = now + timedelta(hours=24)
