from __future__ import annotations

from flask import session

from models.product import Product
from modules.storefront.services.catalog_service import (
    cash_store_product_is_visible,
    published_installment_item,
)
from modules.storefront.services.product_presenter import product_card
from modules.storefront.services.settings_service import StorefrontSettingsService
from utils.product_color_service import get_color_quantity, get_product_colors, product_has_colors
from utils.trade_in_service import TradeInError, resolve_sale_selection


class StorefrontCartService:
    def __init__(self, tenant_slug: str):
        self.tenant_slug = str(tenant_slug or "").strip()
        self._settings = StorefrontSettingsService()
        self._cart_key = f"storefront_cart:{self.tenant_slug}"
        self._coupon_key = f"storefront_coupon:{self.tenant_slug}"

    def _safe_int(self, value, default=0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _line_key(
        self,
        product_id: int,
        color: str = "",
        sale_mode: str = "normal",
        source_product_id: int | None = None,
    ) -> str:
        return "|".join(
            [
                str(int(product_id)),
                str(color or "").strip(),
                str(sale_mode or "normal").strip(),
                "",
            ]
        )

    def _parse_line_key(self, key: str) -> tuple[int, str, str, int | None]:
        parts = str(key or "").split("|", 3)
        pid = self._safe_int(parts[0] if parts else 0, 0)
        if len(parts) == 1:
            return pid, "", "normal", None
        color = str(parts[1] or "").strip()
        mode = str(parts[2] or "normal").strip()
        source_id = self._safe_int(parts[3] if len(parts) > 3 else 0, 0) or None
        return pid, color, mode, source_id

    def cart_raw(self) -> dict[str, int]:
        raw = session.get(self._cart_key) or {}
        if not isinstance(raw, dict):
            return {}
        clean: dict[str, int] = {}
        for k, v in raw.items():
            pid, color, mode, _source = self._parse_line_key(k)
            qty = max(0, min(self._safe_int(v, 0), 9999))
            if pid > 0 and qty > 0:
                canonical = self._line_key(pid, color, mode)
                clean[canonical] = clean.get(canonical, 0) + qty
        return clean

    def save_cart_raw(self, cart: dict[str, int]) -> None:
        session[self._cart_key] = cart
        session.modified = True

    def clear(self) -> None:
        self.save_cart_raw({})

    def count(self) -> int:
        return sum(self.cart_raw().values())

    def add(
        self,
        product_id: int,
        quantity: int = 1,
        *,
        color: str = "",
        sale_mode: str = "normal",
        source_product_id: int | None = None,
    ) -> None:
        cart = self.cart_raw()
        key = self._line_key(product_id, color, sale_mode, source_product_id)
        current_qty = self._safe_int(cart.get(key), 0)
        cart[key] = current_qty + max(1, min(quantity, 9999))
        self.save_cart_raw(cart)

    def try_add(
        self,
        product_id: int,
        quantity: int = 1,
        *,
        color: str = "",
        sale_mode: str = "normal",
        source_product_id: int | None = None,
    ) -> tuple[bool, str]:
        product = Product.query.get(product_id)
        if not cash_store_product_is_visible(product):
            return False, "المنتج غير متاح."
        # «بيع / استبدال» is a cashier operation (the old device is inspected in the shop): online orders are always
        # a normal sale, whatever the browser sends.
        sale_mode, source_product_id = "normal", None
        color = str(color or "").strip()
        from utils.product_options import validate_selection
        from utils.product_color_service import ProductColorError, get_available_color_quantity
        try:
            color = validate_selection(product, color)
        except ProductColorError as exc:
            return False, str(exc)
        if product_has_colors(product):
            if not color:
                return False, f"يجب اختيار لون للمنتج: {product.name}"
            color_names = {
                str(row.get("name") or "").strip()
                for row in get_product_colors(product.id)
                if str(row.get("name") or "").strip()
            }
            if color not in color_names:
                return False, f"اللون المختار غير متاح للمنتج: {product.name}"
        else:
            color = ""
        try:
            mode, _price, source = resolve_sale_selection(
                product,
                {
                    "sale_mode": sale_mode,
                    "variant_color": color,
                    "trade_in_source_product_id": source_product_id,
                },
            )
        except TradeInError as exc:
            return False, str(exc)
        requested = max(1, min(self._safe_int(quantity, 1), 9999))
        if color and int(product.quantity or 0) > 0:
            current = sum(qty for key, qty in self.cart_raw().items()
                          if self._parse_line_key(key)[:2] == (int(product_id), color))
            if current + requested > get_available_color_quantity(product.id, color):
                return False, "الكمية المطلوبة من هذا الخيار غير متوفرة"
        self.add(
            product_id,
            requested,
            color=color,
            sale_mode=mode,
            source_product_id=None,
        )
        return True, "تمت الإضافة إلى السلة."

    def update_quantities(self, updates: dict) -> None:
        cart = self.cart_raw()
        for raw_key, qty in updates.items():
            key = str(raw_key)
            if "|" not in key:
                matching = [k for k in cart if self._parse_line_key(k)[0] == self._safe_int(key)]
                if len(matching) == 1:
                    key = matching[0]
            if qty <= 0:
                cart.pop(key, None)
            else:
                cart[key] = max(1, min(qty, 9999))
        self.save_cart_raw(cart)

    def try_update_quantities(self, updates: dict) -> tuple[bool, str]:
        if not updates:
            return True, "تم تحديث السلة."
        product_ids = [
            self._parse_line_key(str(key))[0]
            for key in updates.keys()
            if self._parse_line_key(str(key))[0] > 0
        ]
        products = Product.query.filter(
            Product.id.in_(product_ids),
            Product.active == True,  # noqa: E712
        ).all()
        product_by_id = {
            product.id: product
            for product in products
            if cash_store_product_is_visible(product)
        }
        clean: dict[str, int] = {}
        projected = self.cart_raw()
        for raw_key, qty in updates.items():
            key = str(raw_key)
            if "|" not in key:
                matching = [k for k in projected if self._parse_line_key(k)[0] == self._safe_int(key)]
                if len(matching) == 1:
                    key = matching[0]
            pid, color, _mode, _source = self._parse_line_key(key)
            qty = max(0, min(self._safe_int(qty, 0), 9999))
            if qty <= 0:
                clean[key] = 0
                projected.pop(key, None)
                continue
            product = product_by_id.get(pid)
            if not product:
                return False, "أحد منتجات السلة لم يعد متاحاً."
            clean[key] = qty
            projected[key] = qty

        from utils.product_options import validate_selection
        from utils.product_color_service import ProductColorError, get_available_color_quantity
        grouped = {}
        for key, qty in projected.items():
            pid, color, _mode, _source = self._parse_line_key(key)
            if pid not in product_by_id:
                continue
            product = product_by_id[pid]
            try:
                validate_selection(product, color)
            except ProductColorError as exc:
                return False, str(exc)
            if color:
                grouped[(pid, color)] = grouped.get((pid, color), 0) + qty
        for (pid, color), qty in grouped.items():
            if int(product_by_id[pid].quantity or 0) > 0 and qty > get_available_color_quantity(pid, color):
                return False, "الكمية المطلوبة من هذا الخيار غير متوفرة"
        self.update_quantities(clean)
        return True, "تم تحديث السلة."

    def remove(self, product_id: int, line_key: str | None = None) -> None:
        cart = self.cart_raw()
        if line_key:
            cart.pop(str(line_key), None)
        else:
            for key in list(cart):
                if self._parse_line_key(key)[0] == int(product_id):
                    cart.pop(key, None)
        self.save_cart_raw(cart)

    def items(self) -> list[dict]:
        raw = self.cart_raw()
        if not raw:
            return []
        ids = [self._parse_line_key(k)[0] for k in raw.keys()]
        products = Product.query.filter(
            Product.id.in_(ids),
            Product.active == True,  # noqa: E712
        ).all()
        product_by_id = {
            product.id: product
            for product in products
            if cash_store_product_is_visible(product)
        }
        items = []
        for line_key, qty in raw.items():
            pid, color, sale_mode, source_id = self._parse_line_key(line_key)
            product = product_by_id.get(pid)
            if not product:
                continue
            catalog_item = published_installment_item(product.id)
            card = product_card(product, self.tenant_slug, catalog_item=catalog_item)
            try:
                mode, price, source = resolve_sale_selection(
                    product,
                    {
                        "sale_mode": sale_mode,
                        "trade_in_source_product_id": source_id,
                        "variant_color": color,
                    },
                )
            except TradeInError:
                continue
            if mode == "normal" and catalog_item is not None and not color:
                price = int(catalog_item.cash_price or 0)
            card["price"] = price
            if card.get("price_currency") == "USD":
                from modules.storefront.services.product_presenter import iqd_per_usd

                card["price_iqd"] = int(round(int(price or 0) * float(iqd_per_usd())))
            else:
                card["price_iqd"] = int(price or 0)
            card["color"] = color
            card["sale_mode"] = mode
            card["trade_in_source_product_id"] = None
            card["trade_in_source_product_name"] = ""
            card["line_key"] = line_key
            if color:
                from utils.product_color_service import get_available_color_quantity
                card["stock"] = get_available_color_quantity(product.id, color)
                selected = next((row for row in card.get("colors", []) if row["name"] == color), None)
                if selected and selected.get("image_url"):
                    card["image_url"] = selected["image_url"]
            card["quantity"] = max(1, qty)
            card["line_total"] = int(card.get("price_iqd") or card["price"]) * card["quantity"]
            items.append(card)
        return items

    def coupon_get(self) -> dict | None:
        data = session.get(self._coupon_key) or {}
        if not isinstance(data, dict):
            return None
        code = str(data.get("code") or "").strip().upper()
        if not code:
            return None
        return {"code": code}

    def coupon_set(self, code: str | None) -> None:
        if not code:
            session.pop(self._coupon_key, None)
        else:
            session[self._coupon_key] = {"code": str(code).strip().upper()}
        session.modified = True

    def apply_coupon(self, code: str) -> tuple[bool, str]:
        normalized = str(code or "").strip().upper()
        if not normalized:
            self.coupon_set(None)
            return False, "يرجى إدخال كود الكوبون."

        conf = self._settings.coupon_config()
        if not conf["enabled"]:
            self.coupon_set(None)
            return False, "لا يوجد كوبون نشط حالياً."
        if normalized != conf["code"]:
            self.coupon_set(None)
            return False, "كود الكوبون غير صحيح."
        self.coupon_set(normalized)
        return True, "تم تطبيق الكوبون بنجاح."

    def remove_coupon(self) -> None:
        self.coupon_set(None)

    def discount_for_subtotal(self, subtotal: int) -> tuple[int, dict | None]:
        current = self.coupon_get()
        conf = self._settings.coupon_config()
        if not current or not conf["enabled"] or current["code"] != conf["code"]:
            return 0, None
        if conf["type"] == "fixed":
            discount = min(subtotal, conf["value"])
        else:
            discount = min(subtotal, int(round(subtotal * (conf["value"] / 100.0))))
        return max(0, discount), conf

    def totals(self, shipping_fee: int = 0) -> dict:
        items = self.items()
        subtotal = sum(int(i["line_total"]) for i in items)
        discount_amount, coupon = self.discount_for_subtotal(subtotal)
        net_subtotal = max(0, subtotal - discount_amount)
        grand_total = net_subtotal
        return {
            "items": items,
            "subtotal": subtotal,
            "discount_amount": discount_amount,
            "net_subtotal": net_subtotal,
            "shipping_fee": max(0, shipping_fee),
            "grand_total": grand_total,
            "active_coupon": coupon["code"] if coupon else "",
        }

    def summary(self) -> dict:
        totals = self.totals()
        return {
            "count": self.count(),
            "subtotal": totals["subtotal"],
            "discount_amount": totals["discount_amount"],
            "net_subtotal": totals["net_subtotal"],
            "active_coupon": totals["active_coupon"],
            "items": [
                {
                    "id": i["id"],
                    "name": i["name"],
                    "quantity": i["quantity"],
                    "price": i["price"],
                    "line_total": i["line_total"],
                    "line_key": i["line_key"],
                    "color": i.get("color") or "",
                    "sale_mode": i.get("sale_mode") or "normal",
                    "trade_in_source_product_id": i.get("trade_in_source_product_id"),
                    "trade_in_source_product_name": i.get("trade_in_source_product_name") or "",
                    "image_url": i.get("image_url") or "",
                }
                for i in totals["items"]
            ],
        }
