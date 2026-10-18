from __future__ import annotations

import os
import re
from typing import Any

from flask import url_for

from modules.storefront.services.cart_service import StorefrontCartService
from modules.storefront.services.inventory_knowledge import (
    build_catalog_text,
    extract_foot_size,
    match_products,
    product_foot_size,
    product_cards_for_chat,
)
from modules.storefront.services.settings_service import StorefrontSettingsService
from modules.storefront.services.tracking_service import lookup_order


from modules.storefront.constants import DEFAULT_GREETING, DEFAULT_SUGGESTIONS


def _has_openai_key() -> bool:
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return True
    try:
        from flask import g

        old_tenant = getattr(g, "tenant", None)
        g.tenant = None
        from models.core.global_setting import GlobalSetting

        key = (GlobalSetting.get_setting("OPENAI_API_KEY", "") or "").strip()
        g.tenant = old_tenant
        return bool(key)
    except Exception:
        return False


def _build_store_context(
    shop_slug: str,
    store_design: dict[str, Any],
    settings: StorefrontSettingsService,
) -> str:
    city_fees, default_fee = settings.shipping_config()
    coupon = settings.coupon_config()
    shipping_lines = [f"- {city}: {fee} د.ع" for city, fee in city_fees.items()]
    coupon_line = "لا يوجد كوبون نشط."
    if coupon.get("enabled"):
        if coupon.get("type") == "fixed":
            coupon_line = f"كوبون {coupon['code']}: خصم {coupon['value']} د.ع"
        else:
            coupon_line = f"كوبون {coupon['code']}: خصم {coupon['value']}%"

    cart_url = url_for("storefront.cart_page", tenant_slug=shop_slug)
    checkout_url = url_for("storefront.checkout_page", tenant_slug=shop_slug)
    track_url = url_for("storefront.tracking_page", tenant_slug=shop_slug)
    shop_url = url_for("storefront.store_index", tenant_slug=shop_slug)

    return "\n".join(
        [
            f"اسم المتجر: {store_design.get('store_name') or 'متجر المنتجات'}",
            "طريقة الدفع: الدفع عند الاستلام فقط.",
            f"رسوم الشحن الافتراضية: {default_fee} د.ع",
            "رسوم الشحن حسب المدينة:",
            *shipping_lines,
            coupon_line,
            f"رابط المتجر: {shop_url}",
            f"رابط السلة: {cart_url}",
            f"رابط إتمام الطلب: {checkout_url}",
            f"رابط تتبع الطلب: {track_url}",
        ]
    )


def _build_cart_context(cart: StorefrontCartService) -> str:
    summary = cart.summary()
    if not summary.get("items"):
        return "السلة فارغة حالياً."
    lines = [
        f"عدد القطع في السلة: {summary.get('count', 0)}",
        f"المجموع الفرعي: {summary.get('subtotal', 0)} د.ع",
        f"الخصم: {summary.get('discount_amount', 0)} د.ع",
        f"الصافي: {summary.get('net_subtotal', 0)} د.ع",
    ]
    if summary.get("active_coupon"):
        lines.append(f"الكوبون المفعّل: {summary['active_coupon']}")
    lines.append("محتويات السلة:")
    for item in summary.get("items") or []:
        lines.append(
            f"- {item.get('name')} | الكمية: {item.get('quantity')} | السعر: {item.get('price')} د.ع"
        )
    return "\n".join(lines)


def _extract_track_payload(message: str, track: dict[str, Any] | None) -> dict[str, str]:
    payload = track or {}
    invoice_id = str(payload.get("invoice_id") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    if invoice_id and phone:
        return {"invoice_id": invoice_id, "phone": phone}

    text = _normalize_track_text(message)
    invoice_match = re.search(r"(?:طلب|فاتورة|order|#)\s*[:#]?\s*(\d{1,8})", text, re.I)
    if invoice_match:
        invoice_id = invoice_match.group(1)
    phone_match = re.search(r"(07\d{9}|7\d{9})", re.sub(r"\D", "", text))
    if phone_match:
        phone = phone_match.group(1)
        if len(phone) == 10 and phone.startswith("7"):
            phone = "0" + phone
    return {"invoice_id": invoice_id, "phone": phone}


def _normalize_track_text(text: str) -> str:
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return str(text or "").translate(trans)


def _build_system_prompt(assistant_name: str) -> str:
    return f"""أنت {assistant_name} — مساعد مبيعات ودود لمتجر إلكتروني عراقي.
قواعد صارمة:
- أجب فقط بناءً على بيانات المتجر والمخزون والسلة المرفقة في السياق.
- لا تخترع أسعاراً أو منتجات أو حالات طلب غير موجودة.
- تحدث بعربية عراقية خفيفة ومفهومة، بطريقة طبيعية ومحترمة من دون مبالغة.
- اجعل الرد جملة أو جملتين فقط، وبحد أقصى 35 كلمة.
- لا تكتب روابط، ولا قوائم طويلة، ولا عناوين، ولا تكرر بيانات بطاقات المنتجات.
- الأصل أن تسولف مع الزبون وتجاوبه نصياً عن السعر والتوفر والمواصفات.
- لا تفترض أن مجرد سؤال الزبون عن منتج يعني أنه يريد بطاقة أو صورة؛ البطاقات تظهر فقط إذا طلب رؤيتها صراحةً.
- عند ظهور بطاقات منتجات، قدّمها بكلام قصير ثم اسأل سؤال متابعة واحداً مفيداً.
- عند السؤال عن السلة، استخدم ملخص السلة المرفق.
- عند تتبع الطلب، اطلب رقم الطلب ورقم الهاتف إن لم تتوفر.
- اذكر أن الدفع عند الاستلام عند الحاجة.
- لا تذكر الذكاء الاصطناعي أو المفاتيح أو الأخطاء التقنية للزبون."""


_NON_PRODUCT_TERMS = (
    "سلة",
    "سلتي",
    "شحن",
    "توصيل",
    "تتبع",
    "طلبي",
    "حالة الطلب",
    "الدفع",
    "كوبون",
)

_PRODUCT_INQUIRY_TERMS = (
    "منتج",
    "منتجات",
    "متوفر",
    "متوفرة",
    "موجود",
    "سعر",
    "أسعار",
    "عرض",
    "عروض",
    "اشتري",
    "شراء",
    "ثلاجة",
    "ثلاجه",
    "مجمدة",
    "مجمده",
    "فريزر",
    "شاشة",
    "شاشه",
    "تلفزيون",
)


def _normalize_card_intent(text: str) -> str:
    return _normalize_track_text(text).translate(
        str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
    ).strip().lower()


def _is_product_inquiry(message: str, products: list[Any]) -> bool:
    text = _normalize_card_intent(message)
    if not text or any(term in text for term in _NON_PRODUCT_TERMS):
        return False
    if any(_normalize_card_intent(term) in text for term in _PRODUCT_INQUIRY_TERMS):
        return True

    # A brand/model/name by itself is still a product inquiry, but it does not
    # mean the customer asked to see a visual product card.
    for product in products:
        raw_name = product.get("name", "") if isinstance(product, dict) else getattr(product, "name", "")
        name = _normalize_card_intent(str(raw_name or ""))
        if not name:
            continue
        meaningful = [token for token in re.findall(r"[\u0600-\u06ffa-z0-9]{2,}", name) if len(token) > 2]
        if any(token in text for token in meaningful):
            return True
    return False


def _should_show_product_cards(message: str, products: list[Any]) -> bool:
    """Show cards only after an explicit request to see the product visually."""
    if not products:
        return False

    text = _normalize_card_intent(message)
    if not text or any(term in text for term in _NON_PRODUCT_TERMS):
        return False

    direct_requests = (
        "صوره",
        "صورته",
        "صورتها",
        "صور المنتج",
        "شكل المنتج",
        "شكله",
        "شكلها",
        "وريني",
        "فرجيني",
        "اعرضلي",
        "اعرض لي",
        "افتحلي",
        "افتح لي",
        "دزلي",
        "دز لي",
        "ارسللي",
        "ارسل لي",
        "ابعثلي",
        "ابعث لي",
        "اريني",
        "اعرض المنتج",
        "اعرض المنتجات",
        "بطاقه المنتج",
        "رابط المنتج",
        "تفاصيل المنتج",
        "تفاصيله",
        "تفاصيلها",
        "عرض التفاصيل",
    )
    if any(term in text for term in direct_requests):
        return True

    # Covers conversational requests such as "أريد أشوف الشاشة" and
    # "ممكن أشوفها؟" while keeping "أريد شاشة" as a text-only inquiry.
    return bool(
        re.search(
            r"(?:اريد|ممكن|خليني|خل)\s+(?:ا)?شوف(?:ه|ها|هم|\s+(?:ال)?(?:منتج|شاشه|ثلاجه|مجمده|فريزر|تلفزيون))",
            text,
        )
    )


def _compact_reply(reply: str, *, has_products: bool = False) -> str:
    text = str(reply or "").strip()
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?im)^\s*(?:[-*•]|\d+[.)])\s*", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -–—|\n")

    if not text:
        return "هاي المنتجات الموجودة 👇" if has_products else "شلون أگدر أساعدك؟"

    max_chars = 190 if has_products else 240
    if len(text) > max_chars:
        shortened = text[: max_chars + 1].rsplit(" ", 1)[0].rstrip("،؛:.- ")
        text = f"{shortened}…"
    return text


def _foot_size_reply(message: str, products: list[Any]) -> str:
    requested_size = extract_foot_size(message)
    if requested_size is None or not products:
        return ""
    selected_size = product_foot_size(products[0])
    if selected_size is None:
        return ""
    if selected_size == requested_size:
        return f"إي، متوفر قياس {requested_size} قدم 👌 عرضتلك الموجود بالأسفل."
    return (
        f"قياس {requested_size} قدم مو متوفر حالياً، "
        f"أقرب حجم موجود هو {selected_size} قدم 👇"
    )


def _fallback_reply(
    message: str,
    products: list[dict[str, Any]],
    cart_summary: dict[str, Any],
    track_info: dict[str, Any] | None,
    *,
    show_product_cards: bool = True,
) -> str:
    lower = str(message or "").lower()
    if track_info and track_info.get("found"):
        return (
            f"تم العثور على طلبك رقم {track_info.get('invoice_id')}. "
            f"الحالة: {track_info.get('status')}."
        )
    if track_info and track_info.get("error") and ("تتبع" in lower or track_info.get("invoice_id")):
        return str(track_info.get("error"))

    if any(word in lower for word in ("سلة", "السلة", "cart")):
        if cart_summary.get("items"):
            return (
                f"سلتك تحتوي {cart_summary.get('count', 0)} قطعة "
                f"بمجموع {cart_summary.get('net_subtotal', 0)} د.ع."
            )
        return "سلتك فارغة حالياً. يمكنك إضافة منتجات من البطاقات أدناه."

    if any(word in lower for word in ("شحن", "توصيل", "delivery")):
        return "رسوم الشحن تختلف حسب المدينة وتظهر عند إتمام الطلب. الدفع عند الاستلام."

    if products and _is_product_inquiry(message, products):
        if show_product_cards:
            if len(products) == 1:
                return "أكيد، هذا هو المنتج اللي طلبت تشوفه 👇"
            return "أكيد، هاي أقرب الخيارات لطلبك 👇 تحب أساعدك تختار بينها؟"

        first = products[0]
        name = str(first.get("name") or "المنتج").strip()
        price = int(float(first.get("price") or 0))
        availability = "متوفر حالياً" if first.get("is_available") else "متاح بالطلب"
        if len(products) == 1:
            return f"إي، {name} {availability} وسعره {price:,} د.ع. شنو تحب تعرف عنه أكثر؟"
        prices = [int(float(item.get("price") or 0)) for item in products if item.get("price")]
        start_price = min(prices) if prices else price
        return f"إي، عدنا أكثر من خيار قريب من طلبك وتبدأ الأسعار من {start_price:,} د.ع. شكد ميزانيتك حتى أحددلك الأنسب؟"

    return "أكيد، شنو المنتج اللي ببالك؟ اكتب اسمه أو النوع والسعر المناسب إلك."


class StorefrontAIAssistantService:
    def __init__(self):
        self._settings = StorefrontSettingsService()

    def chat(
        self,
        *,
        message: str,
        history: list[dict[str, str]] | None,
        shop_slug: str,
        cart: StorefrontCartService,
        store_design: dict[str, Any] | None = None,
        track: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message = str(message or "").strip()
        if not message:
            return {"success": False, "error": "الرسالة فارغة."}

        design = store_design or self._settings.design_settings()
        assistant_name = str(design.get("ai_assistant_name") or "مساعد المتجر").strip()
        greeting = str(design.get("ai_assistant_greeting") or DEFAULT_GREETING).strip()

        products_db = match_products(message, history)
        catalog_text = build_catalog_text(products_db, shop_slug)
        show_product_cards = _should_show_product_cards(message, products_db)
        matched_product_cards = product_cards_for_chat(products_db, shop_slug)[:4]
        product_cards = matched_product_cards if show_product_cards else []
        cart_summary = cart.summary()
        store_context = _build_store_context(shop_slug, design, self._settings)
        cart_context = _build_cart_context(cart)

        track_payload = _extract_track_payload(message, track)
        track_info: dict[str, Any] | None = None
        if track_payload.get("invoice_id") and track_payload.get("phone"):
            track_info = lookup_order(track_payload["invoice_id"], track_payload["phone"])
        elif any(word in message for word in ("تتبع", "طلبي", "وين طلبي", "حالة الطلب")):
            track_info = {"found": False, "error": "", "steps": [], "public_url": "", "status": ""}

        system_content = "\n\n".join(
            [
                _build_system_prompt(assistant_name),
                "=== إعدادات المتجر ===",
                store_context,
                "=== ملخص السلة ===",
                cart_context,
                "=== أسلوب العرض لهذه الرسالة ===",
                (
                    "الزبون طلب رؤية المنتج صراحةً؛ ستظهر له بطاقات المنتجات مع الرد."
                    if show_product_cards
                    else "هذه محادثة نصية فقط؛ جاوب الزبون وتابع وياه من دون الإشارة إلى بطاقة أو صورة معروضة."
                ),
                "=== كتالوج المنتجات المطابقة ===",
                catalog_text,
            ]
        )
        if track_info:
            if track_info.get("found"):
                system_content += (
                    "\n\n=== حالة الطلب المطلوب ===\n"
                    f"رقم الطلب: {track_info.get('invoice_id')}\n"
                    f"الحالة: {track_info.get('status')}\n"
                    f"المجموع: {track_info.get('grand_total')} د.ع"
                )
            elif track_info.get("error"):
                system_content += f"\n\n=== تتبع الطلب ===\n{track_info['error']}"

        messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
        for item in (history or [])[-10:]:
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})

        reply = ""
        ai_used = False
        if _has_openai_key():
            from ai import ai_utils

            ok, text = ai_utils.call_openai(messages, timeout_sec=25)
            if ok:
                reply = _compact_reply(text, has_products=bool(product_cards))
                ai_used = True
            else:
                reply = _fallback_reply(
                    message,
                    matched_product_cards,
                    cart_summary,
                    track_info,
                    show_product_cards=show_product_cards,
                )
        else:
            reply = _fallback_reply(
                message,
                matched_product_cards,
                cart_summary,
                track_info,
                show_product_cards=show_product_cards,
            )

        nearest_size_reply = _foot_size_reply(message, products_db if product_cards else [])
        if nearest_size_reply:
            reply = nearest_size_reply
        reply = _compact_reply(reply, has_products=bool(product_cards))

        return {
            "success": True,
            "reply": reply,
            "products": product_cards,
            "cart": cart_summary,
            "track": track_info or {},
            "suggestions": list(design.get("ai_assistant_suggestions") or DEFAULT_SUGGESTIONS),
            "greeting": greeting,
            "assistant_name": assistant_name,
            "ai_used": ai_used,
        }
