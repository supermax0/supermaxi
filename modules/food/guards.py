"""Business-type and permission guards for the food workspace."""
from __future__ import annotations

from functools import wraps

from flask import g, jsonify, redirect, request, session

from extensions import db
from models.employee import Employee
from models.tenant import Tenant

BUSINESS_TYPE = "food_wholesale_retail"
FOOD_PERMISSIONS = (
    "food_cashier",
    "food_orders",
    "food_products",
    "food_purchases",
    "food_inventory",
    "food_parties",
    "food_finance",
    "food_reports",
    "food_settings",
)

FOOD_PRODUCT_PERMISSIONS = (
    "products.create",
    "products.update",
    "products.archive",
    "products.manage_cost",
    "products.manage_prices",
    "inventory.opening_balance",
    "view_profit",
)

FOOD_CASHIER_PERMISSIONS = (
    "cashier.sell",
    "cashier.discount_item",
    "cashier.discount_invoice",
    "cashier.override_price",
    "cashier.sell_credit",
    "cashier.override_credit_limit",
    "cashier.return",
    "cashier.void_sale",
    "cashier.reprint",
    "cashier.open_drawer",
    "cashier.view_other_branch_stock",
    "cashier.sell_negative_stock",
)

FOOD_PERMISSION_FALLBACKS = {
    "products.create": "food_products",
    "products.update": "food_products",
    "products.archive": "food_products",
    "products.manage_cost": "food_products",
    "products.manage_prices": "food_products",
    "inventory.opening_balance": "food_inventory",
    "view_profit": "food_reports",
    "cashier.sell": "food_cashier",
    "cashier.sell_credit": "food_cashier",
    "cashier.reprint": "food_cashier",
}


def tenant_business_type() -> str:
    try:
        row = Tenant.query.first()
        if row and getattr(row, "business_type", None):
            return str(row.business_type).strip()
    except Exception:
        db.session.rollback()
    return str(session.get("business_type") or "general").strip()


def is_food_tenant() -> bool:
    return tenant_business_type() == BUSINESS_TYPE


def current_employee() -> Employee | None:
    employee_id = session.get("user_id")
    return db.session.get(Employee, employee_id) if employee_id else None


def current_tenant_id() -> int:
    value = session.get("tenant_id")
    try:
        if value is not None:
            return int(value)
    except (TypeError, ValueError):
        pass
    row = Tenant.query.first()
    return int(row.id) if row else 1


def can_use_food(permission: str | None = None) -> bool:
    employee = current_employee()
    if not employee or not employee.is_active:
        return False
    if employee.role == "admin":
        return True
    if not permission:
        return False
    return bool(
        employee.has_permission(permission)
        or (
            FOOD_PERMISSION_FALLBACKS.get(permission)
            and employee.has_permission(FOOD_PERMISSION_FALLBACKS[permission])
        )
    )


def food_guard_response(json_mode: bool = False):
    if not is_food_tenant():
        message = "هذه المساحة مخصصة لنشاط المواد الغذائية – جملة ومفرد."
        return (jsonify({"ok": False, "error": message}), 403) if json_mode else redirect("/")
    return None


def require_food(permission: str | None = None, *, json_mode: bool = False):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            denied = food_guard_response(json_mode=json_mode)
            if denied:
                return denied
            if not can_use_food(permission):
                message = "ليس لديك صلاحية لهذه العملية."
                return (jsonify({"ok": False, "error": message}), 403) if json_mode else redirect("/food/")
            g.food_employee = current_employee()
            g.food_tenant_id = current_tenant_id()
            return fn(*args, **kwargs)

        return wrapped

    return decorator
