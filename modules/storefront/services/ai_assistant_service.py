from __future__ import annotations

import os
import re
from typing import Any

from flask import url_for

from modules.storefront.services.cart_service import StorefrontCartService
from modules.storefront.services.inventory_knowledge import (
    build_catalog_text,
    match_products,
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
    return f"""أنت {assistant_name} — مساعد ذكي لمتجر إلكتروني باللغة العربية.
قواعد صارمة:
- أجب فقط بناءً على بيانات المتجر والمخزون والسلة المرفقة في السياق.
- لا تخترع أسعاراً أو منتجات أو حالات طلب غير موجودة.
- عند السؤال عن منتج، اذكر الاسم والسعر والتوفر باختصار ووجّه لصفحة التفاصيل.
- عند السؤال عن السلة، استخدم ملخص السلة المرفق.
- عند تتبع الطلب، اطلب رقم الطلب ورقم الهاتف إن لم تتوفر.
- اذكر أن الدفع عند الاستلام عند الحاجة.
- كن مختصراً، ودوداً، واحترافياً.
- استخدم تنسيقاً واضحاً مع نقاط عند الحاجة."""


def _fallback_reply(
    message: str,
    products: list[dict[str, Any]],
    cart_summary: dict[str, Any],
    track_info: dict[str, Any] | None,
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

    if products:
        names = "، ".join(p.get("name", "") for p in products[:4] if p.get("name"))
        return f"إليك بعض المنتجات المناسبة: {names}. يمكنك عرض التفاصيل أو الإضافة للسلة من البطاقات."

    return (
        "أنا مساعد المتجر. اسألني عن منتج معين، السلة، الشحن، أو تتبع طلبك. "
        "(تفعيل الذكاء الاصطناعي الكامل يتطلب مفتاح OpenAI.)"
    )


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
        product_cards = product_cards_for_chat(products_db, shop_slug)
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
                reply = text
                ai_used = True
            else:
                reply = _fallback_reply(message, product_cards, cart_summary, track_info)
                if text and "OpenAI" in text:
                    reply += f"\n\n({text})"
        else:
            reply = _fallback_reply(message, product_cards, cart_summary, track_info)

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
