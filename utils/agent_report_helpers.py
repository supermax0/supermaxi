# utils/agent_report_helpers.py
"""Helpers for delivery-agent (AGT) shipping reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from extensions import db
from models.delivery_agent import DeliveryAgent
from models.shipping_report import ShippingReport
from models.system_alert import SystemAlert

STATUS_TO_EN = {"واصل": "Delivered", "ملغي": "Canceled", "مؤجل": "Delayed"}
STATUS_TO_AR = {v: k for k, v in STATUS_TO_EN.items()}
DELIVERED_STATUSES = frozenset({"واصل", "Delivered"})
POSTPONED_STATUSES = frozenset({"مؤجل", "Delayed"})
CANCELED_STATUSES = frozenset({"ملغي", "Canceled", "راجع", "مرتجع", "Returned"})
FINALIZED_AGENT_STATUSES = frozenset({"واصل", "Delivered", "ملغي", "Canceled"})


def is_agent_report(report) -> bool:
    return bool(report and report.report_number and str(report.report_number).startswith("AGT-"))


def extract_agent_id_from_report(report_number: str) -> int | None:
    try:
        parts = str(report_number).split("-")
        if len(parts) >= 2 and parts[0] == "AGT":
            return int(parts[1])
    except (ValueError, TypeError):
        pass
    return None


def _parse_orders_data(report) -> list:
    if not report or not report.orders_data:
        return []
    try:
        data = json.loads(report.orders_data)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _parse_selections(report) -> dict:
    if not report or not report.order_status_selections:
        return {}
    try:
        sel = json.loads(report.order_status_selections)
        return sel if isinstance(sel, dict) else {}
    except Exception:
        return {}


def order_payment_snapshot(order) -> dict[str, int]:
    """الإجمالي والمدفوع الفعلي والباقي المستحق لتحصيل المندوب."""
    from utils.cash_calculations import _effective_paid_amount

    total = int(getattr(order, "total", 0) or 0)
    paid_amount = int(_effective_paid_amount(order) or 0)
    remaining = total - paid_amount
    if remaining < 0:
        remaining = 0
    return {
        "total": total,
        "paid_amount": paid_amount,
        "remaining": remaining,
    }


def row_collectible_amount(row: dict) -> int:
    """المبلغ الواجب تحصيله من صف الكشف: الباقي إن وُجد وإلا الإجمالي."""
    if not isinstance(row, dict):
        return 0
    if "remaining" in row and row.get("remaining") is not None:
        try:
            return max(0, int(row.get("remaining") or 0))
        except (TypeError, ValueError):
            pass
    try:
        return max(0, int(row.get("total", 0) or 0))
    except (TypeError, ValueError):
        return 0


def enrich_orders_data_payment_fields(orders_data: list, *, refresh_live: bool = False) -> list:
    """أملأ/حدّث الحقول المالية من الفاتورة.

    - refresh_live=False: للكشوف القديمة فقط املأ paid_amount/remaining إن كانت مفقودة.
    - refresh_live=True: اسحب الإجمالي والمدفوع والباقي الحي من الفاتورة (قبل التنفيذ).
    """
    if not orders_data:
        return orders_data

    from models.invoice import Invoice

    target_ids: list[int] = []
    for row in orders_data:
        if not isinstance(row, dict):
            continue
        if (
            not refresh_live
            and "remaining" in row
            and row.get("remaining") is not None
            and "paid_amount" in row
        ):
            continue
        oid = row.get("id") or row.get("order_id")
        if oid is None:
            continue
        try:
            target_ids.append(int(oid))
        except (TypeError, ValueError):
            pass

    if not target_ids:
        return orders_data

    invoices = {
        inv.id: inv
        for inv in Invoice.query.filter(Invoice.id.in_(target_ids)).all()
    }
    for row in orders_data:
        if not isinstance(row, dict):
            continue
        if (
            not refresh_live
            and "remaining" in row
            and row.get("remaining") is not None
            and "paid_amount" in row
        ):
            continue
        oid = row.get("id") or row.get("order_id")
        try:
            oid_int = int(oid)
        except (TypeError, ValueError):
            continue
        invoice = invoices.get(oid_int)
        if not invoice:
            total = int(row.get("total", 0) or 0)
            row.setdefault("paid_amount", 0)
            row.setdefault("remaining", total)
            continue
        snap = order_payment_snapshot(invoice)
        if refresh_live:
            row["total"] = snap["total"]
            row["paid_amount"] = snap["paid_amount"]
            row["remaining"] = snap["remaining"]
        else:
            row["total"] = int(row.get("total") or snap["total"])
            row["paid_amount"] = snap["paid_amount"]
            row["remaining"] = snap["remaining"]
    return orders_data


def enrich_orders_data_display_fields(
    orders_data: list,
    *,
    refresh_live: bool = True,
    refresh_live_amounts: bool = False,
) -> list:
    """أملأ العنوان والحالة الحالية من الفاتورة الحية لعرض الكشف."""
    orders_data = enrich_orders_data_payment_fields(
        orders_data, refresh_live=refresh_live_amounts
    )
    if not orders_data or not refresh_live:
        # حتى بدون تحديث حي: وحّد مفتاح العنوان للعرض
        for row in orders_data or []:
            if not isinstance(row, dict):
                continue
            address = (row.get("customer_address") or row.get("address") or "").strip()
            if address:
                row["customer_address"] = address
                row.setdefault("address", address)
        return orders_data

    from models.invoice import Invoice

    order_ids: list[int] = []
    for row in orders_data:
        if not isinstance(row, dict):
            continue
        oid = row.get("id") or row.get("order_id")
        if oid is None:
            continue
        try:
            order_ids.append(int(oid))
        except (TypeError, ValueError):
            pass

    if not order_ids:
        return orders_data

    invoices = {
        inv.id: inv
        for inv in Invoice.query.filter(Invoice.id.in_(order_ids)).all()
    }
    for row in orders_data:
        if not isinstance(row, dict):
            continue
        oid = row.get("id") or row.get("order_id")
        try:
            oid_int = int(oid)
        except (TypeError, ValueError):
            continue
        invoice = invoices.get(oid_int)
        if not invoice:
            address = (row.get("customer_address") or row.get("address") or "").strip()
            if address:
                row["customer_address"] = address
                row.setdefault("address", address)
            continue

        # الحالة الأصلية الحالية من الفاتورة (وليس لقطة الإنشاء فقط)
        if invoice.status:
            row["status"] = invoice.status
        if invoice.payment_status:
            row["payment_status"] = invoice.payment_status
        agent_note = (getattr(invoice, "agent_note", None) or "").strip()
        if agent_note:
            row["agent_note"] = agent_note

        customer = invoice.customer
        if customer:
            address = (customer.address or "").strip()
            if address:
                row["customer_address"] = address
                row["address"] = address
            city = (customer.city or "").strip()
            if city:
                row["customer_city"] = city
            if customer.phone:
                row["customer_phone"] = customer.phone
            if customer.name:
                row["customer_name"] = customer.name
        else:
            address = (row.get("customer_address") or row.get("address") or "").strip()
            if address:
                row["customer_address"] = address
                row.setdefault("address", address)
    return orders_data


def _safe_item_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_report_item(raw: Any) -> dict | None:
    """وحّد صف منتج من لقطة الكشف أو من صيغة الطباعة القديمة."""
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            return None
        return {"product_name": name, "name": name, "quantity": 1, "price": 0, "total": 0}
    if not isinstance(raw, dict):
        return None
    name = str(
        raw.get("product_name") or raw.get("name") or raw.get("product") or ""
    ).strip()
    if not name:
        return None
    qty_raw = raw.get("quantity") if raw.get("quantity") is not None else raw.get("qty")
    qty = _safe_item_int(qty_raw, 1)
    if qty <= 0:
        qty = 1
    price = _safe_item_int(raw.get("price"), 0)
    total = _safe_item_int(raw.get("total"), price * qty)
    return {
        "product_name": name,
        "name": name,
        "quantity": qty,
        "price": price,
        "total": total,
    }


def _items_from_report_row(row: dict) -> list[dict]:
    raw_list = row.get("items")
    if not isinstance(raw_list, list) or not raw_list:
        raw_list = row.get("products")
    if not isinstance(raw_list, list):
        return []
    items = []
    for raw in raw_list:
        item = normalize_report_item(raw)
        if item:
            items.append(item)
    return items


def _live_items_for_invoice(invoice) -> list[dict]:
    from models.order_item import OrderItem
    from utils.order_shipping import is_shipping_item, order_item_display_name

    items = []
    for order_item in OrderItem.query.filter_by(invoice_id=invoice.id).all():
        if is_shipping_item(order_item):
            continue
        name = order_item_display_name(order_item)
        qty = _safe_item_int(getattr(order_item, "quantity", 1), 1)
        price = _safe_item_int(getattr(order_item, "price", 0), 0)
        total = _safe_item_int(getattr(order_item, "total", price * qty), price * qty)
        items.append({
            "product_name": name,
            "name": name,
            "quantity": max(qty, 1),
            "price": price,
            "total": total,
        })
    return items


def enrich_orders_data_items(orders_data: list, *, refresh_live: bool = True) -> list:
    """أضف قائمة منتجات موحّدة لكل طلب، مع تعبئة حيّة إذا كانت اللقطة فارغة."""
    if not orders_data:
        return orders_data or []

    missing_ids: list[int] = []
    for row in orders_data:
        if not isinstance(row, dict):
            continue
        items = _items_from_report_row(row)
        row["items"] = items
        row["products"] = items
        if items or not refresh_live:
            continue
        oid = row.get("id") or row.get("order_id")
        try:
            missing_ids.append(int(oid))
        except (TypeError, ValueError):
            pass

    if not refresh_live or not missing_ids:
        return orders_data

    from models.invoice import Invoice

    invoices = {
        inv.id: inv
        for inv in Invoice.query.filter(Invoice.id.in_(missing_ids)).all()
    }
    for row in orders_data:
        if not isinstance(row, dict) or row.get("items"):
            continue
        oid = row.get("id") or row.get("order_id")
        try:
            invoice = invoices.get(int(oid))
        except (TypeError, ValueError):
            continue
        if not invoice:
            continue
        items = _live_items_for_invoice(invoice)
        row["items"] = items
        row["products"] = items
    return orders_data


def compute_report_items_totals(orders_data: list) -> dict[str, int]:
    lines = 0
    qty = 0
    for row in orders_data or []:
        if not isinstance(row, dict):
            continue
        for item in row.get("items") or []:
            lines += 1
            qty += _safe_item_int(item.get("quantity"), 0)
    return {"lines": lines, "qty": qty}


def compute_report_delivered_amount(report) -> int:
    """مجموع الباقي (أو الإجمالي للكشوف القديمة) للطلبات المحددة «واصل» فقط."""
    return compute_report_status_breakdown(report)["delivered"]["amount"]


def compute_report_status_breakdown(report) -> dict[str, dict[str, int]]:
    """تفصيل الكشف: عدد ومبلغ كل حالة (واصل / راجع / مؤجل / بانتظار)."""
    selections = _parse_selections(report)
    rows = _parse_orders_data(report)
    if report and not getattr(report, "is_executed", False):
        rows = enrich_orders_data_payment_fields(rows, refresh_live=True)

    breakdown = {
        "delivered": {"count": 0, "amount": 0},
        "canceled": {"count": 0, "amount": 0},
        "postponed": {"count": 0, "amount": 0},
        "pending": {"count": 0, "amount": 0},
    }
    for row in rows:
        order_id = row.get("id") or row.get("order_id")
        if order_id is None:
            continue
        amount = row_collectible_amount(row)
        status = selections.get(str(order_id))
        if status in DELIVERED_STATUSES:
            bucket = "delivered"
        elif status in CANCELED_STATUSES:
            bucket = "canceled"
        elif status in POSTPONED_STATUSES:
            bucket = "postponed"
        else:
            bucket = "pending"
        breakdown[bucket]["count"] += 1
        breakdown[bucket]["amount"] += amount
    return breakdown


def compute_report_orders_amount(report) -> int:
    """مجموع المبالغ القابلة للتحصيل لكل طلبات الكشف (حي قبل التنفيذ)."""
    rows = _parse_orders_data(report)
    if report and not getattr(report, "is_executed", False):
        rows = enrich_orders_data_payment_fields(rows, refresh_live=True)
    return sum(row_collectible_amount(row) for row in rows)


def sync_open_report_payment_amounts(report) -> int:
    """حدّث لقطة المبالغ في الكشف المفتوح من الفواتير الحية واحفظها."""
    if not report or getattr(report, "is_executed", False):
        return int(getattr(report, "total_amount", 0) or 0)

    rows = enrich_orders_data_payment_fields(_parse_orders_data(report), refresh_live=True)
    report.orders_data = json.dumps(rows, ensure_ascii=False)
    total = sum(row_collectible_amount(row) for row in rows)
    report.total_amount = total
    return total


def get_report_order_ids(report) -> list[int]:
    ids = []
    for row in _parse_orders_data(report):
        oid = row.get("id") or row.get("order_id")
        if oid is not None:
            try:
                ids.append(int(oid))
            except (TypeError, ValueError):
                pass
    return ids


def get_report_progress(report) -> dict[str, Any]:
    total = int(report.orders_count or 0) if report else 0
    order_ids = get_report_order_ids(report) if report else []
    if not total:
        total = len(order_ids)
    selections = _parse_selections(report) if report else {}
    applied = sum(1 for oid in order_ids if str(oid) in selections)
    all_complete = total > 0 and applied >= total
    ready_for_execution = bool(report and all_complete and not report.is_executed)
    return {
        "applied": applied,
        "total": total,
        "all_complete": all_complete,
        "ready_for_execution": ready_for_execution,
        "in_progress": applied > 0 and not all_complete,
    }


def find_open_agent_report_for_order(order_id: int):
    reports = find_open_agent_reports_for_order(order_id)
    return reports[0] if reports else None


def find_open_agent_reports_for_order(order_id: int, agent_id: int | None = None) -> list[ShippingReport]:
    query = (
        ShippingReport.query.filter(
            ShippingReport.is_executed.is_(False),
            ShippingReport.report_number.like("AGT-%"),
        )
        .order_by(ShippingReport.created_at.desc())
    )
    if agent_id:
        query = query.filter(ShippingReport.report_number.like(f"AGT-{int(agent_id)}-%"))
    reports = query.all()
    oid = int(order_id)
    return [report for report in reports if oid in get_report_order_ids(report)]


def find_executed_agent_reports_for_order(order_id: int, agent_id: int | None = None) -> list[ShippingReport]:
    query = (
        ShippingReport.query.filter(
            ShippingReport.is_executed.is_(True),
            ShippingReport.report_number.like("AGT-%"),
        )
        .order_by(ShippingReport.created_at.desc())
    )
    if agent_id:
        query = query.filter(ShippingReport.report_number.like(f"AGT-{int(agent_id)}-%"))
    oid = int(order_id)
    return [report for report in query.all() if oid in get_report_order_ids(report)]


def is_order_finalized_in_executed_report(report, order_id: int) -> bool:
    """هل الطلب واصل أو ملغي في كشف منفّذ؟ (المؤجل يُسمح بإعادته لكشف جديد)"""
    if not report or not report.is_executed:
        return False
    oid = int(order_id)
    if oid not in get_report_order_ids(report):
        return False

    status = _parse_selections(report).get(str(oid))
    if status in POSTPONED_STATUSES:
        return False
    if status in FINALIZED_AGENT_STATUSES:
        return True

    from models.invoice import Invoice
    from utils.order_status import is_canceled, is_completed

    order = Invoice.query.get(oid)
    if not order:
        return True
    return is_canceled(order.status, order.payment_status) or is_completed(
        order.status, order.payment_status
    )


def find_blocking_executed_agent_reports_for_order(
    order_id: int, agent_id: int | None = None
) -> list[ShippingReport]:
    """كشوف منفّذة يمنع إعادة الطلب منها (واصل/ملغي فقط — لا يشمل المؤجل)."""
    return [
        report
        for report in find_executed_agent_reports_for_order(order_id, agent_id)
        if is_order_finalized_in_executed_report(report, order_id)
    ]


def get_order_applied_status(order_id: int) -> str | None:
    report = find_open_agent_report_for_order(order_id)
    if not report:
        return None
    raw = _parse_selections(report).get(str(order_id))
    if not raw:
        return None
    return STATUS_TO_AR.get(raw, raw)


def save_selection_to_report(report, order_id: int, status: str) -> dict[str, Any]:
    selections = _parse_selections(report)
    previous = selections.get(str(order_id))
    previous = STATUS_TO_EN.get(previous, previous)
    selections[str(order_id)] = STATUS_TO_EN.get(status, status)
    report.order_status_selections = json.dumps(selections, ensure_ascii=False)
    sync_open_report_payment_amounts(report)
    rows = _parse_orders_data(report)
    for row in rows:
        if str(row.get("id") or row.get("order_id")) == str(order_id) and previous != selections[str(order_id)]:
            row["agent_status_updated_at"] = datetime.now(timezone.utc).isoformat()
    report.orders_data = json.dumps(rows, ensure_ascii=False)
    return get_report_progress(report)


def list_pending_agent_reports():
    return (
        ShippingReport.query.filter(
            ShippingReport.is_executed.is_(False),
            ShippingReport.report_number.like("AGT-%"),
        )
        .order_by(ShippingReport.created_at.desc())
        .all()
    )


def get_agent_name_for_report(report) -> str:
    agent_id = extract_agent_id_from_report(report.report_number)
    if agent_id:
        agent = DeliveryAgent.query.get(agent_id)
        if agent:
            return agent.name
    name = report.shipping_company_name or ""
    prefix = "كشف المندوب: "
    if name.startswith(prefix):
        return name[len(prefix) :].strip()
    return name or "—"


def serialize_pending_report(report) -> dict[str, Any]:
    progress = get_report_progress(report)
    try:
        selected_statuses = json.loads(report.order_status_selections or "{}")
    except Exception:
        selected_statuses = {}
    has_stock_return = any(
        status in {"ملغي", "Canceled", "مؤجل", "Delayed", "راجع", "مرتجع"}
        for status in (selected_statuses.values() if isinstance(selected_statuses, dict) else [])
    )
    status_label = "بانتظار المندوب"
    if report.is_executed:
        status_label = "منفّذ"
    elif progress["ready_for_execution"]:
        status_label = "جاهز للتنفيذ"
    elif progress["in_progress"]:
        status_label = "قيد التطبيق"
    employee_name = (getattr(report, "created_by", None) or "").strip() or None
    breakdown = compute_report_status_breakdown(report)
    delivered_amount = breakdown["delivered"]["amount"]
    total_collectible = (
        delivered_amount
        + breakdown["canceled"]["amount"]
        + breakdown["postponed"]["amount"]
        + breakdown["pending"]["amount"]
    )
    return {
        "id": report.id,
        "report_number": report.report_number,
        "agent_name": get_agent_name_for_report(report),
        "agent_id": extract_agent_id_from_report(report.report_number),
        "employee_name": employee_name,
        "created_by": employee_name,
        "orders_count": progress["total"],
        "applied_count": progress["applied"],
        "progress_label": f"{progress['applied']}/{progress['total']}",
        "status_label": status_label,
        "ready_for_execution": progress["ready_for_execution"],
        "all_complete": progress["all_complete"],
        "created_at": report.created_at.strftime("%Y-%m-%d %H:%M") if report.created_at else "",
        "total_amount": (
            delivered_amount
            if breakdown["delivered"]["count"] > 0 or progress["applied"] > 0
            else (
                compute_report_orders_amount(report)
                if not report.is_executed
                else int(report.total_amount or 0)
            )
        ),
        "delivered_count": breakdown["delivered"]["count"],
        "canceled_count": breakdown["canceled"]["count"],
        "postponed_count": breakdown["postponed"]["count"],
        "pending_selection_count": breakdown["pending"]["count"],
        "delivered_amount": breakdown["delivered"]["amount"],
        "canceled_amount": breakdown["canceled"]["amount"],
        "postponed_amount": breakdown["postponed"]["amount"],
        "pending_amount": breakdown["pending"]["amount"],
        "total_collectible": total_collectible,
        "has_stock_return": has_stock_return,
    }


def notify_agent_report_ready(report, agent_name: str) -> bool:
    progress = get_report_progress(report)
    if not progress["ready_for_execution"]:
        return False
    existing = SystemAlert.query.filter_by(
        alert_type="agent_report_ready",
        related_type="shipping_report",
        related_id=report.id,
        is_dismissed=False,
    ).first()
    if existing:
        return False
    db.session.add(
        SystemAlert(
            alert_type="agent_report_ready",
            title=f"كشف المندوب {report.report_number} جاهز",
            message=f"المندوب {agent_name} طبّق كل {progress['total']} طلب — بانتظار التنفيذ",
            priority="high",
            related_type="shipping_report",
            related_id=report.id,
        )
    )
    return True


def get_pending_agent_reports_summary() -> dict[str, Any]:
    reports = list_pending_agent_reports()
    serialized = [serialize_pending_report(r) for r in reports]
    ready = [r for r in serialized if r["ready_for_execution"]]
    in_progress = [r for r in serialized if r["applied_count"] > 0 and not r["all_complete"]]
    return {
        "ready_count": len(ready),
        "in_progress_count": len(in_progress),
        "pending_count": len(serialized),
        "reports": serialized,
    }


def dismiss_shipping_report_alerts(report_id: int) -> None:
    SystemAlert.query.filter_by(
        related_type="shipping_report",
        related_id=int(report_id),
        is_dismissed=False,
    ).update({"is_dismissed": True}, synchronize_session=False)


def merge_open_agent_reports(
    target_report: ShippingReport,
    source_reports: list[ShippingReport],
) -> dict[str, Any]:
    """ادمج كشوف مندوب مفتوحة في كشف هدف واحد (نفس المندوب فقط)."""
    if not target_report or not is_agent_report(target_report):
        raise ValueError("كشف الهدف غير صالح")
    if target_report.is_executed:
        raise ValueError("لا يمكن الدمج في كشف منفّذ")

    target_agent_id = extract_agent_id_from_report(target_report.report_number)
    if not target_agent_id:
        raise ValueError("تعذر تحديد مندوب كشف الهدف")

    sources: list[ShippingReport] = []
    seen_ids = {int(target_report.id)}
    for src in source_reports or []:
        if not src or int(src.id) in seen_ids:
            continue
        if not is_agent_report(src):
            raise ValueError(f"الكشف {src.report_number} ليس كشف مندوب")
        if src.is_executed:
            raise ValueError(f"لا يمكن دمج الكشف المنفّذ {src.report_number}")
        src_agent_id = extract_agent_id_from_report(src.report_number)
        if src_agent_id != target_agent_id:
            raise ValueError("يمكن دمج كشوف نفس المندوب فقط")
        sources.append(src)
        seen_ids.add(int(src.id))

    if not sources:
        raise ValueError("اختر كشفاً واحداً على الأقل للدمج")

    target_orders = _parse_orders_data(target_report)
    target_selections = _parse_selections(target_report)
    existing_ids = set(get_report_order_ids(target_report))
    moved_orders = 0
    merged_from: list[str] = []

    for src in sources:
        src_orders = _parse_orders_data(src)
        src_selections = _parse_selections(src)
        for row in src_orders:
            if not isinstance(row, dict):
                continue
            oid = row.get("id") or row.get("order_id")
            try:
                oid_int = int(oid)
            except (TypeError, ValueError):
                continue
            if oid_int in existing_ids:
                # إن وُجدت حالة في المصدر فقط انقلها للهدف إن كان الهدف بلا حالة
                src_status = src_selections.get(str(oid_int))
                if src_status and str(oid_int) not in target_selections:
                    target_selections[str(oid_int)] = src_status
                continue
            target_orders.append(row)
            existing_ids.add(oid_int)
            moved_orders += 1
            src_status = src_selections.get(str(oid_int))
            if src_status:
                target_selections[str(oid_int)] = src_status
        merged_from.append(src.report_number)

    target_report.orders_data = json.dumps(target_orders, ensure_ascii=False)
    target_report.order_status_selections = json.dumps(target_selections, ensure_ascii=False)
    target_report.orders_count = len(target_orders)
    sync_open_report_payment_amounts(target_report)

    note_bits = [n for n in [(target_report.notes or "").strip()] if n]
    note_bits.append("دُمج من: " + ", ".join(merged_from))
    target_report.notes = " | ".join(note_bits)

    for src in sources:
        dismiss_shipping_report_alerts(src.id)
        db.session.delete(src)

    # أعد تقييم تنبيه الجاهزية على الهدف بعد الدمج
    dismiss_shipping_report_alerts(target_report.id)
    agent_name = get_agent_name_for_report(target_report)
    notify_agent_report_ready(target_report, agent_name)

    return {
        "target_report_id": target_report.id,
        "target_report_number": target_report.report_number,
        "merged_from": merged_from,
        "moved_orders": moved_orders,
        "orders_count": int(target_report.orders_count or 0),
        "total_amount": int(target_report.total_amount or 0),
        "progress": get_report_progress(target_report),
    }
