from __future__ import annotations

from flask import session

from models.product import Product
from modules.storefront.services.product_presenter import product_card
from modules.storefront.services.settings_service import StorefrontSettingsService


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

    def cart_raw(self) -> dict[str, int]:
        raw = session.get(self._cart_key) or {}
        if not isinstance(raw, dict):
            return {}
        clean: dict[str, int] = {}
        for k, v in raw.items():
            pid = self._safe_int(k, 0)
            qty = max(0, min(self._safe_int(v, 0), 9999))
            if pid > 0 and qty > 0:
                clean[str(pid)] = qty
        return clean

    def save_cart_raw(self, cart: dict[str, int]) -> None:
        session[self._cart_key] = cart
        session.modified = True

    def clear(self) -> None:
        self.save_cart_raw({})

    def count(self) -> int:
        return sum(self.cart_raw().values())

    def add(self, product_id: int, quantity: int = 1) -> None:
        cart = self.cart_raw()
        current_qty = self._safe_int(cart.get(str(product_id)), 0)
        cart[str(product_id)] = current_qty + max(1, min(quantity, 999))
        self.save_cart_raw(cart)

    def try_add(self, product_id: int, quantity: int = 1) -> tuple[bool, str]:
        product = Product.query.get(product_id)
        if not product or not product.active or not product.store_visible:
            return False, "المنتج غير متاح."
        available = max(0, self._safe_int(product.quantity, 0))
        requested = max(1, min(self._safe_int(quantity, 1), 999))
        current_qty = self._safe_int(self.cart_raw().get(str(product_id)), 0)
        if available <= 0:
            return False, "هذا المنتج غير متوفر حالياً."
        if current_qty + requested > available:
            remaining = max(0, available - current_qty)
            if remaining <= 0:
                return False, "وصلت للحد المتاح من هذا المنتج في السلة."
            return False, f"الكمية المتاحة للإضافة هي {remaining} فقط."
        self.add(product_id, requested)
        return True, "تمت الإضافة إلى السلة."

    def update_quantities(self, updates: dict[int, int]) -> None:
        cart = self.cart_raw()
        for pid, qty in updates.items():
            if qty <= 0:
                cart.pop(str(pid), None)
            else:
                cart[str(pid)] = max(1, min(qty, 999))
        self.save_cart_raw(cart)

    def try_update_quantities(self, updates: dict[int, int]) -> tuple[bool, str]:
        if not updates:
            return True, "تم تحديث السلة."
        product_ids = [pid for pid in updates.keys() if pid > 0]
        products = Product.query.filter(
            Product.id.in_(product_ids),
            Product.active == True,  # noqa: E712
            Product.store_visible == True,  # noqa: E712
        ).all()
        product_by_id = {product.id: product for product in products}
        clean: dict[int, int] = {}
        for pid, qty in updates.items():
            qty = max(0, min(self._safe_int(qty, 0), 999))
            if qty <= 0:
                clean[pid] = 0
                continue
            product = product_by_id.get(pid)
            if not product:
                return False, "أحد منتجات السلة لم يعد متاحاً."
            available = max(0, self._safe_int(product.quantity, 0))
            if qty > available:
                return False, f"المنتج {product.name}: الكمية المتاحة {available} فقط."
            clean[pid] = qty
        self.update_quantities(clean)
        return True, "تم تحديث السلة."

    def remove(self, product_id: int) -> None:
        cart = self.cart_raw()
        cart.pop(str(product_id), None)
        self.save_cart_raw(cart)

    def items(self) -> list[dict]:
        raw = self.cart_raw()
        if not raw:
            return []
        ids = [self._safe_int(k, 0) for k in raw.keys()]
        products = Product.query.filter(
            Product.id.in_(ids),
            Product.active == True,  # noqa: E712
            Product.store_visible == True,  # noqa: E712
        ).all()
        product_by_id = {p.id: p for p in products}
        items = []
        for sid, qty in raw.items():
            pid = self._safe_int(sid, 0)
            product = product_by_id.get(pid)
            if not product:
                continue
            card = product_card(product, self.tenant_slug)
            card["quantity"] = max(1, qty)
            card["line_total"] = card["price"] * card["quantity"]
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
                    "image_url": i.get("image_url") or "",
                }
                for i in totals["items"]
            ],
        }
