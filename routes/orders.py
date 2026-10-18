import os
import threading
from pathlib import Path
from types import SimpleNamespace

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    send_file,
    send_from_directory,
    session,
    redirect,
    url_for,
    current_app,
    abort,
    g,
    has_request_context,
)
from extensions import db
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload
from models.invoice import Invoice
from utils.business_time import utc_period_filter
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.order_item import OrderItem
from models.product import Product
from models.customer import Customer
from models.employee import Employee
from utils.permission_checks import (
    allowed_order_statuses_for,
    check_permission,
    employee_can,
    get_current_employee,
    guard_order_access,
    guard_permission,
)
from models.shipping import ShippingCompany
from models.report import Report
from models.shipping_report import ShippingReport
from models.invoice_settings import InvoiceSettings
from models.invoice_template import InvoiceTemplate, TenantTemplateSettings
from models.delivery_agent import DeliveryAgent
from models.activity_log import ActivityLog
from models.message import Message
from datetime import datetime, date
from sqlalchemy import String, cast, func
from io import BytesIO
import pandas as pd
import json
import re
from sqlalchemy import or_, and_
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


# Payment touches the invoice, stock, treasury ledger and commissions in one
# unit.  SQLite ignores row locks, so serialize that unit inside the process;
# PostgreSQL additionally gets a database row lock below.
_ORDER_PAYMENT_LOCK = threading.RLock()

from utils.order_status import (
    is_canceled,
    is_returned,
    is_completed,
    ensure_return_status_unified,
    ensure_delivered_status_normalized,
    RETURN_STATUS,
    invoice_returned_condition,
    is_return_status_value,
)
from utils.order_lifecycle import OrderLifecycleError, process_order_cancel, process_order_return, restore_order_stock_once
from utils.order_stock_lock import (
    LOCKED_ORDER_MESSAGE,
    auto_unlock_locked_orders,
    is_stock_locked,
    locked_order_response,
)
from utils.order_stock_policy import (
    OrderStockError,
    deferred_stock_enabled,
    ensure_policy_initialized,
    ensure_stock_for_transition,
    prepare_order_for_dispatch,
    select_order_stock_branch,
    stock_is_deducted,
)
from utils.cash_calculations import _effective_paid_amount
from utils.delivery_expense_service import remove_delivery_expense_for_invoice, sync_delivery_expense_for_invoice
from utils.order_shipping import apply_manual_delivery_fee_on_payment, is_shipping_item, order_item_display_name
from utils.shipping_barcodes import (
    get_shipping_barcodes_list,
    set_shipping_barcodes,
    shipping_barcodes_display,
    shipping_barcodes_match_code,
    should_move_order_to_shipping_on_barcode_save,
)
from utils.payment_ledger import append_payment_ledger_delta, ensure_invoice_payment_ledger_table
from utils.invoice_schema_guard import ensure_invoice_schema
from utils.shipping_settlement_service import ensure_paid_shipping_order_settled
from services.media_service import get_thumbnail_upload_root, get_video_upload_root, save_uploaded_file
from services.pos_checkout import PosCheckoutError, create_pos_order
from utils.activity_logger import INVOICE_SNAPSHOT_FIELDS, log_activity, log_mutation, snapshot_attrs
from utils.invoice_mutation_policy import (
    PAID_INVOICE_MUTATION_DISABLED_MESSAGE,
    invoice_has_financial_effect,
    paid_invoice_mutation_denied,
    paid_invoice_mutations_enabled,
)

orders_bp = Blueprint("orders", __name__, url_prefix="/orders")
_ORDERS_PUBLIC_PREFIXES = ("/orders/p/o/", "/orders/invoice-video/")
# A single server page stays bounded; the browser can still navigate every order.
_ORDERS_GRID_PAGE_MAX = 500


def required_order_mutation_permission(path, payload=None):
    """Map an order write request to its narrowest RBAC permission."""
    path = (path or "").rstrip("/")
    payload = payload if isinstance(payload, dict) else {}

    if path in ("/orders/payment", "/orders/payment/adjust"):
        payment_status = payload.get("payment")
        return "return_orders" if is_return_status_value(payment_status) else "pay_orders"
    if path == "/orders/bulk-return":
        return "return_orders"
    if path.startswith("/orders/delete/") or path.startswith("/orders/cancel/"):
        return "delete_orders"
    if path == "/orders/update":
        status = payload.get("status")
        if is_return_status_value(status):
            return "return_orders"
        if is_canceled(status, None):
            return "delete_orders"
    return "manage_orders"


def _can_return_order(order):
    """Match the full-return lifecycle, including payment-only cancellation repair."""
    return bool(
        not is_stock_locked(order)
        and (order.status or "").strip() not in {"تم الطلب", "ملغي"}
        and not is_returned(order.status, order.payment_status)
    )


def _order_history_name_maps(logs):
    """Resolve saved assignment ids to readable names for the order timeline."""
    shipping_ids = set()
    agent_ids = set()

    def collect(snapshot):
        if not isinstance(snapshot, dict):
            return
        shipping_id = snapshot.get("shipping_company_id")
        agent_id = snapshot.get("delivery_agent_id")
        if shipping_id not in (None, ""):
            try:
                shipping_ids.add(int(shipping_id))
            except (TypeError, ValueError):
                pass
        if agent_id not in (None, ""):
            try:
                agent_ids.add(int(agent_id))
            except (TypeError, ValueError):
                pass

    for entry in logs:
        payload = entry.get_payload()
        collect(payload.get("before"))
        collect(payload.get("after"))
        collect(payload.get("invoice"))
        extra = payload.get("extra")
        if isinstance(extra, dict):
            collect(extra)

    shipping_names = {
        row.id: row.name
        for row in ShippingCompany.query.filter(ShippingCompany.id.in_(shipping_ids)).all()
    } if shipping_ids else {}
    agent_names = {
        row.id: row.name
        for row in DeliveryAgent.query.filter(DeliveryAgent.id.in_(agent_ids)).all()
    } if agent_ids else {}
    return shipping_names, agent_names


def _order_history_snapshot(payload, key):
    value = payload.get(key)
    if isinstance(value, dict):
        return value
    if key == "after" and isinstance(payload.get("invoice"), dict):
        return payload["invoice"]
    return {}


def _order_history_events(order, logs):
    """Expand audit entries into clear, one-movement-per-row timeline records."""
    shipping_names, agent_names = _order_history_name_maps(logs)
    events = []
    stats = {
        "views": 0,
        "prints": 0,
        "agent_dispatches": 0,
        "shipping_dispatches": 0,
    }
    has_create = False

    def readable(mapping, value, empty="بدون تحديد"):
        if value in (None, ""):
            return empty
        try:
            key = int(value)
        except (TypeError, ValueError):
            return str(value)
        return mapping.get(key, f"#{key}")

    def append(entry, movement, details="", movement_type="other", suffix=0):
        events.append({
            "id": f"{entry.id}-{suffix}",
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "movement": movement,
            "details": details or "",
            "employee": entry.employee_name or "النظام",
            "type": movement_type,
        })

    for entry in logs:
        payload = entry.get_payload()
        before = _order_history_snapshot(payload, "before")
        after = _order_history_snapshot(payload, "after")
        action = (entry.action or "").lower()

        if action == "create":
            has_create = True
            append(entry, "إنشاء الطلب", entry.summary, "create")
            create_shipping = after.get("shipping_company_id")
            create_agent = after.get("delivery_agent_id")
            if create_shipping not in (None, ""):
                stats["shipping_dispatches"] += 1
                append(
                    entry,
                    "إرسال الطلب إلى شركة النقل",
                    readable(shipping_names, create_shipping),
                    "shipping",
                    1,
                )
            if create_agent not in (None, ""):
                stats["agent_dispatches"] += 1
                append(
                    entry,
                    "إرسال الطلب إلى المندوب",
                    readable(agent_names, create_agent),
                    "agent",
                    2,
                )
            continue
        if action == "view":
            stats["views"] += 1
            append(entry, "مشاهدة تفاصيل الطلب", entry.summary, "view")
            continue
        if action == "print":
            stats["prints"] += 1
            append(entry, "طباعة الفاتورة", entry.summary, "print")
            continue

        changes = []
        old_status, new_status = before.get("status"), after.get("status")
        if new_status is not None and old_status != new_status:
            changes.append((
                "تغيير حالة الطلب",
                f"من {old_status or '—'} إلى {new_status or '—'}",
                "status",
            ))

        old_payment, new_payment = before.get("payment_status"), after.get("payment_status")
        if new_payment is not None and old_payment != new_payment:
            changes.append((
                "تغيير حالة التسديد",
                f"من {old_payment or '—'} إلى {new_payment or '—'}",
                "payment",
            ))

        old_shipping = before.get("shipping_company_id")
        new_shipping = after.get("shipping_company_id")
        if "shipping_company_id" in after and old_shipping != new_shipping:
            if new_shipping not in (None, ""):
                stats["shipping_dispatches"] += 1
                changes.append((
                    "إرسال الطلب إلى شركة النقل",
                    f"من {readable(shipping_names, old_shipping)} إلى {readable(shipping_names, new_shipping)}",
                    "shipping",
                ))
            else:
                changes.append((
                    "إلغاء ربط شركة النقل",
                    readable(shipping_names, old_shipping),
                    "shipping",
                ))

        if any(key in after and before.get(key) != after.get(key) for key in ("shipping_barcode", "shipping_barcodes_json")):
            def receipt_text(values):
                raw = values.get("shipping_barcodes_json")
                try:
                    numbers = json.loads(raw) if raw else []
                except (TypeError, ValueError):
                    numbers = []
                return " | ".join(str(number) for number in numbers) if isinstance(numbers, list) and numbers else str(values.get("shipping_barcode") or "—")
            changes.append(("تحديث وصل شركة النقل", f"من {receipt_text(before)} إلى {receipt_text(after)}", "shipping_receipt"))
        old_agent = before.get("delivery_agent_id")
        new_agent = after.get("delivery_agent_id")
        if "delivery_agent_id" in after and old_agent != new_agent:
            if new_agent not in (None, ""):
                stats["agent_dispatches"] += 1
                changes.append((
                    "إرسال الطلب إلى المندوب",
                    f"من {readable(agent_names, old_agent)} إلى {readable(agent_names, new_agent)}",
                    "agent",
                ))
            else:
                changes.append((
                    "إلغاء ربط المندوب",
                    readable(agent_names, old_agent),
                    "agent",
                ))

        if changes:
            for index, (movement, details, movement_type) in enumerate(changes):
                append(entry, movement, details, movement_type, index)
        else:
            append(entry, entry.summary or "تحديث الطلب", "", action or "other")

    if not has_create:
        events.append({
            "id": "created",
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "movement": "إنشاء الطلب",
            "details": f"تم إنشاء الطلب #{order.id}",
            "employee": order.employee_name or "النظام",
            "type": "create",
        })

    events.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return events, stats


@orders_bp.after_request
def _orders_no_store_cache(response):
    """Prevent browsers from keeping stale orders table UI/JS."""
    if request.endpoint and str(request.endpoint).startswith("orders."):
        if response.mimetype and "html" in response.mimetype:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["X-Orders-UI-Build"] = "20260720i"
    return response


def _orders_grid_rows(q, limit=_ORDERS_GRID_PAGE_MAX):
    """Load one bounded slice for the orders grid and attach stock traces."""
    rows = q.limit(int(limit)).all()
    try:
        from utils.order_stock_trace import build_order_stock_trace_map

        traces = build_order_stock_trace_map(rows)
        for row in rows:
            row.stock_trace = traces.get(int(row.id))
    except Exception:
        current_app.logger.exception("Failed building order stock traces")
        for row in rows:
            row.stock_trace = None
    return rows


_ORDERS_PAGE_STATUS_FILTERS = {
    "ordered": lambda: Invoice.status == "تم الطلب",
    "packed": lambda: Invoice.status == "معباة",
    "shipping": lambda: Invoice.status == "جاري الشحن",
    "delivered": lambda: or_(
        Invoice.status == "تم التوصيل",
        Invoice.payment_status == "مسدد",
    ),
    "returned": lambda: or_(
        invoice_returned_condition(Invoice),
        Invoice.status == "ملغي",
        Invoice.payment_status == "ملغي",
    ),
    "cancelled": lambda: Invoice.status == "ملغي",
}

_ORDERS_PAGE_PERMISSIONS = {
    "ordered": "can_see_orders_placed",
    "packed": "can_see_orders_packed",
    "shipping": "can_see_orders_shipped",
    "delivered": "can_see_orders_delivered",
    "returned": "can_see_orders_returned",
    "cancelled": "can_see_orders_returned",
}


def _orders_data_permission_denied(page_type):
    denied = guard_permission("can_see_orders", json=True)
    if denied:
        return denied
    permission = _ORDERS_PAGE_PERMISSIONS.get(page_type)
    if permission and not check_permission(permission):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    return None


def _orders_text_filter(expression, model):
    """Translate the small, safe subset of AG Grid text filters we expose."""
    value = str((model or {}).get("filter") or "").strip()
    if not value:
        return None
    filter_type = str((model or {}).get("type") or "contains")
    if filter_type == "equals":
        return expression == value
    if filter_type == "notEqual":
        return expression != value
    if filter_type == "startsWith":
        return expression.ilike(f"{value}%")
    if filter_type == "endsWith":
        return expression.ilike(f"%{value}")
    if filter_type == "notContains":
        return ~expression.ilike(f"%{value}%")
    return expression.ilike(f"%{value}%")


def _orders_number_filter(expression, model):
    try:
        value = float((model or {}).get("filter"))
    except (TypeError, ValueError):
        return None
    filter_type = str((model or {}).get("type") or "equals")
    if filter_type == "notEqual":
        return expression != value
    if filter_type == "lessThan":
        return expression < value
    if filter_type == "lessThanOrEqual":
        return expression <= value
    if filter_type == "greaterThan":
        return expression > value
    if filter_type == "greaterThanOrEqual":
        return expression >= value
    if filter_type == "inRange":
        try:
            upper = float((model or {}).get("filterTo"))
        except (TypeError, ValueError):
            return expression == value
        return expression.between(value, upper)
    return expression == value


def _orders_phone_filter(model):
    phone_condition = _orders_text_filter(Customer.phone, model)
    phone2_condition = _orders_text_filter(func.coalesce(Customer.phone2, ""), model)
    if phone_condition is None or phone2_condition is None:
        return None
    filter_type = str((model or {}).get("type") or "contains")
    if filter_type in {"notEqual", "notContains"}:
        return and_(phone_condition, phone2_condition)
    return or_(phone_condition, phone2_condition)


def _orders_search_condition(search):
    like = f"%{search}%"
    return or_(
        Customer.name.ilike(like),
        Customer.phone.ilike(like),
        Customer.phone2.ilike(like),
        cast(Invoice.id, String).ilike(like),
        Invoice.barcode.ilike(like),
        Invoice.shipping_barcode.ilike(like),
        Invoice.shipping_barcodes_json.ilike(like),
    )


def _orders_apply_grid_column_filters(q):
    raw = request.args.get("filter_model", "")
    if not raw or len(raw) > 12000:
        return q
    try:
        models = json.loads(raw)
    except (TypeError, ValueError):
        return q
    if not isinstance(models, dict):
        return q

    text_fields = {
        "barcode": Invoice.barcode,
        "customer_name": Customer.name,
        "phone2": Customer.phone2,
        "status": Invoice.status,
        "payment_status": Invoice.payment_status,
        "employee": Invoice.employee_name,
        "page_name": Invoice.page_name,
        "city": Customer.city,
        "address": Customer.address,
        "shipping_company": ShippingCompany.name,
        "shipping_barcode": Invoice.shipping_barcode,
        "delivery_agent": DeliveryAgent.name,
        "note": Invoice.note,
    }
    number_fields = {
        "order_id": Invoice.id,
        "total": Invoice.total,
        "paid_amount": Invoice.paid_amount,
        "remaining": func.coalesce(Invoice.total, 0) - func.coalesce(Invoice.paid_amount, 0),
    }
    for field, model in models.items():
        if not isinstance(model, dict):
            continue
        condition = None
        if field == "phone":
            condition = _orders_phone_filter(model)
        elif field in text_fields:
            condition = _orders_text_filter(text_fields[field], model)
        elif field in number_fields:
            condition = _orders_number_filter(number_fields[field], model)
        if condition is not None:
            q = q.filter(condition)
    return q


def _orders_data_query(page_type):
    q = (
        Invoice.query
        .join(Customer)
        .outerjoin(ShippingCompany, Invoice.shipping_company_id == ShippingCompany.id)
        .outerjoin(DeliveryAgent, Invoice.delivery_agent_id == DeliveryAgent.id)
    )

    page_condition = _ORDERS_PAGE_STATUS_FILTERS.get(page_type)
    if page_condition:
        q = q.filter(page_condition())

    employee = get_current_employee()
    if page_type == "all" and employee and employee.role != "admin":
        allowed_statuses = allowed_order_statuses_for(employee)
        q = q.filter(Invoice.status.in_(allowed_statuses)) if allowed_statuses else q.filter(Invoice.id == -1)

    scheduled_date = request.args.get("scheduled_date", "").strip()
    created_date = request.args.get("created_date", "").strip()
    # Keep scheduled orders discoverable in the normal tables. Restrict them
    # only when the user explicitly chooses a scheduled date.
    if scheduled_date:
        try:
            target = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target)
        except ValueError:
            pass
    if created_date:
        try:
            target = datetime.strptime(created_date, "%Y-%m-%d").date()
            q = q.filter(utc_period_filter(Invoice.created_at, target, target))
        except ValueError:
            pass

    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    if date_from:
        try:
            q = q.filter(utc_period_filter(Invoice.created_at, datetime.strptime(date_from, "%Y-%m-%d").date(), None))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(utc_period_filter(Invoice.created_at, None, datetime.strptime(date_to, "%Y-%m-%d").date()))
        except ValueError:
            pass
    amount_min = request.args.get("amount_min", type=int)
    amount_max = request.args.get("amount_max", type=int)
    if amount_min is not None:
        q = q.filter(func.coalesce(Invoice.total, 0) >= amount_min)
    if amount_max is not None:
        q = q.filter(func.coalesce(Invoice.total, 0) <= amount_max)

    cities = [value.strip() for value in request.args.getlist("city") if value.strip()]
    if cities:
        q = q.filter(Customer.city.in_(cities))
    if request.args.get("status"):
        q = q.filter(Invoice.status == request.args["status"])
    if request.args.get("payment"):
        q = q.filter(Invoice.payment_status == request.args["payment"])
    if request.args.get("employee"):
        q = q.filter(Invoice.employee_name == request.args["employee"])
    if request.args.get("shipping"):
        q = q.filter(ShippingCompany.name == request.args["shipping"])

    agent = request.args.get("delivery_agent", "").strip()
    if agent == "none":
        q = q.filter(Invoice.delivery_agent_id.is_(None))
    elif agent:
        q = q.filter(DeliveryAgent.name == agent)

    search = request.args.get("search", "").strip()
    if search:
        q = q.filter(_orders_search_condition(search))

    installment_type = (request.args.get("installment_type") or "").strip().lower()
    installment_status = (request.args.get("installment_status") or "").strip().upper()
    if installment_type in {"installment", "normal"} or installment_status:
        try:
            from modules.order_installment_lifecycle.models import OrderInstallmentLifecycle
            from modules.order_installment_lifecycle.schema_guard import ensure_order_installment_tables

            ensure_order_installment_tables()
            oil_subq = db.session.query(OrderInstallmentLifecycle.order_id).distinct()
            if installment_status:
                oil_subq = oil_subq.filter(OrderInstallmentLifecycle.status == installment_status)
            oil_subq = oil_subq.subquery()
            if installment_type == "installment" or installment_status:
                q = q.filter(Invoice.id.in_(db.session.query(oil_subq.c.order_id)))
            elif installment_type == "normal":
                q = q.filter(~Invoice.id.in_(db.session.query(oil_subq.c.order_id)))
        except Exception:
            pass

    return _orders_apply_grid_column_filters(q)


def _orders_duplicate_meta(q, rows):
    """Keep duplicate-risk highlighting accurate across server pages."""
    customer_ids = {row.customer_id for row in rows if row.customer_id}
    if not customer_ids:
        return {}
    groups = {}
    matches = (
        q.order_by(None)
        .filter(Invoice.customer_id.in_(customer_ids))
        .with_entities(Invoice.customer_id, Invoice.employee_id, Invoice.employee_name)
        .all()
    )
    for customer_id, employee_id, employee_name in matches:
        group = groups.setdefault(customer_id, {"count": 0, "employees": set()})
        group["count"] += 1
        employee_key = (
            f"id:{employee_id}"
            if employee_id
            else f"name:{str(employee_name or '').strip().lower()}"
        )
        group["employees"].add(employee_key)
    return {
        customer_id: {
            "count": group["count"],
            "risk": (
                "different_employee"
                if group["count"] > 1 and len(group["employees"]) > 1
                else "same_employee" if group["count"] > 1 else ""
            ),
        }
        for customer_id, group in groups.items()
    }


def _food_sale_mix_by_invoice(invoice_ids):
    ids = [int(value) for value in invoice_ids if value]
    if not ids:
        return {}
    try:
        from modules.food.models import FoodSaleItemSnapshot

        rows = db.session.query(
            OrderItem.invoice_id,
            FoodSaleItemSnapshot.sale_mode,
        ).join(
            FoodSaleItemSnapshot,
            FoodSaleItemSnapshot.order_item_id == OrderItem.id,
        ).filter(OrderItem.invoice_id.in_(ids)).all()
    except Exception:
        return {}
    modes = {}
    for invoice_id, sale_mode in rows:
        modes.setdefault(int(invoice_id), set()).add(str(sale_mode or "").upper())
    return {
        invoice_id: (
            "مختلط" if len(values) > 1
            else "جملة" if values == {"WHOLESALE"}
            else "مفرد" if values == {"RETAIL"}
            else "—"
        )
        for invoice_id, values in modes.items()
    }


def _serialize_order_grid_row(order, duplicate_meta=None, food_sale_mix=None, installment_lifecycle=None):
    customer = order.customer
    total = int(order.total or 0)
    paid = int(order.paid_amount or 0)
    status = order.status or "تم الطلب"
    payment_status = order.payment_status or "غير مسدد"
    returned_values = {"راجع", "مرتجع", "راجعة", "ملغي"}
    duplicate = (duplicate_meta or {}).get(order.customer_id, {})
    oil = None
    if installment_lifecycle is not None:
        try:
            from modules.order_installment_lifecycle.service import countdown_label

            oil = {
                **installment_lifecycle.to_dict(),
                "countdown": countdown_label(installment_lifecycle),
                "is_installment": True,
            }
        except Exception:
            oil = {"is_installment": True, "status": getattr(installment_lifecycle, "status", None)}
    return {
        "id": order.id,
        "checkbox": "",
        "order_id": order.id,
        "date": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "—",
        "created_date": order.created_at.strftime("%Y-%m-%d") if order.created_at else "",
        "scheduled_date": order.scheduled_date.strftime("%Y-%m-%d") if order.scheduled_date else "",
        "barcode": order.barcode or "—",
        "customer_id": order.customer_id,
        "customer_name": customer.name if customer and customer.name else "—",
        "phone": customer.phone if customer and customer.phone else "—",
        "phone2": customer.phone2 if customer and customer.phone2 else "—",
        "quantity": len(order.items or []),
        "stock_trace": getattr(order, "stock_trace", None),
        "total": total,
        "paid_amount": paid,
        "remaining": total - paid,
        "status": status,
        "payment_status": payment_status,
        "source_module": order.source_module,
        "food_sale_mix": (food_sale_mix or {}).get(int(order.id), "—"),
        "employee_id": order.employee_id,
        "employee": order.employee_name or "—",
        "page_name": order.page_name or "—",
        "city": customer.city if customer and customer.city else "—",
        "address": customer.address if customer and customer.address else "—",
        "shipping_company_id": order.shipping_company_id,
        "shipping_company": order.shipping_company.name if order.shipping_company else "—",
        "shipping_barcode": shipping_barcodes_display(order) or "—",
        "shipping_status": order.shipping_status or "—",
        "delivery_agent_id": order.delivery_agent_id,
        "delivery_agent": order.delivery_agent.name if order.delivery_agent else "—",
        "note": order.note or "",
        "is_stock_locked": bool(order.is_stock_locked),
        "stock_is_deducted": bool(order.stock_is_deducted),
        "stock_lock_reason": order.stock_lock_reason or "",
        "can_pay": bool(
            not order.is_stock_locked
            and total > paid
            and payment_status not in {"مسدد", "مرتجع", "ملغي"}
            and status not in returned_values
        ),
        "can_cancel": bool(not order.is_stock_locked and status == "تم الطلب"),
        "can_return": _can_return_order(order),
        "duplicate_count": int(duplicate.get("count") or 1),
        "duplicate_risk": duplicate.get("risk") or "",
        "installment": oil,
        "is_installment_order": bool(oil),
        "installment_badge": (oil.get("countdown") if oil else None),
    }


@orders_bp.route("/data")
def orders_data(*, _snapshot=False):
    """Return one filtered page while reporting totals for the complete result set."""
    page_type = request.args.get("page_type", "all").strip().lower()
    if page_type not in {"all", *_ORDERS_PAGE_STATUS_FILTERS.keys()}:
        return jsonify({"success": False, "error": "نوع صفحة الطلبات غير صالح"}), 400
    denied = _orders_data_permission_denied(page_type)
    if denied:
        return denied

    _ensure_order_columns_and_unlock()
    try:
        page = max(1, request.args.get("page", 1, type=int) or 1)
        requested_size = request.args.get("page_size", 100, type=int) or 100
        page_size = min(_ORDERS_GRID_PAGE_MAX, max(1, requested_size))
        q = _orders_data_query(page_type)

        total_count = q.order_by(None).count()
        if _snapshot:
            if total_count > 50000:
                return jsonify(success=False, error="عدد الطلبات يتجاوز حد النسخة المحلية الحالية (50000)"), 413
            page_size = total_count or 1
        total_amount = int(
            q.order_by(None).with_entities(func.coalesce(func.sum(Invoice.total), 0)).scalar() or 0
        )
        filtered_ids = q.order_by(None).with_entities(Invoice.id).subquery()
        total_quantity = int(
            db.session.query(func.count(OrderItem.id))
            .join(filtered_ids, OrderItem.invoice_id == filtered_ids.c.id)
            .scalar() or 0
        )

        total_pages = max(1, (total_count + page_size - 1) // page_size)
        page = min(page, total_pages)
        sort_fields = {
            "order_id": Invoice.id,
            "date": Invoice.created_at,
            "barcode": Invoice.barcode,
            "customer_name": Customer.name,
            "phone": Customer.phone,
            "phone2": Customer.phone2,
            "total": Invoice.total,
            "paid_amount": Invoice.paid_amount,
            "remaining": func.coalesce(Invoice.total, 0) - func.coalesce(Invoice.paid_amount, 0),
            "status": Invoice.status,
            "payment_status": Invoice.payment_status,
            "employee": Invoice.employee_name,
            "page_name": Invoice.page_name,
            "city": Customer.city,
            "address": Customer.address,
            "shipping_company": ShippingCompany.name,
            "shipping_barcode": Invoice.shipping_barcode,
            "delivery_agent": DeliveryAgent.name,
            "note": Invoice.note,
        }
        sort_expression = sort_fields.get(request.args.get("sort_field"), Invoice.created_at)
        sort_expression = sort_expression.asc() if request.args.get("sort_dir") == "asc" else sort_expression.desc()
        rows_query = q.options(
            joinedload(Invoice.customer),
            joinedload(Invoice.shipping_company),
            joinedload(Invoice.delivery_agent),
            selectinload(Invoice.items),
        ).order_by(sort_expression, Invoice.id.desc()).offset((page - 1) * page_size)
        rows = _orders_grid_rows(rows_query, page_size)
        duplicate_meta = _orders_duplicate_meta(q, rows)
        food_sale_mix = _food_sale_mix_by_invoice(
            [row.id for row in rows if str(row.source_module or "").lower() == "food"]
        )
        oil_map = {}
        try:
            from modules.order_installment_lifecycle.service import map_lifecycles_for_orders

            oil_map = map_lifecycles_for_orders([row.id for row in rows])
        except Exception:
            oil_map = {}

        return jsonify({
            "success": True,
            "rows": [
                _serialize_order_grid_row(
                    row,
                    duplicate_meta,
                    food_sale_mix,
                    installment_lifecycle=oil_map.get(row.id),
                )
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total_count,
            "total_pages": total_pages,
            "total_amount": total_amount,
            "total_quantity": total_quantity,
        })
    except Exception as exc:
        current_app.logger.exception("Failed loading paginated orders grid")
        return jsonify({"success": False, "error": _db_user_facing_error(exc)}), 500


@orders_bp.route("/api/lookups")
def orders_api_lookups():
    """Filter/bulk-action options for API clients (desktop) — same data the orders page renders."""
    denied = guard_permission("can_see_orders", json=True)
    if denied:
        return denied
    from models.branch import Branch

    cities = sorted({c[0].strip() for c in db.session.query(Customer.city).distinct().all() if c[0] and c[0].strip()})
    return jsonify({
        "success": True,
        "cities": cities,
        "shipping_companies": [
            {"id": row.id, "name": row.name}
            for row in ShippingCompany.query.order_by(ShippingCompany.name.asc()).all()
        ],
        "delivery_agents": [
            {"id": row.id, "name": row.name}
            for row in DeliveryAgent.query.order_by(DeliveryAgent.name.asc()).all()
        ],
        "branches": [
            {"id": row.id, "name": row.name}
            for row in Branch.query.filter_by(is_active=True).order_by(Branch.id.asc()).all()
        ],
    })


@orders_bp.route("/api/counts")
def orders_api_counts():
    """Order totals per status tab for the current search/filters (tabs the user may not see are omitted)."""
    denied = guard_permission("can_see_orders", json=True)
    if denied:
        return denied
    _ensure_order_columns_and_unlock()
    counts = {}
    for page_type in ("all", *_ORDERS_PAGE_STATUS_FILTERS.keys()):
        permission = _ORDERS_PAGE_PERMISSIONS.get(page_type)
        if permission and not check_permission(permission):
            continue
        counts[page_type] = _orders_data_query(page_type).order_by(None).count()
    return jsonify({"success": True, "counts": counts})


def _orders_page_lookups():
    cities = [c[0] for c in db.session.query(Customer.city).distinct().all() if c[0]]
    oil_ui = {
        "feature_enabled": False,
        "can_toggle": False,
        "mode_on": False,
        "settings": {},
    }
    try:
        from modules.order_installment_lifecycle.service import ui_context_for_employee

        oil_ui = ui_context_for_employee(get_current_employee())
    except Exception:
        pass
    return {
        "employees": Employee.query.all(),
        "shippings": ShippingCompany.query.all(),
        "delivery_agents": DeliveryAgent.query.all(),
        "cities": cities,
        "order_installment_ui": oil_ui,
        "orders_status_links": [
            {"key": key, "href": href, "label": label, "feature": feature}
            for key, href, label, feature, permission in (
                ("all", "/orders/", "orders_nav_all", "orders_all", "can_see_orders"),
                ("ordered", "/orders/ordered", "orders_status_ordered", "orders_placed", "can_see_orders_placed"),
                ("packed", "/orders/packed", "orders_status_packed", "orders_packed", "can_see_orders_packed"),
                ("shipping", "/orders/shipping", "orders_status_shipping", "orders_shipping", "can_see_orders_shipped"),
                ("delivered", "/orders/delivered", "orders_status_delivered", "orders_delivered", "can_see_orders_delivered"),
                ("returned", "/orders/returned", "orders_status_returned", "orders_returned", "can_see_orders_returned"),
                ("cancelled", "/orders/cancelled", "orders_nav_cancelled", "orders_returned", "can_see_orders_returned"),
            ) if check_permission(permission)
        ],
    }


@orders_bp.context_processor
def _orders_branch_sales_ctx():
    try:
        from utils.branch_sales import (
            active_branches_for_sales,
            is_sell_from_all_branches_enabled,
        )

        return {
            "sell_from_all_branches": is_sell_from_all_branches_enabled(),
            "paid_invoice_mutations_enabled": paid_invoice_mutations_enabled(),
            "company_branches": [
                {"id": b.id, "name": b.name, "code": b.code}
                for b in active_branches_for_sales()
            ],
        }
    except Exception:
        return {
            "sell_from_all_branches": False,
            "paid_invoice_mutations_enabled": False,
            "company_branches": [],
        }


@orders_bp.before_request
def _orders_mutations_guard():
    try:
        ensure_invoice_schema()
    except Exception:
        pass
    if "user_id" in session:
        try:
            ensure_policy_initialized()
            ensure_return_status_unified()
            ensure_delivered_status_normalized()
        except Exception:
            pass
    path = request.path or ""
    if any(path.startswith(prefix) for prefix in _ORDERS_PUBLIC_PREFIXES):
        return None
    if "user_id" not in session:
        return None
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        payload = request.get_json(silent=True) or {}
        permission = required_order_mutation_permission(path, payload)
        denied = guard_permission(permission, json=True)
        if denied:
            return denied
        # /orders/update can combine a lifecycle action with a shipping edit.
        # A narrow return/delete permission must not smuggle in a general edit.
        if (
            path.rstrip("/") == "/orders/update"
            and payload.get("shipping") is not None
            and permission != "manage_orders"
        ):
            return guard_permission("manage_orders", json=True)
        return None
    return None

# Per-tenant (or core) bind: video-column ensure must inspect the same engine Invoice rows use.
_ORDER_VIDEO_COLUMNS_ENSURED_BINDS: set[str] = set()
# After a failed ALTER (read-only DB, lock, etc.) skip retrying every request in this process.
_ORDER_VIDEO_COLUMNS_FAILED_BINDS: set[str] = set()


def _orders_schema_engine():
    """قاعدة الفواتير/الطلبات للطلب الحالي: SQLite المستأجر أو محرك النواة."""
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    return db.engine


def _tenant_invoice_template_bundle():
    """
    جداول TenantTemplateSettings في Core DB؛ مع g.tenant يجب تعطيله مؤقتاً عند الاستعلام.
    معرّف المالك يطابق invoice_store/settings (tenant_slug -> Core Tenant.id + fallback قديم).
    """
    from routes.invoice_store import _core_db, _template_tenant_uid, _template_lookup_owner_ids

    template_file = "invoice.html"
    template_styles = {}
    uid = _template_tenant_uid()
    lookup_ids = _template_lookup_owner_ids(uid)
    with _core_db():
        q = TenantTemplateSettings.query
        t_settings = q.filter_by(tenant_id=uid).first() if uid else None
        if not t_settings and lookup_ids:
            t_settings = q.filter(TenantTemplateSettings.tenant_id.in_(lookup_ids)).first()
        if t_settings:
            template_styles = {
                "primary": t_settings.primary_color,
                "secondary": t_settings.secondary_color,
                "custom_css": t_settings.custom_css,
            }
            aid = t_settings.active_template_id
            if aid:
                inv_tpl = db.session.get(InvoiceTemplate, aid)
                if inv_tpl and getattr(inv_tpl, "html_file_name", None):
                    template_file = f"invoices/{inv_tpl.html_file_name}"
    if template_file != "invoice.html":
        full_path = os.path.join(current_app.template_folder, template_file.replace("/", os.sep))
        if not os.path.exists(full_path):
            template_file = "invoice.html"
    return template_file, template_styles




def _db_user_facing_error(exc: BaseException) -> str:
    """رسالة للمستخدم عند أخطاء SQLite الشائعة في الإنتاج (مثل قاعدة للقراءة فقط)."""
    raw = str(exc)
    low = raw.lower()
    if "readonly" in low or "attempt to write a readonly" in low:
        current_app.logger.error("SQLite write failed (check tenants/ permissions): %s", raw, exc_info=True)
        return (
            "تعذر حفظ التغييرات: قاعدة بيانات الشركة أو مجلد «tenants» للقراءة فقط على الخادم. "
            "تأكد أن حساب تشغيل التطبيق يملك الكتابة على المجلد وملفات ‎.db (مثلاً chown لـ www-data وchmod)، "
            "وأن القرص غير ممتلئ."
        )
    return raw


def _order_video_payload(order: Invoice) -> dict:
    has_video = bool(getattr(order, "order_video_path", None))
    if not has_video:
        return {
            "has_video": False,
            "preview_url": None,
            "download_url": None,
            "share_url": None,
            "filename": None,
            "size_mb": None,
            "duration_sec": None,
            "recorded_at": None,
        }
    preview_url = url_for("orders.stream_order_video", order_id=order.id)
    return {
        "has_video": True,
        "preview_url": preview_url,
        "download_url": url_for("orders.download_order_video", order_id=order.id),
        "share_url": preview_url,
        "filename": order.order_video_original_name or Path(order.order_video_path).name,
        "size_mb": order.order_video_size_mb,
        "duration_sec": order.order_video_duration_sec,
        "recorded_at": order.order_video_recorded_at.strftime("%Y-%m-%d %H:%M:%S") if order.order_video_recorded_at else None,
    }


_INVOICE_VIDEO_TOKEN_SALT = "invoice-order-video-guest-v2"


def _invoice_video_guest_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt=_INVOICE_VIDEO_TOKEN_SALT)


def _tenant_slug_for_public_tokens() -> str:
    """معرّف الشركة (المستأجر) لربط الرموز بقاعدة الطلبات الصحيحة."""
    return (getattr(g, "tenant", None) or session.get("tenant_slug") or "").strip()


def build_invoice_video_guest_token(order_id: int) -> str:
    """رمز موقّع لفيديو الطلب للعامة؛ يتضمن tenant حتى يعمل الاستعلام بدون جلسة."""
    tslug = _tenant_slug_for_public_tokens()
    if not tslug:
        raise ValueError("tenant slug missing for invoice video token")
    return _invoice_video_guest_serializer().dumps({"id": int(order_id), "t": tslug})


def parse_invoice_video_guest_token(token: str, *, max_age: int = 86400 * 400) -> tuple[int, str] | None:
    """(رقم الطلب، tenant_slug) أو None."""
    try:
        data = _invoice_video_guest_serializer().loads(token, max_age=max_age)
        oid = int(data.get("id", 0))
        tslug = (data.get("t") or "").strip()
        if oid <= 0 or not tslug:
            return None
        return (oid, tslug)
    except (BadSignature, SignatureExpired, TypeError, ValueError, KeyError):
        return None


_PUBLIC_ORDER_VIEW_SALT = "public-order-view-v2"


def _public_order_view_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt=_PUBLIC_ORDER_VIEW_SALT)


def build_public_order_view_token(order_id: int) -> str:
    """رمز لصفحة تفاصيل الطلب العامة (QR)؛ يتضمن tenant."""
    tslug = _tenant_slug_for_public_tokens()
    if not tslug:
        raise ValueError("tenant slug missing for public order view token")
    return _public_order_view_serializer().dumps({"id": int(order_id), "t": tslug})


def parse_public_order_view_token(token: str, *, max_age: int = 86400 * 400) -> tuple[int, str] | None:
    try:
        data = _public_order_view_serializer().loads(token, max_age=max_age)
        oid = int(data.get("id", 0))
        tslug = (data.get("t") or "").strip()
        if oid <= 0 or not tslug:
            return None
        return (oid, tslug)
    except (BadSignature, SignatureExpired, TypeError, ValueError, KeyError):
        return None


def _host_is_loopback_or_private(host: str) -> bool:
    """True إذا كان النطاق/الـ IP محلياً أو شبكة داخلية — روابط الـ QR للعامة لا تعتمد عليه."""
    h = (host or "").strip().lower()
    if not h:
        return True
    h = h.split(",")[0].strip()
    if h.startswith("[") and "]" in h:
        inner = h[1 : h.index("]")].lower()
        if inner in ("::1", "0:0:0:0:0:0:0:1"):
            return True
    # host:port — نفصل المنفذ لـ IPv4 فقط
    if ":" in h and not h.startswith("["):
        if h.count(":") == 1:
            h = h.rsplit(":", 1)[0]
    if h in ("localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"):
        return True
    if h.startswith("192.168.") or h.startswith("10."):
        return True
    if h.startswith("172."):
        parts = h.split(".")
        if len(parts) >= 2 and parts[0] == "172":
            try:
                if 16 <= int(parts[1]) <= 31:
                    return True
            except ValueError:
                pass
    return False


def _absolute_url_for_path(path: str) -> str:
    """رابط مطلق https://النطاق/... — X-Forwarded-* خلف البروكسي، وإلا BASE_URL عند 127.0.0.1/شبكة داخلية."""
    if not path.startswith("/"):
        path = "/" + path
    base_cfg = (current_app.config.get("BASE_URL") or "").strip().rstrip("/")
    if has_request_context():
        try:
            proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",")[0].strip()
            host = (
                request.headers.get("X-Forwarded-Host")
                or request.headers.get("Host")
                or (getattr(request, "host", None) or "")
            )
            host = (host or "").split(",")[0].strip()
            if host and not _host_is_loopback_or_private(host):
                return f"{proto}://{host}{path}"
        except Exception:
            current_app.logger.debug("absolute url from request failed", exc_info=True)
    if base_cfg:
        return f"{base_cfg}{path}"
    return path


def _absolute_url_for_endpoint(endpoint: str, **values) -> str:
    return _absolute_url_for_path(url_for(endpoint, **values))


def _collect_order_video_cleanup_targets(order: Invoice) -> dict | None:
    video_name = Path(order.order_video_path).name if getattr(order, "order_video_path", None) else None
    thumb_name = Path(order.order_video_thumbnail_path).name if getattr(order, "order_video_thumbnail_path", None) else None
    if not video_name and not thumb_name:
        return None
    return {"video_name": video_name, "thumb_name": thumb_name}


def _delete_order_video_cleanup_targets(targets: dict | None) -> None:
    if not targets:
        return
    try:
        video_name = targets.get("video_name")
        if video_name:
            (get_video_upload_root() / Path(video_name).name).unlink(missing_ok=True)
    except Exception:
        current_app.logger.warning("Failed removing order video file", exc_info=True)
    try:
        thumb_name = targets.get("thumb_name")
        if thumb_name:
            (get_thumbnail_upload_root() / Path(thumb_name).name).unlink(missing_ok=True)
    except Exception:
        current_app.logger.warning("Failed removing order video thumbnail", exc_info=True)


def _clear_order_video_fields(order: Invoice) -> None:
    order.order_video_path = None
    order.order_video_original_name = None
    order.order_video_thumbnail_path = None
    order.order_video_size_mb = None
    order.order_video_duration_sec = None
    order.order_video_recorded_at = None


def _delete_saved_upload_result(result: dict | None) -> None:
    if not result:
        return
    try:
        filename = Path(str(result.get("url") or "")).name
        if filename:
            (get_video_upload_root() / filename).unlink(missing_ok=True)
    except Exception:
        current_app.logger.warning("Failed removing newly uploaded order video", exc_info=True)
    try:
        thumb_name = Path(str(result.get("thumbnail_url") or "")).name
        if thumb_name:
            (get_thumbnail_upload_root() / thumb_name).unlink(missing_ok=True)
    except Exception:
        current_app.logger.warning("Failed removing newly uploaded order video thumbnail", exc_info=True)


def _apply_order_video_result(order: Invoice, result: dict, original_name: str | None = None) -> None:
    order.order_video_path = Path(str(result.get("url") or "")).name or None
    order.order_video_original_name = (Path(original_name).name if original_name else order.order_video_path)[:255] if (original_name or order.order_video_path) else None
    order.order_video_thumbnail_path = Path(str(result.get("thumbnail_url") or "")).name or None
    order.order_video_size_mb = result.get("size_mb")
    order.order_video_duration_sec = result.get("duration_sec")
    order.order_video_recorded_at = datetime.utcnow()


def _ensure_order_video_columns() -> None:
    bind_key = getattr(g, "tenant", None) or "__core__"
    if bind_key in _ORDER_VIDEO_COLUMNS_ENSURED_BINDS:
        return
    if bind_key in _ORDER_VIDEO_COLUMNS_FAILED_BINDS:
        return
    try:
        from sqlalchemy import inspect, text

        engine = _orders_schema_engine()
        inspector = inspect(engine)
        if "invoice" not in inspector.get_table_names():
            _ORDER_VIDEO_COLUMNS_ENSURED_BINDS.add(bind_key)
            return

        invoice_columns = {col["name"] for col in inspector.get_columns("invoice")}
        dialect = engine.dialect.name
        recorded_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
        bool_default = "BOOLEAN DEFAULT false" if dialect == "postgresql" else "BOOLEAN DEFAULT 0"
        stmts: list[str] = []
        if "order_video_path" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN order_video_path VARCHAR(255)")
        if "order_video_original_name" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN order_video_original_name VARCHAR(255)")
        if "order_video_thumbnail_path" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN order_video_thumbnail_path VARCHAR(255)")
        if "order_video_size_mb" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN order_video_size_mb FLOAT")
        if "order_video_duration_sec" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN order_video_duration_sec FLOAT")
        if "order_video_recorded_at" not in invoice_columns:
            stmts.append(f"ALTER TABLE invoice ADD COLUMN order_video_recorded_at {recorded_type}")
        if "shipping_barcodes_json" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN shipping_barcodes_json TEXT")
        if "discount_amount" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN discount_amount INTEGER DEFAULT 0")
        if "is_stock_locked" not in invoice_columns:
            stmts.append(f"ALTER TABLE invoice ADD COLUMN is_stock_locked {bool_default}")
        if "stock_lock_reason" not in invoice_columns:
            stmts.append("ALTER TABLE invoice ADD COLUMN stock_lock_reason TEXT")
        if "stock_locked_at" not in invoice_columns:
            stmts.append(f"ALTER TABLE invoice ADD COLUMN stock_locked_at {recorded_type}")
        if "stock_unlocked_at" not in invoice_columns:
            stmts.append(f"ALTER TABLE invoice ADD COLUMN stock_unlocked_at {recorded_type}")
        if stmts:
            with engine.begin() as conn:
                for stmt in stmts:
                    conn.execute(text(stmt))
        _ORDER_VIDEO_COLUMNS_ENSURED_BINDS.add(bind_key)
    except Exception:
        current_app.logger.exception("Failed ensuring order video columns on invoice table")
        _ORDER_VIDEO_COLUMNS_FAILED_BINDS.add(bind_key)


def _ensure_order_columns_and_unlock() -> None:
    _ensure_order_video_columns()
    try:
        auto_unlock_locked_orders()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed auto-unlocking stock-locked orders")


def _reject_if_stock_locked(order):
    if is_stock_locked(order):
        payload = locked_order_response()
        payload["locked"] = True
        payload["reason"] = getattr(order, "stock_lock_reason", None) or LOCKED_ORDER_MESSAGE
        return jsonify(payload), 423
    return None


def _insufficient_stock_response(exc, order=None):
    """JSON payload for stock shortage errors (includes order id for UI highlight)."""
    order_id = getattr(exc, "order_id", None)
    if order_id is None and order is not None:
        order_id = getattr(order, "id", None)
    try:
        order_id = int(order_id) if order_id is not None else None
    except (TypeError, ValueError):
        order_id = None
    message = getattr(exc, "message", None) or str(exc)
    shortages = list(getattr(exc, "shortages", None) or [])
    if message and message not in shortages:
        shortages = [message] + [s for s in shortages if s != message]
    payload = {
        "success": False,
        "code": "INSUFFICIENT_STOCK",
        "error": message,
        "shortages": shortages,
        "order_id": order_id,
        "order_ids": [order_id] if order_id else [],
    }
    product_name = getattr(exc, "product_name", None)
    if product_name:
        payload["product_name"] = product_name
    return jsonify(payload), 409


def _agent_report_stock_shortage_context(order_ids, target_branch_id=None):
    """Build structured product, branch and supplier data for shortage recovery."""
    from collections import defaultdict

    from models.branch import Branch, BranchStock
    from models.supplier import Supplier
    from utils.branch_migration import get_default_branch
    from utils.branch_sales import is_sell_from_all_branches_enabled
    from utils.order_stock_policy import is_physical_order_item
    from utils.product_color_service import get_color_quantity, product_has_colors

    clean_ids = []
    for raw_id in order_ids or []:
        try:
            order_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if order_id > 0 and order_id not in clean_ids:
            clean_ids.append(order_id)
        if len(clean_ids) >= 250:
            break

    branches = (
        Branch.query.filter_by(is_active=True)
        .order_by(Branch.is_default.desc(), Branch.name.asc())
        .all()
    )
    branch_by_id = {int(branch.id): branch for branch in branches}
    try:
        target_branch_id = int(target_branch_id) if target_branch_id else None
    except (TypeError, ValueError):
        target_branch_id = None
    if target_branch_id not in branch_by_id:
        target_branch_id = None

    default_branch = get_default_branch()
    default_branch_id = (
        int(default_branch.id)
        if default_branch and int(default_branch.id) in branch_by_id
        else (int(branches[0].id) if branches else None)
    )
    orders = (
        Invoice.query.options(selectinload(Invoice.items))
        .filter(Invoice.id.in_(clean_ids))
        .order_by(Invoice.id.asc())
        .all()
        if clean_ids
        else []
    )

    # Keep demand per order because report dispatch reserves inventory one order
    # at a time; fragmented branch stock can fail even when the company total is
    # large enough.
    requirements = {}
    for order in orders:
        if stock_is_deducted(order):
            continue
        per_order = defaultdict(int)
        per_order_branches = defaultdict(set)
        for item in list(order.items or []):
            if not is_physical_order_item(item):
                continue
            product = getattr(item, "product", None) or Product.query.get(item.product_id)
            quantity = max(0, int(item.quantity or 0))
            if not product or quantity <= 0:
                continue
            color = (getattr(item, "variant_color", None) or "").strip()
            key = (int(product.id), color)
            per_order[key] += quantity
            explicit_branch_id = getattr(item, "fulfillment_branch_id", None)
            if explicit_branch_id:
                per_order_branches[key].add(int(explicit_branch_id))
            row = requirements.setdefault(key, {
                "product": product,
                "required": 0,
                "order_ids": [],
                "order_requirements": [],
                "branch_candidates": set(),
            })
            row["required"] += quantity
            row["branch_candidates"].update(per_order_branches[key])

        for key, quantity in per_order.items():
            row = requirements[key]
            row["order_ids"].append(int(order.id))
            explicit = sorted(per_order_branches.get(key) or [])
            preferred = (
                target_branch_id
                or (explicit[0] if len(explicit) == 1 else None)
                or (int(order.branch_id) if getattr(order, "branch_id", None) else None)
                or default_branch_id
            )
            row["order_requirements"].append({
                "order_id": int(order.id),
                "quantity": int(quantity),
                "explicit_branch_id": explicit[0] if len(explicit) == 1 else None,
                "preferred_branch_id": preferred,
            })

    # In shared mode one catalog item can have a different local product ID
    # in each branch.  Cap stock with available_fulfillment_qty so color and
    # local copies stay aligned when deciding transfer sources.
    from utils.branch_sales import available_fulfillment_qty

    # Cap each branch by the ordered color so the transfer UI never offers
    # stock that only exists in a different color on that branch.
    original_stock = defaultdict(int)
    for key in requirements:
        product_id, color = key
        for branch_id in branch_by_id:
            original_stock[(int(product_id), color, int(branch_id))] = available_fulfillment_qty(
                int(branch_id), int(product_id), color or None
            )
    simulated_stock = dict(original_stock)
    sell_all = is_sell_from_all_branches_enabled()
    failed_by_key = defaultdict(int)

    for key, row in requirements.items():
        product_id, color = key
        for demand in row["order_requirements"]:
            quantity = int(demand["quantity"])
            explicit = target_branch_id or demand.get("explicit_branch_id")
            preferred = target_branch_id or demand.get("preferred_branch_id") or default_branch_id
            chosen = None
            if explicit in branch_by_id and simulated_stock.get((product_id, color, explicit), 0) >= quantity:
                chosen = explicit
            if chosen is None and preferred in branch_by_id and simulated_stock.get((product_id, color, preferred), 0) >= quantity:
                chosen = preferred
            if chosen is None and sell_all and not target_branch_id:
                candidates = [
                    (simulated_stock.get((product_id, color, int(branch.id)), 0), int(branch.id))
                    for branch in branches
                    if simulated_stock.get((product_id, color, int(branch.id)), 0) >= quantity
                ]
                if candidates:
                    candidates.sort(key=lambda value: (-value[0], value[1]))
                    chosen = candidates[0][1]
            if chosen is None:
                best_available = max(
                    [simulated_stock.get((product_id, color, int(branch.id)), 0) for branch in branches] or [0]
                )
                failed_by_key[key] += max(1, quantity - best_available)
                continue
            simulated_stock[(product_id, color, chosen)] = (
                simulated_stock.get((product_id, color, chosen), 0) - quantity
            )

    details = []
    for key, row in requirements.items():
        product_id, color = key
        product = row["product"]
        required = int(row["required"])
        branch_stocks = [{
            "id": int(branch.id),
            "name": branch.name,
            "code": branch.code or "",
            "quantity": int(original_stock.get((product_id, color, int(branch.id)), 0)),
        } for branch in branches]
        total_available = sum(branch["quantity"] for branch in branch_stocks)
        remedy_branch_id = target_branch_id
        if not remedy_branch_id:
            candidates = sorted(row["branch_candidates"])
            remedy_branch_id = candidates[0] if len(candidates) == 1 else default_branch_id
        target_available = (
            int(original_stock.get((product_id, color, remedy_branch_id), 0))
            if remedy_branch_id else 0
        )
        company_shortfall = max(0, required - total_available)
        failed_quantity = int(failed_by_key.get(key, 0))
        color_available = int(get_color_quantity(product_id, color) or 0) if color else None
        color_shortfall = max(0, required - color_available) if color_available is not None else 0
        shortage = max(company_shortfall, failed_quantity, color_shortfall)
        target_shortfall = max(0, required - target_available)
        if not shortage and not (target_branch_id and target_shortfall):
            continue
        details.append({
            "product_id": product_id,
            "product_name": product.name,
            "sku": product.sku or product.barcode or "",
            "image_url": product.image_url or "",
            "variant_color": color,
            "required": required,
            "available_total": total_available,
            "available_target": target_available,
            "shortage": max(1, shortage or target_shortfall),
            "purchase_quantity": max(1, company_shortfall or color_shortfall or failed_quantity or target_shortfall),
            "transfer_quantity": max(1, target_shortfall or failed_quantity or shortage),
            "target_branch_id": remedy_branch_id,
            "target_branch_name": branch_by_id[remedy_branch_id].name if remedy_branch_id in branch_by_id else "",
            "buy_price": int(product.buy_price or 0),
            "has_colors": bool(product_has_colors(product)),
            "color_available": color_available,
            "order_ids": sorted(set(row["order_ids"])),
            "branches": branch_stocks,
        })

    can_manage_inventory = check_permission("can_manage_inventory")
    employee = get_current_employee()
    can_complete_transfer = bool(employee and employee.role == "admin" and can_manage_inventory)
    suppliers = []
    if can_manage_inventory:
        from utils.branch_mode import independent_branches_enabled

        supplier_query = Supplier.query.order_by(Supplier.name.asc(), Supplier.id.asc())
        if not independent_branches_enabled():
            supplier_query = supplier_query.execution_options(skip_branch_scope=True)
            from routes.suppliers import _shared_supplier_rows

            supplier_rows = _shared_supplier_rows(supplier_query.all())
        else:
            supplier_rows = supplier_query.all()
        suppliers = [{"id": int(row.id), "name": row.name} for row in supplier_rows]
    return {
        "success": True,
        "order_ids": clean_ids,
        "target_branch_id": target_branch_id or default_branch_id,
        "shortages": details,
        "summary": {
            "products_count": len(details),
            "units_short": sum(int(row["shortage"]) for row in details),
            "orders_count": len(orders),
        },
        "branches": [{
            "id": int(branch.id), "name": branch.name, "code": branch.code or ""
        } for branch in branches],
        "suppliers": suppliers,
        "permissions": {
            "can_manage_inventory": can_manage_inventory,
            "can_complete_transfer": can_complete_transfer,
        },
    }


@orders_bp.route("/stock-shortage-context", methods=["POST"])
def stock_shortage_context():
    """Return all missing products and their quick remediation choices."""
    denied = guard_permission("can_see_orders", json=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    order_ids = data.get("order_ids") or []
    if not isinstance(order_ids, list) or not order_ids:
        return jsonify({"success": False, "error": "لا توجد طلبات محددة"}), 400
    context = _agent_report_stock_shortage_context(
        order_ids,
        target_branch_id=data.get("target_branch_id"),
    )
    visible_orders = Invoice.query.filter(Invoice.id.in_(context["order_ids"])).all()
    for order in visible_orders:
        denied = guard_order_access(order, json=True)
        if denied:
            return denied
    return jsonify(context)


class _OrderPrintProxy:
    def __init__(self, order, customer):
        self._order = order
        self.customer = customer

    def __getattr__(self, name):
        return getattr(self._order, name)


def _order_for_print(order):
    order.shipping_receipt_numbers = get_shipping_barcodes_list(order)
    if getattr(order, "customer", None) is not None:
        return order
    fallback_customer = SimpleNamespace(
        id=getattr(order, "customer_id", None),
        name=getattr(order, "customer_name", None) or "—",
        phone="",
        phone2="",
        city="",
        address="",
    )
    return _OrderPrintProxy(order, fallback_customer)


def _render_order_invoice(template_file, **context):
    from utils.invoice_shipping_receipt import attach_shipping_receipt
    from utils.invoice_sales_returns import attach_return_summary

    return attach_return_summary(attach_shipping_receipt(render_template(template_file, **context), context['order']), context['order'])


def _attach_food_item_snapshots(order, items):
    """Attach read-only food metadata without changing legacy OrderItem fields."""
    if getattr(order, "source_module", None) != "food" or not items:
        return {}
    try:
        from modules.food.models import FoodSaleItemSnapshot

        item_ids = [int(item.id) for item in items if getattr(item, "id", None)]
        rows = FoodSaleItemSnapshot.query.filter(
            FoodSaleItemSnapshot.order_item_id.in_(item_ids)
        ).all()
        by_item = {row.order_item_id: row for row in rows}
        for item in items:
            snapshot = by_item.get(item.id)
            if not snapshot:
                continue
            item.food_variant_name = snapshot.variant_name_snapshot
            item.food_unit_name = snapshot.unit_name_snapshot
            item.food_unit_factor = int(snapshot.unit_factor_snapshot or 1)
            item.food_sale_mode = snapshot.sale_mode
            item.food_quantity_base = int(snapshot.quantity_base or 0)
            item.product_name = snapshot.product_name_snapshot or item.product_name
            item.display_name = item.product_name
            item.quantity = snapshot.quantity_snapshot or item.quantity
            item.price = int(snapshot.unit_price_snapshot or item.price or 0)
            item.total = int(snapshot.line_total_snapshot or item.total or 0)
        return by_item
    except Exception:
        current_app.logger.exception("failed loading food item snapshots for invoice %s", order.id)
        return {}

# =====================================================
# Orders Page (Optimized for many orders)
# =====================================================
@orders_bp.route("/")
def orders():
    # فحص الصلاحية
    if not check_permission("can_see_orders"):
        return redirect("/pos"), 403
    _ensure_order_columns_and_unlock()

    # ------------------ Base Query ------------------
    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer)

    # ------------------ Filters ------------------
    city = request.args.get("city")
    status = request.args.get("status")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")  # فلتر الطلبات المؤجلة
    
    # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
    today = date.today()
    if not scheduled_date:
        # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),  # طلبات غير مؤجلة
                func.date(Invoice.scheduled_date) <= today  # طلبات مؤجلة حان موعدها
            )
        )

    if city:
        q = q.filter(Customer.city == city)

    if status:
        q = q.filter(Invoice.status == status)

    if payment:
        q = q.filter(Invoice.payment_status == payment)

    if employee:
        q = q.filter(Invoice.employee_name == employee)

    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)

    if search:
        q = q.filter(_orders_search_condition(search))
    
    # فلتر الطلبات المؤجلة - إظهار فقط الطلبات المؤجلة للتاريخ المحدد
    if scheduled_date:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(
                func.date(Invoice.scheduled_date) == target_date
            )
        except:
            pass
    else:
        # إذا لم يتم تحديد تاريخ، إخفاء الطلبات المؤجلة التي لم يحن موعدها
        # (تمت إضافتها أعلاه)
        pass

    q = q.order_by(Invoice.created_at.desc())

    # ------------------ Filter by Permissions ------------------
    employee = get_current_employee()
    if employee and employee.role != "admin":
        allowed_statuses = allowed_order_statuses_for(employee)
        if allowed_statuses:
            q = q.filter(Invoice.status.in_(allowed_statuses))
        else:
            q = q.filter(Invoice.id == -1)

    # Rows are loaded page-by-page from /orders/data after the shell renders.
    orders = []

    return render_template(
        "orders.html",
        orders=orders,
        pagination=None,
        page_type="all",
        **_orders_page_lookups(),
    )

# =====================================================
# Orders by Status - تم الطلب
# =====================================================
@orders_bp.route("/ordered")
def orders_ordered():
    # فحص الصلاحية (الطلبات + حالة تم الطلب)
    if not check_permission("can_see_orders") or not check_permission("can_see_orders_placed"):
        return redirect("/pos"), 403
    _ensure_order_columns_and_unlock()

    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(Invoice.status == "تم الطلب")
    
    # Filters
    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")
    
    # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except:
            pass
    
    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        q = q.filter(_orders_search_condition(search))
    
    q = q.order_by(Invoice.created_at.desc())
    orders = []

    return render_template(
        "orders.html",
        orders=orders,
        pagination=None,
        page_type="ordered",
        **_orders_page_lookups(),
    )

# =====================================================
# Orders by Status - معباة
# =====================================================
@orders_bp.route("/packed")
def orders_packed():
    # فحص الصلاحية (الطلبات + حالة معباة)
    if not check_permission("can_see_orders") or not check_permission("can_see_orders_packed"):
        return redirect("/pos"), 403
    _ensure_order_columns_and_unlock()

    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(Invoice.status == "معباة")

    # Filters
    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")

    # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except:
            pass

    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        q = q.filter(_orders_search_condition(search))

    q = q.order_by(Invoice.created_at.desc())
    orders = []

    return render_template(
        "orders.html",
        orders=orders,
        pagination=None,
        page_type="packed",
        **_orders_page_lookups(),
    )

# =====================================================
# Orders by Status - جاري الشحن
# =====================================================
@orders_bp.route("/shipping")
def orders_shipping():
    # فحص الصلاحية (الطلبات + حالة جاري الشحن)
    if not check_permission("can_see_orders") or not check_permission("can_see_orders_shipped"):
        return redirect("/pos"), 403
    _ensure_order_columns_and_unlock()

    
    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(Invoice.status == "جاري الشحن")
    
    # Filters
    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")
    
    # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except:
            pass
    
    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        q = q.filter(_orders_search_condition(search))
    
    q = q.order_by(Invoice.created_at.desc())
    orders = []

    return render_template(
        "orders.html",
        orders=orders,
        pagination=None,
        page_type="shipping",
        **_orders_page_lookups(),
    )

# =====================================================
# Orders by Status - تم التوصيل / مسدد
# =====================================================
@orders_bp.route("/delivered")
def orders_delivered():
    # فحص الصلاحية (الطلبات + حالة تم التوصيل)
    if not check_permission("can_see_orders") or not check_permission("can_see_orders_delivered"):
        return redirect("/pos"), 403
    _ensure_order_columns_and_unlock()

    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(
        or_(
            Invoice.status == "تم التوصيل",
            Invoice.payment_status == "مسدد"
        )
    )

    # نفس الفلاتر القياسية
    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")

    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except Exception:
            pass

    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        q = q.filter(_orders_search_condition(search))

    q = q.order_by(Invoice.created_at.desc())
    orders = []

    return render_template(
        "orders.html",
        orders=orders,
        pagination=None,
        page_type="delivered",
        **_orders_page_lookups(),
    )

# =====================================================
# Orders by Status - راجع / ملغي / مرتجع
# =====================================================
@orders_bp.route("/returned")
def orders_returned():
    if not check_permission("can_see_orders") or not check_permission("can_see_orders_returned"):
        return redirect("/pos"), 403
    _ensure_order_columns_and_unlock()

    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(
        or_(
            invoice_returned_condition(Invoice),
            Invoice.status == "ملغي",
            Invoice.payment_status == "ملغي",
        )
    )

    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")

    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except Exception:
            pass

    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        q = q.filter(_orders_search_condition(search))

    q = q.order_by(Invoice.created_at.desc())
    orders = []

    return render_template(
        "orders.html",
        orders=orders,
        pagination=None,
        page_type="returned",
        **_orders_page_lookups(),
    )

# =====================================================
# Orders by Status - ملغي
# =====================================================
@orders_bp.route("/cancelled")
def orders_cancelled():
    # Cancellation belongs to the same access scope as returned orders.
    if not check_permission("can_see_orders") or not check_permission("can_see_orders_returned"):
        return redirect("/pos"), 403
    _ensure_order_columns_and_unlock()

    
    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(Invoice.status == "ملغي")
    
    # Filters
    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")
    
    # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except:
            pass
    
    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        q = q.filter(_orders_search_condition(search))
    
    q = q.order_by(Invoice.created_at.desc())
    orders = []

    return render_template(
        "orders.html",
        orders=orders,
        pagination=None,
        page_type="cancelled",
        **_orders_page_lookups(),
    )

# =====================================================
# Update Order (Status / Shipping) – Bulk safe
# =====================================================
@orders_bp.route("/update", methods=["POST"])
def update_order():
    data = request.json
    order = Invoice.query.get_or_404(int(data["id"]))
    locked_response = _reject_if_stock_locked(order)
    if locked_response:
        return locked_response
    before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
    prev_effective_paid = _effective_paid_amount(order)
    lifecycle_changed = False

    if data.get("status"):
        new_status = data["status"]
        # لا نسمح بتغيير "راجع" عبر تحديث بسيط بدون باركود/تسوية — استخدم مسار الترجيع الموحّد
        if is_return_status_value(new_status):
            scanned_barcode = (data.get("barcode") or "").strip()
            if not scanned_barcode:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "يجب مسح باركود الطلب لتأكيد الراجع",
                        }
                    ),
                    400,
                )
            try:
                already_returned, msg = process_order_return(
                    order,
                    scanned_barcode,
                    return_branch_id=data.get("return_branch_id"),
                )
            except OrderLifecycleError as exc:
                return jsonify({"success": False, "error": exc.message}), exc.status_code
            if already_returned:
                return jsonify({"success": True, "message": msg})
            lifecycle_changed = True
        elif is_canceled(new_status, None):
            try:
                process_order_cancel(order)
            except OrderLifecycleError as exc:
                return jsonify({"success": False, "error": exc.message}), exc.status_code
            lifecycle_changed = True
        else:
            try:
                ensure_stock_for_transition(order, target_status=new_status)
            except OrderStockError as exc:
                db.session.rollback()
                return _insufficient_stock_response(exc, order)
            order.status = new_status

    if data.get("shipping"):
        order.shipping_company_id = int(data["shipping"])

    if lifecycle_changed:
        append_payment_ledger_delta(order.id, _effective_paid_amount(order) - prev_effective_paid)
        sync_delivery_expense_for_invoice(order)
        try:
            from utils.payroll_service import sync_commission_line_for_invoice

            sync_commission_line_for_invoice(order)
        except Exception:
            pass

    db.session.commit()
    try:
        log_mutation(
            "update",
            "orders",
            "invoice",
            order.id,
            before,
            snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
            f"تعديل الطلب #{order.id}",
        )
    except Exception:
        pass
    return jsonify({"success": True})


@orders_bp.route("/quick-edit/<int:order_id>", methods=["POST"])
def quick_edit_order(order_id):
    """Edit an order from the details overlay using the stock-safe POS workflow."""
    data = request.get_json(silent=True) or {}
    employee = get_current_employee()
    if not employee:
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    order_query = Invoice.query
    if employee.role == "admin":
        order_query = order_query.execution_options(skip_branch_scope=True)
    order = order_query.filter(Invoice.id == order_id).first()
    if not order:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404
    denied = guard_order_access(order, json=True)
    if denied:
        return denied

    customer_updates = data.get("customer") if isinstance(data.get("customer"), dict) else None
    if customer_updates and not employee_can(employee, "manage_customers"):
        return jsonify({"success": False, "error": "ليس لديك صلاحية تعديل بيانات الزبون"}), 403

    try:
        payload = create_pos_order(
            employee=employee,
            customer_id=order.customer_id,
            items=data.get("items") or [],
            branch_id=order.branch_id,
            note=data.get("note"),
            scheduled_date=(order.scheduled_date.strftime("%Y-%m-%d") if order.scheduled_date else None),
            page_id=order.page_id,
            discount_amount=data.get("discount_amount"),
            order_id=order.id,
            source="orders_quick_edit",
            raw_data=data,
            customer_updates=customer_updates,
        )
    except PosCheckoutError as exc:
        return jsonify(exc.payload), exc.status_code
    return jsonify(payload)


def _bulk_stock_order_payload(order):
    from utils.branch_stock_service import get_total_stock
    from utils.order_stock_policy import is_physical_order_item

    requirements = []
    for item in order.items:
        if not is_physical_order_item(item):
            continue
        requirements.append({
            "product_id": item.product_id,
            "product_name": item.product_name,
            "quantity": int(item.quantity or 0),
            "variant_color": (getattr(item, "variant_color", None) or ""),
            "available": int(get_total_stock(item.product_id) or 0),
        })
    return {
        "id": order.id,
        "customer_name": order.customer_name,
        "stock_is_deducted": stock_is_deducted(order),
        "requirements": requirements,
    }


def _apply_bulk_status_rows(orders, target_status):
    for order in orders:
        try:
            ensure_stock_for_transition(order, target_status=target_status)
            if target_status == "جاري الشحن":
                from utils.shipping_branch_schedule import apply_shipping_branch_schedule

                apply_shipping_branch_schedule(order, previous_status=order.status)
                order.shipping_status = "جاري الشحن"
        except OrderStockError as exc:
            if getattr(exc, "order_id", None) is None:
                exc.order_id = order.id
            raise
        except Exception as exc:
            from utils.branch_stock_service import BranchStockError

            if isinstance(exc, BranchStockError):
                raise OrderStockError(str(exc), [str(exc)], order_id=order.id) from exc
            raise
        order.status = target_status
    db.session.flush()


def _complete_order_return_side_effects(order, before_pay):
    video_cleanup_targets = _collect_order_video_cleanup_targets(order)
    _clear_order_video_fields(order)
    append_payment_ledger_delta(order.id, _effective_paid_amount(order) - before_pay)
    sync_delivery_expense_for_invoice(order)
    try:
        from utils.payroll_service import sync_commission_line_for_invoice

        sync_commission_line_for_invoice(order)
    except Exception:
        pass
    return video_cleanup_targets


@orders_bp.route("/bulk-return", methods=["POST"])
def bulk_return():
    """Return multiple orders: restore stock, clear payment, mark as راجع."""
    denied = guard_permission("return_orders", json=True)
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    if not isinstance(data,dict):
        return jsonify({'success':False,'error':'بيانات الترجيع غير صالحة'}),400
    return_location_id=data.get('return_location_id')
    if return_location_id is not None and (type(return_location_id) is not int or return_location_id<1):
        return jsonify({'success':False,'error':'اختر مخزن استلام صالحاً'}),400
    try:
        order_ids = list(dict.fromkeys(int(v) for v in (data.get("order_ids") or [])))
        return_branch_id = int(data.get("return_branch_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "بيانات الترجيع الجماعي غير صالحة"}), 400

    if not order_ids:
        return jsonify({"success": False, "error": "لا توجد طلبات محددة"}), 400
    if return_branch_id <= 0:
        return jsonify({"success": False, "error": "اختر فرع إرجاع المخزون"}), 400

    orders = Invoice.query.filter(Invoice.id.in_(order_ids)).order_by(Invoice.id.asc()).all()
    if len(orders) != len(order_ids):
        return jsonify({"success": False, "error": "بعض الطلبات غير موجودة"}), 404

    updated_ids = []
    skipped = []
    failed = []
    video_cleanup_batch = []

    for order in orders:
        if guard_order_access(order, json=True):
            failed.append({"id": order.id, "error": "غير مصرح بإرجاع هذا الطلب"})
            continue
        if is_stock_locked(order):
            failed.append({
                "id": order.id,
                "error": getattr(order, "stock_lock_reason", None) or LOCKED_ORDER_MESSAGE,
            })
            continue

        before_pay = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
        prev_effective_paid = _effective_paid_amount(order)
        nested = db.session.begin_nested()
        try:
            already_returned, message = process_order_return(
                order,
                str(order.id),
                return_branch_id=return_branch_id,
                return_location_id=return_location_id,
            )
            if already_returned:
                nested.rollback()
                skipped.append({"id": order.id, "message": message})
                continue

            video_cleanup_batch.append(_complete_order_return_side_effects(order, prev_effective_paid))
            nested.commit()
            updated_ids.append(order.id)
            try:
                log_mutation(
                    "update",
                    "orders",
                    "invoice",
                    order.id,
                    before_pay,
                    snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
                    f"ترجيع جماعي للطلب #{order.id}",
                )
            except Exception:
                pass
        except OrderLifecycleError as exc:
            nested.rollback()
            failed.append({"id": order.id, "error": exc.message})
        except Exception as exc:
            nested.rollback()
            failed.append({"id": order.id, "error": _db_user_facing_error(exc)})

    if updated_ids:
        db.session.commit()
        for targets in video_cleanup_batch:
            _delete_order_video_cleanup_targets(targets)
        for order_id in updated_ids:
            try:
                from utils.customer_blacklist import maybe_auto_blacklist_after_return

                maybe_auto_blacklist_after_return(order_id)
            except Exception:
                current_app.logger.exception("auto blacklist after bulk return failed for order %s", order_id)
    else:
        db.session.rollback()

    if not updated_ids and not skipped:
        first_error = (failed[0]["error"] if failed else "تعذر ترجيع الطلبات المحددة")
        return jsonify({
            "success": False,
            "error": first_error,
            "updated": 0,
            "updated_ids": [],
            "skipped": skipped,
            "failed": failed,
        }), 400

    return jsonify({
        "success": True,
        "updated": len(updated_ids),
        "updated_ids": updated_ids,
        "skipped": skipped,
        "failed": failed,
        "message": f"تم ترجيع {len(updated_ids)} طلب",
    })


@orders_bp.route("/bulk-status", methods=["POST"])
def bulk_status():
    """Atomic bulk status transition with optional manual shortage allocation."""
    data = request.get_json(silent=True) or {}
    target_status = (data.get("status") or "").strip()
    allowed = {"تم الطلب", "معباة", "جاري الشحن", "تم التوصيل"}
    if target_status not in allowed:
        return jsonify({"success": False, "error": "حالة التحويل الجماعي غير صالحة"}), 400

    try:
        candidate_ids = list(dict.fromkeys(int(v) for v in (data.get("order_ids") or [])))
        selected_raw = data.get("selected_order_ids")
        selected_ids = None if selected_raw is None else list(dict.fromkeys(int(v) for v in selected_raw))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "أرقام الطلبات غير صالحة"}), 400
    if not candidate_ids:
        return jsonify({"success": False, "error": "لا توجد طلبات محددة"}), 400
    if selected_ids is not None and not set(selected_ids).issubset(set(candidate_ids)):
        return jsonify({"success": False, "error": "الطلبات المختارة ليست ضمن المجموعة"}), 400

    candidates = Invoice.query.filter(Invoice.id.in_(candidate_ids)).order_by(Invoice.id.asc()).all()
    if len(candidates) != len(candidate_ids):
        return jsonify({"success": False, "error": "بعض الطلبات غير موجودة"}), 404
    by_id = {order.id: order for order in candidates}
    chosen = candidates if selected_ids is None else [by_id[oid] for oid in selected_ids]

    if selected_ids is None:
        preview = db.session.begin_nested()
        try:
            _apply_bulk_status_rows(chosen, target_status)
        except OrderStockError as exc:
            preview.rollback()
            if not deferred_stock_enabled():
                db.session.rollback()
                return _insufficient_stock_response(exc)
            return jsonify({
                "success": False,
                "code": "STOCK_SELECTION_REQUIRED",
                "selection_required": True,
                "error": "المخزون لا يكفي جميع الطلبات؛ اختر الطلبات التي تريد تنفيذها",
                "shortages": exc.shortages,
                "order_id": getattr(exc, "order_id", None),
                "order_ids": [getattr(exc, "order_id", None)] if getattr(exc, "order_id", None) else [],
                "orders": [_bulk_stock_order_payload(order) for order in candidates],
            }), 409
        except Exception:
            preview.rollback()
            raise
        else:
            preview.rollback()

    before_by_id = {
        order.id: snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
        for order in chosen
    }
    try:
        _apply_bulk_status_rows(chosen, target_status)
        db.session.commit()
        updated_ids = [order.id for order in chosen]
        for order in chosen:
            log_mutation(
                "update",
                "orders",
                "invoice",
                order.id,
                before_by_id.get(order.id, {}),
                snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
                f"تغيير حالة الطلب #{order.id} إلى {target_status}",
            )
        return jsonify({
            "success": True,
            "updated": len(updated_ids),
            "updated_ids": updated_ids,
            "skipped_ids": [oid for oid in candidate_ids if oid not in set(updated_ids)],
        })
    except OrderStockError as exc:
        db.session.rollback()
        return _insufficient_stock_response(exc)
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": _db_user_facing_error(exc)}), 400


# =====================================================
# Payment (Full / Partial)
# =====================================================
@orders_bp.route("/payment-accounts", methods=["GET"])
def payment_accounts():
    """Active cash/bank accounts available when collecting an order."""
    denied = guard_permission("pay_orders", json=True)
    if denied:
        return denied
    from models.treasury_account import TreasuryAccount
    from utils.branch_scope import is_general_admin
    from utils.treasury_calculations import list_treasury_accounts
    from models.branch import Branch

    if is_general_admin():
        accounts = (
            TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter(TreasuryAccount.is_active.is_(True))
            .order_by(
                TreasuryAccount.branch_id.asc(),
                TreasuryAccount.is_default.desc(),
                TreasuryAccount.account_type.asc(),
                TreasuryAccount.name.asc(),
            )
            .all()
        )
    else:
        accounts = list_treasury_accounts()
    branch_ids = {int(account.branch_id) for account in accounts if account.branch_id}
    branch_names = {
        int(branch.id): branch.name
        for branch in Branch.query.execution_options(skip_branch_scope=True)
        .filter(Branch.id.in_(branch_ids or [-1]))
        .all()
    }
    return jsonify({
        "success": True,
        "accounts": [
            {
                "id": account.id,
                "name": account.name,
                "type": account.account_type,
                "is_default": bool(account.is_default),
                "branch_id": account.branch_id,
                "branch_name": branch_names.get(int(account.branch_id or 0), "فرع غير محدد"),
                "label": (
                    f"{branch_names.get(int(account.branch_id or 0), 'فرع غير محدد')} — تسليم باليد — {account.name}"
                    if account.is_cash
                    else f"{branch_names.get(int(account.branch_id or 0), 'فرع غير محدد')} — تحويل بنكي — {account.name}"
                ),
            }
            for account in accounts
        ],
    })


@orders_bp.route("/payment", methods=["POST"])
def payment():
    _ensure_order_video_columns()
    _ORDER_PAYMENT_LOCK.acquire()
    try:
        data = request.json
        if not data or "id" not in data:
            return jsonify({"success": False, "error": "بيانات غير صحيحة"}), 400
        
        order_id = int(data["id"])
        order = Invoice.query.filter(Invoice.id == order_id).with_for_update().first()
        
        if not order:
            return jsonify({"success": False, "error": "الطلب غير موجود"}), 404

        locked_response = _reject_if_stock_locked(order)
        if locked_response:
            return locked_response

        from utils.employee_commission_service import attach_session_employee_to_invoice

        attach_session_employee_to_invoice(order)

        before_pay = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
        payment_status = data.get("payment")
        paid_amount = data.get("paid_amount", 0)
        try:
            delivery_fee = max(0, int(data.get("delivery_fee") or 0))
        except (TypeError, ValueError):
            delivery_fee = 0
        video_cleanup_targets = None
        prev_effective_paid = _effective_paid_amount(order)
        payment_allocations = None
        payment_accounts_by_id = {}

        collection_due = max(0, int(order.total or 0) - int(prev_effective_paid or 0))
        if payment_status == "جزئي":
            try:
                paid_amount = int(paid_amount)
            except (ValueError, TypeError):
                return jsonify({"success": False, "error": "مبلغ التسديد الجزئي غير صحيح"}), 400
            if paid_amount <= 0:
                return jsonify({"success": False, "error": "مبلغ التسديد الجزئي يجب أن يكون أكبر من صفر"}), 400
            if paid_amount > collection_due:
                return jsonify({
                    "success": False,
                    "error": f"مبلغ التسديد الجزئي يتجاوز المستحق ({collection_due:,} د.ع)",
                }), 400

        raw_allocations = data.get("payment_allocations")
        if raw_allocations is not None:
            if payment_status not in ("مسدد", "جزئي"):
                return jsonify({
                    "success": False,
                    "error": "اختيار طريقة الدفع متاح عند التسديد الكامل أو الجزئي فقط",
                }), 400
            if not isinstance(raw_allocations, list) or not raw_allocations or len(raw_allocations) > 8:
                return jsonify({
                    "success": False,
                    "error": "تفاصيل طرق الدفع غير صحيحة",
                }), 400

            from models.treasury_account import TreasuryAccount
            from utils.treasury_schema_guard import ensure_treasury_schema

            ensure_treasury_schema()
            combined = {}
            try:
                for allocation in raw_allocations:
                    account_id = int(allocation.get("treasury_account_id") or 0)
                    amount = int(allocation.get("amount") or 0)
                    if account_id <= 0 or amount <= 0:
                        raise ValueError
                    combined[account_id] = combined.get(account_id, 0) + amount
            except (AttributeError, TypeError, ValueError):
                return jsonify({
                    "success": False,
                    "error": "كل دفعة تحتاج حساباً ومبلغاً أكبر من صفر",
                }), 400

            active_accounts_query = TreasuryAccount.query
            from utils.branch_scope import is_general_admin
            if is_general_admin():
                active_accounts_query = active_accounts_query.execution_options(
                    skip_branch_scope=True
                )
            active_accounts = active_accounts_query.filter(
                TreasuryAccount.id.in_(list(combined)),
                TreasuryAccount.is_active.is_(True),
            ).all()
            payment_accounts_by_id = {account.id: account for account in active_accounts}
            if len(payment_accounts_by_id) != len(combined):
                return jsonify({
                    "success": False,
                    "error": "أحد حسابات الدفع غير موجود أو غير مفعّل",
                }), 400

            requested_collection = paid_amount if payment_status == "جزئي" else collection_due
            if sum(combined.values()) != requested_collection:
                return jsonify({
                    "success": False,
                    "error": (
                        "مجموع الدفعات يجب أن يساوي المبلغ المطلوب تحصيله "
                        f"({requested_collection:,} د.ع)"
                    ),
                }), 400
            payment_allocations = [
                {"treasury_account_id": account_id, "amount": amount}
                for account_id, amount in combined.items()
            ]

        if payment_status in ["جزئي", "مسدد"]:
            try:
                # Inventory that was already deducted is tied to the fulfillment
                # branch saved on its lines.  Legacy orders can have a different
                # invoice branch, so do not treat the modal's display value as a
                # request to move already-deducted stock during settlement.
                if not stock_is_deducted(order):
                    select_order_stock_branch(order, data.get("branch_id"))
                ensure_stock_for_transition(order, target_payment_status=payment_status)
            except OrderStockError as exc:
                db.session.rollback()
                return _insufficient_stock_response(exc, order)

            if payment_accounts_by_id:
                # Localize genuinely legacy rows (created before branch_id
                # existed) once, then enforce strict same-branch collection.
                if not order.branch_id:
                    from utils.branch_migration import get_default_branch

                    default_branch = get_default_branch()
                    if default_branch:
                        order.branch_id = default_branch.id
                order_branch_id = int(order.branch_id or 0)
                if order_branch_id:
                    for account in payment_accounts_by_id.values():
                        if not account.branch_id:
                            account.branch_id = order_branch_id
                wrong_branch_accounts = [
                    account.name
                    for account in payment_accounts_by_id.values()
                    if int(account.branch_id or 0) != order_branch_id
                ]
                if wrong_branch_accounts:
                    db.session.rollback()
                    return jsonify({
                        "success": False,
                        "error": "حساب استلام الدفعة يجب أن يتبع فرع الطلب",
                    }), 400

        if payment_status in ["غير مسدد", "جزئي", "مسدد", RETURN_STATUS, "مرتجع"]:
            if is_return_status_value(payment_status):
                scanned_barcode = (data.get("barcode") or "").strip()
                if not scanned_barcode:
                    return jsonify({"success": False, "error": "يجب مسح باركود الطلب لتأكيد الراجع"}), 400

                try:
                    already_returned, _msg = process_order_return(
                        order,
                        scanned_barcode,
                        return_branch_id=data.get("return_branch_id"),
                    )
                except OrderLifecycleError as exc:
                    return jsonify({"success": False, "error": exc.message}), exc.status_code

                if already_returned:
                    return jsonify({"success": True, "message": _msg})

                video_cleanup_targets = _collect_order_video_cleanup_targets(order)
                _clear_order_video_fields(order)
                delta_pay = _effective_paid_amount(order) - prev_effective_paid
                append_payment_ledger_delta(order.id, delta_pay)
                sync_delivery_expense_for_invoice(order)
                try:
                    from utils.payroll_service import sync_commission_line_for_invoice

                    sync_commission_line_for_invoice(order)
                except Exception:
                    pass
                db.session.commit()
                _delete_order_video_cleanup_targets(video_cleanup_targets)
                try:
                    log_mutation(
                        "update",
                        "orders",
                        "invoice",
                        order.id,
                        before_pay,
                        snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
                        f"ترجيع الطلب #{order.id}",
                    )
                except Exception:
                    pass
                try:
                    from utils.customer_blacklist import maybe_auto_blacklist_after_return

                    maybe_auto_blacklist_after_return(order_id)
                except Exception:
                    current_app.logger.exception("auto blacklist after return failed")
                return jsonify({"success": True})

            if payment_status == "جزئي":
                try:
                    paid_amount = int(paid_amount)
                except (ValueError, TypeError):
                    return jsonify({"success": False, "error": "مبلغ التسديد الجزئي غير صحيح"}), 400
                if paid_amount <= 0:
                    return jsonify({"success": False, "error": "مبلغ التسديد الجزئي يجب أن يكون أكبر من صفر"}), 400

            order.payment_status = payment_status
            
            # تحديث المبلغ المدفوع
            if payment_status == "مسدد":
                order.paid_amount = order.total
            elif payment_status == "جزئي" and paid_amount is not None:
                try:
                    # عند التسديد الجزئي، إضافة المبلغ المدفوع للمبلغ الموجود
                    order.paid_amount = min(order.paid_amount + paid_amount, order.total)
                    # إذا وصل المستحق إلى 0 (paid_amount == total)، تسديد تلقائي
                    if order.paid_amount >= order.total:
                        order.paid_amount = order.total
                        order.payment_status = "مسدد"
                        payment_status = "مسدد"  # تحديث المتغير للاستخدام لاحقاً
                except (ValueError, TypeError):
                    pass
            elif payment_status == "غير مسدد":
                order.paid_amount = 0
            
            # إذا تم التسديد (كامل أو جزئي وصل للكامل)، تحديث الحالة إلى "تم التوصيل"
            if payment_status == "مسدد" and order.status not in ["تم التوصيل", RETURN_STATUS]:
                order.status = "تم التوصيل"
        else:
            return jsonify({"success": False, "error": "حالة الدفع غير صحيحة"}), 400

        if payment_status in ["جزئي", "مسدد"] and delivery_fee > 0:
            tenant_id = getattr(order, "tenant_id", None)
            if getattr(order, "customer", None) is not None:
                tenant_id = getattr(order.customer, "tenant_id", tenant_id)
            apply_manual_delivery_fee_on_payment(order, delivery_fee, tenant_id)

        if payment_status == "مسدد":
            video_cleanup_targets = _collect_order_video_cleanup_targets(order)
            _clear_order_video_fields(order)
            if delivery_fee <= 0:
                order.paid_amount = order.total
            ensure_paid_shipping_order_settled(
                order,
                allocations=payment_allocations,
            )
        delta_pay = _effective_paid_amount(order) - prev_effective_paid
        if payment_allocations:
            for allocation in payment_allocations:
                append_payment_ledger_delta(
                    order.id,
                    allocation["amount"],
                    allocation["treasury_account_id"],
                )
        else:
            append_payment_ledger_delta(order.id, delta_pay)

        delivery_expense_account_id = None
        if payment_status == "مسدد":
            # أجرة التوصيل مصروف نقدي وتُخصم دائماً من الصندوق الافتراضي،
            # بصرف النظر عن الحسابات التي استلمت دفعات الزبون.
            from utils.treasury_helpers import get_default_cash_account

            delivery_expense_account_id = get_default_cash_account(order.branch_id).id
        sync_delivery_expense_for_invoice(
            order,
            treasury_account_id=delivery_expense_account_id,
        )
        try:
            from utils.payroll_service import sync_commission_line_for_invoice

            sync_commission_line_for_invoice(order)
        except Exception:
            pass
        from utils.trade_in_service import sync_trade_in_receipts

        sync_trade_in_receipts(order)
        if payment_status in ("مسدد", "جزئي"):
            try:
                from modules.order_installment_lifecycle.service import on_manual_payment
                from flask import session as _sess

                on_manual_payment(order, employee_id=_sess.get("user_id"))
            except Exception:
                pass
        db.session.commit()
        _delete_order_video_cleanup_targets(video_cleanup_targets)
        try:
            log_mutation(
                "update",
                "orders",
                "invoice",
                order.id,
                before_pay,
                snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
                f"تسديد الطلب #{order.id} — {order.payment_status}",
            )
        except Exception:
            pass
        return jsonify({
            "success": True,
            "order": {
                "id": order.id,
                "total": int(order.total or 0),
                "paid_amount": int(order.paid_amount or 0),
                "remaining": max(0, int(order.total or 0) - int(order.paid_amount or 0)),
                "status": order.status,
                "payment_status": order.payment_status,
                "payment_allocations": payment_allocations or [],
            },
        })
    except Exception as e:
        db.session.rollback()
        from modules.finance.common import FinanceError

        return jsonify({"success": False, "error": _db_user_facing_error(e)}), e.status if isinstance(e, FinanceError) else 500
    finally:
        _ORDER_PAYMENT_LOCK.release()


@orders_bp.route("/payment/adjust", methods=["POST"])
def adjust_payment():
    """Set the invoice collection state directly (unpaid / partial / paid)."""
    _ensure_order_video_columns()
    _ORDER_PAYMENT_LOCK.acquire()
    try:
        data = request.json or {}
        if "id" not in data:
            return jsonify({"success": False, "error": "بيانات غير صحيحة"}), 400

        order_id = int(data["id"])
        order = Invoice.query.filter(Invoice.id == order_id).with_for_update().first()
        if not order:
            return jsonify({"success": False, "error": "الطلب غير موجود"}), 404

        locked_response = _reject_if_stock_locked(order)
        if locked_response:
            return locked_response

        if is_returned(order.status, order.payment_status) or is_canceled(
            order.status, order.payment_status
        ):
            return jsonify({"success": False, "error": "لا يمكن تعديل تحصيل طلب ملغي أو راجع"}), 400

        payment_status = (data.get("payment") or "").strip()
        if payment_status not in ("غير مسدد", "جزئي", "مسدد"):
            return jsonify({"success": False, "error": "حالة الدفع غير صحيحة"}), 400

        total = max(0, int(order.total or 0))
        before_pay = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
        prev_effective_paid = _effective_paid_amount(order)

        if payment_status == "مسدد":
            if total <= 0:
                return jsonify({"success": False, "error": "لا يمكن تسديد طلب بمجموع صفر"}), 400
            new_paid = total
        elif payment_status == "جزئي":
            try:
                new_paid = int(data.get("paid_amount"))
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "مبلغ التسديد الجزئي غير صحيح"}), 400
            if new_paid <= 0:
                return jsonify({"success": False, "error": "مبلغ التسديد الجزئي يجب أن يكون أكبر من صفر"}), 400
            if new_paid >= total:
                return jsonify(
                    {
                        "success": False,
                        "error": f"للتسديد الكامل اختر «مسدد» (المجموع {total:,} د.ع)",
                    }
                ), 400
        else:
            new_paid = 0

        current_paid = int(order.paid_amount or 0)
        if (
            payment_status == order.payment_status
            and (
                (payment_status == "مسدد" and prev_effective_paid == total)
                or (payment_status == "جزئي" and current_paid == new_paid)
                or (payment_status == "غير مسدد" and prev_effective_paid == 0)
            )
        ):
            return jsonify(
                {
                    "success": True,
                    "message": "لا يوجد تغيير",
                    "order": {
                        "id": order.id,
                        "total": total,
                        "paid_amount": current_paid,
                        "remaining": max(0, total - current_paid),
                        "status": order.status,
                        "payment_status": order.payment_status,
                    },
                }
            )

        order.payment_status = payment_status
        order.paid_amount = new_paid
        if payment_status == "مسدد" and order.status not in ["تم التوصيل", RETURN_STATUS]:
            order.status = "تم التوصيل"
            ensure_paid_shipping_order_settled(order)

        delta_pay = _effective_paid_amount(order) - prev_effective_paid
        append_payment_ledger_delta(order.id, delta_pay, note="تعديل التحصيل")
        sync_delivery_expense_for_invoice(order)
        try:
            from utils.payroll_service import sync_commission_line_for_invoice

            sync_commission_line_for_invoice(order)
        except Exception:
            pass
        db.session.commit()
        try:
            log_mutation(
                "update",
                "orders",
                "invoice",
                order.id,
                before_pay,
                snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
                f"تعديل تحصيل الطلب #{order.id} — {order.payment_status}",
            )
        except Exception:
            pass
        return jsonify(
            {
                "success": True,
                "message": "تم تعديل التحصيل",
                "order": {
                    "id": order.id,
                    "total": total,
                    "paid_amount": int(order.paid_amount or 0),
                    "remaining": max(0, total - int(order.paid_amount or 0)),
                    "status": order.status,
                    "payment_status": order.payment_status,
                },
            }
        )
    except Exception as e:
        db.session.rollback()
        from modules.finance.common import FinanceError

        return jsonify({"success": False, "error": _db_user_facing_error(e)}), e.status if isinstance(e, FinanceError) else 500
    finally:
        _ORDER_PAYMENT_LOCK.release()


@orders_bp.route("/trade-in-receipt/<int:receipt_id>/reverse", methods=["POST"])
def reverse_trade_in(receipt_id):
    if not (
        check_permission("can_see_orders")
        and check_permission("can_manage_inventory")
    ):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    from models.trade_in_receipt import TradeInReceipt
    from utils.trade_in_service import TradeInError, reverse_trade_in_receipt

    receipt = TradeInReceipt.query.get_or_404(receipt_id)
    try:
        qty = reverse_trade_in_receipt(receipt)
        db.session.commit()
    except TradeInError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "quantity": qty, "status": receipt.status})


# =====================================================
# Cancel Order (soft cancel — تم الطلب only)
# =====================================================
@orders_bp.route("/cancel/<int:order_id>", methods=["POST"])
def cancel_order(order_id):
    order = Invoice.query.get_or_404(order_id)
    locked_response = _reject_if_stock_locked(order)
    if locked_response:
        return locked_response
    before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
    prev_effective_paid = _effective_paid_amount(order)

    try:
        process_order_cancel(order)
        append_payment_ledger_delta(order.id, _effective_paid_amount(order) - prev_effective_paid)
        sync_delivery_expense_for_invoice(order)
        try:
            from utils.payroll_service import sync_commission_line_for_invoice

            sync_commission_line_for_invoice(order)
        except Exception:
            pass
        db.session.commit()
        try:
            log_mutation(
                "update",
                "orders",
                "invoice",
                order.id,
                before,
                snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
                f"إلغاء الطلب #{order.id}",
            )
        except Exception:
            pass
        return jsonify({"success": True})
    except OrderLifecycleError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": exc.message}), exc.status_code
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": _db_user_facing_error(e)}), 500


# =====================================================
# Delete Order (Invoice) - with stock rollback
# =====================================================
@orders_bp.route("/delete/<int:order_id>", methods=["POST"])
def delete_order(order_id):
    _ensure_order_video_columns()
    order = Invoice.query.get_or_404(order_id)
    locked_response = _reject_if_stock_locked(order)
    if locked_response:
        return locked_response
    before_del = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)

    if paid_invoice_mutation_denied(order):
        return jsonify({
            "success": False,
            "error": PAID_INVOICE_MUTATION_DISABLED_MESSAGE,
            "feature_disabled": True,
        }), 403

    try:
        video_cleanup_targets = _collect_order_video_cleanup_targets(order)
        ensure_invoice_payment_ledger_table()
        from utils.invoice_hard_delete import hard_delete_invoice

        cleanup_summary = hard_delete_invoice(
            order,
            allow_paid_commission=paid_invoice_mutations_enabled(),
        )
        db.session.commit()
        try:
            log_mutation(
                "delete",
                "orders",
                "invoice",
                order_id,
                before_del,
                None,
                f"حذف الطلب #{order_id}",
            )
        except Exception:
            pass
        _delete_order_video_cleanup_targets(video_cleanup_targets)
        return jsonify({"success": True, "cleanup": cleanup_summary})
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": _db_user_facing_error(e)}), 500

# ======================================
# Update Shipping Company
# ======================================
@orders_bp.route("/update-shipping", methods=["POST"])
def update_shipping():
    data = request.json
    order = Invoice.query.get_or_404(data["order_id"])
    locked_response = _reject_if_stock_locked(order)
    if locked_response:
        return locked_response
    before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
    
    shipping_id = data.get("shipping_id")
    # إذا كان shipping_id هو None أو "none" أو ""، نضبطه على None
    if shipping_id is None or shipping_id == "" or shipping_id == "none":
        order.shipping_company_id = None
    else:
        order.shipping_company_id = int(shipping_id)
    
    db.session.commit()
    try:
        log_mutation(
            "update",
            "orders",
            "invoice",
            order.id,
            before,
            snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
            f"تحديث شركة الشحن للطلب #{order.id}",
        )
    except Exception:
        pass

    return jsonify({"success": True})

@orders_bp.route("/update-delivery-agent", methods=["POST"])
def update_delivery_agent():
    """تحديث مندوب التوصيل للطلب"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "بيانات غير صحيحة"}), 400
        
        order_id = data.get("order_id") or data.get("id")
        agent_id = data.get("agent_id")
        
        if not order_id:
            return jsonify({"error": "رقم الطلب مطلوب"}), 400
        
        order = Invoice.query.get(int(order_id))
        if not order:
            return jsonify({"error": "الطلب غير موجود"}), 404
        
        # إذا كان agent_id هو None أو "none" أو ""، نضبطه على None
        locked_response = _reject_if_stock_locked(order)
        if locked_response:
            return locked_response

        before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
        if agent_id is None or agent_id == "" or agent_id == "none":
            order.delivery_agent_id = None
        else:
            order.delivery_agent_id = int(agent_id)
        
        db.session.commit()
        log_mutation(
            "update",
            "orders",
            "invoice",
            order.id,
            before,
            snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
            f"تحديث مندوب التوصيل للطلب #{order.id}",
        )
        
        return jsonify({"success": True, "message": "تم تحديث مندوب التوصيل بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# =====================================================
# Order Details (Modal View - JSON API)
# =====================================================
@orders_bp.route("/details/<int:order_id>")
def details(order_id):
    from modules.inventory_locations.selection import describe as describe_storage_source
    from modules.sales_returns.facts import summary, returned_quantities
    _ensure_order_columns_and_unlock()
    denied = guard_permission("can_see_orders", json=True)
    if denied:
        return denied
    order = Invoice.query.get_or_404(order_id)
    denied = guard_order_access(order, json=True)
    if denied:
        return denied

    all_items = OrderItem.query.filter_by(invoice_id=order.id).all()
    items = [item for item in all_items if not is_shipping_item(item)]
    food_snapshots = _attach_food_item_snapshots(order, items)
    food_modes = {row.sale_mode for row in food_snapshots.values()}
    
    # حساب عدد الرواجع بناءً على رقم الهاتف (phone أو phone2)
    customer_phone = order.customer.phone
    customers_with_same_phone = Customer.query.filter(
        or_(
            Customer.phone == customer_phone,
            Customer.phone2 == customer_phone
        )
    ).all()
    
    customer_ids = [c.id for c in customers_with_same_phone]
    
    returned_count = Invoice.query.filter(
        Invoice.customer_id.in_(customer_ids),
        or_(
            invoice_returned_condition(Invoice),
        )
    ).count()

    from utils.branch_sales import (
        branches_stock_for_product,
        is_sell_from_all_branches_enabled,
        order_can_edit_fulfillment,
    )
    from models.branch import Branch

    branch_ids = {i.fulfillment_branch_id for i in items if i.fulfillment_branch_id}
    if order.branch_id:
        branch_ids.add(order.branch_id)
    branch_names = {}
    if branch_ids:
        for branch in Branch.query.filter(Branch.id.in_(list(branch_ids))).all():
            branch_names[branch.id] = branch.name

    sell_all = is_sell_from_all_branches_enabled()
    can_edit_fulfillment = sell_all and order_can_edit_fulfillment(order) and not is_stock_locked(order)
    from models.trade_in_receipt import TradeInReceipt

    trade_in_receipts = TradeInReceipt.query.filter_by(invoice_id=order.id).order_by(
        TradeInReceipt.id.asc()
    ).all()

    # LEON and the order details modal use the payment ledger as the canonical
    # source for financial movements.  This avoids inferring payments from the
    # current status and also exposes reversals/partial payments accurately.
    ensure_invoice_payment_ledger_table()
    payment_movements = (
        InvoicePaymentLedger.query
        .options(joinedload(InvoicePaymentLedger.treasury_account))
        .filter_by(invoice_id=order.id)
        .order_by(InvoicePaymentLedger.recorded_at.desc(), InvoicePaymentLedger.id.desc())
        .all()
    )
    effective_paid = int(_effective_paid_amount(order) or 0)
    order_total = int(order.total or 0)
    collected_total = sum(max(0, int(row.amount_delta or 0)) for row in payment_movements)
    reversed_total = sum(abs(min(0, int(row.amount_delta or 0))) for row in payment_movements)

    invoice_url = ""
    try:
        if current_app.secret_key:
            public_path = url_for(
                "orders.public_order_view",
                token=build_public_order_view_token(order.id),
            )
            invoice_url = _absolute_url_for_path(public_path)
    except Exception:
        current_app.logger.exception("details invoice_url failed for order %s", order.id)

    facebook_thread = None
    try:
        from modules.employee_desk.page_link import load_thread

        facebook_thread = load_thread(order)
    except Exception:
        facebook_thread = None

    return_info = summary(order)
    returned_by_item = returned_quantities(order.id) if return_info else {}
    response_data = {
        "order": {
            "id": order.id,
            "customer_id": order.customer_id,
            "source_module": order.source_module,
            "food_sale_mix": (
                "مختلط" if len(food_modes) > 1
                else ("جملة" if food_modes == {"WHOLESALE"} else ("مفرد" if food_modes == {"RETAIL"} else None))
            ),
            "customer": order.customer.name,
            "phone": order.customer.phone,
            "phone2": order.customer.phone2,
            "city": order.customer.city,
            "address": order.customer.address,
            "location_lat": getattr(order, "location_lat", None),
            "location_lng": getattr(order, "location_lng", None),
            "location_url": getattr(order, "location_url", None) or "",
            "location_label": getattr(order, "location_label", None) or "",
            "employee": order.employee_name,
            "employee_id": order.employee_id,
            "page_name": (order.page_name or "").strip() or None,
            "facebook_thread": facebook_thread,
            "invoice_url": invoice_url or None,
            "total": order.total,
            "return_summary": return_info,
            "discount_amount": int(getattr(order, "discount_amount", 0) or 0),
            "paid_amount": order.paid_amount or 0,
            "status": order.status,
            "payment": order.payment_status,
            "is_stock_locked": is_stock_locked(order),
            "stock_is_deducted": stock_is_deducted(order),
            "stock_lock_reason": getattr(order, "stock_lock_reason", None),
            "returned_count": returned_count,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else "",
            "shipping_company": order.shipping_company.name if order.shipping_company else None,
            "shipping_company_id": order.shipping_company_id,
            "shipping_barcode": shipping_barcodes_display(order) or order.shipping_barcode,
            "shipping_barcodes": get_shipping_barcodes_list(order),
            "can_return": bool(check_permission("return_orders") and _can_return_order(order)),
            "shipping_status": order.shipping_status,
            "note": order.note,
            "video": _order_video_payload(order),
            "branch_id": order.branch_id,
            "branch_name": branch_names.get(order.branch_id) if order.branch_id else None,
            "return_branch_id": getattr(order, "return_branch_id", None),
            "sell_from_all_branches": sell_all,
            "can_edit_fulfillment": bool(can_edit_fulfillment and not return_info),
            "can_edit_invoice": bool(
                order.source_module != "food"
                and
                not return_info
                and
                check_permission("manage_orders")
                and not is_stock_locked(order)
                and not is_canceled(order.status, order.payment_status)
                and not is_returned(order.status, order.payment_status)
                and (
                    not invoice_has_financial_effect(order)
                    or paid_invoice_mutations_enabled()
                )
            ),
            "can_edit_price": bool(not return_info and employee_can(get_current_employee(), "edit_price")),
            "can_edit_customer": bool(not return_info and employee_can(get_current_employee(), "manage_customers")),
            "can_hard_delete": bool(
                check_permission("delete_orders")
                and not return_info
                and (
                    not invoice_has_financial_effect(order)
                    or paid_invoice_mutations_enabled()
                )
            ),
        },
        "items": [
            {
                "id": i.id,
                "product_id": i.product_id,
                "name": order_item_display_name(i),
                "qty": i.quantity,
                "returned_qty": returned_by_item.get(i.id, 0),
                "remaining_qty": i.quantity-returned_by_item.get(i.id, 0),
                "price": i.price,
                "total": i.total,
                "variant_name": getattr(i, "food_variant_name", None),
                "unit_name": getattr(i, "food_unit_name", None),
                "unit_factor": getattr(i, "food_unit_factor", None),
                "sale_mode": (
                    getattr(i, "food_sale_mode", None)
                    if order.source_module == "food"
                    else (getattr(i, "sale_mode", None) or "normal")
                ),
                "quantity_base": getattr(i, "food_quantity_base", None),
                "fulfillment_branch_id": i.fulfillment_branch_id,
                "storage_source":describe_storage_source(i),
                "fulfillment_branch_name": branch_names.get(i.fulfillment_branch_id) if i.fulfillment_branch_id else None,
                "variant_color": (getattr(i, "variant_color", None) or "").strip() or None,
                "branch_stocks": (
                    branches_stock_for_product(
                        i.product_id,
                        getattr(i, "variant_color", None),
                    )
                    if can_edit_fulfillment
                    else []
                ),
            } for i in items
        ],
        "trade_in_receipts": [
            {
                "id": receipt.id,
                "source_product_name": receipt.source_product_name,
                "quantity": receipt.quantity,
                "status": receipt.status,
                "can_reverse": check_permission("can_manage_inventory"),
                "received_at": receipt.received_at.isoformat() if receipt.received_at else None,
                "reversed_at": receipt.reversed_at.isoformat() if receipt.reversed_at else None,
            }
            for receipt in trade_in_receipts
        ],
        "financial_movements": [
            {
                "id": row.id,
                "amount_delta": int(row.amount_delta or 0),
                "direction": "collection" if int(row.amount_delta or 0) >= 0 else "reversal",
                "currency": row.currency or "IQD",
                "exchange_rate": row.exchange_rate or 1,
                "source_module": row.source_module,
                "note": row.note,
                "payment_method": row.payment_method,
                "treasury_account_id": row.treasury_account_id,
                "treasury_account": row.treasury_account.name if row.treasury_account else None,
                "recorded_at": row.recorded_at.strftime("%Y-%m-%d %H:%M:%S") if row.recorded_at else None,
            }
            for row in payment_movements
        ],
        "financial_summary": {
            "order_total": order_total,
            "paid_amount": effective_paid,
            "remaining_amount": max(0, order_total - effective_paid),
            "collected_total": collected_total,
            "reversed_total": reversed_total,
            "net_ledger_amount": collected_total - reversed_total,
            "movement_count": len(payment_movements),
        },
    }
    log_activity(
        "view",
        "orders",
        f"مشاهدة تفاصيل الطلب #{order.id}",
        entity_type="invoice",
        entity_id=order.id,
    )
    return jsonify(response_data)


@orders_bp.route("/history/<int:order_id>")
def order_history(order_id):
    """Return the complete employee-facing movement timeline for one order."""
    denied = guard_permission("can_see_orders", json=True)
    if denied:
        return denied
    order = Invoice.query.get_or_404(order_id)
    denied = guard_order_access(order, json=True)
    if denied:
        return denied

    logs = (
        ActivityLog.query
        .filter(
            ActivityLog.entity_type == "invoice",
            ActivityLog.entity_id == str(order.id),
        )
        .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        .all()
    )
    events, stats = _order_history_events(order, logs)
    return jsonify({
        "success": True,
        "order_id": order.id,
        "events": events,
        "stats": stats,
    })


@orders_bp.route("/notify-employee/<int:order_id>", methods=["POST"])
def notify_order_employee(order_id):
    """إرسال تبليغ بخصوص الطلب إلى الموظف الذي أنشأه عبر محادثة الموظفين."""
    denied = guard_permission("can_see_orders", json=True)
    if denied:
        return denied

    sender_id = session.get("user_id")
    if not sender_id:
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    order = Invoice.query.get_or_404(order_id)
    denied = guard_order_access(order, json=True)
    if denied:
        return denied
    locked_response = _reject_if_stock_locked(order)
    if locked_response:
        return locked_response

    if not order.employee_id:
        return jsonify({"success": False, "error": "لا يوجد موظف مرتبط بهذا الطلب"}), 400

    if int(order.employee_id) == int(sender_id):
        return jsonify({"success": False, "error": "لا يمكنك إرسال تبليغ لنفسك"}), 400

    receiver = Employee.query.get(order.employee_id)
    if not receiver or not getattr(receiver, "is_active", True):
        return jsonify({"success": False, "error": "الموظف غير موجود أو غير نشط"}), 404

    data = request.get_json(silent=True) or {}
    user_note = ""
    file_type = None
    file_path = None
    file_name = None

    if request.content_type and "multipart/form-data" in request.content_type:
        user_note = (request.form.get("message") or "").strip()
        upload = request.files.get("file")
        if upload and upload.filename:
            from routes.messages import _save_uploaded_file

            file_type, file_path, file_name = _save_uploaded_file(upload)
    else:
        user_note = (data.get("message") or "").strip()

    if not user_note:
        return jsonify({"success": False, "error": "نص التبليغ مطلوب"}), 400

    sender = Employee.query.get(sender_id)
    sender_name = sender.name if sender else "مستخدم"
    customer_name = order.customer.name if order.customer else (order.customer_name or "—")
    customer_phone = order.customer.phone if order.customer else "—"

    if file_type == "image":
        content = f"📦 تبليغ الطلب #{order.id}: {user_note}"
    else:
        content = (
            f"📦 تبليغ بخصوص الطلب #{order.id}\n\n"
            f"{user_note}\n\n"
            f"──────────────\n"
            f"الزبون: {customer_name}\n"
            f"الهاتف: {customer_phone}\n"
            f"الحالة: {order.status} | {order.payment_status}\n"
            f"المبلغ: {int(order.total or 0):,} د.ع\n"
            f"من: {sender_name}"
        )

    message = Message(
        sender_id=sender_id,
        receiver_id=order.employee_id,
        content=content,
        file_type=file_type,
        file_path=file_path,
        file_name=file_name,
    )
    db.session.add(message)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": f"تم إرسال صورة الفاتورة والتبليغ إلى {receiver.name}",
        "receiver_id": receiver.id,
    })


@orders_bp.route("/update-fulfillment-branch", methods=["POST"])
def update_fulfillment_branch():
    """تحديد/تغيير فرع خصم المخزون لصنف أو لكل أصناف الطلب أثناء التجهيز."""
    denied = guard_permission("can_see_orders", json=True)
    if denied:
        return denied

    from utils.branch_sales import (
        is_sell_from_all_branches_enabled,
        order_can_edit_fulfillment,
        preserved_deducted_fulfillment_branch,
        reassign_item_fulfillment_branch,
    )
    from utils.branch_stock_service import BranchStockError

    # Shared-branch companies already treat inventory as company-wide, so
    # choosing a fulfillment branch is part of normal order preparation even
    # when the optional independent-branch sales setting is off.
    from utils.branch_mode import independent_branches_enabled

    if independent_branches_enabled() and not is_sell_from_all_branches_enabled():
        return jsonify({
            "success": False,
            "error": "خيار البيع لكل الفروع غير مفعّل في إعدادات الشركة",
        }), 400

    data = request.get_json(silent=True) or {}
    order_id = data.get("order_id") or data.get("id")
    branch_id = data.get("branch_id") or data.get("fulfillment_branch_id")
    item_id = data.get("item_id")
    preserve_deducted = data.get("preserve_deducted") is True

    if not order_id or not branch_id:
        return jsonify({"success": False, "error": "رقم الطلب والفرع مطلوبان"}), 400

    try:
        order_id = int(order_id)
        branch_id = int(branch_id)
        item_id = int(item_id) if item_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "بيانات غير صالحة"}), 400

    order = Invoice.query.get_or_404(order_id)
    denied = guard_order_access(order, json=True)
    if denied:
        return denied
    locked_response = _reject_if_stock_locked(order)
    if locked_response:
        return locked_response

    if not order_can_edit_fulfillment(order):
        return jsonify({
            "success": False,
            "error": "لا يمكن تغيير فرع الخصم بعد اكتمال أو إلغاء الطلب",
        }), 400

    items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
    if item_id:
        items = [i for i in items if i.id == item_id]
        if not items:
            return jsonify({"success": False, "error": "الصنف غير موجود في الطلب"}), 404

    # Agent-report preparation may choose a branch for orders whose stock has
    # not been deducted yet.  Already-dispatched orders, however, own an exact
    # branch reservation and must keep it; moving that reservation here can
    # fail with a false shortage even though the report itself is ready.
    preserve_existing, preserved_branch_id = preserved_deducted_fulfillment_branch(
        items,
        inventory_is_deducted=stock_is_deducted(order),
        preserve_deducted=preserve_deducted,
    )
    if preserve_existing:
        from models.branch import Branch

        preserved_branch = Branch.query.get(preserved_branch_id) if preserved_branch_id else None
        return jsonify({
            "success": True,
            "preserved": True,
            "message": "تم الإبقاء على فرع الخصم المسجل لأن المخزون مخصوم مسبقاً",
            "branch_id": preserved_branch_id,
            "branch_name": preserved_branch.name if preserved_branch else None,
        })

    before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
    try:
        for item in items:
            reassign_item_fulfillment_branch(
                item,
                branch_id,
                inventory_is_deducted=stock_is_deducted(order),
            )
        if not item_id:
            order.branch_id = branch_id
        db.session.commit()
        try:
            log_mutation(
                "update",
                "orders",
                "invoice",
                order.id,
                before,
                snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
                f"تحديث فرع الخصم للطلب #{order.id}",
            )
        except Exception:
            pass

        from models.branch import Branch

        branch = Branch.query.get(branch_id)
        return jsonify({
            "success": True,
            "message": "تم تحديث فرع الخصم",
            "branch_id": branch_id,
            "branch_name": branch.name if branch else None,
        })
    except BranchStockError as exc:
        db.session.rollback()
        return jsonify({
            "success": False,
            "code": "INSUFFICIENT_STOCK",
            "error": str(exc),
            "shortages": [str(exc)],
            "order_id": order.id,
            "order_ids": [order.id],
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": _db_user_facing_error(e)}), 500


@orders_bp.route("/<int:order_id>")
def order_page_shortcut(order_id):
    """Compatibility: some UI paths used `/orders/<id>` which is not a real page.

    Redirect to the main orders list and let the client auto-open the details modal.
    """
    if not check_permission("can_see_orders"):
        return redirect("/pos"), 403
    return redirect(url_for("orders.orders", open_details=order_id))


@orders_bp.route("/<int:order_id>/video", methods=["POST"])
def upload_order_video(order_id):
    _ensure_order_video_columns()
    if not check_permission("can_see_orders"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    order = Invoice.query.get_or_404(order_id)
    denied = guard_order_access(order, json=True)
    if denied:
        return denied
    locked_response = _reject_if_stock_locked(order)
    if locked_response:
        return locked_response
    file = request.files.get("video")
    if not file or not file.filename:
        return jsonify({"success": False, "error": "يرجى اختيار ملف فيديو."}), 400

    result = save_uploaded_file(file, max_mb=250)
    if not result.get("ok"):
        return jsonify({"success": False, "error": result.get("message") or "فشل رفع الفيديو."}), 400

    previous_targets = _collect_order_video_cleanup_targets(order)
    try:
        _apply_order_video_result(order, result, file.filename)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        _delete_saved_upload_result(result)
        return jsonify({"success": False, "error": _db_user_facing_error(e)}), 500

    _delete_order_video_cleanup_targets(previous_targets)
    return jsonify({
        "success": True,
        "message": "تم حفظ فيديو الطلب بنجاح.",
        "video": _order_video_payload(order),
    })


@orders_bp.route("/<int:order_id>/video", methods=["GET"])
def stream_order_video(order_id):
    _ensure_order_video_columns()
    if not check_permission("can_see_orders"):
        abort(403)

    order = Invoice.query.get_or_404(order_id)
    safe_name = Path(order.order_video_path).name if order.order_video_path else None
    if not safe_name:
        abort(404)
    root = get_video_upload_root()
    path = root / safe_name
    if not path.exists() or not path.is_file():
        abort(404)
    try:
        return send_from_directory(str(root), safe_name, conditional=True)
    except OSError as e:
        current_app.logger.warning("stream_order_video send failed: %s", e, exc_info=True)
        abort(404)


@orders_bp.route("/<int:order_id>/video/download", methods=["GET"])
def download_order_video(order_id):
    _ensure_order_video_columns()
    if not check_permission("can_see_orders"):
        abort(403)

    order = Invoice.query.get_or_404(order_id)
    safe_name = Path(order.order_video_path).name if order.order_video_path else None
    if not safe_name:
        abort(404)
    root = get_video_upload_root()
    path = root / safe_name
    if not path.exists() or not path.is_file():
        abort(404)

    original_name = order.order_video_original_name or safe_name
    try:
        return send_from_directory(
            str(root),
            safe_name,
            as_attachment=True,
            download_name=original_name,
            conditional=True,
        )
    except OSError as e:
        current_app.logger.warning("download_order_video send failed: %s", e, exc_info=True)
        abort(404)


@orders_bp.route("/invoice-video/<token>")
def stream_invoice_video_guest(token: str):
    """بث فيديو الطلب لمن يفتح رابط الفاتورة/QR بدون اشتراط جلسة (الرمز موقّع بـ SECRET_KEY)."""
    _ensure_order_video_columns()
    parsed = parse_invoice_video_guest_token(token.strip())
    if not parsed:
        abort(404)
    order_id, tenant_slug = parsed
    g.tenant = tenant_slug
    order = Invoice.query.get_or_404(order_id)
    safe_name = Path(order.order_video_path).name if getattr(order, "order_video_path", None) else None
    if not safe_name:
        abort(404)
    root = get_video_upload_root()
    path = root / safe_name
    if not path.exists() or not path.is_file():
        abort(404)
    try:
        return send_from_directory(str(root), safe_name, conditional=True)
    except OSError as e:
        current_app.logger.warning("stream_invoice_video_guest send failed: %s", e, exc_info=True)
        abort(404)


@orders_bp.route("/p/o/<token>")
def public_order_view(token: str):
    """تفاصيل الطلب + فيديو للعامة (مسح QR) دون تسجيل دخول — الرمز موقّع."""
    from utils.invoice_sales_returns import attach_return_summary
    _ensure_order_video_columns()
    parsed = parse_public_order_view_token((token or "").strip())
    if not parsed:
        abort(404)
    oid, tenant_slug = parsed
    g.tenant = tenant_slug
    order = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
    ).get_or_404(oid)
    from utils.order_shipping import prepare_invoice_items_for_print, invoice_print_amounts, invoice_display_amounts

    raw_items = OrderItem.query.filter_by(invoice_id=order.id).all()
    items, print_total = prepare_invoice_items_for_print(raw_items)
    _attach_food_item_snapshots(order, items)
    display_amounts = invoice_display_amounts(order, raw_items, print_total)
    total = display_amounts["total"]
    total_before_discount = display_amounts["total_before_discount"]
    discount_amount = display_amounts["discount_amount"]
    amounts = invoice_print_amounts(order, total)
    due = amounts["due"]
    paid_amount = amounts["paid_amount"]
    is_partial = amounts["is_partial"]
    settings = InvoiceSettings.get_settings()
    invoice_video_guest_url = None
    if getattr(order, "order_video_path", None):
        try:
            vpath = url_for(
                "orders.stream_invoice_video_guest",
                token=build_invoice_video_guest_token(order.id),
            )
            invoice_video_guest_url = _absolute_url_for_path(vpath)
        except Exception:
            current_app.logger.exception("public_order_view video url for order %s", order.id)
    return attach_return_summary(render_template(
        "order_public_view.html",
        order=_order_for_print(order),
        items=items,
        total=total,
        total_before_discount=total_before_discount,
        discount_amount=discount_amount,
        due=due,
        paid_amount=paid_amount,
        is_partial=is_partial,
        settings=settings,
        invoice_video_guest_url=invoice_video_guest_url,
    ), order)


# =====================================================
# Order Query API (For Voice Assistant)
# =====================================================
@orders_bp.route("/query/<int:order_id>")
def query_order(order_id):
    """API للاستعلام عن تفاصيل الطلب للمساعد الصوتي"""
    denied = guard_permission("can_see_orders", json=True)
    if denied:
        return denied
    order = Invoice.query.get(order_id)
    
    if not order:
        return jsonify({
            "success": False,
            "error": "الطلب غير موجود"
        }), 404
    denied = guard_order_access(order, json=True)
    if denied:
        return denied
    
    items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
    
    return jsonify({
        "success": True,
        "order": {
            "id": order.id,
            "customer_name": order.customer_name,
            "customer_phone": order.customer.phone if order.customer else "",
            "customer_city": order.customer.city if order.customer else "",
            "customer_address": order.customer.address if order.customer else "",
            "employee_name": order.employee_name,
            "employee_id": order.employee_id,
            "total": order.total,
            "status": order.status,
            "payment_status": order.payment_status,
            "shipping_company": order.shipping_company.name if order.shipping_company else None,
            "shipping_status": order.shipping_status,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else "",
            "items_count": len(items),
            "items": [
                {
                    "name": order_item_display_name(i),
                    "quantity": i.quantity,
                    "price": i.price,
                    "total": i.total
                } for i in items
            ]
        }
    })

# =====================================================
# Invoice Page (Display Invoice)
# =====================================================
@orders_bp.route("/invoice/<int:order_id>")
def invoice_page(order_id):
    ensure_invoice_schema()
    _ensure_order_video_columns()
    denied = guard_permission("print_pos_invoice")
    if denied:
        return denied
    order = Invoice.query.get_or_404(order_id)
    denied = guard_order_access(order, for_print=True)
    if denied:
        return denied
    log_activity(
        "print",
        "orders",
        f"فتح فاتورة الطلب #{order.id} للطباعة",
        entity_type="invoice",
        entity_id=order.id,
    )

    from utils.order_shipping import prepare_invoice_items_for_print, invoice_print_amounts, invoice_display_amounts

    raw_items = OrderItem.query.filter_by(invoice_id=order.id).all()
    items, print_total = prepare_invoice_items_for_print(raw_items)
    _attach_food_item_snapshots(order, items)

    display_amounts = invoice_display_amounts(order, raw_items, print_total)
    total = display_amounts["total"]
    total_before_discount = display_amounts["total_before_discount"]
    discount_amount = display_amounts["discount_amount"]
    amounts = invoice_print_amounts(order, total)
    due = amounts["due"]
    paid_amount = amounts["paid_amount"]
    is_partial = amounts["is_partial"]

    # حساب عدد الرواجع بناءً على رقم الهاتف (phone أو phone2)
    customer_phone = getattr(order.customer, "phone", None) if order.customer else None
    returned_count = 0
    cancelled_count = 0
    if customer_phone:
        customers_with_same_phone = Customer.query.filter(
            or_(
                Customer.phone == customer_phone,
                Customer.phone2 == customer_phone
            )
        ).all()
        customer_ids = [c.id for c in customers_with_same_phone]
        returned_count = Invoice.query.filter(
            Invoice.customer_id.in_(customer_ids),
            or_(
                invoice_returned_condition(Invoice),
            )
        ).count()
        cancelled_count = Invoice.query.filter(
            Invoice.customer_id.in_(customer_ids),
            Invoice.status == "ملغي"
        ).count()

    # Get invoice settings
    settings = InvoiceSettings.get_settings()
    
    template_file, template_styles = _tenant_invoice_template_bundle()

    order_public_view_url = ""
    try:
        if current_app.secret_key:
            p = url_for("orders.public_order_view", token=build_public_order_view_token(order.id))
            order_public_view_url = _absolute_url_for_path(p)
    except Exception:
        current_app.logger.exception("order_public_view_url failed for order %s", order.id)

    invoice_capture = request.args.get("capture") == "1"
    from utils.invoice_print_codes import invoice_print_codes
    printable_codes=invoice_print_codes(order.id,order_public_view_url or url_for("orders.invoice_page",order_id=order.id))

    return _render_order_invoice(
        template_file,
        order=_order_for_print(order),
        items=items,
        total=total,
        total_before_discount=total_before_discount,
        discount_amount=discount_amount,
        due=due,
        paid_amount=paid_amount,
        is_partial=is_partial,
        returned_count=returned_count,
        cancelled_count=cancelled_count,
        settings=settings,
        template_styles=template_styles,
        order_public_view_url=order_public_view_url,
        invoice_capture=invoice_capture,
        printable_codes=printable_codes,
    )

# =====================================================
# Print Selected Invoices (each with active template)
# =====================================================
@orders_bp.route("/print-invoices")
def print_invoices():
    denied = guard_permission("print_pos_invoice")
    if denied:
        return denied

    ids_param = request.args.get("ids", "").strip()
    if not ids_param:
        return "لا توجد فواتير محددة", 400
    try:
        ids_list = [int(x) for x in ids_param.split(",") if x.strip().isdigit()]
    except Exception:
        return "صيغة معرفات غير صحيحة", 400
    if not ids_list:
        return "لا توجد فواتير محددة", 400

    invoices = Invoice.query.filter(Invoice.id.in_(ids_list)).all()
    id_to_invoice = {inv.id: inv for inv in invoices}
    ordered_ids = []
    for order_id in ids_list:
        order = id_to_invoice.get(order_id)
        if not order:
            continue
        denied = guard_order_access(order, for_print=True)
        if denied:
            return denied
        ordered_ids.append(order_id)

    if not ordered_ids:
        return "لا توجد فواتير محددة", 400

    from utils.order_shipping import prepare_invoice_items_for_print, invoice_print_amounts, invoice_display_amounts

    settings = InvoiceSettings.get_settings()
    template_file, template_styles = _tenant_invoice_template_bundle()
    rendered_invoices = []

    for order_id in ordered_ids:
        order = id_to_invoice[order_id]
        raw_items = OrderItem.query.filter_by(invoice_id=order.id).all()
        items, print_total = prepare_invoice_items_for_print(raw_items)
        _attach_food_item_snapshots(order, items)

        display_amounts = invoice_display_amounts(order, raw_items, print_total)
        total = display_amounts["total"]
        total_before_discount = display_amounts["total_before_discount"]
        discount_amount = display_amounts["discount_amount"]
        amounts = invoice_print_amounts(order, total)

        returned_count = 0
        cancelled_count = 0
        customer_phone = getattr(order.customer, "phone", None) if order.customer else None
        if customer_phone:
            customer_ids = [
                customer.id
                for customer in Customer.query.filter(
                    or_(Customer.phone == customer_phone, Customer.phone2 == customer_phone)
                ).all()
            ]
            if customer_ids:
                returned_count = Invoice.query.filter(
                    Invoice.customer_id.in_(customer_ids),
                    invoice_returned_condition(Invoice),
                ).count()
                cancelled_count = Invoice.query.filter(
                    Invoice.customer_id.in_(customer_ids),
                    Invoice.status == "ملغي",
                ).count()

        order_public_view_url = ""
        try:
            if current_app.secret_key:
                public_path = url_for(
                    "orders.public_order_view",
                    token=build_public_order_view_token(order.id),
                )
                order_public_view_url = _absolute_url_for_path(public_path)
        except Exception:
            current_app.logger.exception(
                "print_invoices public URL failed for order %s", order.id
            )

        from utils.invoice_print_codes import invoice_print_codes
        printable_codes=invoice_print_codes(order.id,order_public_view_url or url_for("orders.invoice_page",order_id=order.id))
        rendered_invoices.append(
            {
                "id": order.id,
                "html": _render_order_invoice(
                    template_file,
                    order=_order_for_print(order),
                    items=items,
                    total=total,
                    total_before_discount=total_before_discount,
                    discount_amount=discount_amount,
                    due=amounts["due"],
                    paid_amount=amounts["paid_amount"],
                    is_partial=amounts["is_partial"],
                    returned_count=returned_count,
                    cancelled_count=cancelled_count,
                    settings=settings,
                    template_styles=template_styles,
                    order_public_view_url=order_public_view_url,
                    invoice_capture=True,
                    printable_codes=printable_codes,
                ),
            }
        )
        log_activity(
            "print",
            "orders",
            f"طباعة جماعية لفاتورة الطلب #{order.id}",
            entity_type="invoice",
            entity_id=order.id,
        )

    # Flatten the selected invoice documents into one print DOM. Loading each
    # invoice in its own iframe repeats fonts, styles, barcode libraries and QR
    # setup dozens of times, which is noticeably slow for large selections.
    head_assets = ""
    flattened_invoices = []
    for index, rendered in enumerate(rendered_invoices):
        invoice_html = rendered["html"]
        head_match = re.search(r"<head\b[^>]*>(.*?)</head>", invoice_html, re.IGNORECASE | re.DOTALL)
        body_match = re.search(r"<body\b[^>]*>(.*?)</body>", invoice_html, re.IGNORECASE | re.DOTALL)

        if index == 0 and head_match:
            head_assets = "".join(
                re.findall(
                    r"(?:<link\b[^>]*>|<style\b[^>]*>.*?</style>|<script\b[^>]*\bsrc=[^>]*>.*?</script>)",
                    head_match.group(1),
                    re.IGNORECASE | re.DOTALL,
                )
            )

        flattened_invoices.append(
            {
                "id": rendered["id"],
                "html": body_match.group(1) if body_match else invoice_html,
            }
        )

    return render_template(
        "print_invoices.html",
        ids=ordered_ids,
        rendered_invoices=flattened_invoices,
        invoice_head_assets=head_assets,
    )


# =====================================================
# Print Batch Invoices (legacy default template)
# =====================================================
@orders_bp.route("/print-batch")
def print_batch():
    ids_param = request.args.get("ids", "").strip()
    if not ids_param:
        return "لا توجد فواتير محددة", 400
    try:
        ids_list = [int(x) for x in ids_param.split(",") if x.strip().isdigit()]
    except Exception:
        return "صيغة معرفات غير صحيحة", 400
    if not ids_list:
        return "لا توجد فواتير محددة", 400

    # اجلب جميع الفواتير المطلوبة
    invoices = Invoice.query.filter(Invoice.id.in_(ids_list)).all()
    # حافظ على ترتيب الإدخالات كما اختارها المستخدم
    id_to_invoice = {inv.id: inv for inv in invoices}
    ordered_invoices = [id_to_invoice[i] for i in ids_list if i in id_to_invoice]

    from utils.order_shipping import prepare_invoice_items_for_print, invoice_print_amounts, invoice_display_amounts

    settings = InvoiceSettings.get_settings()
    batch = []
    for order in ordered_invoices:
        raw_items = OrderItem.query.filter_by(invoice_id=order.id).all()
        items, print_total = prepare_invoice_items_for_print(raw_items)
        _attach_food_item_snapshots(order, items)

        # حساب الرواجع والملغي لنفس الزبون
        customer_phones = []
        if order.customer:
            if order.customer.phone:
                customer_phones.append(order.customer.phone)
            if getattr(order.customer, "phone2", None):
                customer_phones.append(order.customer.phone2)

        returned_count = 0
        cancelled_count = 0
        if customer_phones:
            returned_count = Invoice.query.join(Customer).filter(
                or_(Customer.phone.in_(customer_phones), Customer.phone2.in_(customer_phones)),
                invoice_returned_condition(Invoice)
            ).count()
            cancelled_count = Invoice.query.join(Customer).filter(
                or_(Customer.phone.in_(customer_phones), Customer.phone2.in_(customer_phones)),
                Invoice.status == "ملغي"
            ).count()

        display_amounts = invoice_display_amounts(order, raw_items, print_total)
        total = display_amounts["total"]
        total_before_discount = display_amounts["total_before_discount"]
        discount_amount = display_amounts["discount_amount"]
        amounts = invoice_print_amounts(order, total)
        due = amounts["due"]
        paid_amount = amounts["paid_amount"]
        is_partial = amounts["is_partial"]

        public_view_url = ""
        try:
            if current_app.secret_key:
                p = url_for("orders.public_order_view", token=build_public_order_view_token(order.id))
                public_view_url = _absolute_url_for_path(p)
        except Exception:
            current_app.logger.exception("print_batch public_view_url order %s", order.id)

        batch.append({
            "order": order,
            "items": items,
            "total": total,
            "total_before_discount": total_before_discount,
            "discount_amount": discount_amount,
            "due": due,
            "paid_amount": paid_amount,
            "is_partial": is_partial,
            "returned_count": returned_count,
            "cancelled_count": cancelled_count,
            "public_view_url": public_view_url,
        })
        log_activity(
            "print",
            "orders",
            f"طباعة دفعة لفاتورة الطلب #{order.id}",
            entity_type="invoice",
            entity_id=order.id,
        )

    _, template_styles = _tenant_invoice_template_bundle()

    return render_template(
        "print_batch.html",
        batch=batch,
        settings=settings,
        template_styles=template_styles,
    )

# =====================================================
# Export PDF (selected columns)
# =====================================================
def _collect_orders_for_export(order_ids=None):
    q = Invoice.query.options(joinedload(Invoice.customer)).order_by(Invoice.created_at.desc())

    employee = get_current_employee()
    if employee and employee.role != "admin":
        allowed_statuses = allowed_order_statuses_for(employee)
        if allowed_statuses:
            q = q.filter(Invoice.status.in_(allowed_statuses))
        else:
            q = q.filter(Invoice.id == -1)

    if order_ids:
        orders_map = {
            o.id: o for o in q.filter(Invoice.id.in_(order_ids)).all()
        }
        return [orders_map[i] for i in order_ids if i in orders_map]

    return q.all()


def _orders_export_rows(orders):
    rows = []
    total_amount = 0
    for o in orders:
        amount = int(o.total or 0)
        total_amount += amount
        rows.append({
            "invoice_no": o.id,
            "shipping_barcode": shipping_barcodes_display(o) or o.shipping_barcode or "",
            "phone": o.customer.phone if o.customer else "",
            "customer_name": o.customer.name if o.customer else "",
            "amount": amount,
        })
    return rows, total_amount


def _parse_export_order_ids():
    order_ids = None
    if request.method == "POST":
        data = request.get_json(silent=True)
        if data is None:
            raw = (request.form.get("ids") or "").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        data = {"ids": parsed}
                except Exception:
                    data = {"ids": [i.strip() for i in raw.split(",") if i.strip()]}
        if data:
            raw_ids = data.get("ids") or []
            order_ids = [int(i) for i in raw_ids if str(i).strip().isdigit()]
    else:
        ids_param = (request.args.get("ids") or "").strip()
        if ids_param:
            order_ids = [int(i.strip()) for i in ids_param.split(",") if i.strip().isdigit()]
    return order_ids


@orders_bp.route("/export", methods=["GET", "POST"])
@orders_bp.route("/export-pdf", methods=["GET", "POST"])
def export_pdf():
    if not check_permission("can_see_orders"):
        return redirect("/pos"), 403

    order_ids = _parse_export_order_ids()
    orders = _collect_orders_for_export(order_ids)
    rows, total_amount = _orders_export_rows(orders)

    settings = InvoiceSettings.get_settings()
    now = datetime.now()
    export_date = now.strftime("%Y-%m-%d")
    export_datetime = now.strftime("%Y-%m-%d %H:%M")

    return render_template(
        "orders_export_pdf.html",
        rows=rows,
        total_amount=total_amount,
        company_name=(settings.report_company_name or settings.company_name or "Finora System"),
        company_subtitle=settings.company_subtitle or "",
        export_date=export_date,
        export_datetime=export_datetime,
        filename=f"orders_{export_date.replace('-', '')}.pdf",
    )

# =====================================================
# Print Selected Invoices (Multiple)
# =====================================================
@orders_bp.route("/print-selected", methods=["POST"])
def print_selected():
    data = request.json
    order_ids = data.get("ids", [])
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    orders_data = []
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
            # حساب عدد الرواجع بناءً على رقم الهاتف (phone أو phone2)
            customer_phone = order.customer.phone
            customers_with_same_phone = Customer.query.filter(
                or_(
                    Customer.phone == customer_phone,
                    Customer.phone2 == customer_phone
                )
            ).all()
            
            customer_ids = [c.id for c in customers_with_same_phone]
            
            returned_count = Invoice.query.filter(
                Invoice.customer_id.in_(customer_ids),
                or_(
                    invoice_returned_condition(Invoice),
                )
            ).count()
            
            orders_data.append({
                "order": {
                    "id": order.id,
                    "customer": order.customer.name,
                    "phone": order.customer.phone,
                    "phone2": order.customer.phone2,
                    "city": order.customer.city,
                    "address": order.customer.address,
                    "employee": order.employee_name,
                    "total": order.total,
                    "status": order.status,
                    "payment": order.payment_status,
                    "returned_count": returned_count
                },
                "items": [
                    {
                        "name": order_item_display_name(i),
                        "qty": i.quantity,
                        "price": i.price,
                        "total": i.total
                    } for i in items
                ]
            })
    
    return jsonify({"orders": orders_data})

# =====================================================
# Print Report (Summary)
# =====================================================
@orders_bp.route("/print-report", methods=["POST"])
def print_report():
    data = request.json
    order_ids = data.get("ids", [])
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    orders_data = []
    total_amount = 0
    
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            # جلب تفاصيل المنتجات في الفاتورة لعرضها في كشف الطباعة
            items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
            items_count = sum((item.quantity or 0) for item in items) if items else 0
            products_list = []
            for item in items:
                name = order_item_display_name(item)
                products_list.append({
                    "name": name,
                    "quantity": item.quantity
                })
            from utils.agent_report_helpers import order_payment_snapshot

            payment = order_payment_snapshot(order)
            orders_data.append({
                "id": order.id,
                "phone": order.customer.phone,
                "quantity": items_count,
                "total": payment["total"],
                "paid_amount": payment["paid_amount"],
                "remaining": payment["remaining"],
                "city": order.customer.city or "",
                "address": order.customer.address or "",
                "shipping": order.shipping_company.name if order.shipping_company else "",
                "products": products_list
            })
            total_amount += payment["remaining"]
    
    return jsonify({
        "orders": orders_data,
        "total": total_amount,
        "count": len(orders_data)
    })

@orders_bp.route("/print-report-page")
def print_report_page():
    """صفحة HTML لطباعة الكشف"""
    agent_id = request.args.get("agent_id")
    agent_name = None
    save_report = request.args.get("save", "false").lower() == "true"
    report_id = None
    
    if agent_id:
        try:
            agent = DeliveryAgent.query.get(int(agent_id))
            if agent:
                agent_name = agent.name
                
                # إذا طلب حفظ الكشف، احفظه تلقائياً
                if save_report:
                    ids_param = request.args.get("ids", "")
                    if ids_param:
                        try:
                            order_ids = [int(id.strip()) for id in ids_param.split(",") if id.strip()]
                            if order_ids:
                                # استدعاء دالة إنشاء الكشف
                                report_data = create_agent_report_internal(
                                    order_ids=order_ids,
                                    agent_id=int(agent_id),
                                    save_to_db=True
                                )
                                if report_data.get("success"):
                                    report_id = report_data.get("report_id")
                        except:
                            pass
        except:
            pass
    
    return render_template("print_report.html", agent_name=agent_name, report_id=report_id)


@orders_bp.route("/print-items-report-page")
def print_items_report_page():
    """(قديمة) لم تعد مستخدمة بعد دمج كشف المنتجات مع كشف المندوب."""
    return redirect(url_for("orders.print_report_page", **request.args))

@orders_bp.route("/get-print-report-data")
def get_print_report_data():
    """API لجلب بيانات الطلبات للطباعة"""
    ids_param = request.args.get("ids", "")
    agent_id = request.args.get("agent_id")  # معرف المندوب (اختياري)
    
    if not ids_param:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    try:
        order_ids = [int(id.strip()) for id in ids_param.split(",") if id.strip()]
    except ValueError:
        return jsonify({"error": "معرفات الطلبات غير صحيحة"}), 400
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    # جلب معلومات المندوب إذا كان معرفه موجوداً
    agent_name = None
    if agent_id:
        try:
            agent = DeliveryAgent.query.get(int(agent_id))
            if agent:
                agent_name = agent.name
        except:
            pass
    
    orders_data = []
    total_amount = 0
    
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            # جلب تفاصيل المنتجات لكل فاتورة حتى تظهر في كشف الطباعة
            items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
            items_count = sum((item.quantity or 0) for item in items) if items else 0
            products_list = []
            for item in items:
                name = order_item_display_name(item)
                products_list.append({
                    "name": name,
                    "quantity": item.quantity
                })
            from utils.agent_report_helpers import order_payment_snapshot

            payment = order_payment_snapshot(order)
            orders_data.append({
                "id": order.id,
                "phone": order.customer.phone,
                "quantity": items_count,
                "total": payment["total"],
                "paid_amount": payment["paid_amount"],
                "remaining": payment["remaining"],
                "city": order.customer.city or "",
                "address": order.customer.address or "",
                "shipping": order.shipping_company.name if order.shipping_company else "",
                "products": products_list
            })
            total_amount += payment["remaining"]
    
    response_data = {
        "success": True,
        "orders": orders_data,
        "total": total_amount,
        "count": len(orders_data)
    }
    
    # إضافة اسم المندوب إذا كان موجوداً
    if agent_name:
        response_data["agent_name"] = agent_name
    
    return jsonify(response_data)

# =====================================================
# Save Report
# =====================================================
@orders_bp.route("/save-report", methods=["POST"])
def save_report():
    data = request.json
    order_ids = data.get("ids", [])
    notes = data.get("notes", "")
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    # Generate report number
    last_report = Report.query.order_by(Report.id.desc()).first()
    if last_report:
        try:
            last_num = int(last_report.report_number.split("-")[-1])
            report_number = f"RPT-{last_num + 1:04d}"
        except:
            report_number = "RPT-0001"
    else:
        report_number = "RPT-0001"
    
    # Get orders data (مع تفاصيل المنتجات لكل فاتورة ليُستخدم لاحقاً في الكشوفات)
    orders_data = []
    total_amount = 0
    
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
            items_count = sum((item.quantity or 0) for item in items) if items else 0
            products_list = []
            for item in items:
                name = order_item_display_name(item)
                products_list.append({
                    "name": name,
                    "quantity": item.quantity
                })
            orders_data.append({
                "id": order.id,
                "phone": order.customer.phone,
                "quantity": items_count,
                "total": order.total,
                "city": order.customer.city or "",
                "address": order.customer.address or "",
                "shipping": order.shipping_company.name if order.shipping_company else "",
                "products": products_list
            })
            total_amount += order.total
    
    # Create report
    report = Report(
        report_number=report_number,
        orders_data=json.dumps(orders_data, ensure_ascii=False),
        total_amount=total_amount,
        orders_count=len(orders_data),
        notes=notes,
        created_by=session.get("username", "Unknown")
    )
    
    db.session.add(report)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "report_id": report.id,
        "report_number": report_number
    })

# =====================================================
# Reports Page
# =====================================================
@orders_bp.route("/reports")
def reports_page():
    reports = Report.query.order_by(Report.created_at.desc()).all()
    return render_template("orders_reports.html", reports=reports)

# =====================================================
# Get Report Details
# =====================================================
@orders_bp.route("/search-by-barcode")
def search_by_barcode():
    barcode = request.args.get("barcode", "").strip()
    if not barcode:
        return jsonify({"success": False, "error": "باركود مطلوب"}), 400

    # مطابقة باركود الفاتورة / شركة النقل، أو رقم الطلب نفسه (نفس القيمة المرمّزة على قوالب الفاتورة CODE128)
    invoice = Invoice.query.filter(
        or_(
            Invoice.barcode == barcode,
            Invoice.shipping_barcode == barcode,
        )
    ).first()

    if not invoice and barcode.isdigit():
        try:
            oid = int(barcode)
            if oid > 0:
                invoice = Invoice.query.get(oid)
        except (TypeError, ValueError):
            invoice = None

    if not invoice:
        # مطابقة باركودات النقل المتعددة (shipping_barcodes_json)
        candidates = (
            Invoice.query.filter(Invoice.shipping_barcodes_json.ilike(f'%"{barcode}"%'))
            .order_by(Invoice.id.desc())
            .limit(50)
            .all()
        )
        for cand in candidates:
            if shipping_barcodes_match_code(cand, barcode):
                invoice = cand
                break

    if not invoice:
        return jsonify({"success": False, "error": "لم يتم العثور على فاتورة"}), 404
    
    return jsonify({
        "success": True,
        "invoice": {
            "id": invoice.id,
            "customer_name": invoice.customer_name,
            "customer": invoice.customer_name,
            "phone": invoice.customer.phone if invoice.customer else "",
            "total": invoice.total,
            "status": invoice.status,
            "payment_status": invoice.payment_status,
            "barcode": invoice.barcode,
            "shipping_barcode": shipping_barcodes_display(invoice) or invoice.shipping_barcode,
            "shipping_barcodes": get_shipping_barcodes_list(invoice),
        }
    })

@orders_bp.route("/update-barcode/<int:invoice_id>", methods=["POST"])
def update_barcode(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    locked_response = _reject_if_stock_locked(invoice)
    if locked_response:
        return locked_response
    data = request.get_json() or {}
    
    barcode = data.get("barcode", "").strip()
    invoice.barcode = barcode if barcode else None
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم حفظ الباركود بنجاح"
    })

@orders_bp.route("/update-shipping-barcode/<int:invoice_id>", methods=["POST"])
def update_shipping_barcode(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    denied = guard_order_access(invoice, json=True)
    if denied:
        return denied
    locked_response = _reject_if_stock_locked(invoice)
    if locked_response:
        return locked_response
    if is_returned(invoice.status, invoice.payment_status) or (invoice.status or "").strip() == "ملغي":
        return jsonify(success=False, error="لا يمكن تعديل وصل طلب راجع أو ملغي"), 409
    before = snapshot_attrs(invoice, *INVOICE_SNAPSHOT_FIELDS)
    data = request.get_json() or {}
    if not isinstance(data, dict):
        return jsonify(success=False, error="صيغة الوصل غير صالحة"), 400
    
    shipping_barcode = data.get("shipping_barcode", "")
    if not isinstance(shipping_barcode, str):
        return jsonify(success=False, error="رقم الوصل غير صالح"), 400
    shipping_barcode = shipping_barcode.strip()
    shipping_barcodes_raw = data.get("shipping_barcodes")
    shipping_company_id = data.get("shipping_company_id")
    shipping_company = invoice.shipping_company

    if shipping_company_id is not None and shipping_company_id != "":
        try:
            shipping_company_id = int(shipping_company_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "معرّف شركة النقل غير صالح"}), 400
        shipping_company = ShippingCompany.query.get(shipping_company_id)
        if not shipping_company:
            return jsonify({"success": False, "error": "شركة النقل غير موجودة"}), 404
        invoice.shipping_company_id = shipping_company_id
    elif not invoice.shipping_company_id:
        return jsonify({"success": False, "error": "اختر شركة النقل"}), 400

    if shipping_barcodes_raw is not None:
        if not isinstance(shipping_barcodes_raw, list):
            return jsonify({"success": False, "error": "صيغة الباركودات غير صحيحة"}), 400
        if len(shipping_barcodes_raw) > 500 or any(not isinstance(b, str) for b in shipping_barcodes_raw):
            return jsonify(success=False, error="أرقام الوصولات غير صالحة"), 400
        cleaned = [b.strip() for b in shipping_barcodes_raw if b.strip()]
        if not cleaned:
            return jsonify({"success": False, "error": "أدخل باركود الشحن لكل قطعة"}), 400
        if len(set(cleaned)) != len(cleaned):
            return jsonify({"success": False, "error": "لا يمكن تكرار نفس باركود الشحن"}), 400
        if any(len(b) > 200 for b in cleaned):
            return jsonify(success=False, error="رقم الوصل لا يتجاوز 200 حرف"), 400
        set_shipping_barcodes(invoice, cleaned)
    else:
        if not shipping_barcode:
            return jsonify({"success": False, "error": "أدخل باركود الشحن"}), 400
        if len(shipping_barcode) > 200:
            return jsonify(success=False, error="رقم الوصل لا يتجاوز 200 حرف"), 400
        set_shipping_barcodes(invoice, [shipping_barcode])

    move_to_shipping = should_move_order_to_shipping_on_barcode_save(invoice)
    if move_to_shipping:
        try:
            from utils.branch_stock_service import BranchStockError
            from utils.shipping_branch_schedule import apply_shipping_branch_schedule

            ensure_stock_for_transition(invoice, target_status="جاري الشحن")
            apply_shipping_branch_schedule(invoice, previous_status=invoice.status)
            invoice.status = "جاري الشحن"
            invoice.shipping_status = "جاري الشحن"
        except (BranchStockError, OrderStockError) as exc:
            db.session.rollback()
            return _insufficient_stock_response(exc, invoice)
    
    db.session.commit()
    try:
        log_mutation(
            "update",
            "orders",
            "invoice",
            invoice.id,
            before,
            snapshot_attrs(invoice, *INVOICE_SNAPSHOT_FIELDS),
            (
                f"حفظ باركود شركة النقل وتحويل الطلب للشحن #{invoice.id}"
                if move_to_shipping
                else f"تحديث باركود شركة النقل للطلب #{invoice.id}"
            ),
        )
    except Exception:
        pass
    
    return jsonify({
        "success": True,
        "message": (
            "تم حفظ باركود شركة النقل وتحويل الطلب إلى جاري الشحن"
            if move_to_shipping
            else "تم حفظ باركود شركة النقل"
        ),
        "status_changed": move_to_shipping,
        "status": invoice.status,
        "shipping_status": invoice.shipping_status,
        "shipping_company_id": invoice.shipping_company_id,
        "shipping_company": shipping_company.name if shipping_company else None,
        "shipping_barcode": shipping_barcodes_display(invoice) or invoice.shipping_barcode,
        "shipping_barcodes": get_shipping_barcodes_list(invoice),
    })

@orders_bp.route("/get-selected-orders", methods=["POST"])
def get_selected_orders():
    data = request.get_json() or {}
    order_ids = data.get("ids", [])
    
    if not order_ids:
        return jsonify({"success": False, "error": "لا توجد طلبات محددة"}), 400
    
    orders_data = []
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
            product_names = [order_item_display_name(item) for item in items]
            
            orders_data.append({
                "id": order.id,
                "customer_phone": order.customer.phone if order.customer else "",
                "customer_name": order.customer_name,
                "products": product_names,
                "total_amount": order.total
            })
    
    return jsonify({
        "success": True,
        "orders": orders_data
    })

@orders_bp.route("/report/<int:report_id>")
def get_report(report_id):
    report = Report.query.get_or_404(report_id)
    return jsonify(report.to_dict())

# =====================================================
# DB Migration: add barcode columns (runs on same DB)
# =====================================================
@orders_bp.route("/migrate-barcode", methods=["POST"])
def migrate_barcode():
    try:
        conn = db.session.connection()
        # Read current columns
        pragma_rows = conn.exec_driver_sql("PRAGMA table_info(invoice)").fetchall()
        existing_cols = {row[1] for row in pragma_rows}

        added = []
        if "barcode" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE invoice ADD COLUMN barcode VARCHAR(100)")
            added.append("barcode")
        if "shipping_barcode" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE invoice ADD COLUMN shipping_barcode VARCHAR(100)")
            added.append("shipping_barcode")

        db.session.commit()
        return jsonify({"success": True, "added": added})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": _db_user_facing_error(e)}), 500

# =====================================================
# Create Shipping Report
# =====================================================
def _create_shipping_report_from_ids(order_ids, shipping_company_id):
    """Create a shipping company statement and return (payload, status_code)."""
    if not order_ids:
        return {"error": "لا توجد طلبات محددة"}, 400

    if not shipping_company_id:
        return {"error": "يجب اختيار شركة نقل"}, 400

    try:
        shipping_company_id = int(shipping_company_id)
        order_ids = [int(oid) for oid in order_ids]
    except (TypeError, ValueError):
        return {"error": "بيانات غير صحيحة"}, 400

    order_ids = list(dict.fromkeys(order_ids))
    shipping_company = ShippingCompany.query.get(shipping_company_id)
    if not shipping_company:
        return {"error": "شركة النقل غير موجودة"}, 404

    orders = Invoice.query.filter(Invoice.id.in_(order_ids)).all()
    if len(orders) != len(order_ids):
        return {"error": "بعض الطلبات غير موجودة"}, 404
    if any(is_stock_locked(order) for order in orders):
        return {"error": LOCKED_ORDER_MESSAGE, "locked": True}, 423

    try:
        for order in orders:
            order.shipping_company_id = int(shipping_company.id)
            prepare_order_for_dispatch(order)
    except OrderStockError as exc:
        db.session.rollback()
        return _insufficient_stock_response(exc)

    orders_data = []
    total_amount = 0

    from utils.agent_report_helpers import order_payment_snapshot

    for order in orders:
        items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
        payment = order_payment_snapshot(order)
        order_info = {
            "id": order.id,
            "customer_name": order.customer.name if order.customer else order.customer_name,
            "customer_phone": order.customer.phone if order.customer else "",
            "customer_city": order.customer.city if order.customer else "",
            "customer_address": order.customer.address if order.customer else "",
            "total": payment["total"],
            "paid_amount": payment["paid_amount"],
            "remaining": payment["remaining"],
            "status": order.status,
            "payment_status": order.payment_status,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
            "items": [
                {
                    "product_name": order_item_display_name(item),
                    "quantity": item.quantity,
                    "price": item.price,
                    "total": item.total,
                }
                for item in items
            ],
        }
        orders_data.append(order_info)
        total_amount += payment["remaining"]

    today = datetime.utcnow().strftime("%Y%m%d")
    last_report = ShippingReport.query.filter(
        ShippingReport.report_number.like(f"KSH-{today}-%")
    ).order_by(ShippingReport.id.desc()).first()

    if last_report:
        last_num = int(last_report.report_number.split("-")[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    report_number = f"KSH-{today}-{new_num:04d}"

    report = ShippingReport(
        report_number=report_number,
        shipping_company_id=shipping_company_id,
        shipping_company_name=shipping_company.name,
        orders_data=json.dumps(orders_data, ensure_ascii=False),
        total_amount=total_amount,
        orders_count=len(orders),
        created_by=session.get("name", "غير محدد"),
    )

    db.session.add(report)
    db.session.commit()

    agent_ids = {order.delivery_agent_id for order in orders if order.delivery_agent_id}
    response_data = {
        "success": True,
        "report_id": report.id,
        "report_number": report.report_number,
        "message": f"تم إنشاء الكشف {report_number} بنجاح",
    }
    if len(agent_ids) == 1:
        response_data["agent_id"] = list(agent_ids)[0]
    return response_data, 200


def _shipping_report_http_result(order_ids, shipping_company_id):
    """Normalize helper output into a Flask response."""
    result = _create_shipping_report_from_ids(order_ids, shipping_company_id)
    # Stock shortage helper already returns a full Flask response tuple.
    if hasattr(result, "status_code") or (
        isinstance(result, tuple) and len(result) == 2 and hasattr(result[0], "status_code")
    ):
        return result
    payload, status = result
    return jsonify(payload), status


@orders_bp.route("/create-shipping-report", methods=["POST"])
def create_shipping_report():
    """إنشاء كشف لشركة نقل معينة"""

    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    data = request.get_json() or {}
    return _shipping_report_http_result(
        data.get("order_ids", []),
        data.get("shipping_company_id"),
    )


@orders_bp.route("/print-shipping-report")
@orders_bp.route("/print_shipping_report")
def print_shipping_report():
    """Compatibility for older UI links that opened a missing print URL."""
    if "user_id" not in session:
        return redirect("/login")

    ids_param = request.args.get("ids", "")
    shipping_company_id = request.args.get("shipping_id")
    try:
        order_ids = [int(part.strip()) for part in ids_param.split(",") if part.strip()]
    except ValueError:
        return redirect("/orders")

    result = _create_shipping_report_from_ids(order_ids, shipping_company_id)
    if hasattr(result, "status_code") or (
        isinstance(result, tuple) and len(result) == 2 and hasattr(result[0], "status_code")
    ):
        # Stock shortage JSON isn't useful for a browser navigation; go back to orders.
        return redirect("/orders")

    payload, status = result
    if status != 200 or not payload.get("report_id"):
        return redirect("/orders")

    return redirect(url_for("delivery.view_report", report_id=payload["report_id"]))

# =====================================================
# Create Agent Report (Internal Function - يمكن استدعاؤها من أماكن مختلفة)
# =====================================================
def create_agent_report_internal(order_ids, agent_id, save_to_db=True):
    """دالة داخلية لإنشاء كشف المندوب"""
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return {"error": "المندوب غير موجود"}

    try:
        order_ids = [int(oid) for oid in order_ids]
    except (TypeError, ValueError):
        return {"error": "أرقام الطلبات غير صحيحة"}

    order_ids = list(dict.fromkeys(order_ids))
    if not order_ids:
        return {"error": "لا توجد طلبات محددة"}

    from utils.agent_report_helpers import (
        find_blocking_executed_agent_reports_for_order,
        find_open_agent_reports_for_order,
        get_report_order_ids,
    )

    duplicate_open: dict[int, list[str]] = {}
    executed_hits: dict[int, list[str]] = {}
    requested_set = set(order_ids)
    exact_existing_report = None
    for oid in order_ids:
        open_reports = find_open_agent_reports_for_order(oid, int(agent_id))
        if open_reports:
            duplicate_open[oid] = [r.report_number for r in open_reports]
            for report in open_reports:
                if set(get_report_order_ids(report)) == requested_set:
                    exact_existing_report = report
        executed_reports = find_blocking_executed_agent_reports_for_order(oid, int(agent_id))
        if executed_reports:
            executed_hits[oid] = [r.report_number for r in executed_reports]

    if exact_existing_report and len(duplicate_open) == len(order_ids):
        return {
            "success": True,
            "already_exists": True,
            "report_id": exact_existing_report.id,
            "report_number": exact_existing_report.report_number,
            "agent_id": int(agent_id),
            "message": f"الكشف موجود سابقاً: {exact_existing_report.report_number}",
        }

    if duplicate_open:
        details = "، ".join(
            f"#{oid} داخل {', '.join(report_numbers)}"
            for oid, report_numbers in sorted(duplicate_open.items())
        )
        return {"error": f"لا يمكن إنشاء كشف مكرر: {details}"}

    if executed_hits:
        details = "، ".join(
            f"#{oid} منفذ في {', '.join(report_numbers)}"
            for oid, report_numbers in sorted(executed_hits.items())
        )
        return {"error": f"لا يمكن إدخال طلب منفذ سابقاً بكشف جديد: {details}"}
    
    # جلب الطلبات
    orders = Invoice.query.filter(Invoice.id.in_(order_ids)).all()
    if len(orders) != len(order_ids):
        return {"error": "بعض الطلبات غير موجودة"}
    if any(is_stock_locked(order) for order in orders):
        return {"error": LOCKED_ORDER_MESSAGE, "locked": True}

    if save_to_db:
        try:
            for order in orders:
                order.delivery_agent_id = int(agent_id)
                prepare_order_for_dispatch(order)
        except OrderStockError as exc:
            db.session.rollback()
            return {
                "error": exc.message,
                "code": "INSUFFICIENT_STOCK",
                "shortages": exc.shortages,
                "order_id": exc.order_id,
                "order_ids": order_ids,
            }
    
    # تحضير بيانات الطلبات
    orders_data = []
    total_amount = 0
    
    from utils.agent_report_helpers import order_payment_snapshot

    for order in orders:
        items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
        payment = order_payment_snapshot(order)
        order_info = {
            "id": order.id,
            "customer_name": order.customer.name if order.customer else order.customer_name,
            "customer_phone": order.customer.phone if order.customer else "",
            "customer_city": order.customer.city if order.customer else "",
            "customer_address": order.customer.address if order.customer else "",
            "total": payment["total"],
            "paid_amount": payment["paid_amount"],
            "remaining": payment["remaining"],
            "status": order.status,
            "payment_status": order.payment_status,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
            "items": [
                {
                    "product_name": order_item_display_name(item),
                    "quantity": item.quantity,
                    "price": item.price,
                    "total": item.total
                }
                for item in items
            ]
        }
        orders_data.append(order_info)
        total_amount += payment["remaining"]
    
    # إنشاء رقم الكشف (تاريخ + رقم متسلسل للمندوب)
    today = datetime.utcnow().strftime("%Y%m%d")
    last_report = ShippingReport.query.filter(
        ShippingReport.report_number.like(f"AGT-{agent_id}-{today}-%")
    ).order_by(ShippingReport.id.desc()).first()
    
    if last_report:
        try:
            last_num = int(last_report.report_number.split("-")[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1
    
    report_number = f"AGT-{agent_id}-{today}-{new_num:04d}"
    
    if save_to_db:
        # تثبيت ربط كل طلب بالمندوب المختار حتى تظهر جميع الكشوف في بوابته.
        for order in orders:
            order.delivery_agent_id = int(agent_id)

        # إنشاء الكشف وحفظه
        report = ShippingReport(
            report_number=report_number,
            shipping_company_id=None,
            shipping_company_name=f"كشف المندوب: {agent.name}",
            orders_data=json.dumps(orders_data, ensure_ascii=False),
            total_amount=total_amount,
            orders_count=len(orders),
            created_by=session.get("name", session.get("agent_name", "غير محدد"))
        )
        
        db.session.add(report)
        db.session.commit()
        
        return {
            "success": True,
            "report_id": report.id,
            "report_number": report.report_number,
            "agent_id": int(agent_id),
            "message": f"تم إنشاء الكشف {report_number} بنجاح"
        }
    else:
        return {
            "success": True,
            "report_number": report_number,
            "agent_id": int(agent_id),
            "orders_data": orders_data,
            "total_amount": total_amount,
            "orders_count": len(orders)
        }

# =====================================================
# Create Agent Report (API Endpoint)
# =====================================================
@orders_bp.route("/create-agent-report", methods=["POST"])
def create_agent_report():
    """إنشاء كشف للمندوب بدون الحاجة لشركة نقل"""
    
    if "user_id" not in session and "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    data = request.get_json() or {}
    order_ids = data.get("order_ids", [])
    agent_id = data.get("agent_id")
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    if not agent_id:
        return jsonify({"error": "يجب تحديد مندوب"}), 400
    
    result = create_agent_report_internal(order_ids, agent_id, save_to_db=True)
    
    if result.get("error"):
        return jsonify(result), 400
    
    return jsonify(result)
