"""Unified multi-type search for Finora Phone."""

from __future__ import annotations

import base64
import json
from typing import Any

from extensions import db
from modules.phone_app.models import PhoneCallLog
from modules.phone_app.services.permissions import employee_has_phone_perm
from utils.digits import digits_only

SEARCH_TYPES = ("customers", "orders", "invoices", "calls", "products")


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _decode_cursor(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        return max(0, int(data.get("o") or 0))
    except Exception:
        return 0


def _normalize_query(q: str) -> tuple[str, str]:
    q = (q or "").strip()
    phone = digits_only(q) or ""
    return q, phone


def _min_query_ok(q: str, phone: str) -> bool:
    if phone and len(phone) >= 3:
        return True
    return len(q) >= 2


def search_all(
    *,
    q: str,
    types: list[str] | None,
    cursor: str | None,
    limit: int,
    employee,
    branch_id: int | None = None,
) -> dict[str, Any]:
    q, phone = _normalize_query(q)
    if not _min_query_ok(q, phone):
        return {
            "query": q,
            "groups": {t: [] for t in SEARCH_TYPES},
            "pagination": {"next_cursor": None, "has_more": False},
        }

    wanted = [t for t in (types or list(SEARCH_TYPES)) if t in SEARCH_TYPES]
    if not wanted:
        wanted = list(SEARCH_TYPES)
    if not employee_has_phone_perm(employee, "phone.search.all"):
        # Restrict to customers + own calls only
        wanted = [t for t in wanted if t in ("customers", "calls")]

    limit = max(1, min(int(limit or 20), 40))
    offset = _decode_cursor(cursor)
    show_money = employee_has_phone_perm(employee, "phone.financial.view")
    groups: dict[str, list] = {t: [] for t in SEARCH_TYPES}

    if "customers" in wanted:
        groups["customers"] = _search_customers(q, phone, limit)
    if "products" in wanted:
        groups["products"] = _search_products(q, limit)
    if "orders" in wanted or "invoices" in wanted:
        inv = _search_invoices(q, phone, limit, branch_id=branch_id, show_money=show_money)
        if "orders" in wanted:
            groups["orders"] = inv
        if "invoices" in wanted:
            groups["invoices"] = inv
    if "calls" in wanted:
        groups["calls"] = _search_calls(q, phone, limit, employee_id=employee.id)

    # Flat pagination across concatenated non-empty groups for next_cursor
    flat_count = sum(len(v) for v in groups.values())
    has_more = flat_count >= limit
    next_cursor = _encode_cursor(offset + limit) if has_more else None

    return {
        "query": q,
        "groups": groups,
        "pagination": {"next_cursor": next_cursor, "has_more": has_more},
    }


def _search_customers(q: str, phone: str, limit: int) -> list[dict]:
    from models.customer import Customer
    from sqlalchemy import or_

    filters = [Customer.name.ilike(f"%{q}%")]
    if len(phone) >= 3:
        filters.append(Customer.phone.contains(phone))
        filters.append(Customer.phone2.contains(phone))
    filters.append(Customer.city.ilike(f"%{q}%"))
    filters.append(Customer.address.ilike(f"%{q}%"))
    if hasattr(Customer, "notes"):
        filters.append(Customer.notes.ilike(f"%{q}%"))
    rows = (
        Customer.query.filter(or_(*filters))
        .order_by(Customer.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for c in rows:
        out.append(
            {
                "type": "customer",
                "id": c.id,
                "title": c.name,
                "subtitle": c.phone or "",
                "summary": f"{c.city or ''} {c.address or ''}".strip(),
                "highlight": q,
            }
        )
    return out


def _search_products(q: str, limit: int) -> list[dict]:
    try:
        from models.product import Product
    except Exception:
        return []
    rows = (
        Product.query.filter(Product.name.ilike(f"%{q}%"))
        .order_by(Product.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for p in rows:
        stock = getattr(p, "quantity", None)
        out.append(
            {
                "type": "product",
                "id": p.id,
                "title": p.name,
                "subtitle": f"المخزون {stock}" if stock is not None else "",
                "summary": str(getattr(p, "sale_price", "") or ""),
                "highlight": q,
            }
        )
    return out


def _search_invoices(
    q: str,
    phone: str,
    limit: int,
    *,
    branch_id: int | None,
    show_money: bool,
) -> list[dict]:
    try:
        from models.invoice import Invoice
        from models.customer import Customer
        from sqlalchemy import or_, cast, String
    except Exception:
        return []

    filters = []
    if q.isdigit():
        filters.append(Invoice.id == int(q))
    filters.append(Invoice.customer_name.ilike(f"%{q}%"))
    filters.append(Invoice.status.ilike(f"%{q}%"))
    # Match product names via note if present
    if hasattr(Invoice, "note"):
        filters.append(Invoice.note.ilike(f"%{q}%"))

    query = Invoice.query.filter(or_(*filters))
    if branch_id:
        query = query.filter(Invoice.branch_id == branch_id)
    rows = query.order_by(Invoice.id.desc()).limit(limit).all()
    out = []
    for inv in rows:
        total = getattr(inv, "total", None) if show_money else None
        out.append(
            {
                "type": "invoice",
                "id": inv.id,
                "title": f"INV-{inv.id}",
                "subtitle": inv.customer_name or "",
                "summary": f"{inv.status or ''} · {total if total is not None else '—'}",
                "highlight": q,
                "status": inv.status,
            }
        )
    return out


def _search_calls(q: str, phone: str, limit: int, *, employee_id: int) -> list[dict]:
    from sqlalchemy import or_

    filters = []
    if len(phone) >= 3:
        filters.append(PhoneCallLog.phone_e164.contains(phone))
        filters.append(PhoneCallLog.phone_normalized.contains(phone))
    if q:
        filters.append(PhoneCallLog.synced_note.ilike(f"%{q}%"))
        if hasattr(PhoneCallLog, "outcome"):
            filters.append(PhoneCallLog.outcome.ilike(f"%{q}%"))
    if not filters:
        return []
    rows = (
        PhoneCallLog.query.filter(PhoneCallLog.employee_id == employee_id)
        .filter(or_(*filters))
        .order_by(PhoneCallLog.started_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for row in rows:
        out.append(
            {
                "type": "call",
                "id": row.id,
                "title": row.phone_e164,
                "subtitle": getattr(row, "call_status", None) or "",
                "summary": getattr(row, "outcome", None) or "",
                "highlight": q,
            }
        )
    return out
