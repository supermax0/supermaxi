from __future__ import annotations

import os
import re

from flask import current_app

from modules.storefront.constants import DEFAULT_GREETING, DEFAULT_SUGGESTIONS

DEFAULT_SHIPPING_BY_CITY = {
    "بغداد": 5000,
    "البصرة": 7000,
    "نينوى": 7000,
    "أربيل": 7000,
    "النجف": 6000,
    "كربلاء": 6000,
    "ذي قار": 7000,
}


def safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_hex_color(value: str, default: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw
    return default


class StorefrontSettingsService:
    def _flags(self) -> dict:
        try:
            settings = SystemSettings.get_settings()
            return settings.get_ui_flags() if settings else {}
        except Exception:
            current_app.logger.exception("failed loading storefront settings")
            return {}

    def design_settings(self) -> dict:
        defaults = {
            "primary_color": "#4f8cff",
            "shipping_color": "#10b981",
            "card_style": "modern",
            "preset": "custom",
            "theme_mode": "light",
        }
        flags = self._flags()
        card_style = str(flags.get("storefront_product_card_style") or defaults["card_style"]).strip()
        if card_style not in {"modern", "compact", "showcase", "minimal", "bordered", "overlay"}:
            card_style = defaults["card_style"]
        preset = str(flags.get("storefront_theme_preset") or defaults["preset"]).strip()
        if preset not in {"custom", "ocean", "sunset", "emerald"}:
            preset = defaults["preset"]
        theme_mode = str(flags.get("storefront_theme_mode") or defaults["theme_mode"]).strip().lower()
        if theme_mode not in {"light", "dark", "auto"}:
            theme_mode = defaults["theme_mode"]

        ai_enabled_raw = flags.get("storefront_ai_assistant_enabled")
        if ai_enabled_raw is None:
            ai_assistant_enabled = self._default_ai_enabled()
        else:
            ai_assistant_enabled = bool(ai_enabled_raw)

        return {
            "primary_color": safe_hex_color(flags.get("storefront_primary_color"), defaults["primary_color"]),
            "shipping_color": safe_hex_color(flags.get("storefront_shipping_color"), defaults["shipping_color"]),
            "card_style": card_style,
            "preset": preset,
            "theme_mode": theme_mode,
            "hero_title": str(flags.get("storefront_hero_title") or "واجهة متجر احترافية").strip(),
            "hero_subtitle": str(
                flags.get("storefront_hero_subtitle")
                or "ابحث، فلتر، واختر منتجاتك بسهولة. كل عملية شراء تمر عبر سلة متكاملة ثم Checkout بالدفع عند الاستلام."
            ).strip(),
            "store_name": str(flags.get("storefront_store_name") or "متجر المنتجات").strip(),
            "logo_url": str(flags.get("storefront_logo_url") or "").strip(),
            "whatsapp": str(flags.get("storefront_whatsapp") or "").strip(),
            "ai_assistant_enabled": ai_assistant_enabled,
            "ai_assistant_name": str(flags.get("storefront_ai_assistant_name") or "مساعد المتجر").strip(),
            "ai_assistant_greeting": str(flags.get("storefront_ai_assistant_greeting") or DEFAULT_GREETING).strip(),
            "ai_assistant_suggestions": list(DEFAULT_SUGGESTIONS),
        }

    @staticmethod
    def _default_ai_enabled() -> bool:
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
            return True

    def coupon_config(self) -> dict:
        flags = self._flags()
        code = str(flags.get("storefront_coupon_code") or "").strip().upper()
        ctype = str(flags.get("storefront_coupon_type") or "percent").strip().lower()
        if ctype not in {"percent", "fixed"}:
            ctype = "percent"
        value = max(0, safe_int(flags.get("storefront_coupon_value"), 0))
        enabled = bool(code and value > 0)
        return {"enabled": enabled, "code": code, "type": ctype, "value": value}

    def shipping_config(self) -> tuple[dict[str, int], int]:
        city_fees = dict(DEFAULT_SHIPPING_BY_CITY)
        default_fee = 7000
        flags = self._flags()
        custom = flags.get("storefront_shipping_by_city")
        if isinstance(custom, dict):
            for city, fee in custom.items():
                city_name = str(city or "").strip()
                if not city_name:
                    continue
                city_fees[city_name] = max(0, safe_int(fee, city_fees.get(city_name, default_fee)))
        default_fee = max(0, safe_int(flags.get("storefront_shipping_default_fee"), default_fee))
        return city_fees, default_fee

    @staticmethod
    def normalized_city(value: str) -> str:
        return str(value or "").replace("-", " ").strip().lower()

    def shipping_fee_for_city(self, city: str) -> tuple[int, dict[str, int]]:
        city_fees, default_fee = self.shipping_config()
        normalized = self.normalized_city(city)
        for name, fee in city_fees.items():
            if self.normalized_city(name) == normalized:
                return fee, city_fees
        return default_fee, city_fees

    def shipping_fee_for_cart(self, city: str, cart_items: list[dict]) -> tuple[int, list[dict]]:
        from utils.product_delivery_fees import fee_for_cart_items

        items = []
        for row in cart_items or []:
            if not isinstance(row, dict):
                continue
            product_id = safe_int(row.get("product_id") or row.get("id"), 0)
            qty = max(1, safe_int(row.get("quantity") or row.get("qty"), 1))
            if product_id > 0:
                items.append({"product_id": product_id, "qty": qty})
        if not items:
            fee, city_fees = self.shipping_fee_for_city(city)
            return fee, []
        fee, breakdown = fee_for_cart_items(items, city)
        return fee, breakdown
