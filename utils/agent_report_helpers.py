# utils/agent_report_helpers.py
"""Helpers for delivery-agent (AGT) shipping reports."""

from __future__ import annotations

import json
from typing import Any

from extensions import db
from models.delivery_agent import DeliveryAgent
from models.shipping_report import ShippingReport
from models.system_alert import SystemAlert

STATUS_TO_EN = {"واصل": "Delivered", "ملغي": "Canceled", "مؤجل": "Delayed"}
STATUS_TO_AR = {v: k for k, v in STATUS_TO_EN.items()}
DELIVERED_STATUSES = frozenset({"واصل", "Delivered"})
POSTPONED_STATUSES = frozenset({"مؤجل", "Delayed"})
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


def compute_report_delivered_amount(report) -> int:
    """مجموع مبالغ الطلبات المحددة «واصل» فقط (يستثني المؤجل والملغي)."""
    total = 0
    selections = _parse_selections(report)
    for row in _parse_orders_data(report):
        order_id = row.get("id") or row.get("order_id")
        if order_id is None:
            continue
        if selections.get(str(order_id)) not in DELIVERED_STATUSES:
            continue
        total += int(row.get("total", 0) or 0)
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
    selections[str(order_id)] = STATUS_TO_EN.get(status, status)
    report.order_status_selections = json.dumps(selections, ensure_ascii=False)
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
    status_label = "بانتظار المندوب"
    if report.is_executed:
        status_label = "منفّذ"
    elif progress["ready_for_execution"]:
        status_label = "جاهز للتنفيذ"
    elif progress["in_progress"]:
        status_label = "قيد التطبيق"
    return {
        "id": report.id,
        "report_number": report.report_number,
        "agent_name": get_agent_name_for_report(report),
        "agent_id": extract_agent_id_from_report(report.report_number),
        "orders_count": progress["total"],
        "applied_count": progress["applied"],
        "progress_label": f"{progress['applied']}/{progress['total']}",
        "status_label": status_label,
        "ready_for_execution": progress["ready_for_execution"],
        "all_complete": progress["all_complete"],
        "created_at": report.created_at.strftime("%Y-%m-%d %H:%M") if report.created_at else "",
        "total_amount": int(report.total_amount or 0),
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
