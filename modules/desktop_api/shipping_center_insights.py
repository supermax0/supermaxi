"""Shipping & Logistics Center — missing orders in a manifest and overdue follow-up (read-only).

* Missing: orders the carrier / agent still holds (shipped or delivered, money still due) that the manifest being
  prepared does not contain — the accountant decides whether they belong in it.
* Overdue: parcels out longer than N days, returns not received / inspected, and settlement drafts left open.

Time out with the carrier is measured from FINORA's stock deduction (the moment the order left the shelf),
falling back to the order date for orders that never deducted stock.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import request
from sqlalchemy import func, or_

from models.invoice import Invoice
from models.shipping_report import ShippingReport
from modules.desktop_api.routes import _error, desktop_api_bp
from modules.desktop_api.shipping_center import (
    DEAD,
    PREFIX,
    SETTLEMENT_PREFIX,
    _authorize,
    _agent_ids,
    _company_ids,
    _meta_agent_id,
    _order_row,
    _report_meta,
    _report_summary,
    _rows,
    _tables,
)

HELD_STATUSES = ("جاري الشحن", "تم التوصيل", "استبدال")
MAX_ROWS = 300


def _out_since(order) -> datetime | None:
    return order.stock_deducted_at or order.created_at


def _days_out(order, now: datetime) -> int:
    since = _out_since(order)
    return max((now - since).days, 0) if since else 0


def _held(query):
    """Orders still with the party and still owed: shipped / delivered, not closed, remaining > 0."""
    from services.reports_service import effective_paid_expr

    return query.filter(Invoice.status.in_(HELD_STATUSES), Invoice.status.notin_(DEAD),
                        or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(DEAD)),
                        func.coalesce(Invoice.total, 0) - effective_paid_expr() > 0)


def _open_settlement_orders(exclude_id: int | None = None) -> dict[int, str]:
    found: dict[int, str] = {}
    q = ShippingReport.query.filter(ShippingReport.is_executed.is_(False),
                                    ShippingReport.report_number.like(f"{SETTLEMENT_PREFIX}%"))
    for report in q.all():
        if report.id == exclude_id:
            continue
        for row in _rows(report):
            if row.get("id") is not None:
                found.setdefault(int(row["id"]), report.report_number)
    return found


@desktop_api_bp.get(f"{PREFIX}/manifests/<int:manifest_id>/missing")
def shipping_center_manifest_missing(manifest_id: int):
    denied = _authorize()
    if denied:
        return denied
    report = ShippingReport.query.get(manifest_id)
    if report is None:
        return _error("الكشف غير موجود", 404, "not_found")
    if not str(report.report_number or "").startswith(SETTLEMENT_PREFIX):
        return _error("الطلبات الناقصة تخص كشوف التسوية فقط", 409, "conflict")
    agent_id = _meta_agent_id(_report_meta(report))
    if agent_id:
        base = Invoice.query.filter(Invoice.delivery_agent_id.in_(_agent_ids(agent_id)))
    elif report.shipping_company_id:
        base = Invoice.query.filter(Invoice.shipping_company_id.in_(_company_ids(report.shipping_company_id)))
    else:
        return _ok(rows=[], total=0, amount=0)
    present = {int(r.get("id")) for r in _rows(report) if r.get("id") is not None}
    elsewhere = _open_settlement_orders(exclude_id=report.id)
    now = datetime.utcnow()
    rows = []
    for order in _held(base).order_by(Invoice.created_at.asc(), Invoice.id.asc()).limit(2000).all():
        if order.id in present:
            continue
        row = _order_row(order)
        row.update(days_out=_days_out(order, now), in_manifest=elsewhere.get(order.id, ""))
        rows.append(row)
    rows.sort(key=lambda r: (-r["days_out"], r["id"]))
    return _ok(rows=rows[:MAX_ROWS], total=len(rows), amount=sum(r["remaining"] for r in rows))


@desktop_api_bp.get(f"{PREFIX}/overdue")
def shipping_center_overdue():
    denied = _authorize()
    if denied:
        return denied
    days = max(1, min(request.args.get("days", 7, type=int) or 7, 365))
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)

    since = func.coalesce(Invoice.stock_deducted_at, Invoice.created_at)
    late = (_held(Invoice.query.filter(or_(Invoice.shipping_company_id.isnot(None), Invoice.delivery_agent_id.isnot(None))))
            .filter(Invoice.status == "جاري الشحن", since <= cutoff)
            .order_by(since.asc()).limit(MAX_ROWS).all())
    elsewhere = _open_settlement_orders()
    parcels = []
    for order in late:
        row = _order_row(order)
        row.update(days_out=_days_out(order, now), in_manifest=elsewhere.get(order.id, ""))
        parcels.append(row)

    from models.shipping_center import ShippingReturn

    _tables()
    stale_returns = (ShippingReturn.query.filter(ShippingReturn.state != "closed",
                                                 or_(ShippingReturn.received_at <= cutoff,
                                                     ShippingReturn.reported_at <= cutoff))
                     .order_by(ShippingReturn.reported_at.asc()).limit(MAX_ROWS).all())
    returns = [{"id": r.id, "order_id": r.order_id, "state": r.state, "party_name": r.party_name or "",
                "manifest_number": r.manifest_number or "", "order_amount": int(r.order_amount or 0),
                "days": max((now - (r.received_at or r.reported_at)).days, 0)} for r in stale_returns]

    drafts = (ShippingReport.query.filter(ShippingReport.is_executed.is_(False),
                                          ShippingReport.report_number.like(f"{SETTLEMENT_PREFIX}%"),
                                          ShippingReport.created_at <= cutoff)
              .order_by(ShippingReport.created_at.asc()).limit(MAX_ROWS).all())
    manifests = [{**_report_summary(r), "days": max((now - r.created_at).days, 0) if r.created_at else 0}
                 for r in drafts]
    return _ok(days=days, parcels=parcels, returns=returns, manifests=manifests,
               counts={"parcels": len(parcels), "returns": len(returns), "manifests": len(manifests)},
               amount=sum(p["remaining"] for p in parcels))


def _ok(**data: Any):
    from flask import jsonify

    return jsonify({"ok": True, **data})
