"""Persistent counts with explicit review; counting does not mutate any stock."""
import json
from datetime import datetime
from uuid import uuid4

from flask import session
from sqlalchemy import case, func, or_

from extensions import db
from models.employee import Employee
from models.product import Product
from models.inventory_audit import InventoryStockSnapshot
from .common import AuditError, can, check_version, dumps, get_session, integer, require, text
from .models import InventoryCountEvent, InventoryCountLine, InventoryCountSession
from .stock import planned_products, product_data, product_identity, scope_locations, stock_state


def time(value):
    return value.isoformat() + "Z" if value else None


def lines(row):
    return InventoryCountLine.query.filter_by(session_id=row.id).order_by(InventoryCountLine.id)


def get_line(row, line_id):
    line = lines(row).filter_by(id=integer(line_id, minimum=1)).first()
    if not line:
        raise AuditError("سطر الجرد غير موجود في هذه الجلسة", "not_found", 404)
    return line


def ensure_counting(row):
    if row.status != "counting":
        if row.status == "paused":
            raise AuditError("الجلسة متوقفة مؤقتاً؛ استأنف الجرد قبل إدخال أو تعديل العدد", "state", 409)
        raise AuditError("الجلسة مقفلة للعد؛ أعد فتح المراجعة بصلاحيتها قبل التعديل", "state", 409)


def line_data(line, *, inspect_current=True):
    show_system, show_cost = can("inventory.audit.system"), can("inventory.audit.cost")
    conflict, current, current_stamp = False, None, None
    if inspect_current and line.counted_quantity is not None and not line.excluded:
        try:
            current, current_stamp = stock_state(line)
            conflict = current_stamp != line.counted_stamp
        except AuditError:
            conflict = True
    difference = line.counted_quantity - line.expected_quantity if line.counted_quantity is not None else None
    status = "excluded" if line.excluded else "uncounted" if difference is None else "conflict" if conflict else (
        "shortage" if difference < 0 else "surplus" if difference > 0 else "matched")
    return {"id": line.id, "location_key": line.location_key, "branch_id": line.branch_id,
        "warehouse_id": line.warehouse_id, "product": product_data(line, show_cost=show_cost, saved=line.counted_quantity is not None or not inspect_current), "version": line.version,
        "counted_quantity": line.counted_quantity, "expected_quantity": line.expected_quantity if show_system else None,
        "baseline_quantity": line.baseline_quantity if show_system else None,
        "current_quantity": current if show_system else None, "difference": difference if show_system else None,
        "status": status if show_system or status in ("excluded", "uncounted", "conflict") else "counted",
        "conflict": conflict, "counted_at": time(line.counted_at), "counted_by": line.counted_by,
        "notes": line.notes, "excluded": line.excluded, "resolution": line.resolution if show_system else "reviewed" if line.reviewed_by else "unreviewed",
        "resolution_note": line.resolution_note if show_system else "", "reviewed_by": line.reviewed_by, "reviewed_at": time(line.reviewed_at),
        "posted_delta": line.posted_delta if show_system else None, "posted_cost": line.posted_cost if show_cost else None,
        "movement_id": line.movement_id, "journal_entry_id": line.journal_entry_id,
        "count_open": bool(line.ticket), "count_open_by": line.ticket_by if line.ticket else None}


def session_data(row):
    all_lines = lines(row).all()
    counted = [line for line in all_lines if line.counted_quantity is not None and not line.excluded]
    differences = [line.counted_quantity - line.expected_quantity for line in counted]
    creator = db.session.get(Employee, row.created_by)
    stats = {"planned": len(all_lines), "counted": len(counted),
             "uncounted": sum(line.counted_quantity is None and not line.excluded for line in all_lines),
             "excluded": sum(line.excluded for line in all_lines)}
    if can("inventory.audit.system"):
        stats.update(unreviewed=sum(bool(delta) and line.resolution == "unreviewed" for line, delta in zip(counted, differences)), matched=sum(delta == 0 for delta in differences), shortage=sum(delta < 0 for delta in differences),
            surplus=sum(delta > 0 for delta in differences), shortage_units=sum(-delta for delta in differences if delta < 0),
            surplus_units=sum(delta for delta in differences if delta > 0), net_units=sum(differences))
    return {"id": row.id, "number": row.number, "title": row.title, "ledger_kind": row.ledger_kind,
        "locations": json.loads(row.locations_json), "status": row.status, "version": row.version, "stats": stats,
        "created_by": row.created_by, "created_by_name": creator.name if creator else str(row.created_by),
        "created_at": time(row.created_at), "submitted_at": time(row.submitted_at), "approved_by": row.approved_by,
        "approved_at": time(row.approved_at), "posted_by": row.posted_by, "posted_at": time(row.posted_at),
        "review_note": row.review_note}


def create(payload, user):
    require("inventory.audit.count")
    kind = payload.get("ledger_kind", "branch")
    selected = scope_locations(kind, payload.get("location_keys"))
    row = InventoryCountSession(number=f"INV-{datetime.utcnow():%Y%m%d}-{uuid4().hex[:10].upper()}",
        tenant_key=session["tenant_slug"], ledger_kind=kind, locations_json=dumps(selected),
        title=text(payload.get("title", ""), limit=150), created_by=user.id)
    db.session.add(row)
    db.session.flush()
    for location in selected:
        for product, variants in planned_products(location, kind):
            for variant in variants or [None]:
                line = InventoryCountLine(session_id=row.id, location_key=location["key"],
                    branch_id=location["branch_id"], warehouse_id=location["warehouse_id"], product_id=product.id,
                    variant_id=variant.id if variant else 0, variant_name=variant.color_name if variant else "",
                    catalog_key=product_identity(product), baseline_quantity=0, baseline_stamp="")
                quantity, stamp = stock_state(line)
                line.baseline_quantity, line.baseline_stamp = quantity, stamp
                line.product_snapshot_json = dumps(product_data(line, show_cost=True, saved=False))
                db.session.add(line)
            if kind == "branch":
                db.session.add(InventoryStockSnapshot(snapshot_key=uuid4().hex, product_id=product.id,
                    branch_id=location["branch_id"], quantity=sum(int(v.quantity) for v in variants) if variants else quantity,
                    session_id=str(row.id), source="inventory_count_start"))
    return {"session_id": row.id}, {"locations": selected, "title": row.title}


def begin_count(row, payload, user):
    require("inventory.audit.count")
    ensure_counting(row)
    line = get_line(row, payload.get("line_id"))
    check_version(line, payload.get("version"))
    if line.excluded:
        raise AuditError("الصنف مستبعد؛ أعده للجلسة بمراجعة موثقة أولاً", "state", 409)
    if line.ticket and line.ticket_by != user.id:
        raise AuditError("موظف آخر بدأ عد الصنف؛ أكمل الإدخال أو اطلب إغلاقه من المسؤول", "count_in_progress", 409)
    quantity, stamp = stock_state(line, lock=True)
    other = InventoryCountLine.query.join(InventoryCountSession).filter(
        InventoryCountLine.id != line.id, InventoryCountLine.location_key == line.location_key,
        InventoryCountLine.product_id == line.product_id, InventoryCountLine.variant_id == line.variant_id,
        InventoryCountSession.status.in_(["counting", "paused", "pending_review", "approved"]),
        InventoryCountLine.counted_quantity.isnot(None), InventoryCountLine.excluded.is_(False)).count()
    line.ticket, line.ticket_quantity, line.ticket_stamp = str(uuid4()), quantity, stamp
    line.ticket_product_json = dumps(product_data(line, show_cost=True, saved=False))
    line.ticket_at, line.ticket_by = datetime.utcnow(), user.id
    line.version += 1
    row.version += 1
    result = {"session_id": row.id, "line_id": line.id, "version": line.version,
              "ticket": line.ticket, "started_at": time(line.ticket_at), "concurrent_counts": other}
    if can("inventory.audit.system"):
        result["expected_quantity"] = quantity
    return result, {"line_id": line.id, "expected": quantity, "stamp": stamp, "previous_count": line.counted_quantity}


def save_count(row, payload, user):
    require("inventory.audit.count")
    ensure_counting(row)
    line = get_line(row, payload.get("line_id"))
    check_version(line, payload.get("version"))
    if line.excluded or not line.ticket or payload.get("ticket") != line.ticket or line.ticket_by != user.id:
        raise AuditError("ابدأ العد من هذا الجهاز والموظف قبل تثبيت العدد", "count_ticket", 409)
    quantity = integer(payload.get("quantity"))
    _current, stamp = stock_state(line, lock=True)
    if stamp != line.ticket_stamp:
        raise AuditError("المخزون تغيّر أثناء العد؛ أعد العد قبل الحفظ", "stock_conflict", 409)
    before = line.counted_quantity
    line.counted_quantity, line.expected_quantity, line.counted_stamp = quantity, line.ticket_quantity, stamp
    line.counted_at, line.counted_by = datetime.utcnow(), user.id
    line.product_snapshot_json = line.ticket_product_json
    line.notes = text(payload.get("notes", ""))
    line.ticket = None
    line.version += 1
    line.resolution, line.resolution_note = "unreviewed", ""
    line.reviewed_by = line.reviewed_at = None
    line.investigation_json, line.investigation_stamp = "{}", None
    row.version += 1
    return {"session_id": row.id, "line_id": line.id, "version": line.version}, {
        "before": before, "after": quantity, "expected": line.expected_quantity,
        "count_started_at": time(line.ticket_at), "counted_at": time(line.counted_at), "notes": line.notes}


def cancel_count(row, payload, user):
    require("inventory.audit.count")
    ensure_counting(row)
    line = get_line(row, payload.get("line_id"))
    check_version(line, payload.get("version"))
    if not line.ticket or payload.get("ticket") != line.ticket or line.ticket_by != user.id:
        raise AuditError("بدء العد تغيّر؛ حدّث الصنف قبل إلغاء الإدخال", "count_ticket", 409)
    line.ticket = None
    line.version += 1
    row.version += 1
    return {"session_id": row.id, "line_id": line.id, "version": line.version}, {"reason": "إلغاء إدخال غير مثبت؛ العدد السابق محفوظ"}


def release_ticket(row, payload, user):
    require("inventory.audit.review")
    ensure_counting(row)
    line = get_line(row, payload.get("line_id"))
    check_version(line, payload.get("version"))
    reason = text(payload.get("reason"), required=True)
    if not line.ticket:
        raise AuditError("لا يوجد إدخال مفتوح لهذا الصنف", "state", 409)
    previous = line.ticket_by
    line.ticket = None
    line.version += 1
    row.version += 1
    return {"session_id":row.id, "line_id":line.id, "version":line.version}, {"reason":reason, "previous_counter":previous}


def exclude(row, payload, user):
    require("inventory.audit.review")
    ensure_counting(row)
    line = get_line(row, payload.get("line_id"))
    check_version(line, payload.get("version"))
    reason = text(payload.get("reason"), required=True)
    value = payload.get("excluded")
    if not isinstance(value, bool):
        raise AuditError("اختر استبعاد الصنف أو إعادته للجلسة")
    line.excluded, line.notes, line.ticket = value, reason, None
    line.version += 1
    row.version += 1
    return {"session_id": row.id, "line_id": line.id}, {"excluded": value, "reason": reason}


def review_line(row, payload, user):
    require("inventory.audit.review")
    require("inventory.audit.system")
    if row.status not in ("counting", "pending_review"):
        raise AuditError("الجلسة لا تقبل تعديل المراجعة الآن", "state", 409)
    line = get_line(row, payload.get("line_id"))
    check_version(line, payload.get("version"))
    resolution = payload.get("resolution")
    if resolution not in ("loss", "surplus", "unexplained"):
        raise AuditError("اختر نتيجة مراجعة صالحة")
    if line.excluded or line.counted_quantity is None:
        raise AuditError("جرد الصنف أولاً قبل مراجعة الفرق")
    _quantity, stamp = stock_state(line, lock=True)
    if stamp != line.counted_stamp:
        raise AuditError("تغيّر المخزون بعد العد؛ أعد العد", "stock_conflict", 409)
    delta = line.counted_quantity - line.expected_quantity
    if (resolution == "loss" and delta >= 0) or (resolution == "surplus" and delta <= 0):
        raise AuditError("نتيجة المراجعة لا تطابق إشارة الفرق")
    reason = text(payload.get("reason"), required=True)
    line.resolution, line.resolution_note = resolution, reason
    line.reviewed_by, line.reviewed_at = user.id, datetime.utcnow()
    line.version += 1
    row.version += 1
    return {"session_id": row.id, "line_id": line.id}, {"resolution": resolution, "reason": reason, "difference": delta}


def validate_counts(row, *, approval=False):
    if lines(row).filter(InventoryCountLine.ticket.isnot(None), InventoryCountLine.excluded.is_(False)).first():
        raise AuditError("يوجد عد مفتوح؛ ثبته أو ألغ الإدخال قبل المراجعة", "open_count", 409)
    # A draft explicitly linked to this discrepancy must be received or canceled
    # before settlement. Otherwise a later receipt could book the same gap twice.
    for event in InventoryCountEvent.query.filter_by(session_id=row.id, action="transfer_draft"):
        detail = json.loads(event.detail_json)
        if detail["transfer_kind"] == "warehouse":
            from modules.wholesale.models.warehouse import WarehouseTransfer
            document = db.session.get(WarehouseTransfer, detail["transfer_id"])
        else:
            from models.branch import StockTransfer
            document = db.session.get(StockTransfer, detail["transfer_id"])
        if not document or document.status not in ("received", "cancelled", "canceled"):
            raise AuditError("راجع التحويل المرتبط بالفرق وأكمل استلامه أو إلغاءه، ثم أعد العد قبل التسوية", "pending_transfer", 409)
    counted = lines(row).filter(InventoryCountLine.counted_quantity.isnot(None), InventoryCountLine.excluded.is_(False)).all()
    if not counted:
        raise AuditError("أضف عدّاً واحداً على الأقل قبل المراجعة")
    for line in counted:
        _quantity, stamp = stock_state(line, lock=True)
        if stamp != line.counted_stamp or line.ticket:
            raise AuditError("تغيّر المخزون أو يوجد عد غير مثبت؛ أعد عد الأصناف المتأثرة", "stock_conflict", 409)
        if approval and line.counted_quantity != line.expected_quantity and line.resolution not in ("loss", "surplus"):
            raise AuditError("الفروقات غير المفسرة تحتاج إعادة عد أو سبب تسوية معتمد", "unreviewed", 409)
    return counted


def transition(row, payload, user):
    action = payload.get("action")
    check_version(row, payload.get("version"))
    reason = text(payload.get("reason", ""))
    if action == "pause":
        require("inventory.audit.count")
        ensure_counting(row)
        if lines(row).filter(InventoryCountLine.ticket.isnot(None)).first():
            raise AuditError("أكمل أو ألغ إدخالات العد المفتوحة قبل إيقاف الجلسة", "open_count", 409)
        # A device that has not seen the pause must not later apply its old lease.
        # Saved counts remain untouched; queued device counts remain recoverable.
        from .models import InventoryCountOfflineTicket
        InventoryCountOfflineTicket.query.filter_by(session_id=row.id, consumed_at=None).update(
            {InventoryCountOfflineTicket.consumed_at: datetime.utcnow()}, synchronize_session=False)
        row.status = "paused"
    elif action == "resume":
        require("inventory.audit.count")
        if row.status != "paused":
            raise AuditError("الجلسة ليست متوقفة مؤقتاً", "state", 409)
        row.status = "counting"
    elif action == "submit":
        require("inventory.audit.count")
        ensure_counting(row)
        validate_counts(row)
        missing = lines(row).filter(InventoryCountLine.counted_quantity.is_(None), InventoryCountLine.excluded.is_(False)).count()
        if missing and payload.get("acknowledge_partial") is not True:
            raise AuditError("الجرد غير مكتمل؛ راجع الأصناف غير المجردة وأكد الجرد الجزئي صراحة", "incomplete", 409)
        row.status, row.submitted_at = "pending_review", datetime.utcnow()
    elif action == "reopen":
        require("inventory.audit.review")
        reason = text(payload.get("reason"), required=True)
        if row.status not in ("pending_review", "approved"):
            raise AuditError("الجلسة لا يمكن إعادة فتحها", "state", 409)
        row.status, row.approved_by, row.approved_at = "counting", None, None
    elif action == "approve":
        require("inventory.audit.approve")
        require("inventory.audit.system")
        if row.status != "pending_review":
            raise AuditError("أرسل الجلسة للمراجعة أولاً", "state", 409)
        validate_counts(row, approval=True)
        from modules.finance.common import policy
        if policy()["separate_approval"] and row.created_by == user.id:
            raise AuditError("سياسة الشركة تتطلب اعتماد موظف آخر", "separate_approval", 403)
        row.status, row.approved_by, row.approved_at = "approved", user.id, datetime.utcnow()
    else:
        raise AuditError("إجراء الجلسة غير معروف")
    row.review_note = reason
    row.version += 1
    return {"session_id": row.id, "version": row.version}, {"action": action, "reason": reason, "status": row.status}


def search_lines(row, query="", location_key=None, *, counted=None, status=None, page=1, page_size=30, exact=False):
    query = text(query, limit=150)
    page, page_size = integer(page, minimum=1, maximum=100000), integer(page_size, minimum=1, maximum=100)
    q = lines(row)
    if location_key:
        if location_key not in {loc["key"] for loc in json.loads(row.locations_json)}:
            raise AuditError("الموقع خارج نطاق الجلسة", "forbidden", 403)
        q = q.filter_by(location_key=location_key)
    if counted is True:
        q = q.filter(InventoryCountLine.counted_quantity.isnot(None))
    elif counted is False:
        q = q.filter(InventoryCountLine.counted_quantity.is_(None))
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        conditions = [Product.sku == query, Product.barcode == query] if exact else [
            Product.name.ilike(like, escape="\\"), Product.sku.ilike(like, escape="\\"), Product.barcode.ilike(like, escape="\\")]
        if query.isascii() and query.isdigit() and len(query) <= 10 and int(query) <= 2147483647:
            conditions.append(Product.id == int(query))
        if not exact and db.session.connection().dialect.name == "sqlite":
            valid = case((func.json_valid(Product.meta_json) == 1, Product.meta_json), else_="{}")
            conditions.append(func.json_extract(valid, "$.model").ilike(like, escape="\\"))
        product_ids = Product.query.execution_options(skip_branch_scope=True).filter(or_(*conditions)).with_entities(Product.id)
        q = q.filter(InventoryCountLine.product_id.in_(product_ids)) if exact else q.filter(or_(
            InventoryCountLine.product_id.in_(product_ids), InventoryCountLine.variant_name.ilike(like, escape="\\")))
    if status in ("shortage", "surplus", "matched"):
        require("inventory.audit.system")
        delta = InventoryCountLine.counted_quantity - InventoryCountLine.expected_quantity
        q = q.filter(InventoryCountLine.excluded.is_(False), delta < 0 if status == "shortage" else delta > 0 if status == "surplus" else delta == 0)
    elif status == "unreviewed":
        q = q.filter(InventoryCountLine.resolution == "unreviewed", InventoryCountLine.counted_quantity.isnot(None))
    elif status == "uncounted":
        q = q.filter(InventoryCountLine.counted_quantity.is_(None), InventoryCountLine.excluded.is_(False))
    elif status == "excluded":
        q = q.filter(InventoryCountLine.excluded.is_(True))
    elif status not in (None, "", "all"):
        raise AuditError("مرشح الجرد غير معروف")
    total = q.count()
    items = [line_data(line, inspect_current=row.status != "posted") for line in q.offset((page - 1) * page_size).limit(page_size)]
    return {"items": items, "page": page, "page_size": page_size, "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size)}


def history(row, line_id=None, *, page=1, page_size=30):
    page, page_size = integer(page, minimum=1, maximum=100000), integer(page_size, minimum=1, maximum=100)
    q = InventoryCountEvent.query.filter_by(session_id=row.id)
    if line_id:
        get_line(row, line_id)
        q = q.filter_by(line_id=line_id)
    items = []
    for event in q.order_by(InventoryCountEvent.id.desc()).offset((page - 1) * page_size).limit(page_size):
        detail = json.loads(event.detail_json)
        # Blind-count staff cannot reconstruct hidden system quantity through history.
        if not can("inventory.audit.system"):
            detail = {key: value for key, value in detail.items() if key in ("before", "after", "notes", "reason", "action", "excluded", "status", "count_started_at", "counted_at")}
            if event.action in ("review_line", "transfer_draft", "post", "investigate"):
                detail = {}
        if not can("inventory.audit.cost"):
            def redact(value):
                if isinstance(value, list):
                    return [redact(item) for item in value]
                if isinstance(value, dict):
                    return {key: redact(item) for key, item in value.items()
                            if key not in ("cost", "unit_cost", "total_cost", "amount", "layers", "valuation", "valuation_reconciliation")}
                return value
            detail = redact(detail)
        items.append({"id": event.id, "line_id": event.line_id, "action": event.action,
            "actor_id": event.actor_id, "actor_name": event.actor_name or f"الموظف #{event.actor_id}",
            "created_at": time(event.created_at), "detail": detail})
    return {"items": items, "page": page, "page_size": page_size, "total": q.count()}
