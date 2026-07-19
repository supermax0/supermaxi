"""Safe Finora-backed tools for mobile AI (no invented products/prices)."""
from __future__ import annotations

import json
import re
from typing import Any

from extensions import db
from models.product import Product
from modules.mobile_app.models import MobileFavorite, MobileUser
from modules.mobile_app.services import cart_checkout as cart_service
from modules.mobile_app.services import catalog as catalog_service
from modules.mobile_app.services import discounts as discount_service
from modules.mobile_app.services import rewards as reward_service
from modules.mobile_app.services.cart_checkout import CartError


TOOL_NAMES = (
    "get_shopper_context",
    "search_products",
    "get_product_details",
    "get_current_price",
    "get_stock_status",
    "suggest_by_budget",
    "compare_products",
    "get_user_rewards",
    "get_active_coupons",
    "get_order_status",
    "add_item_to_cart",
)


def tool_definitions() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "get_shopper_context",
                "description": "Get privacy-safe shopper context: first name, city, rewards, recent-order totals, and favorite categories",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_products",
                "description": "Search real store products by keyword",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_product_details",
                "description": "Get one product card by id",
                "parameters": {
                    "type": "object",
                    "properties": {"product_id": {"type": "integer"}},
                    "required": ["product_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_price",
                "description": "Get live sale price for a product",
                "parameters": {
                    "type": "object",
                    "properties": {"product_id": {"type": "integer"}},
                    "required": ["product_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_stock_status",
                "description": "Get stock availability for a product",
                "parameters": {
                    "type": "object",
                    "properties": {"product_id": {"type": "integer"}},
                    "required": ["product_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "suggest_by_budget",
                "description": "Suggest available products within a max budget (IQD)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "budget": {"type": "integer"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["budget"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "compare_products",
                "description": "Compare 2-3 real products by id",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                        }
                    },
                    "required": ["product_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_user_rewards",
                "description": "Get the shopper points balance and tier",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_active_coupons",
                "description": "List active public coupons",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_order_status",
                "description": "Get order tracking for an invoice owned by the user",
                "parameters": {
                    "type": "object",
                    "properties": {"order_id": {"type": "integer"}},
                    "required": ["order_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_item_to_cart",
                "description": "Propose adding a product to cart (requires user confirmation)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer"},
                        "quantity": {"type": "integer"},
                    },
                    "required": ["product_id"],
                },
            },
        },
    ]


def responses_tool_definitions() -> list[dict]:
    """Convert the registry to strict Responses API function tools."""
    tools: list[dict] = []
    for definition in tool_definitions():
        function = dict(definition.get("function") or {})
        parameters = dict(function.get("parameters") or {"type": "object"})
        parameters.setdefault("type", "object")
        parameters.setdefault("properties", {})
        parameters.setdefault("required", [])
        parameters["additionalProperties"] = False
        tools.append(
            {
                "type": "function",
                "name": function.get("name"),
                "description": function.get("description") or "",
                "parameters": parameters,
                "strict": True,
            }
        )
    return tools


def _compact_product(card: dict) -> dict:
    return {
        "id": card.get("id"),
        "name": card.get("name") or card.get("custom_title"),
        "price": card.get("special_price") or card.get("price"),
        "old_price": card.get("old_price"),
        "stock_status": card.get("stock_status"),
        "is_available": card.get("is_available"),
        "category": card.get("category"),
        "image_url": card.get("image_url"),
        "description": (card.get("description") or "")[:240],
    }


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    user_id: int,
) -> dict[str, Any]:
    name = str(name or "").strip()
    args = arguments or {}

    if name == "get_shopper_context":
        user = db.session.get(MobileUser, user_id)
        rewards = reward_service.get_rewards_summary(user_id)
        recent_orders = cart_service.list_orders(user_id, limit=5)
        favorite_rows = (
            MobileFavorite.query.filter_by(user_id=user_id)
            .order_by(MobileFavorite.id.desc())
            .limit(20)
            .all()
        )
        categories: dict[str, int] = {}
        for favorite in favorite_rows:
            product = db.session.get(Product, favorite.product_id)
            if product is None:
                continue
            category = str(
                catalog_service.to_mobile_product(product).get("category") or ""
            ).strip()
            if category:
                categories[category] = categories.get(category, 0) + 1
        customer = getattr(user, "customer", None) if user else None
        return {
            "profile": {
                "first_name": str(getattr(user, "name", "") or "")
                .strip()
                .split(" ")[0],
                "city": str(getattr(customer, "city", "") or "").strip(),
            },
            "rewards": {
                "balance": int(rewards.get("balance") or 0),
                "tier": str((rewards.get("tier") or {}).get("name") or ""),
            },
            "recent_orders": [
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "total": item.get("total"),
                }
                for item in recent_orders
            ],
            "favorite_categories": [
                category
                for category, _ in sorted(
                    categories.items(), key=lambda pair: (-pair[1], pair[0])
                )[:5]
            ],
        }

    if name == "search_products":
        q = str(args.get("query") or "").strip()
        limit = min(20, max(1, int(args.get("limit") or 8)))
        items = catalog_service.search_products(q, user_id=user_id, limit=limit) if q else []
        return {"items": [_compact_product(i) for i in items], "count": len(items)}

    if name == "get_product_details":
        pid = int(args.get("product_id") or 0)
        item = catalog_service.get_product(pid, user_id=user_id)
        if item is None:
            return {"error": "المنتج غير موجود", "product": None}
        return {"product": _compact_product(item)}

    if name == "get_current_price":
        pid = int(args.get("product_id") or 0)
        product = db.session.get(Product, pid)
        if product is None or not product.active:
            return {"error": "المنتج غير موجود"}
        card = catalog_service.to_mobile_product(product)
        return {
            "product_id": pid,
            "name": product.name,
            "price": card.get("special_price") or card.get("price") or int(product.sale_price or 0),
            "old_price": card.get("old_price"),
        }

    if name == "get_stock_status":
        pid = int(args.get("product_id") or 0)
        product = db.session.get(Product, pid)
        if product is None:
            return {"error": "المنتج غير موجود"}
        qty = max(0, int(product.quantity or 0))
        return {
            "product_id": pid,
            "name": product.name,
            "quantity": qty,
            "stock_status": catalog_service.stock_label(qty, active=bool(product.active)),
            "is_available": bool(product.active and qty > 0),
        }

    if name == "suggest_by_budget":
        budget = max(0, int(args.get("budget") or 0))
        q = str(args.get("query") or "").strip()
        limit = min(15, max(1, int(args.get("limit") or 6)))
        if q:
            pool = catalog_service.search_products(q, user_id=user_id, limit=40)
        else:
            pool = catalog_service.list_products(
                q="", category="", sort="price_asc", availability="in_stock", limit=40, offset=0, user_id=user_id
            )
        matched = []
        for item in pool:
            price = int(item.get("special_price") or item.get("price") or 0)
            if price <= 0:
                continue
            if budget > 0 and price > budget:
                continue
            if not item.get("is_available", True):
                continue
            matched.append(_compact_product(item))
            if len(matched) >= limit:
                break
        return {"budget": budget, "items": matched, "count": len(matched)}

    if name == "compare_products":
        ids = [int(x) for x in (args.get("product_ids") or []) if str(x).isdigit() or isinstance(x, int)]
        ids = ids[:3]
        items = []
        for pid in ids:
            item = catalog_service.get_product(pid, user_id=user_id)
            if item:
                items.append(_compact_product(item))
        return {"items": items, "count": len(items)}

    if name == "get_user_rewards":
        return {"rewards": reward_service.get_rewards_summary(user_id)}

    if name == "get_active_coupons":
        return {"items": discount_service.list_public_coupons()}

    if name == "get_order_status":
        oid = int(args.get("order_id") or 0)
        order = cart_service.get_order(user_id, oid)
        if order is None:
            return {"error": "الطلب غير موجود أو لا يخصك", "order": None}
        return {
            "order": {
                "id": order["id"],
                "status": order["status"],
                "payment_status": order.get("payment_status"),
                "total": order["total"],
                "steps": order.get("steps") or [],
            }
        }

    if name == "add_item_to_cart":
        pid = int(args.get("product_id") or 0)
        qty = max(1, min(int(args.get("quantity") or 1), 99))
        product = db.session.get(Product, pid)
        if product is None or not product.active:
            return {"error": "المنتج غير متاح", "requires_confirmation": False}
        card = catalog_service.to_mobile_product(product, favorited=False)
        return {
            "requires_confirmation": True,
            "pending_action": {
                "type": "add_to_cart",
                "product_id": pid,
                "quantity": qty,
                "name": product.name,
                "price": int(card.get("special_price") or card.get("price") or product.sale_price or 0),
            },
            "message": f"هل تريد إضافة «{product.name}» إلى العربة؟",
        }

    return {"error": f"أداة غير معروفة: {name}"}


def confirm_add_to_cart(*, user_id: int, product_id: int, quantity: int = 1) -> dict:
    try:
        cart = cart_service.add_item(
            user_id=user_id, product_id=product_id, quantity=quantity
        )
        return {"ok": True, "cart": cart, "ui_actions": [{"type": "open_cart"}]}
    except CartError as exc:
        return {"ok": False, "error": exc.message, "code": exc.code}


def extract_budget(text: str) -> int | None:
    """Parse Iraqi/Arabic budget mentions like 700 ألف or 700000."""
    raw = str(text or "")
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    raw = raw.translate(trans)
    # Prefer explicit budget phrasing
    m = re.search(
        r"(?:ميزانية|ميزانيتي|بحدود|حتى|اقل من|أقل من)?\s*(\d[\d,]*)\s*(ألف|الف|k)",
        raw,
        re.I,
    )
    if m:
        return int(m.group(1).replace(",", "")) * 1000
    m = re.search(r"(?:ميزانية|ميزانيتي)\s*(\d[\d,]*)", raw, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def extract_order_id(text: str) -> int | None:
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    raw = str(text or "").translate(trans)
    m = re.search(r"(?:طلب|فاتورة|order)\s*(?:رقم|#|:)?\s*(\d{1,8})", raw, re.I)
    if m:
        return int(m.group(1))
    return None


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)
