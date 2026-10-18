"""Prepare bounded on-hand snapshots; reconcile dated counts only against unchanged sources."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from extensions import db
from .common import AuditError, can, check_version, dumps, integer, require, text
from .models import InventoryCountOfflineTicket
from .service import ensure_counting, get_line, line_data, session_data, time
from .stock import stock_state, product_data


def prepare(row, payload, user):
    require("inventory.audit.count")
    ensure_counting(row)
    identifiers = payload.get("line_ids")
    if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 100:
        raise AuditError("اختر من 1 إلى 100 صنف لتنزيل الدفعة")
    identifiers = [integer(value, minimum=1) for value in identifiers]
    if len(set(identifiers)) != len(identifiers):
        raise AuditError("دفعة التنزيل تحتوي أصنافاً مكررة")
    records = []
    for identifier in identifiers:
        line = get_line(row, identifier)
        if line.ticket or line.excluded:
            raise AuditError("أكمل أو ألغ الإدخال المفتوح قبل تنزيل الأصناف", "open_count", 409)
        quantity, stamp = stock_state(line, lock=True)
        ticket = InventoryCountOfflineTicket(token=str(uuid4()), session_id=row.id, line_id=line.id,
            actor_id=user.id, version=line.version, quantity=quantity, stamp=stamp,
            product_snapshot_json=dumps(product_data(line, show_cost=True, saved=False)))
        db.session.add(ticket)
        db.session.flush()
        captured = line_data(line)
        captured["product"] = product_data(line, show_cost=can("inventory.audit.cost"), saved=False)
        records.append({"line": captured, "ticket": ticket.token, "version": ticket.version,
            "issued_at": time(ticket.created_at), **({"expected_quantity": quantity} if can("inventory.audit.system") else {})})
    result = {"session_id": row.id, "snapshot": session_data(row), "records": records,
              "snapshot_permissions": [name for name in ("inventory.audit.system", "inventory.audit.cost") if can(name)]}
    return result, {"prepared_records": len(records), "source": "on_hand"}


def save(row, payload, user):
    require("inventory.audit.count")
    ensure_counting(row)
    line = get_line(row, payload.get("line_id"))
    check_version(line, payload.get("version"))
    ticket = db.session.get(InventoryCountOfflineTicket, text(payload.get("ticket"), limit=36, required=True))
    if not ticket or ticket.session_id != row.id or ticket.line_id != line.id or ticket.actor_id != user.id:
        raise AuditError("لقطة العد غير صالحة لهذا الموظف والصنف", "count_ticket", 409)
    if ticket.consumed_at or ticket.version != line.version or line.ticket or line.excluded:
        raise AuditError("تغيّر عد الصنف؛ راجع التعارض وأعد العد", "conflict", 409)
    now = datetime.utcnow()
    if now - ticket.created_at > timedelta(hours=24):
        raise AuditError("لقطة الجرد انتهت؛ نزّل لقطة جديدة وأعد العد", "snapshot_expired", 409)
    counted_at = text(payload.get("counted_at"), limit=40, required=True)
    try:
        observed = datetime.fromisoformat(counted_at.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError()
        observed = observed.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise AuditError("وقت العد المحلي غير صالح")
    if observed < ticket.created_at - timedelta(minutes=5) or observed > now + timedelta(minutes=5):
        raise AuditError("وقت الجهاز لا يطابق لقطة الجرد؛ تحقق من الساعة وأعد العد", "count_time", 409)
    _current, stamp = stock_state(line, lock=True)
    if stamp != ticket.stamp:
        raise AuditError("حدثت حركة بعد تنزيل اللقطة؛ لا يطبّق العد القديم، أعد العد", "stock_conflict", 409)
    before = line.counted_quantity
    line.counted_quantity = integer(payload.get("quantity"))
    line.expected_quantity, line.counted_stamp = ticket.quantity, stamp
    line.counted_at, line.counted_by = observed, user.id
    line.product_snapshot_json = ticket.product_snapshot_json if ticket.product_snapshot_json != "{}" else dumps(product_data(line, show_cost=True, saved=False))
    line.notes = text(payload.get("notes", ""))
    line.version += 1
    row.version += 1
    line.resolution, line.resolution_note, line.investigation_json = "unreviewed", "", "{}"
    line.reviewed_by = line.reviewed_at = line.investigation_stamp = None
    ticket.consumed_at = now
    return {"session_id": row.id, "line_id": line.id, "version": line.version}, {
        "before": before, "after": line.counted_quantity, "expected": ticket.quantity,
        "count_started_at": time(ticket.created_at), "counted_at": time(observed), "synced_at": time(now),
        "notes": line.notes, "offline": True}
