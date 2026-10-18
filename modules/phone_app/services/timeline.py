"""Unified customer timeline aggregation (no denormalized event table)."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

from extensions import db
from modules.phone_app.models import PhoneCallLog, PhoneCallNote, PhoneFollowupTask
from modules.phone_app.services.permissions import employee_has_phone_perm


def _iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode_cursor(occurred_at: datetime, typ: str, ref_id: int) -> str:
    payload = {
        "t": _iso_z(occurred_at),
        "type": typ,
        "id": ref_id,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _emp(employee_id: int | None) -> dict | None:
    if not employee_id:
        return None
    try:
        from models.employee import Employee

        e = db.session.get(Employee, employee_id)
        if e:
            return {"id": e.id, "name": getattr(e, "name", None)}
    except Exception:
        pass
    return {"id": employee_id, "name": None}


def _branch(branch_id: int | None) -> dict | None:
    if not branch_id:
        return None
    try:
        from models.branch import Branch

        b = db.session.get(Branch, branch_id)
        if b:
            return {"id": b.id, "name": getattr(b, "name", None)}
    except Exception:
        pass
    return {"id": branch_id, "name": None}


def _item(
    *,
    typ: str,
    ref_id: int,
    occurred_at: datetime,
    title: str,
    summary: str,
    employee_id: int | None = None,
    branch_id: int | None = None,
    status: str | None = None,
    metadata: dict | None = None,
) -> dict:
    return {
        "id": f"{typ}_{ref_id}",
        "type": typ,
        "occurred_at": _iso_z(occurred_at),
        "title": title,
        "summary": summary,
        "employee": _emp(employee_id),
        "branch": _branch(branch_id),
        "status": status,
        "reference_type": typ,
        "reference_id": ref_id,
        "metadata": metadata or {},
        "_sort_at": occurred_at,
        "_sort_id": ref_id,
    }


def _duration_label(sec: int | None) -> str:
    if not sec or sec < 0:
        return "—"
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def collect_timeline_events(
    customer_id: int,
    *,
    employee,
    include_financial: bool = True,
    limit_per_source: int = 200,
) -> list[dict]:
    items: list[dict] = []

    # Customer created / updated
    try:
        from models.customer import Customer

        customer = db.session.get(Customer, customer_id)
        if customer and getattr(customer, "created_at", None):
            items.append(
                _item(
                    typ="customer_created",
                    ref_id=customer_id,
                    occurred_at=customer.created_at,
                    title="إنشاء الزبون",
                    summary=getattr(customer, "name", "") or f"#{customer_id}",
                    status="created",
                    metadata={"name": getattr(customer, "name", None)},
                )
            )
    except Exception:
        pass

    calls = (
        PhoneCallLog.query.filter_by(customer_id=customer_id)
        .order_by(PhoneCallLog.started_at.desc())
        .limit(limit_per_source)
        .all()
    )
    for row in calls:
        direction = row.direction or "inbound"
        status = getattr(row, "call_status", None) or "detected"
        title = "مكالمة واردة" if direction == "inbound" else "مكالمة صادرة"
        if status == "missed":
            title = "مكالمة فائتة"
        elif status == "rejected":
            title = "مكالمة مرفوضة"
        summary = f"{status} — مدة {_duration_label(row.duration_sec)}"
        outcome = getattr(row, "outcome", None)
        if outcome:
            summary = f"{summary} · {outcome}"
        items.append(
            _item(
                typ="call",
                ref_id=row.id,
                occurred_at=row.started_at or row.created_at,
                title=title,
                summary=summary,
                employee_id=row.employee_id,
                status=status,
                metadata={
                    "direction": direction,
                    "duration_seconds": row.duration_sec,
                    "outcome": outcome,
                    "phone": row.phone_e164,
                    "has_recording": bool(getattr(row, "recording_path", None)),
                },
            )
        )

    notes = (
        PhoneCallNote.query.filter_by(customer_id=customer_id)
        .order_by(PhoneCallNote.created_at.desc())
        .limit(limit_per_source)
        .all()
    )
    for n in notes:
        body = (n.body or "").strip()
        items.append(
            _item(
                typ="note",
                ref_id=n.id,
                occurred_at=n.created_at,
                title="ملاحظة",
                summary=body[:160],
                employee_id=n.employee_id,
                status="saved",
                metadata={"call_id": n.call_id},
            )
        )

    tasks = (
        PhoneFollowupTask.query.filter_by(customer_id=customer_id)
        .order_by(PhoneFollowupTask.created_at.desc())
        .limit(limit_per_source)
        .all()
    )
    for t in tasks:
        items.append(
            _item(
                typ="task",
                ref_id=t.id,
                occurred_at=t.created_at,
                title=t.title or "مهمة متابعة",
                summary=f"{t.status} · أولوية {getattr(t, 'priority', None) or 'normal'}",
                employee_id=t.employee_id,
                status=t.status,
                metadata={
                    "task_type": getattr(t, "task_type", None),
                    "due_at": _iso_z(t.due_at),
                    "priority": getattr(t, "priority", None),
                    "attempt_count": getattr(t, "attempt_count", 1),
                },
            )
        )

    if include_financial and employee_has_phone_perm(employee, "phone.financial.view"):
        try:
            from models.invoice import Invoice

            invoices = (
                Invoice.query.filter_by(customer_id=customer_id)
                .order_by(Invoice.id.desc())
                .limit(limit_per_source)
                .all()
            )
            for inv in invoices:
                created = getattr(inv, "created_at", None) or datetime.utcnow()
                status = getattr(inv, "status", None)
                total = getattr(inv, "total", None)
                items.append(
                    _item(
                        typ="invoice",
                        ref_id=inv.id,
                        occurred_at=created,
                        title=f"فاتورة #{inv.id}",
                        summary=f"{status or '—'} · {total or 0}",
                        employee_id=getattr(inv, "employee_id", None),
                        branch_id=getattr(inv, "branch_id", None),
                        status=status,
                        metadata={
                            "total": total,
                            "payment_status": getattr(inv, "payment_status", None),
                        },
                    )
                )
                # Order/status change proxy: if updated_at differs meaningfully
                updated = getattr(inv, "updated_at", None)
                if updated and created and updated != created:
                    items.append(
                        _item(
                            typ="order_status",
                            ref_id=inv.id,
                            occurred_at=updated,
                            title="تحديث حالة الطلب",
                            summary=str(status or ""),
                            employee_id=getattr(inv, "employee_id", None),
                            branch_id=getattr(inv, "branch_id", None),
                            status=status,
                            metadata={"invoice_id": inv.id},
                        )
                    )
        except Exception:
            pass

        try:
            from models.invoice import Invoice
            from models.invoice_payment_ledger import InvoicePaymentLedger

            inv_ids = [
                r.id
                for r in Invoice.query.filter_by(customer_id=customer_id)
                .with_entities(Invoice.id)
                .limit(limit_per_source)
                .all()
            ]
            if inv_ids:
                payments = (
                    InvoicePaymentLedger.query.filter(
                        InvoicePaymentLedger.invoice_id.in_(inv_ids)
                    )
                    .order_by(InvoicePaymentLedger.recorded_at.desc())
                    .limit(limit_per_source)
                    .all()
                )
                for p in payments:
                    items.append(
                        _item(
                            typ="payment",
                            ref_id=p.id,
                            occurred_at=p.recorded_at or datetime.utcnow(),
                            title="دفعة",
                            summary=f"{p.amount_delta} · فاتورة #{p.invoice_id}",
                            status="recorded",
                            metadata={
                                "invoice_id": p.invoice_id,
                                "amount_delta": p.amount_delta,
                                "method": getattr(p, "payment_method", None),
                            },
                        )
                    )
        except Exception:
            pass
    else:
        # Non-financial: still show order shells without amounts
        try:
            from models.invoice import Invoice

            invoices = (
                Invoice.query.filter_by(customer_id=customer_id)
                .order_by(Invoice.id.desc())
                .limit(limit_per_source)
                .all()
            )
            for inv in invoices:
                created = getattr(inv, "created_at", None) or datetime.utcnow()
                items.append(
                    _item(
                        typ="order",
                        ref_id=inv.id,
                        occurred_at=created,
                        title=f"طلب #{inv.id}",
                        summary=str(getattr(inv, "status", None) or ""),
                        employee_id=getattr(inv, "employee_id", None),
                        branch_id=getattr(inv, "branch_id", None),
                        status=getattr(inv, "status", None),
                        metadata={},
                    )
                )
        except Exception:
            pass

    return items


def paginate_timeline(
    events: list[dict],
    *,
    cursor: str | None,
    limit: int = 30,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 30), 100))
    # Sort newest first; stable on equal timestamps via type+id
    events.sort(
        key=lambda e: (
            e.get("_sort_at") or datetime.min,
            e.get("_sort_id") or 0,
            e.get("type") or "",
        ),
        reverse=True,
    )

    cur = _decode_cursor(cursor)
    if cur:
        cur_at = _parse_iso(cur.get("t"))
        cur_id = int(cur.get("id") or 0)
        cur_type = str(cur.get("type") or "")
        filtered = []
        for e in events:
            at = e.get("_sort_at")
            if cur_at is None:
                filtered.append(e)
                continue
            if at is None:
                continue
            if at < cur_at:
                filtered.append(e)
            elif at == cur_at:
                eid = int(e.get("_sort_id") or 0)
                et = str(e.get("type") or "")
                if (eid, et) < (cur_id, cur_type):
                    filtered.append(e)
        events = filtered

    page = events[:limit]
    has_more = len(events) > limit
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(
            last["_sort_at"], last["type"], int(last["_sort_id"])
        )

    clean = []
    for e in page:
        row = {k: v for k, v in e.items() if not k.startswith("_")}
        clean.append(row)

    return {
        "items": clean,
        "pagination": {"next_cursor": next_cursor, "has_more": has_more},
    }
