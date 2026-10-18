"""Unified movements feed: receipts + supplier payments + expenses."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_

from models.expense import Expense
from models.receipt import Receipt
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from modules.receipts.services.helpers import parse_date, parse_int
from modules.receipts.services.receipt_service import dashboard_stats as receipt_dashboard_stats
from utils.expense_categories import resolve_category_label


KIND_RECEIPT = "receipt"
KIND_SUPPLIER = "supplier_payment"
KIND_EXPENSE = "expense"

KIND_LABELS = {
    KIND_RECEIPT: "قبض",
    KIND_SUPPLIER: "تسديد مورد",
    KIND_EXPENSE: "مصروف / راتب",
}


def _utc_day_start(day):
    # SupplierPayment timestamps are UTC; date filters are business days in Iraq.
    return datetime.combine(day,datetime.min.time(),tzinfo=ZoneInfo("Asia/Baghdad")).astimezone(timezone.utc).replace(tzinfo=None)


def _parse_bound(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return parse_date(value)


def list_movements(filters: dict | None = None) -> dict:
    filters = filters or {}
    kind = (filters.get("kind") or filters.get("movement_type") or "").strip()
    page = max(1, parse_int(filters.get("page"), 1))
    per_page = min(100, max(1, parse_int(filters.get("per_page"), 25)))
    date_from = _parse_bound(filters.get("date_from"))
    date_to = _parse_bound(filters.get("date_to"))
    q = (filters.get("q") or filters.get("search") or "").strip()
    status = (filters.get("status") or "").strip()

    items: list[dict] = []
    if not kind or kind == KIND_RECEIPT:
        items.extend(_receipt_rows(date_from, date_to, q, status, filters))
    if not kind or kind == KIND_SUPPLIER:
        if not status or status == "معتمد":
            items.extend(_supplier_payment_rows(date_from, date_to, q))
    if not kind or kind == KIND_EXPENSE:
        if not status or status == "معتمد":
            items.extend(_expense_rows(date_from, date_to, q, filters))

    items.sort(key=lambda r: (r.get("sort_ts") or "", r.get("id") or 0), reverse=True)
    total = len(items)
    page_items = items[(page - 1) * per_page : page * per_page]
    for row in page_items:
        row.pop("sort_ts", None)

    stats = _combined_stats(filters, date_from, date_to)
    return {
        "items": page_items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "stats": stats,
        "filters": filters,
        "kind_labels": KIND_LABELS,
    }


def _receipt_rows(date_from, date_to, q, status, filters) -> list[dict]:
    from modules.receipts.services import receipt_service

    rf = {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "q": q,
        "status": status,
        "source_type": filters.get("source_type"),
        "payment_method": filters.get("payment_method"),
        "created_by": filters.get("created_by"),
        "treasury_account_id": filters.get("treasury_account_id"),
    }
    rows = receipt_service.list_receipts_query(rf).limit(500).all()
    out = []
    for r in rows:
        d = receipt_service.receipt_to_dict(r)
        sort_ts = ""
        if r.receipt_date:
            sort_ts = r.receipt_date.isoformat()
        if r.created_at:
            sort_ts = f"{sort_ts}T{r.created_at.strftime('%H:%M:%S')}"
        out.append(
            {
                "kind": KIND_RECEIPT,
                "kind_label": KIND_LABELS[KIND_RECEIPT],
                "id": r.id,
                "ref": d.get("receipt_number"),
                "date": d.get("receipt_date"),
                "party_name": d.get("source_name") or "—",
                "party_type": d.get("source_type"),
                "amount": d.get("amount"),
                "direction": "in",
                "status": d.get("status"),
                "status_label": d.get("status"),
                "payment_method": d.get("payment_method"),
                "created_by_name": d.get("creator_name"),
                "detail_url": f"/receipts/{r.id}",
                "can_cancel": d.get("status") != "ملغى",
                "can_print": True,
                "sort_ts": sort_ts,
                "subtype": None,
            }
        )
    return out


def _supplier_payment_rows(date_from, date_to, q) -> list[dict]:
    query = SupplierPayment.query.filter(
        or_(SupplierPayment.deleted_at.is_(None), SupplierPayment.deleted_at == None),  # noqa: E711
        or_(
            SupplierPayment.payment_method.is_(None),
            SupplierPayment.payment_method != "offset",
        ),
    )
    if date_from:
        query = query.filter(SupplierPayment.created_at >= _utc_day_start(date_from))
    if date_to:
        query = query.filter(SupplierPayment.created_at < _utc_day_start(date_to+timedelta(days=1)))
    if q:
        like = f"%{q}%"
        query = query.outerjoin(Supplier, Supplier.id == SupplierPayment.supplier_id).filter(
            or_(
                Supplier.name.ilike(like),
                SupplierPayment.document_number.ilike(like),
                SupplierPayment.note.ilike(like),
            )
        )
    rows = query.order_by(SupplierPayment.id.desc()).limit(500).all()
    out = []
    for p in rows:
        supplier = Supplier.query.get(p.supplier_id) if p.supplier_id else None
        name = supplier.name if supplier else "—"
        created = p.created_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Baghdad")) if p.created_at else None
        day = created.date().isoformat() if created else None
        sort_ts = created.isoformat() if created else (day or "")
        ref = (p.document_number or "").strip() or f"SP-{p.id}"
        out.append(
            {
                "kind": KIND_SUPPLIER,
                "kind_label": KIND_LABELS[KIND_SUPPLIER],
                "id": p.id,
                "ref": ref,
                "date": day,
                "party_name": name,
                "party_type": "supplier",
                "amount": int(p.amount or 0),
                "direction": "out",
                "status": "معتمد",
                "status_label": "معتمد",
                "payment_method": p.payment_method or "cash",
                "created_by_name": "—",
                "detail_url": f"/suppliers/{p.supplier_id}" if p.supplier_id else "/suppliers",
                "can_cancel": False,
                "can_print": False,
                "sort_ts": sort_ts,
                "subtype": None,
            }
        )
    return out


def _expense_rows(date_from, date_to, q, filters) -> list[dict]:
    query = Expense.query
    if date_from:
        query = query.filter(Expense.expense_date >= date_from)
    if date_to:
        query = query.filter(Expense.expense_date <= date_to)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Expense.title.ilike(like), Expense.note.ilike(like), Expense.category.ilike(like))
        )
    subtype = (filters.get("subtype") or "").strip()
    if subtype == "payroll":
        query = query.filter(
            or_(
                Expense.employee_payment_id.isnot(None),
                Expense.note.ilike("payroll:%"),
            )
        )
    rows = query.order_by(Expense.id.desc()).limit(500).all()
    out = []
    for e in rows:
        note = str(e.note or "")
        is_payroll = bool(e.employee_payment_id) or note.startswith("payroll:")
        day = e.expense_date.isoformat() if e.expense_date else None
        created = e.created_at
        sort_ts = ""
        if day:
            sort_ts = day
        if created:
            sort_ts = f"{day or ''}T{created.strftime('%H:%M:%S')}"
        cat_label = resolve_category_label(e.category)
        out.append(
            {
                "kind": KIND_EXPENSE,
                "kind_label": "راتب موظف" if is_payroll else KIND_LABELS[KIND_EXPENSE],
                "id": e.id,
                "ref": e.title,
                "date": day,
                "party_name": e.title,
                "party_type": "expense",
                "amount": int(e.amount or 0),
                "direction": "out",
                "status": "معتمد",
                "status_label": cat_label,
                "payment_method": None,
                "created_by_name": "—",
                "detail_url": "/expenses",
                "can_cancel": False,
                "can_print": False,
                "sort_ts": sort_ts,
                "subtype": "payroll" if is_payroll else None,
                "category": e.category,
            }
        )
    return out


def _combined_stats(filters, date_from, date_to) -> dict:
    rf = dict(filters or {})
    rf["date_from"] = date_from.isoformat() if date_from else rf.get("date_from")
    rf["date_to"] = date_to.isoformat() if date_to else rf.get("date_to")
    receipt_stats = receipt_dashboard_stats(rf)

    pay_q = SupplierPayment.query.filter(
        or_(SupplierPayment.deleted_at.is_(None), SupplierPayment.deleted_at == None),  # noqa: E711
        or_(
            SupplierPayment.payment_method.is_(None),
            SupplierPayment.payment_method != "offset",
        ),
    )
    if date_from:
        pay_q = pay_q.filter(SupplierPayment.created_at >= _utc_day_start(date_from))
    if date_to:
        pay_q = pay_q.filter(SupplierPayment.created_at < _utc_day_start(date_to+timedelta(days=1)))
    supplier_out = int(pay_q.with_entities(func.coalesce(func.sum(SupplierPayment.amount), 0)).scalar() or 0)
    supplier_count = pay_q.count()

    exp_q = Expense.query
    if date_from:
        exp_q = exp_q.filter(Expense.expense_date >= date_from)
    if date_to:
        exp_q = exp_q.filter(Expense.expense_date <= date_to)
    expense_out = int(exp_q.with_entities(func.coalesce(func.sum(Expense.amount), 0)).scalar() or 0)
    expense_count = exp_q.count()

    outbound_total = supplier_out + expense_out
    return {
        **receipt_stats,
        "outbound_total": outbound_total,
        "supplier_payment_amount": supplier_out,
        "supplier_payment_count": supplier_count,
        "expense_amount": expense_out,
        "expense_count": expense_count,
        "inbound_total": int(receipt_stats.get("total_amount") or 0),
    }
