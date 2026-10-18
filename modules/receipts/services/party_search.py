"""Party search + summaries for unified settlements modal."""
from __future__ import annotations

from datetime import date

from sqlalchemy import or_

from models.customer import Customer
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from models.shipping import ShippingCompany
from models.supplier import Supplier
from modules.receipts.services import source_summary as summary_svc
from modules.receipts.services.helpers import ReceiptError, parse_int
from utils.branch_scope import scope_query
from utils.supplier_payment_ops import shared_supplier_member_ids


def search_parties(kind: str, q: str, *, limit: int = 20) -> list[dict]:
    kind = (kind or "").strip()
    q = (q or "").strip()
    limit = max(1, min(int(limit or 20), 50))

    if kind in {"customer", "courier", "shipping_company"}:
        return summary_svc.search_sources(kind, q, limit=limit)

    if kind == "supplier":
        return _search_suppliers(q, limit=limit)

    if kind == "employee":
        return _search_employees(q, limit=limit)

    if kind == "delivery_agent":
        return _search_delivery_agents(q, limit=limit)

    raise ReceiptError("نوع الجهة غير مدعوم")


def party_summary(kind: str, party_id: int) -> dict:
    kind = (kind or "").strip()
    party_id = parse_int(party_id)
    if party_id <= 0:
        raise ReceiptError("معرّف الجهة غير صالح")

    if kind in {"customer", "courier", "shipping_company"}:
        return summary_svc.source_summary(kind, party_id)

    if kind == "supplier":
        return _supplier_summary(party_id)

    if kind in {"employee", "delivery_agent"}:
        return _payroll_summary(kind, party_id)

    raise ReceiptError("نوع الجهة غير مدعوم")


def _search_suppliers(q: str, *, limit: int) -> list[dict]:
    query = Supplier.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Supplier.name.ilike(like), Supplier.phone.ilike(like), Supplier.phone2.ilike(like))
        )
    rows = query.order_by(Supplier.name.asc()).limit(limit).all()
    out = []
    for s in rows:
        remaining = max(int(getattr(s, "remaining", 0) or 0), 0)
        out.append(
            {
                "id": s.id,
                "name": s.name,
                "phone": s.phone,
                "balance": remaining,
                "kind": "supplier",
            }
        )
    return out


def _search_employees(q: str, *, limit: int) -> list[dict]:
    query = scope_query(Employee.query, Employee).filter(Employee.is_active.is_(True))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Employee.name.ilike(like), Employee.phone.ilike(like), Employee.username.ilike(like))
        )
    rows = query.order_by(Employee.name.asc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "name": e.name,
            "phone": getattr(e, "phone", None),
            "kind": "employee",
            "payee_type": "employee",
        }
        for e in rows
    ]


def _search_delivery_agents(q: str, *, limit: int) -> list[dict]:
    query = DeliveryAgent.query.filter(DeliveryAgent.is_active.is_(True))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                DeliveryAgent.name.ilike(like),
                DeliveryAgent.phone.ilike(like),
                DeliveryAgent.username.ilike(like),
            )
        )
    rows = query.order_by(DeliveryAgent.name.asc()).limit(limit).all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "phone": getattr(a, "phone", None),
            "kind": "delivery_agent",
            "payee_type": "delivery_agent",
        }
        for a in rows
        if getattr(a, "username", None)
    ]


def _supplier_summary(supplier_id: int) -> dict:
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        raise ReceiptError("المورد غير موجود")
    member_ids = shared_supplier_member_ids(supplier)
    members = (
        Supplier.query.execution_options(skip_branch_scope=True)
        .filter(Supplier.id.in_(member_ids))
        .all()
    )
    remaining = sum(max(int(m.remaining or 0), 0) for m in members)
    return {
        "kind": "supplier",
        "id": supplier.id,
        "name": supplier.name,
        "phone": supplier.phone,
        "balance": remaining,
        "open_count": 0,
        "invoices": [],
    }


def _payroll_summary(payee_type: str, payee_id: int) -> dict:
    from utils.payroll_service import (
        get_salary_due_amount,
        salary_paid_in_current_cycle,
        is_salary_due,
        compute_next_salary_date,
        _has_salary_schedule,
        _schedule_label,
        _serialize_payee_due,
    )

    today = date.today()
    if payee_type == "employee":
        payee = Employee.query.get(payee_id)
    else:
        payee = DeliveryAgent.query.get(payee_id)
    if not payee:
        raise ReceiptError("المستفيد غير موجود")

    amount = int(get_salary_due_amount(payee) or 0) if _has_salary_schedule(payee) else 0
    paid_in_cycle = bool(salary_paid_in_current_cycle(payee, today=today)) if amount else False
    due = bool(is_salary_due(payee, today=today)) if amount else False
    next_date = compute_next_salary_date(payee, today=today) if amount else None
    rows = _serialize_payee_due(payee, today=today) or []
    salary_row = next((r for r in rows if r.get("kind") == "salary"), None)

    return {
        "kind": payee_type,
        "id": payee_id,
        "name": getattr(payee, "name", None),
        "phone": getattr(payee, "phone", None),
        "payee_type": payee_type,
        "payee_id": payee_id,
        "amount": amount,
        "balance": amount,
        "has_salary_schedule": bool(amount > 0),
        "paid_in_cycle": paid_in_cycle,
        "is_due": due,
        "can_pay_manually": bool(salary_row.get("can_pay_manually")) if salary_row else (amount > 0 and not paid_in_cycle),
        "schedule_label": _schedule_label(payee) if amount else "",
        "next_pay_date": next_date.isoformat() if next_date else None,
        "open_count": 0,
        "invoices": [],
    }
