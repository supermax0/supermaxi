"""Shipping & Logistics Center (FINORA Management Desktop) — JSON over FINORA's own shipping engine.

Nothing here re-implements accounting:
- handover manifests reuse ``routes.orders._create_shipping_report_from_ids`` (dispatch + KSH manifest);
- settlement manifests are ``ShippingReport`` rows (``STL-…``) whose per-order selections are executed by
  ``utils.shipping_report_execute.execute_shipping_report`` — the same function the web and portals use
  (status, payment ledger, treasury, courier fee per order, stock return);
- order lookup accepts the FINORA order number, the invoice barcode or the carrier waybill(s).

Approval is admin-only (as everywhere in FINORA) and is refused while the manifest has blocking issues,
rows marked «مشكلة», or when the money actually received differs from the expected net. Differences are
never auto-corrected.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from flask import g, request, session
from sqlalchemy import case, func, or_

from extensions import db
from models.delivery_agent import DeliveryAgent
from models.invoice import Invoice
from models.shipping import ShippingCompany
from models.shipping_payment import ShippingPayment
from models.shipping_report import ShippingReport
from modules.desktop_api.routes import _error, desktop_api_bp
from utils.branch_context import init_branch_context
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES, is_canceled, is_returned
from utils.permission_checks import employee_can, get_current_employee

PREFIX = "/shipping-center"
SETTLEMENT_PREFIX = "STL-"
STATUS_DELIVERED, STATUS_RETURNED, STATUS_POSTPONED, STATUS_PROBLEM = "واصل", "راجع", "مؤجل", "مشكلة"
ROW_STATUSES = (STATUS_DELIVERED, STATUS_RETURNED, STATUS_POSTPONED, STATUS_PROBLEM)
DEAD = list(CANCELED_STATUSES | RETURN_STATUSES)
MAX_CODES = 500


def _ok(**data: Any):
    from flask import jsonify

    return jsonify({"ok": True, **data})


def _authorize(permission: str | tuple[str, ...] = "can_see_shipping"):
    if not session.get("user_id") or not session.get("tenant_slug"):
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    if str(getattr(g, "tenant", "")) != session["tenant_slug"]:
        return _error("تعذر تحديد الشركة", 403, "tenant_required")
    employee = get_current_employee()
    if not employee or not employee.is_active:
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    permissions = (permission,) if isinstance(permission, str) else permission
    if not any(employee_can(employee, p) for p in permissions):
        return _error("ليست لديك صلاحية لهذا الإجراء في مركز الشحن", 403, "forbidden")
    if not getattr(g, "branch_scope_ready", False):
        init_branch_context()
    return None


def _is_admin() -> bool:
    employee = get_current_employee()
    return bool(employee and employee.role == "admin")


# ───────────────────────────── shared helpers (FINORA's own rules) ─────────────────────────────


def _carrier_helpers():
    from routes.shipping import _merged_shipping_company_ids, _unique_shipping_companies, remaining_amount

    return _merged_shipping_company_ids, _unique_shipping_companies, remaining_amount


def _fee(order) -> int:
    from utils.order_shipping import get_shipping_fee_from_invoice

    try:
        return max(int(get_shipping_fee_from_invoice(order) or 0), 0)
    except Exception:
        return 0


def _fee_due(order, fee: int) -> int:
    """The courier fee is withdrawn once per order (first settlement, even a partial one) — never again."""
    if fee <= 0:
        return 0
    from utils.delivery_expense_service import _find_delivery_withdraw_tx

    try:
        return 0 if _find_delivery_withdraw_tx(int(order.id)) is not None else fee
    except Exception:
        return fee


def _order_row(order) -> dict[str, Any]:
    """Same fields as FINORA's manifest rows (routes/orders.py) plus carrier / agent / waybill / fee."""
    from utils.agent_report_helpers import order_payment_snapshot
    from utils.shipping_barcodes import get_shipping_barcodes_list

    payment = order_payment_snapshot(order)
    customer = order.customer
    fee = _fee(order)
    return {
        "id": int(order.id),
        "customer_name": (customer.name if customer else None) or order.customer_name or "",
        "customer_phone": (customer.phone if customer else "") or "",
        "customer_city": (customer.city if customer else "") or "",
        "customer_address": (customer.address if customer else "") or "",
        "total": payment["total"],
        "paid_amount": payment["paid_amount"],
        "remaining": payment["remaining"],
        "status": order.status or "",
        "shipping_status": getattr(order, "shipping_status", None) or "",
        "payment_status": order.payment_status or "",
        "shipping_company_id": order.shipping_company_id,
        "shipping_company": order.shipping_company.name if order.shipping_company else "",
        "delivery_agent_id": order.delivery_agent_id,
        "delivery_agent": order.delivery_agent.name if order.delivery_agent else "",
        "waybills": get_shipping_barcodes_list(order),
        "fee": fee,
        "fee_due": _fee_due(order, fee),
        "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
    }


def find_order_by_code(code: str):
    """FINORA order number, invoice barcode or carrier waybill (single or multi-piece)."""
    from utils.barcode_normalization import normalize_barcode
    from utils.shipping_barcodes import shipping_barcodes_match_code

    raw = str(code or "").strip().lstrip("#")
    if not raw:
        return None
    normalized = normalize_barcode(raw) or raw
    invoice = Invoice.query.filter(
        or_(Invoice.barcode == raw, Invoice.shipping_barcode == raw,
            Invoice.barcode == normalized, Invoice.shipping_barcode == normalized)
    ).first()
    if invoice is None and raw.isdigit():
        invoice = Invoice.query.get(int(raw))
    if invoice is None:
        for candidate in (
            Invoice.query.filter(Invoice.shipping_barcodes_json.ilike(f'%"{raw}"%'))
            .order_by(Invoice.id.desc()).limit(50).all()
        ):
            if shipping_barcodes_match_code(candidate, raw):
                return candidate
    return invoice


def _tables() -> None:
    from models.shipping_center import ensure_shipping_center_tables

    ensure_shipping_center_tables()


def _return_fee(company_id: int | None) -> int:
    if not company_id:
        return 0
    from models.shipping_center import ShippingCarrierSetting

    _tables()
    ids = _company_ids(company_id) or [company_id]
    row = ShippingCarrierSetting.query.filter(ShippingCarrierSetting.carrier_id.in_(ids)).first()
    return max(int(row.return_fee or 0), 0) if row else 0


def _pending_return(order_id: int) -> bool:
    from models.shipping_center import ShippingReturn

    _tables()
    return ShippingReturn.query.filter(ShippingReturn.order_id == order_id,
                                       ShippingReturn.state != "closed").first() is not None


def _agent_key(agent) -> str:
    """Same person = same name and phone (FINORA may hold one copy per branch); carriers merge by name likewise."""
    from utils.agent_manifest_sync import agent_key
    return agent_key(agent)


def _agent_groups() -> list[tuple[Any, list[int]]]:
    """[(representative, all ids)] — the representative is the record with the portal login, then active, then oldest."""
    groups: dict[str, list] = {}
    for agent in DeliveryAgent.query.order_by(DeliveryAgent.id).all():
        groups.setdefault(_agent_key(agent), []).append(agent)
    result = []
    for members in groups.values():
        rep = sorted(members, key=lambda a: (not a.username, not a.is_active, a.id))[0]
        result.append((rep, [a.id for a in members]))
    return result


def _agent_ids(agent_id: int | None) -> list[int]:
    if not agent_id:
        return []
    agent = DeliveryAgent.query.get(int(agent_id))
    if agent is None:
        return [int(agent_id)]
    key = _agent_key(agent)
    return [a.id for a in DeliveryAgent.query.order_by(DeliveryAgent.id).all() if _agent_key(a) == key]


def _portal_reports_filter(agent_ids: list[int]):
    return or_(*[ShippingReport.report_number.like(f"AGT-{int(i)}-%") for i in agent_ids]) if agent_ids else False


def _agent_custody(agent_id: int) -> dict[str, int]:
    from modules.desktop_api.shipping_center_finance import _agent_custody as custody

    return custody(agent_id)


def _codes_from_request() -> list[str]:
    data = request.get_json(silent=True) or {}
    raw = data.get("codes") or []
    if isinstance(raw, str):
        raw = raw.replace(",", "\n").replace("\t", "\n").split("\n")
    codes = [str(c).strip() for c in raw if str(c).strip()]
    return codes[:MAX_CODES]


def _company_ids(company_id: int) -> list[int]:
    merged, _, _ = _carrier_helpers()
    company = ShippingCompany.query.get(company_id)
    return merged(company) if company else []


def _remaining_sql():
    from services.reports_service import effective_paid_expr

    difference = func.coalesce(Invoice.total, 0) - effective_paid_expr()
    return func.sum(case((difference > 0, difference), else_=0))  # portable (tenant DBs are SQLite)


def _bucket_stats(base) -> dict[str, Any]:
    """Counts / amounts per operational bucket over an Invoice query (already scoped to a carrier or agent)."""
    alive = base.filter(Invoice.status.notin_(DEAD), or_(Invoice.payment_status.is_(None),
                                                         Invoice.payment_status.notin_(DEAD)))
    remaining = _remaining_sql()

    def agg(q):
        count, amount = q.with_entities(func.count(Invoice.id), remaining).one()
        return {"count": int(count or 0), "amount": int(amount or 0)}

    return {
        "total": {"count": base.count(), "amount": 0},
        "transit": agg(alive.filter(Invoice.status == "جاري الشحن")),
        "delivered_unsettled": agg(alive.filter(Invoice.status.in_(("تم التوصيل", "استبدال")),
                                                or_(Invoice.payment_status.is_(None), Invoice.payment_status != "مسدد"))),
        "due": agg(alive),
        "returned": {"count": base.filter(or_(Invoice.status.in_(list(RETURN_STATUSES)),
                                              Invoice.payment_status.in_(list(RETURN_STATUSES)))).count(), "amount": 0},
    }


def _report_kind(report) -> str:
    number = str(report.report_number or "")
    if number.startswith(SETTLEMENT_PREFIX):
        return "settlement"
    if number.startswith("AGT-"):
        return "agent"
    return "handover"


def _report_summary(report) -> dict[str, Any]:
    from utils.agent_report_helpers import compute_report_status_breakdown, get_agent_name_for_report, compute_report_orders_amount

    try:
        breakdown = compute_report_status_breakdown(report)
    except Exception:
        breakdown = {}
    meta = _report_meta(report)
    agent_id = _meta_agent_id(meta)
    return {
        "id": int(report.id),
        "number": report.report_number,
        "kind": _report_kind(report),
        "carrier_id": None if agent_id else report.shipping_company_id,
        "carrier": "" if agent_id else (report.shipping_company_name or ""),
        "agent_id": agent_id,
        "agent": ((report.shipping_company_name or "") if report.is_executed and _report_kind(report) == "agent" else get_agent_name_for_report(report) if _report_kind(report) == "agent"
                  else str(meta.get("agent_name") or "") if agent_id else ""),
        "settlement_state": _settlement_state(report, meta),
        "orders_count": int(report.orders_count or 0) if report.is_executed else len(_rows(report)),
        "total_amount": int(report.total_amount or 0) if report.is_executed else compute_report_orders_amount(report),
        "executed": bool(report.is_executed),
        "created_at": report.created_at.strftime("%Y-%m-%d %H:%M") if report.created_at else "",
        "created_by": report.created_by or "",
        "reference": meta.get("reference", ""),
        "breakdown": breakdown,
    }


def _meta_agent_id(meta: dict[str, Any]) -> int | None:
    try:
        value = int(meta.get("agent_id") or 0)
    except (TypeError, ValueError):
        return None
    return value or None


def _settlement_state(report, meta: dict[str, Any]) -> str:
    """draft → approved; approved settlements are «full» or «partial» (money still owed after the receipt)."""
    if not report.is_executed:
        return "draft"
    ledger = meta.get("ledger") if isinstance(meta.get("ledger"), dict) else None
    if ledger and int(ledger.get("outstanding") or 0) > 0:
        return "partial"
    return "full" if _report_kind(report) == "settlement" else "executed"


def _report_meta(report) -> dict[str, Any]:
    try:
        meta = json.loads(report.notes or "{}")
        return meta if isinstance(meta, dict) else {"text": str(report.notes)}
    except (TypeError, ValueError):
        return {"text": str(report.notes or "")}


def _selections(report) -> dict[str, str]:
    try:
        data = json.loads(report.order_status_selections or "{}")
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _rows(report) -> list[dict]:
    from utils.agent_report_helpers import _parse_orders_data
    return _parse_orders_data(report)


# ───────────────────────────── reads ─────────────────────────────


@desktop_api_bp.get(f"{PREFIX}/meta")
def shipping_center_meta():
    denied = _authorize()
    if denied:
        return denied
    from utils.treasury_helpers import treasury_choices_for_form

    _, unique, _ = _carrier_helpers()
    carriers = unique(ShippingCompany.query.order_by(ShippingCompany.name, ShippingCompany.id).all())
    agents = sorted((rep for rep, _ in _agent_groups() if rep.is_active), key=lambda a: a.name or "")
    return _ok(
        carriers=[{"id": c.id, "name": c.name, "phone": c.phone or "", "price": int(c.price or 0)} for c in carriers],
        agents=[{"id": a.id, "name": a.name, "phone": a.phone or "", "carrier_id": a.shipping_company_id} for a in agents],
        treasury_accounts=[{"id": a.id, "name": a.name, "is_default": bool(a.is_default)}
                           for a in treasury_choices_for_form()],
        can_approve=_is_admin(),
        can_manage=employee_can(get_current_employee(), "can_manage_shipping"),
    )


@desktop_api_bp.get(f"{PREFIX}/overview")
def shipping_center_overview():
    denied = _authorize()
    if denied:
        return denied
    carriers = _bucket_stats(Invoice.query.filter(Invoice.shipping_company_id.isnot(None)))
    agents = _bucket_stats(Invoice.query.filter(Invoice.delivery_agent_id.isnot(None)))
    in_transit = Invoice.query.filter(
        or_(Invoice.shipping_company_id.isnot(None), Invoice.delivery_agent_id.isnot(None)),
        Invoice.status == "جاري الشحن",
    )
    open_manifests = ShippingReport.query.filter(ShippingReport.is_executed.is_(False)).count()
    flagged = 0
    for report in ShippingReport.query.filter(ShippingReport.is_executed.is_(False)).limit(200).all():
        flagged += sum(1 for v in _selections(report).values() if v == STATUS_PROBLEM)
    return _ok(
        cards={
            "in_transit": {"count": in_transit.count()},
            "delivered_unsettled": {
                "count": carriers["delivered_unsettled"]["count"] + agents["delivered_unsettled"]["count"],
                "amount": carriers["delivered_unsettled"]["amount"] + agents["delivered_unsettled"]["amount"],
            },
            "carriers_due": carriers["due"],
            "agents_due": agents["due"],
            "returns": {"count": carriers["returned"]["count"] + agents["returned"]["count"]},
            "open_manifests": {"count": open_manifests, "flagged": flagged},
        },
    )


@desktop_api_bp.get(f"{PREFIX}/carriers")
def shipping_center_carriers():
    denied = _authorize()
    if denied:
        return denied
    merged, unique, _ = _carrier_helpers()
    rows = []
    for company in unique(ShippingCompany.query.order_by(ShippingCompany.name, ShippingCompany.id).all()):
        ids = merged(company)
        stats = _bucket_stats(Invoice.query.filter(Invoice.shipping_company_id.in_(ids)))
        opening = sum(int(getattr(c, "opening_balance", 0) or 0)
                      for c in ShippingCompany.query.filter(ShippingCompany.id.in_(ids)).all())
        rows.append({
            "id": company.id, "name": company.name, "phone": company.phone or "", "price": int(company.price or 0),
            "notes": company.notes or "", "opening_balance": opening, "stats": stats,
            "due": opening + stats["due"]["amount"],
            "open_manifests": ShippingReport.query.filter(ShippingReport.shipping_company_id.in_(ids),
                                                          ShippingReport.is_executed.is_(False)).count(),
        })
    return _ok(rows=rows)


def _orders_page(base):
    bucket = (request.args.get("bucket") or "all").strip()
    search = (request.args.get("search") or "").strip()
    page = max(1, request.args.get("page", 1, type=int) or 1)
    size = max(10, min(request.args.get("page_size", 25, type=int) or 25, 100))
    q = base
    alive = [Invoice.status.notin_(DEAD), or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(DEAD))]
    if bucket == "transit":
        q = q.filter(*alive, Invoice.status == "جاري الشحن")
    elif bucket == "delivered_unsettled":
        q = q.filter(*alive, Invoice.status.in_(("تم التوصيل", "استبدال")),
                     or_(Invoice.payment_status.is_(None), Invoice.payment_status != "مسدد"))
    elif bucket == "due":
        from services.reports_service import effective_paid_expr

        q = q.filter(*alive, func.coalesce(Invoice.total, 0) - effective_paid_expr() > 0)
    elif bucket == "returned":
        q = q.filter(or_(Invoice.status.in_(list(RETURN_STATUSES)), Invoice.payment_status.in_(list(RETURN_STATUSES))))
    if search:
        like = f"%{search}%"
        clauses = [Invoice.customer_name.ilike(like), Invoice.shipping_barcode.ilike(like)]
        if search.isdigit():
            clauses.append(Invoice.id == int(search))
        q = q.filter(or_(*clauses))
    total = q.count()
    rows = q.order_by(Invoice.created_at.desc(), Invoice.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"rows": [_order_row(o) for o in rows], "page": page, "page_size": size, "total": total,
            "total_pages": max(1, (total + size - 1) // size)}


@desktop_api_bp.get(f"{PREFIX}/carriers/<int:company_id>")
def shipping_center_carrier(company_id: int):
    denied = _authorize()
    if denied:
        return denied
    company = ShippingCompany.query.get(company_id)
    if company is None:
        return _error("شركة النقل غير موجودة", 404, "not_found")
    ids = _company_ids(company_id)
    stats = _bucket_stats(Invoice.query.filter(Invoice.shipping_company_id.in_(ids)))
    received = int(db.session.query(func.coalesce(func.sum(ShippingPayment.amount), 0)).filter(
        ShippingPayment.shipping_company_id.in_(ids), ShippingPayment.action == "تسديد").scalar() or 0)
    manifests = (ShippingReport.query.filter(ShippingReport.shipping_company_id.in_(ids))
                 .order_by(ShippingReport.created_at.desc()).limit(60).all())
    payments = (ShippingPayment.query.filter(ShippingPayment.shipping_company_id.in_(ids))
                .order_by(ShippingPayment.created_at.desc()).limit(200).all())
    return _ok(
        carrier={"id": company.id, "name": company.name, "phone": company.phone or "", "price": int(company.price or 0),
                 "notes": company.notes or ""},
        stats=stats,
        received_total=received,
        balance=statement_balance("carrier", company.id),
        manifests=[_report_summary(r) for r in manifests],
        statement=[{"id": p.id, "date": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "",
                    "invoice_id": p.invoice_id, "action": p.action, "amount": int(p.amount or 0),
                    "note": p.note or ""} for p in payments],
    )


@desktop_api_bp.get(f"{PREFIX}/carriers/<int:company_id>/orders")
def shipping_center_carrier_orders(company_id: int):
    denied = _authorize()
    if denied:
        return denied
    return _ok(**_orders_page(Invoice.query.filter(Invoice.shipping_company_id.in_(_company_ids(company_id)))))


@desktop_api_bp.get(f"{PREFIX}/agents")
def shipping_center_agents():
    denied = _authorize()
    if denied:
        return denied
    rows = []
    groups = sorted(_agent_groups(), key=lambda g: (not any(DeliveryAgent.query.get(i).is_active for i in g[1]),
                                                    g[0].name or ""))
    for agent, ids in groups:
        stats = _bucket_stats(Invoice.query.filter(Invoice.delivery_agent_id.in_(ids)))
        rows.append({"id": agent.id, "name": agent.name, "phone": agent.phone or "", "active": any(bool(DeliveryAgent.query.get(x).is_active) for x in ids),
                     "carrier": agent.shipping_company.name if agent.shipping_company else "",
                     "has_portal": any(bool(DeliveryAgent.query.get(x).username) for x in ids),
                     "merged_ids": ids, "stats": stats})
    return _ok(rows=rows)


@desktop_api_bp.get(f"{PREFIX}/agents/duplicates")
def agents_duplicates():
    """Duplicate agent records inside one branch (admin only). Per-branch copies of a person are never listed."""
    denied = _authorize()
    if denied:
        return denied
    if not (_is_admin() or employee_can(get_current_employee(), "merge_delivery_agents")):
        return _error("دمج المناديب يحتاج صلاحية دمج المناديب", 403, "forbidden")
    from utils import agent_merge

    return _ok(rows=agent_merge.duplicates())


@desktop_api_bp.post(f"{PREFIX}/agents/merge")
def agents_merge():
    """Moves the duplicates' invoices to the primary and deactivates them (nothing is deleted)."""
    denied = _authorize()
    if denied:
        return denied
    if not (_is_admin() or employee_can(get_current_employee(), "merge_delivery_agents")):
        return _error("دمج المناديب يحتاج صلاحية دمج المناديب", 403, "forbidden")
    from utils import agent_merge
    from utils.branch_management import BranchError

    data = request.get_json(silent=True) or {}
    try:
        result = agent_merge.merge(int(data.get("primary_id") or 0), [int(x) for x in data.get("duplicate_ids") or []])
    except BranchError as exc:
        db.session.rollback()
        return _error(str(exc), exc.status, exc.code)
    except (TypeError, ValueError):
        return _error("بيانات الدمج غير صحيحة", 400, "validation")
    return _ok(**result)


@desktop_api_bp.get(f"{PREFIX}/agents/<int:agent_id>")
def shipping_center_agent(agent_id: int):
    denied = _authorize()
    if denied:
        return denied
    agent = DeliveryAgent.query.get(agent_id)
    if agent is None:
        return _error("المندوب غير موجود", 404, "not_found")
    ids = _agent_ids(agent.id)
    stats = _bucket_stats(Invoice.query.filter(Invoice.delivery_agent_id.in_(ids)))
    manifests = (ShippingReport.query.filter(or_(
                     _portal_reports_filter(ids),
                     *[ShippingReport.notes.like(f'%"agent_id": {i},%') for i in ids]))
                 .order_by(ShippingReport.created_at.desc()).limit(60).all())
    return _ok(
        agent={"id": agent.id, "name": agent.name, "phone": agent.phone or "", "active": bool(agent.is_active),
               "carrier": agent.shipping_company.name if agent.shipping_company else "",
               "has_portal": bool(agent.username)},
        stats=stats,
        custody=_agent_custody(agent.id),
        manifests=[_report_summary(r) for r in manifests],
    )


@desktop_api_bp.get(f"{PREFIX}/agents/<int:agent_id>/orders")
def shipping_center_agent_orders(agent_id: int):
    denied = _authorize()
    if denied:
        return denied
    return _ok(**_orders_page(Invoice.query.filter(Invoice.delivery_agent_id.in_(_agent_ids(agent_id)))))


@desktop_api_bp.post(f"{PREFIX}/lookup")
def shipping_center_lookup():
    denied = _authorize(("can_see_shipping", "manage_orders"))
    if denied:
        return denied
    found, missing, seen = [], [], set()
    for code in _codes_from_request():
        order = find_order_by_code(code)
        if order is None:
            missing.append(code)
        elif order.id not in seen:
            seen.add(order.id)
            found.append({"code": code, **_order_row(order)})
    return _ok(found=found, missing=missing)


@desktop_api_bp.get(f"{PREFIX}/manifests")
def shipping_center_manifests():
    denied = _authorize()
    if denied:
        return denied
    q = ShippingReport.query
    state = (request.args.get("state") or "all").strip()
    if state == "open":
        q = q.filter(ShippingReport.is_executed.is_(False))
    elif state == "executed":
        q = q.filter(ShippingReport.is_executed.is_(True))
    kind = (request.args.get("kind") or "").strip()
    if kind == "settlement":
        q = q.filter(ShippingReport.report_number.like(f"{SETTLEMENT_PREFIX}%"))
    elif kind == "agent":
        q = q.filter(ShippingReport.report_number.like("AGT-%"))
    elif kind == "handover":
        q = q.filter(~ShippingReport.report_number.like(f"{SETTLEMENT_PREFIX}%"),
                     ~ShippingReport.report_number.like("AGT-%"))
    carrier_id = request.args.get("carrier_id", type=int)
    if carrier_id:
        q = q.filter(ShippingReport.shipping_company_id.in_(_company_ids(carrier_id)))
    search = (request.args.get("search") or "").strip()
    if search:
        q = q.filter(or_(ShippingReport.report_number.ilike(f"%{search}%"),
                         ShippingReport.shipping_company_name.ilike(f"%{search}%"),
                         ShippingReport.notes.ilike(f"%{search}%")))
    rows = q.order_by(ShippingReport.created_at.desc(), ShippingReport.id.desc()).limit(150).all()
    return _ok(rows=[_report_summary(r) for r in rows])


# ───────────────────────────── settlement manifest analysis ─────────────────────────────


def _analyze(report) -> dict[str, Any]:
    """Rule-based checks over the live orders (never the model): what blocks approval and what to review."""
    from utils.agent_report_helpers import find_blocking_executed_agent_reports_for_order

    selections = _selections(report)
    rows = _rows(report)
    meta = _report_meta(report)
    agent_id = _meta_agent_id(meta)
    carrier_ids = (set(_company_ids(report.shipping_company_id))
                   if report.shipping_company_id and not agent_id else set())
    claims = meta.get("agent_claim") if isinstance(meta.get("agent_claim"), dict) else {}
    return_fee = _return_fee(report.shipping_company_id) if not agent_id else 0
    issues: list[dict[str, Any]] = []
    seen: set[int] = set()
    live_rows = []
    totals = {"delivered": {"count": 0, "amount": 0, "fee": 0}, "returned": {"count": 0, "amount": 0, "fee": 0},
              "postponed": {"count": 0, "amount": 0}, "problem": {"count": 0, "amount": 0},
              "unclassified": {"count": 0, "amount": 0}}

    open_elsewhere: dict[int, list[str]] = {}
    agent_ids = set(_agent_ids(agent_id))
    own_portal = tuple(f"AGT-{i}-" for i in agent_ids) or None
    for other in ShippingReport.query.filter(ShippingReport.is_executed.is_(False), ShippingReport.id != report.id).all():
        if own_portal and str(other.report_number or "").startswith(own_portal):
            continue  # the agent's own portal report is the source of this settlement, not a duplicate
        for row in _rows(other):
            oid = row.get("id")
            if oid is not None:
                open_elsewhere.setdefault(int(oid), []).append(other.report_number)

    for row in rows:
        oid = int(row.get("id") or 0)
        order = Invoice.query.get(oid) if oid else None
        status = selections.get(str(oid), "")
        if order is None:
            issues.append({"severity": "error", "code": "missing", "order_id": oid,
                           "message": f"الطلب #{oid} لم يعد موجوداً في FINORA"})
            continue
        live = _order_row(order)
        live["selection"] = status
        live_rows.append(live)
        if oid in seen:
            issues.append({"severity": "error", "code": "duplicate", "order_id": oid,
                           "message": f"الطلب #{oid} مكرر داخل الكشف"})
        seen.add(oid)
        dead = is_canceled(order.status, order.payment_status) or is_returned(order.status, order.payment_status)
        if carrier_ids and order.shipping_company_id not in carrier_ids:
            issues.append({"severity": "error", "code": "other_carrier", "order_id": oid,
                           "message": f"الطلب #{oid} مسند إلى {live['shipping_company'] or 'جهة أخرى'} وليس لهذه الشركة"})
        if agent_id and order.delivery_agent_id not in agent_ids:
            issues.append({"severity": "error", "code": "other_agent", "order_id": oid,
                           "message": f"الطلب #{oid} مسند إلى {live['delivery_agent'] or 'جهة أخرى'} وليس لهذا المندوب"})
        claim = claims.get(str(oid))
        if claim and status and claim != status:
            issues.append({"severity": "warning", "code": "agent_claim", "order_id": oid,
                           "message": f"الطلب #{oid}: المندوب أبلغ «{claim}» والمحاسب صنّفه «{status}»"})
        if status == STATUS_RETURNED and _pending_return(oid):
            issues.append({"severity": "error", "code": "return_pending", "order_id": oid,
                           "message": f"الطلب #{oid} مسجل مرتجعاً بانتظار الاستلام مسبقاً"})
        if dead:
            issues.append({"severity": "error", "code": "closed", "order_id": oid,
                           "message": f"الطلب #{oid} ملغي أو راجع مسبقاً ({order.status})"})
        if status == STATUS_DELIVERED and live["remaining"] <= 0 and not dead:
            issues.append({"severity": "error", "code": "already_paid", "order_id": oid,
                           "message": f"الطلب #{oid} مسدد مسبقاً — لا يمكن تسديده مرتين"})
        if status == STATUS_DELIVERED and order.status not in ("جاري الشحن", "تم التوصيل", "استبدال") and not dead:
            issues.append({"severity": "warning", "code": "status_mismatch", "order_id": oid,
                           "message": f"الطلب #{oid} حالته «{order.status}» ولم يُشحن بعد"})
        if oid in open_elsewhere:
            issues.append({"severity": "warning", "code": "open_elsewhere", "order_id": oid,
                           "message": f"الطلب #{oid} موجود أيضاً في كشف مفتوح: {', '.join(open_elsewhere[oid][:3])}"})
        try:
            if find_blocking_executed_agent_reports_for_order(oid, None):
                issues.append({"severity": "error", "code": "executed_elsewhere", "order_id": oid,
                               "message": f"الطلب #{oid} نُفذ سابقاً في كشف مندوب"})
        except Exception:
            pass
        amount = live["remaining"]
        if status == STATUS_DELIVERED:
            totals["delivered"]["count"] += 1
            totals["delivered"]["amount"] += amount
            totals["delivered"]["fee"] += live["fee_due"]
        elif status == STATUS_RETURNED:
            totals["returned"]["count"] += 1
            totals["returned"]["amount"] += amount
            totals["returned"]["fee"] += return_fee
        elif status == STATUS_POSTPONED:
            totals["postponed"]["count"] += 1
            totals["postponed"]["amount"] += amount
        elif status == STATUS_PROBLEM:
            totals["problem"]["count"] += 1
            totals["problem"]["amount"] += amount
        else:
            totals["unclassified"]["count"] += 1
            totals["unclassified"]["amount"] += amount

    expected_net = totals["delivered"]["amount"] - totals["delivered"]["fee"] - totals["returned"]["fee"]
    blocking = [i for i in issues if i["severity"] == "error"]
    if totals["problem"]["count"]:
        blocking.append({"severity": "error", "code": "problem_rows", "order_id": None,
                         "message": f"{totals['problem']['count']} طلب معلّم «مشكلة» — عالجها قبل الاعتماد"})
    if not any(totals[k]["count"] for k in ("delivered", "returned", "postponed")):
        blocking.append({"severity": "error", "code": "empty", "order_id": None,
                         "message": "لم يُصنّف أي طلب بعد (واصل / راجع / مؤجل)"})
    return {"rows": live_rows, "issues": issues, "blocking": blocking, "totals": totals,
            "expected_net": expected_net, "ready": not blocking, "return_fee_each": return_fee}


def _settlement_number() -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    last = (ShippingReport.query.filter(ShippingReport.report_number.like(f"{SETTLEMENT_PREFIX}{today}-%"))
            .order_by(ShippingReport.id.desc()).first())
    seq = int(last.report_number.rsplit("-", 1)[-1]) + 1 if last else 1
    return f"{SETTLEMENT_PREFIX}{today}-{seq:04d}"


def _manifest_payload(report):
    meta = _report_meta(report)
    if report.is_executed:
        # Read the approved snapshot, never the current invoice or assignment.
        ledger = meta.get("ledger") if isinstance(meta.get("ledger"), dict) else {}
        allocations = ledger.get("allocations") if isinstance(ledger.get("allocations"), dict) else {}
        rows = []
        totals = {"delivered": {"count": 0, "amount": 0, "fee": 0}, "returned": {"count": 0, "amount": 0, "fee": 0},
                  "postponed": {"count": 0, "amount": 0}, "problem": {"count": 0, "amount": 0}, "unclassified": {"count": 0, "amount": 0}}
        for stored in _rows(report):
            try:
                order_id = int(stored.get("id") or stored.get("order_id"))
            except (TypeError, ValueError):
                continue
            row = {"customer_name": "", "customer_phone": "", "customer_city": "", "customer_address": "",
                   "total": 0, "paid_amount": 0, "status": "", "shipping_status": "", "payment_status": "",
                   "shipping_company_id": None, "shipping_company": report.shipping_company_name or "",
                   "delivery_agent_id": None, "delivery_agent": "", "waybills": [], "fee": 0, "fee_due": 0,
                   "created_at": "", **stored}
            row["id"] = order_id
            row["remaining"] = int(row.get("remaining", max(int(row["total"] or 0) - int(row["paid_amount"] or 0), 0)) or 0)
            row["selection"] = _selections(report).get(str(row["id"]), "")
            row["allocated"] = int(allocations.get(str(row["id"]), 0) or 0)
            bucket = {STATUS_DELIVERED: "delivered", STATUS_RETURNED: "returned", STATUS_POSTPONED: "postponed", STATUS_PROBLEM: "problem"}.get(row["selection"], "unclassified")
            totals[bucket]["count"] += 1
            totals[bucket]["amount"] += row["remaining"]
            rows.append(row)
        totals["delivered"]["fee"] = int(ledger.get("fees", 0) or 0)
        totals["returned"]["fee"] = int(ledger.get("return_fees", 0) or 0)
        snapshot = meta.get("approved_analysis") if isinstance(meta.get("approved_analysis"), dict) else {}
        analysis = {"rows": rows, "issues": [], "blocking": [], "ready": False, "totals": totals,
                    "expected_net": int(ledger.get("expected_net", meta.get("received_amount", 0)) or 0),
                    "return_fee_each": int(snapshot.get("return_fee_each", totals["returned"]["fee"] // max(totals["returned"]["count"], 1)) or 0)}
    else:
        analysis = _analyze(report)
    ids = {str(row["id"]) for row in analysis["rows"]}
    selections = _selections(report)
    if not report.is_executed:
        selections = {key: value for key, value in selections.items() if key in ids}
    return {**_report_summary(report), "meta": meta, "selections": selections, **analysis}


def _editable_settlement(manifest_id: int):
    report = ShippingReport.query.get(manifest_id)
    if report is None:
        return None, _error("الكشف غير موجود", 404, "not_found")
    if report.is_executed:
        return None, _error("الكشف معتمد ولا يمكن تعديله — أنشئ تصحيحاً بكشف جديد", 409, "conflict")
    return report, None


@desktop_api_bp.get(f"{PREFIX}/manifests/<int:manifest_id>")
def shipping_center_manifest(manifest_id: int):
    denied = _authorize()
    if denied:
        return denied
    report = ShippingReport.query.get(manifest_id)
    if report is None:
        return _error("الكشف غير موجود", 404, "not_found")
    return _ok(manifest=_manifest_payload(report))


@desktop_api_bp.post(f"{PREFIX}/manifests")
def shipping_center_manifest_create():
    """New settlement manifest (draft) for one carrier or one delivery agent.

    Rows are added by order number / waybill afterwards — or, for an agent with ``from_portal``, taken from the
    agent's open portal reports with the agent's own classification kept as a claim to compare against.
    """
    denied = _authorize("can_manage_shipping")
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    reference = str(data.get("reference") or "").strip()[:60]
    meta: dict[str, Any] = {"reference": reference, "date": str(data.get("date") or "")[:10], "operation": "settlement"}
    rows: list[dict] = []
    selections: dict[str, str] = {}
    agent = DeliveryAgent.query.get(int(data.get("agent_id") or 0)) if data.get("agent_id") else None
    if data.get("agent_id") and agent is None:
        return _error("المندوب غير موجود", 404, "not_found")
    if agent is not None:
        company = agent.shipping_company
        meta.update(agent_id=agent.id, agent_name=agent.name)
        if data.get("from_portal"):
            rows, claims = _portal_claims(agent.id)
            if not rows:
                return _error("لا توجد طلبات مُبلّغ عنها في بوابة المندوب", 409, "conflict")
            meta["agent_claim"] = claims
            selections = dict(claims)
    else:
        company = ShippingCompany.query.get(int(data.get("carrier_id") or 0))
        if company is None:
            return _error("اختر شركة النقل أو المندوب", 400, "validation")
    report = ShippingReport(
        report_number=_settlement_number(),
        shipping_company_id=company.id if company else None,
        shipping_company_name=company.name if company else (agent.name if agent else ""),
        orders_data=json.dumps(rows, ensure_ascii=False),
        total_amount=sum(int(r.get("remaining") or 0) for r in rows),
        orders_count=len(rows),
        notes=json.dumps(meta, ensure_ascii=False),
        created_by=session.get("name", "غير محدد"),
        order_status_selections=json.dumps(selections, ensure_ascii=False),
    )
    db.session.add(report)
    db.session.commit()
    return _ok(manifest=_manifest_payload(report))


ROW_FIELDS = ("id", "customer_name", "customer_phone", "customer_city", "customer_address", "total", "paid_amount",
              "remaining", "status", "payment_status", "created_at")
PORTAL_STATUS = {"واصل": STATUS_DELIVERED, "Delivered": STATUS_DELIVERED, "استبدال": STATUS_DELIVERED,
                 "ملغي": STATUS_RETURNED, "Canceled": STATUS_RETURNED, "راجع": STATUS_RETURNED,
                 "مؤجل": STATUS_POSTPONED, "Delayed": STATUS_POSTPONED}


def _portal_claims(agent_id: int) -> tuple[list[dict], dict[str, str]]:
    """Orders the agent reported in the portal (open AGT reports) with the agent's own classification."""
    rows: list[dict] = []
    claims: dict[str, str] = {}
    reports = (ShippingReport.query.filter(ShippingReport.is_executed.is_(False),
                                           _portal_reports_filter(_agent_ids(agent_id)))
               .order_by(ShippingReport.created_at.asc(), ShippingReport.id.asc()).all())
    for report in reports:
        selections = _selections(report)
        for raw in _rows(report):
            oid = raw.get("id") or raw.get("order_id")
            claim = PORTAL_STATUS.get(selections.get(str(oid), ""))
            if not oid or not claim or str(oid) in claims:
                continue
            order = Invoice.query.get(int(oid))
            if order is None or is_canceled(order.status, order.payment_status) or is_returned(order.status, order.payment_status):
                continue
            row = _order_row(order)
            rows.append({k: row[k] for k in ROW_FIELDS})
            claims[str(order.id)] = claim
    return rows, claims


@desktop_api_bp.post(f"{PREFIX}/manifests/<int:manifest_id>/rows")
def shipping_center_manifest_add_rows(manifest_id: int):
    denied = _authorize("can_manage_shipping")
    if denied:
        return denied
    report, error = _editable_settlement(manifest_id)
    if error:
        return error
    rows = _rows(report)
    present = {int(r.get("id")) for r in rows if r.get("id") is not None}
    added, duplicates, missing = [], [], []
    for code in _codes_from_request():
        order = find_order_by_code(code)
        if order is None:
            missing.append(code)
            continue
        if order.id in present:
            duplicates.append(code)
            continue
        present.add(order.id)
        row = _order_row(order)
        rows.append({k: row[k] for k in ROW_FIELDS})
        added.append(order.id)
    report.orders_data = json.dumps(rows, ensure_ascii=False)
    report.orders_count = len(rows)
    report.total_amount = sum(int(r.get("remaining") or 0) for r in rows)
    db.session.commit()
    return _ok(added=added, duplicates=duplicates, missing=missing, manifest=_manifest_payload(report))


@desktop_api_bp.post(f"{PREFIX}/manifests/<int:manifest_id>/rows/<int:order_id>/remove")
def shipping_center_manifest_remove_row(manifest_id: int, order_id: int):
    denied = _authorize("can_manage_shipping")
    if denied:
        return denied
    report, error = _editable_settlement(manifest_id)
    if error:
        return error
    rows = [r for r in _rows(report) if int(r.get("id") or 0) != order_id]
    selections = _selections(report)
    selections.pop(str(order_id), None)
    report.orders_data = json.dumps(rows, ensure_ascii=False)
    report.orders_count = len(rows)
    report.total_amount = sum(int(r.get("remaining") or 0) for r in rows)
    report.order_status_selections = json.dumps(selections, ensure_ascii=False)
    db.session.commit()
    return _ok(manifest=_manifest_payload(report))


@desktop_api_bp.post(f"{PREFIX}/manifests/<int:manifest_id>/selections")
def shipping_center_manifest_selections(manifest_id: int):
    """Save the draft classification (واصل / راجع / مؤجل / مشكلة). Nothing is posted until approval."""
    denied = _authorize("can_manage_shipping")
    if denied:
        return denied
    report, error = _editable_settlement(manifest_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    incoming = data.get("selections") or {}
    if not isinstance(incoming, dict):
        return _error("صيغة الحالات غير صالحة", 400, "validation")
    ids = {str(int(r.get("id"))) for r in _rows(report) if r.get("id") is not None}
    selections = _selections(report)
    for key, value in incoming.items():
        key = str(key)
        if key not in ids:
            continue
        if value in (None, ""):
            selections.pop(key, None)
        elif value in ROW_STATUSES:
            selections[key] = value
        else:
            return _error(f"حالة غير معروفة: {value}", 400, "validation")
    report.order_status_selections = json.dumps(selections, ensure_ascii=False)
    db.session.commit()
    return _ok(manifest=_manifest_payload(report))


@desktop_api_bp.post(f"{PREFIX}/manifests/<int:manifest_id>/approve")
def shipping_center_manifest_approve(manifest_id: int):
    """Admin approval of a settlement manifest — one transaction over FINORA's own engines.

    * «واصل» rows are paid by ``execute_shipping_report`` up to the amount allocated to each order: the full
      remaining amount, part of it (FINORA's piece settlement — the order stays open for the rest) or nothing
      (carried to a later settlement while the carrier still holds the money). The courier fee is withdrawn once.
    * «راجع» rows are registered as returns awaiting receipt; stock and the sale are only reversed when the
      parcel is received and inspected (``/returns``). The carrier's return fee is posted as an expense.
    * «مؤجل» rows return to «تم الطلب» and restore their dispatched stock once.
    * A receipt voucher (``receipts``) documents the money received and its allocation per order.

    The money received must equal the allocated net exactly — differences are never auto-corrected.
    """
    denied = _authorize("can_manage_shipping")
    if denied:
        return denied
    if not _is_admin():
        return _error("اعتماد الكشوف للمدير فقط", 403, "forbidden")
    report, error = _editable_settlement(manifest_id)
    if error:
        return error
    if _report_kind(report) != "settlement":
        return _error("يُعتمد من هنا كشف التسوية فقط", 409, "conflict")
    _tables()
    data = request.get_json(silent=True) or {}
    analysis = _analyze(report)
    if analysis["blocking"]:
        return _error("لا يمكن الاعتماد: " + " · ".join(i["message"] for i in analysis["blocking"][:4]), 409, "conflict")
    try:
        received = int(data.get("received_amount"))
    except (TypeError, ValueError):
        return _error("أدخل المبلغ المستلم فعلياً", 400, "validation")
    if received < 0:
        return _error("المبلغ المستلم لا يكون سالباً", 400, "validation")

    delivered = [r for r in analysis["rows"] if r["selection"] == STATUS_DELIVERED]
    returned = [r for r in analysis["rows"] if r["selection"] == STATUS_RETURNED]
    postponed = [r for r in analysis["rows"] if r["selection"] == STATUS_POSTPONED]
    raw_allocations = data.get("allocations")
    allocations: dict[int, int] = {}
    if raw_allocations is None:
        allocations = {r["id"]: r["remaining"] for r in delivered}
    elif not isinstance(raw_allocations, dict):
        return _error("صيغة توزيع المبلغ غير صالحة", 400, "validation")
    else:
        for r in delivered:
            try:
                amount = int(raw_allocations.get(str(r["id"]), 0) or 0)
            except (TypeError, ValueError):
                return _error(f"مبلغ غير صالح للطلب #{r['id']}", 400, "validation")
            if amount < 0 or amount > r["remaining"]:
                return _error(f"المبلغ المخصص للطلب #{r['id']} يجب أن يكون بين 0 و{r['remaining']:,}", 400, "validation")
            allocations[r["id"]] = amount
    fees = sum(r["fee_due"] for r in delivered if allocations.get(r["id"], 0) > 0)
    return_fees = analysis["totals"]["returned"]["fee"]
    expected = sum(allocations.values()) - fees - return_fees
    if received != expected:
        partial = any(allocations[r["id"]] < r["remaining"] for r in delivered)
        hint = "عدّل توزيع المبلغ على الطلبات" if partial else "صنّف الطلبات بدقة أو وزّع المبلغ جزئياً"
        return _error(f"المبلغ المستلم {received:,} لا يطابق الصافي المستحق {expected:,} — {hint} قبل الاعتماد",
                      409, "conflict")

    from utils.shipping_report_execute import execute_shipping_report
    from utils.treasury_helpers import resolve_treasury_account_id

    treasury_account_id = resolve_treasury_account_id(data.get("treasury_account_id"))
    payment_method = "bank" if str(data.get("payment_method") or "") == "bank" else "cash"
    employee = get_current_employee()
    meta = _report_meta(report)
    agent_id = _meta_agent_id(meta)
    party_type, party_id = ("agent", agent_id) if agent_id else ("carrier", report.shipping_company_id)
    party_name = str(meta.get("agent_name") or "") if agent_id else (report.shipping_company_name or "")
    original_selections = report.order_status_selections
    now = datetime.utcnow()

    executable, exec_rows = {}, []
    for r in delivered:
        amount = allocations[r["id"]]
        if amount <= 0:
            continue
        executable[str(r["id"])] = STATUS_DELIVERED
        exec_rows.append({"id": r["id"], "total": amount, "partial_settlement": amount < r["remaining"]})
    # Use the shared delayed-order lifecycle, including its idempotent stock
    # restoration. These rows do not participate in collection allocations.
    for r in postponed:
        executable[str(r["id"])] = STATUS_POSTPONED
        exec_rows.append({"id": r["id"]})
    carried = [r["id"] for r in delivered if allocations[r["id"]] <= 0]
    outstanding = sum(r["remaining"] - allocations[r["id"]] for r in delivered)

    try:
        prior = statement_balance(party_type, party_id) if party_id else 0
        new_debits = _new_debits(party_type, party_id, delivered, exclude_report_id=report.id) if party_id else {}
        from models.shipping_center import ShippingReturn

        for r in returned:
            db.session.add(ShippingReturn(
                order_id=r["id"], manifest_id=report.id, manifest_number=report.report_number,
                party_type=party_type, party_id=party_id, party_name=party_name, state="awaiting",
                order_amount=int(r["total"] or 0), reported_at=now, reported_by=session.get("name", "")))
        if return_fees > 0:
            _post_return_fee(report, return_fees, len(returned), treasury_account_id)
        receipt = None
        if received > 0:
            receipt = _create_receipt(report, party_type, party_id, party_name, received, payment_method,
                                      treasury_account_id, meta, allocations, prior + sum(new_debits.values()) - fees - return_fees,
                                      employee)
        if agent_id:
            _detach_from_portal_reports(agent_id, [int(k) for k in executable] + [r["id"] for r in returned])
        ledger = {"expected_net": expected, "received": received, "fees": fees, "return_fees": return_fees,
                  "allocations": {str(k): v for k, v in allocations.items()},
                  "debits": {str(k): v for k, v in new_debits.items()}, "carried": carried,
                  "outstanding": outstanding, "returns": [r["id"] for r in returned],
                  "receipt_number": receipt.receipt_number if receipt else ""}
        meta.update({"received_amount": received, "approved_by": session.get("name", ""),
                     "approved_at": now.strftime("%Y-%m-%d %H:%M"), "treasury_account_id": treasury_account_id,
                     "payment_method": payment_method, "ledger": ledger})
        report.notes = json.dumps(meta, ensure_ascii=False)
        if executable:
            report.orders_data = json.dumps(exec_rows, ensure_ascii=False)
            report.order_status_selections = json.dumps(executable, ensure_ascii=False)
            result = execute_shipping_report(report, expense_amount=0, treasury_account_id=treasury_account_id)
            if result.get("error"):
                db.session.rollback()
                return _error(result["error"], 409, "conflict")
        else:
            report.is_executed = True
            result = {"success": True, "message": "اعتُمد الكشف دون تحصيل"}
        # The manifest keeps its own rows and the accountant's classification as the approved record.
        frozen_rows = [dict(row) for row in analysis["rows"]]
        for row in frozen_rows:
            order = db.session.get(Invoice, row["id"])
            if order:
                row.update(status=order.status or "", shipping_status=order.shipping_status or "", payment_status=order.payment_status or "")
        meta["approved_analysis"] = {"return_fee_each": analysis["return_fee_each"]}
        report.notes = json.dumps(meta, ensure_ascii=False)
        report.orders_data = json.dumps(frozen_rows, ensure_ascii=False)
        report.orders_count = len(frozen_rows)
        report.total_amount = sum(row["remaining"] for row in frozen_rows)
        report.order_status_selections = json.dumps({key: value for key, value in json.loads(original_selections or "{}").items() if key in {str(row["id"]) for row in frozen_rows}}, ensure_ascii=False)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return _error(str(exc), 409, "conflict")
    except Exception:
        db.session.rollback()
        return _error("تعذر تنفيذ الكشف — لم يتغير شيء", 500, "server")
    try:
        from utils.activity_logger import log_activity

        log_activity("update", "shipping", f"اعتماد كشف التسوية {report.report_number}", entity_type="shipping_report",
                     entity_id=report.id, payload={"received": received, "ledger": ledger})
    except Exception:
        pass
    return _ok(result=result, manifest=_manifest_payload(report))


def _post_return_fee(report, amount: int, count: int, treasury_account_id) -> None:
    """The carrier's return fee is a real shipping expense, posted with FINORA's own expense posting."""
    from models.expense import Expense
    from routes.expenses import _post_expense_to_treasury
    from utils.branch_scope import resolve_write_branch_id

    expense = Expense(branch_id=resolve_write_branch_id({}), title=f"أجور مرتجعات — كشف {report.report_number}",
                      category="توصيل", amount=int(amount),
                      note=f"{count} طلب راجع × أجرة المرتجع لدى {report.shipping_company_name}",
                      expense_date=datetime.utcnow().date(), treasury_account_id=treasury_account_id,
                      cash_posted=False)
    db.session.add(expense)
    db.session.flush()
    _post_expense_to_treasury(expense, treasury_account_id)


def _receipt_number() -> str:
    from models.receipt import Receipt

    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"RCV-SHP-{today}-"
    last = Receipt.query.filter(Receipt.receipt_number.like(f"{prefix}%")).order_by(Receipt.id.desc()).first()
    seq = int(last.receipt_number.rsplit("-", 1)[-1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def _create_receipt(report, party_type, party_id, party_name, received, payment_method, treasury_account_id, meta,
                    allocations, balance_before, employee):
    """Receipt voucher (سند قبض) documenting the settlement. Cash is posted by the executor, not by this row."""
    from models.receipt import Receipt, ReceiptAllocation

    receipt = Receipt(
        branch_id=getattr(g, "branch_id", None), receipt_number=_receipt_number(),
        source_type="courier" if party_type == "agent" else "shipping_company", source_id=int(party_id or 0),
        source_name=party_name, amount=int(received), payment_method=payment_method,
        treasury_account_id=treasury_account_id, receipt_date=datetime.utcnow().date(),
        reference_number=(str(meta.get("reference") or "") or report.report_number)[:100],
        notes=f"تسوية كشف {report.report_number}", allocation_method="manual", status="معتمد",
        balance_before=int(balance_before), balance_after=int(balance_before) - int(received),
        created_by=employee.id if employee else None, idempotency_key=f"shipping-center:manifest:{report.id}")
    db.session.add(receipt)
    db.session.flush()
    for order_id, amount in allocations.items():
        if amount > 0:
            db.session.add(ReceiptAllocation(receipt_id=receipt.id, reference_type="invoice", reference_id=int(order_id),
                                             reference_label=f"#{order_id}", allocated_amount=int(amount)))
    return receipt


def _detach_from_portal_reports(agent_id: int, order_ids: list[int]) -> None:
    """Settled orders leave the agent's open portal reports so they can never be executed a second time."""
    wanted = {int(i) for i in order_ids}
    if not wanted:
        return
    for portal in ShippingReport.query.filter(ShippingReport.is_executed.is_(False),
                                              _portal_reports_filter(_agent_ids(agent_id))).all():
        rows = _rows(portal)
        kept = [r for r in rows if int(r.get("id") or r.get("order_id") or 0) not in wanted]
        if len(kept) == len(rows):
            continue
        selections = {k: v for k, v in _selections(portal).items() if int(k) not in wanted}
        portal.orders_data = json.dumps(kept, ensure_ascii=False)
        portal.order_status_selections = json.dumps(selections, ensure_ascii=False)
        portal.orders_count = len(kept)
        portal.total_amount = sum(int(r.get("remaining") or r.get("total") or 0) for r in kept)


# ───────────────────────────── account statement (debit / credit / balance) ─────────────────────────────


def _party_reports(party_type: str, party_id: int) -> list:
    q = ShippingReport.query.filter(ShippingReport.is_executed.is_(True),
                                    ShippingReport.report_number.like(f"{SETTLEMENT_PREFIX}%"))
    if party_type == "carrier":
        q = q.filter(ShippingReport.shipping_company_id.in_(_company_ids(party_id) or [party_id]))
    reports = []
    same_agent = set(_agent_ids(party_id)) if party_type == "agent" else set()
    for report in q.order_by(ShippingReport.id.asc()).all():
        agent_id = _meta_agent_id(_report_meta(report))
        if (party_type == "agent" and agent_id in same_agent) or (party_type == "carrier" and not agent_id):
            reports.append(report)
    return reports


def _report_ledger(report) -> dict[str, Any]:
    """Phase 2 manifests store their ledger; phase 1 ones (exact full settlements) are derived from their rows."""
    meta = _report_meta(report)
    ledger = meta.get("ledger")
    if isinstance(ledger, dict):
        return ledger
    selections = _selections(report)
    debits = {str(r.get("id")): int(r.get("remaining") or 0) for r in _rows(report)
              if selections.get(str(r.get("id"))) == STATUS_DELIVERED}
    received = int(meta.get("received_amount") or 0)
    return {"debits": debits, "fees": max(sum(debits.values()) - received, 0), "return_fees": 0,
            "received": received, "receipt_number": ""}


def _new_debits(party_type: str, party_id: int, delivered: list[dict], exclude_report_id: int | None = None) -> dict[int, int]:
    """An order is debited to the party once — the first time it is reported delivered."""
    debited: set[str] = set()
    for report in _party_reports(party_type, party_id):
        if report.id != exclude_report_id:
            debited.update(_report_ledger(report).get("debits", {}).keys())
    return {r["id"]: r["remaining"] for r in delivered if str(r["id"]) not in debited}


def statement_lines(party_type: str, party_id: int) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    balance = 0
    for report in _party_reports(party_type, party_id):
        meta = _report_meta(report)
        ledger = _report_ledger(report)
        date = str(meta.get("approved_at") or (report.created_at.strftime("%Y-%m-%d %H:%M") if report.created_at else ""))
        debits = ledger.get("debits", {})
        entries = []
        if debits:
            entries.append((f"تحصيل {len(debits)} طلب واصل", sum(int(v) for v in debits.values()), 0))
        if int(ledger.get("fees") or 0):
            entries.append(("أجور النقل", 0, int(ledger["fees"])))
        if int(ledger.get("return_fees") or 0):
            entries.append(("أجور المرتجعات", 0, int(ledger["return_fees"])))
        if int(ledger.get("received") or 0):
            label = f"سند قبض {ledger.get('receipt_number')}" if ledger.get("receipt_number") else "مبلغ مستلم"
            entries.append((label, 0, int(ledger["received"])))
        for label, debit, credit in entries:
            balance += debit - credit
            lines.append({"date": date, "manifest_id": report.id, "manifest_number": report.report_number,
                          "label": label, "debit": debit, "credit": credit, "balance": balance})
    return lines


def statement_balance(party_type: str, party_id: int) -> int:
    lines = statement_lines(party_type, party_id)
    return lines[-1]["balance"] if lines else 0


@desktop_api_bp.post(f"{PREFIX}/handover")
def shipping_center_handover():
    """Handover manifest: dispatch orders to a carrier with FINORA's own KSH manifest."""
    denied = _authorize(DISPATCH_PERMISSIONS)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    order_ids = [int(i) for i in (data.get("order_ids") or []) if str(i).isdigit()][:MAX_CODES]
    if not order_ids:
        return _error("أضف طلبات إلى كشف التسليم", 400, "validation")
    from routes.orders import _create_shipping_report_from_ids

    result = _create_shipping_report_from_ids(order_ids, data.get("carrier_id"))
    if hasattr(result, "status_code") or (isinstance(result, tuple) and hasattr(result[0], "status_code")):
        return result  # FINORA's own stock-shortage response
    payload, status = result
    if status != 200:
        return _error(payload.get("error") or "تعذر إنشاء كشف التسليم", status, "conflict" if status in (409, 423) else "validation")
    return _ok(**payload)


DISPATCH_PERMISSIONS = ("can_manage_shipping", "manage_orders")


@desktop_api_bp.post(f"{PREFIX}/agent-report")
def shipping_center_agent_report():
    """Agent manifest (AGT-…): FINORA's own ``create_agent_report_internal`` — links the orders to the agent,
    dispatches them (stock) and shows them in the agent's portal as one batch. Duplicates are refused there."""
    denied = _authorize(DISPATCH_PERMISSIONS)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    order_ids = [int(i) for i in (data.get("order_ids") or []) if str(i).isdigit()][:MAX_CODES]
    if not order_ids:
        return _error("أضف طلبات إلى كشف المندوب", 400, "validation")
    agent = DeliveryAgent.query.get(int(data.get("agent_id") or 0))
    if agent is None or not agent.is_active:
        return _error("اختر مندوباً فعالاً", 400, "validation")
    from routes.orders import create_agent_report_internal

    result = create_agent_report_internal(order_ids, agent.id, save_to_db=True)
    if result.get("error"):
        db.session.rollback()
        return _error(result["error"], 409, "conflict")
    return _ok(report_id=result["report_id"], report_number=result["report_number"],
               already_exists=bool(result.get("already_exists")), message=result.get("message", ""))
