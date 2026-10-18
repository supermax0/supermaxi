"""Extended clinic operations: schedules, inventory, labs, radiology, settlements."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, or_

from extensions import db
from modules.clinics.models import (
    RADIOLOGY_MODALITIES,
    WEEKDAY_LABELS,
    ClinicAppointment,
    ClinicDoctor,
    ClinicDoctorSchedule,
    ClinicDoctorSettlement,
    ClinicDoctorTimeOff,
    ClinicFollowUp,
    ClinicInventoryBatch,
    ClinicInventoryItem,
    ClinicInventoryMovement,
    ClinicInvoice,
    ClinicInvoiceItem,
    ClinicLabOrder,
    ClinicLabOrderItem,
    ClinicLabTest,
    ClinicPatient,
    ClinicPayment,
    ClinicProcedure,
    ClinicProcedureSpecialty,
    ClinicProcedureRecipeItem,
    ClinicRadiologyOrder,
    ClinicRoom,
    ClinicService,
    ClinicSpecialty,
    ClinicVisit,
    ClinicVisitBillLine,
    ClinicVisitProcedure,
)
from modules.clinics.service import (
    _audit,
    _money,
    _parse_date,
    _parse_time,
    _today,
    patient_dict,
)


def _qty(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _qty_float(value) -> float:
    return float(_qty(value))


# ── Schedules / Time off / Rooms ───────────────────────────────────────────


def schedule_dict(row: ClinicDoctorSchedule) -> dict:
    return {
        "id": row.id,
        "doctor_id": row.doctor_id,
        "weekday": row.weekday,
        "weekday_label": WEEKDAY_LABELS[row.weekday] if 0 <= row.weekday < 7 else str(row.weekday),
        "start_time": row.start_time.strftime("%H:%M") if row.start_time else "",
        "end_time": row.end_time.strftime("%H:%M") if row.end_time else "",
        "break_start": row.break_start.strftime("%H:%M") if row.break_start else "",
        "break_end": row.break_end.strftime("%H:%M") if row.break_end else "",
        "slot_minutes": row.slot_minutes,
        "active": bool(row.active),
    }


def list_schedules(tenant_id: int, doctor_id: int | None = None) -> list[dict]:
    query = ClinicDoctorSchedule.query.filter_by(tenant_id=tenant_id, active=True)
    if doctor_id:
        query = query.filter_by(doctor_id=int(doctor_id))
    rows = query.order_by(ClinicDoctorSchedule.doctor_id, ClinicDoctorSchedule.weekday, ClinicDoctorSchedule.start_time).all()
    result = []
    for row in rows:
        data = schedule_dict(row)
        doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=row.doctor_id).first()
        data["doctor_name"] = doctor.full_name if doctor else ""
        result.append(data)
    return result


def upsert_schedule(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    doctor_id = int(payload.get("doctor_id") or 0)
    if not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
        raise ValueError("الطبيب غير موجود")
    weekday = int(payload.get("weekday"))
    if weekday < 0 or weekday > 6:
        raise ValueError("يوم الأسبوع غير صالح")
    start = _parse_time(payload.get("start_time"), "وقت البداية")
    end = _parse_time(payload.get("end_time"), "وقت النهاية")
    if end <= start:
        raise ValueError("وقت النهاية يجب أن يكون بعد البداية")
    break_start = _parse_time(payload["break_start"], "بداية الاستراحة") if payload.get("break_start") else None
    break_end = _parse_time(payload["break_end"], "نهاية الاستراحة") if payload.get("break_end") else None
    if bool(break_start) != bool(break_end):
        raise ValueError("حدد بداية ونهاية الاستراحة معاً")
    if break_start and not (start < break_start < break_end < end):
        raise ValueError("الاستراحة يجب أن تكون داخل فترة استقبال المرضى")
    row = ClinicDoctorSchedule(
        tenant_id=tenant_id,
        branch_id=branch_id,
        doctor_id=doctor_id,
        weekday=weekday,
        start_time=start,
        end_time=end,
        break_start=break_start,
        break_end=break_end,
        slot_minutes=max(5, int(payload.get("slot_minutes") or 15)),
        active=True,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return schedule_dict(row)


def delete_schedule(tenant_id: int, schedule_id: int) -> None:
    row = ClinicDoctorSchedule.query.filter_by(tenant_id=tenant_id, id=schedule_id).first()
    if not row:
        raise ValueError("الجدول غير موجود")
    row.active = False


def time_off_dict(row: ClinicDoctorTimeOff) -> dict:
    return {
        "id": row.id,
        "doctor_id": row.doctor_id,
        "from_date": row.from_date.isoformat(),
        "to_date": row.to_date.isoformat(),
        "from_time": row.from_time.strftime("%H:%M") if row.from_time else "",
        "to_time": row.to_time.strftime("%H:%M") if row.to_time else "",
        "reason": row.reason or "",
    }


def list_time_off(tenant_id: int, doctor_id: int | None = None) -> list[dict]:
    query = ClinicDoctorTimeOff.query.filter_by(tenant_id=tenant_id)
    if doctor_id:
        query = query.filter_by(doctor_id=int(doctor_id))
    rows = query.order_by(ClinicDoctorTimeOff.from_date.desc()).limit(100).all()
    result = []
    for row in rows:
        data = time_off_dict(row)
        doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=row.doctor_id).first()
        data["doctor_name"] = doctor.full_name if doctor else ""
        result.append(data)
    return result


def create_time_off(tenant_id: int, payload: dict, actor_id=None) -> dict:
    doctor_id = int(payload.get("doctor_id") or 0)
    if not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
        raise ValueError("الطبيب غير موجود")
    from_date = _parse_date(payload.get("from_date"), "من تاريخ")
    to_date = _parse_date(payload.get("to_date") or payload.get("from_date"), "إلى تاريخ")
    if to_date < from_date:
        raise ValueError("تاريخ النهاية قبل البداية")
    row = ClinicDoctorTimeOff(
        tenant_id=tenant_id,
        doctor_id=doctor_id,
        from_date=from_date,
        to_date=to_date,
        from_time=_parse_time(payload["from_time"], "من وقت") if payload.get("from_time") else None,
        to_time=_parse_time(payload["to_time"], "إلى وقت") if payload.get("to_time") else None,
        reason=str(payload.get("reason") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return time_off_dict(row)


def doctor_is_off(tenant_id: int, doctor_id: int, day: date, start: time, end: time | None = None) -> bool:
    rows = ClinicDoctorTimeOff.query.filter(
        ClinicDoctorTimeOff.tenant_id == tenant_id,
        ClinicDoctorTimeOff.doctor_id == doctor_id,
        ClinicDoctorTimeOff.from_date <= day,
        ClinicDoctorTimeOff.to_date >= day,
    ).all()
    for row in rows:
        if not row.from_time and not row.to_time:
            return True
        start_bound = row.from_time or time(0, 0)
        end_bound = row.to_time or time(23, 59)
        overlaps = (
            start < end_bound and start_bound < end
            if end is not None
            else start_bound <= start < end_bound
        )
        if overlaps:
            return True
    return False


def doctor_has_shift(tenant_id: int, doctor_id: int, day: date, start: time, end: time | None = None) -> bool:
    schedules = ClinicDoctorSchedule.query.filter_by(
        tenant_id=tenant_id, doctor_id=doctor_id, weekday=day.weekday(), active=True
    ).all()
    if not schedules:
        return True  # no schedule configured = open
    for sch in schedules:
        requested_end = end or start
        if sch.start_time <= start and requested_end <= sch.end_time:
            break_start = getattr(sch, "break_start", None)
            break_end = getattr(sch, "break_end", None)
            if break_start and break_end and start < break_end and break_start < requested_end:
                continue
            return True
    return False


def assert_doctor_available(tenant_id: int, doctor_id: int | None, day: date, start: time, end: time | None = None) -> None:
    if not doctor_id:
        return
    from models.employee import Employee
    from models.hr import HRAttendance, HRLeaveRequest
    from modules.clinics.service import get_or_create_settings

    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
    if not doctor or not doctor.active:
        raise ValueError("الطبيب غير مفعل لاستقبال مواعيد جديدة")
    employee = Employee.query.filter_by(id=doctor.employee_id, tenant_id=tenant_id).first() if doctor.employee_id else None
    profile = employee.hr_profile if employee else None
    employment_status = (profile.employment_status if profile else None) or ("active" if not employee or employee.is_active else "inactive")
    if employment_status in {"terminated", "suspended", "inactive"}:
        raise ValueError("الحالة الوظيفية للطبيب لا تسمح بمواعيد جديدة")
    if employee and HRLeaveRequest.query.filter(
        HRLeaveRequest.employee_id == employee.id,
        HRLeaveRequest.status == "approved",
        HRLeaveRequest.start_date <= day,
        HRLeaveRequest.end_date >= day,
    ).first():
        raise ValueError("الطبيب في إجازة HR معتمدة خلال هذا التاريخ")
    if doctor_is_off(tenant_id, doctor_id, day, start, end):
        raise ValueError("الطبيب لديه حظر تشغيلي في هذا الوقت")
    if not doctor_has_shift(tenant_id, doctor_id, day, start, end):
        raise ValueError("الوقت خارج جدول استقبال مرضى الطبيب أو أثناء الاستراحة")
    settings = get_or_create_settings(tenant_id)
    if day == date.today() and bool(getattr(settings, "doctor_availability_requires_attendance", False)):
        attendance = HRAttendance.query.filter_by(employee_id=employee.id, attendance_date=day).first() if employee else None
        if not attendance or attendance.status not in {"present", "late", "remote"}:
            raise ValueError("يلزم تسجيل حضور الطبيب في HR قبل استقبال مواعيد اليوم")


def update_room(tenant_id: int, room_id: int, payload: dict, actor_id=None) -> dict:
    from modules.clinics.service import room_dict

    row = ClinicRoom.query.filter_by(tenant_id=tenant_id, id=room_id).first()
    if not row:
        raise ValueError("الغرفة غير موجودة")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("اسم الغرفة مطلوب")
        row.name = name
    if "room_type" in payload:
        row.room_type = str(payload.get("room_type") or "consultation").strip() or "consultation"
    if "active" in payload:
        row.active = bool(payload.get("active"))
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    return room_dict(row)


# ── Inventory ──────────────────────────────────────────────────────────────


def inventory_item_dict(row: ClinicInventoryItem, *, include_cost: bool = True) -> dict:
    today = _today()
    batches = ClinicInventoryBatch.query.filter_by(tenant_id=row.tenant_id, item_id=row.id).filter(
        ClinicInventoryBatch.quantity_available > 0
    ).all()
    valid_batch_qty = sum(
        (_qty(b.quantity_available) for b in batches if not b.expiry_date or b.expiry_date >= today),
        Decimal("0"),
    )
    nearest_expiry = min((b.expiry_date for b in batches if b.expiry_date and b.expiry_date >= today), default=None)
    expired_qty = sum(
        (_qty(b.quantity_available) for b in batches if b.expiry_date and b.expiry_date < today),
        Decimal("0"),
    )
    current = _qty(row.current_stock)
    available = valid_batch_qty if row.batch_tracking else current
    average_cost = int(row.average_cost or row.purchase_price or 0)
    if not row.active:
        status = "inactive"
    elif current <= 0:
        status = "out"
    elif row.batch_tracking and available <= 0 and expired_qty > 0:
        status = "expired"
    elif current <= _qty(row.minimum_stock):
        status = "critical" if current <= max(Decimal("1"), _qty(row.minimum_stock) / 2) else "low"
    elif nearest_expiry and nearest_expiry <= today + timedelta(days=30):
        status = "expiring"
    else:
        status = "available"
    payload = {
        "id": row.id,
        "sku": row.sku or "",
        "barcode": row.barcode or "",
        "name": row.name,
        "scientific_name": row.scientific_name or "",
        "category": row.category or "",
        "description": row.description or "",
        "unit": row.unit,
        "selling_price": row.selling_price,
        "current_stock": _qty_float(current),
        "available_stock": _qty_float(available),
        "reserved_stock": 0,
        "expired_stock": _qty_float(expired_qty),
        "minimum_stock": _qty_float(row.minimum_stock),
        "maximum_stock": _qty_float(row.maximum_stock),
        "reorder_point": _qty_float(row.reorder_point),
        "suggested_reorder_qty": _qty_float(row.suggested_reorder_qty),
        "expiry_tracking": bool(row.expiry_tracking),
        "batch_tracking": bool(row.batch_tracking),
        "serial_tracking": bool(row.serial_tracking),
        "requires_cooling": bool(row.requires_cooling),
        "sensitive_item": bool(row.sensitive_item),
        "prevent_expired_usage": bool(row.prevent_expired_usage),
        "default_supplier_id": row.default_supplier_id,
        "active": bool(row.active),
        "low_stock": current <= _qty(row.minimum_stock),
        "nearest_expiry": nearest_expiry.isoformat() if nearest_expiry else "",
        "status": status,
    }
    if include_cost:
        payload.update(
            {
                "purchase_price": row.purchase_price,
                "average_cost": average_cost,
                "last_purchase_cost": int(row.last_purchase_cost or row.purchase_price or 0),
                "inventory_value": int(round(float(current) * average_cost)),
            }
        )
    return payload


def list_inventory(tenant_id: int, q: str = "", low_only: bool = False, *, include_cost: bool = True) -> list[dict]:
    query = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id).filter(ClinicInventoryItem.active.is_(True))
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(
            or_(
                ClinicInventoryItem.name.ilike(like),
                ClinicInventoryItem.sku.ilike(like),
                ClinicInventoryItem.barcode.ilike(like),
            )
        )
    rows = query.order_by(ClinicInventoryItem.name.asc()).all()
    result = [inventory_item_dict(r, include_cost=include_cost) for r in rows]
    if low_only:
        result = [r for r in result if r["low_stock"]]
    return result


def create_inventory_item(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("اسم الصنف مطلوب")
    row = ClinicInventoryItem(
        tenant_id=tenant_id,
        branch_id=branch_id,
        sku=str(payload.get("sku") or "").strip() or None,
        barcode=str(payload.get("barcode") or "").strip() or None,
        name=name,
        scientific_name=str(payload.get("scientific_name") or "").strip() or None,
        category=str(payload.get("category") or "").strip() or None,
        description=str(payload.get("description") or "").strip() or None,
        unit=str(payload.get("unit") or "piece").strip() or "piece",
        purchase_price=_money(payload.get("purchase_price")),
        average_cost=_money(payload.get("opening_cost") or payload.get("purchase_price")),
        last_purchase_cost=_money(payload.get("opening_cost") or payload.get("purchase_price")),
        selling_price=_money(payload.get("selling_price")),
        current_stock=_qty(payload.get("current_stock") or 0),
        minimum_stock=_qty(payload.get("minimum_stock") or 0),
        maximum_stock=_qty(payload.get("maximum_stock") or 0),
        reorder_point=_qty(payload.get("reorder_point") or payload.get("minimum_stock") or 0),
        suggested_reorder_qty=_qty(payload.get("suggested_reorder_qty") or 0),
        expiry_tracking=bool(payload.get("expiry_tracking", False)),
        batch_tracking=bool(payload.get("batch_tracking", False)),
        serial_tracking=bool(payload.get("serial_tracking", False)),
        requires_cooling=bool(payload.get("requires_cooling", False)),
        sensitive_item=bool(payload.get("sensitive_item", False)),
        prevent_expired_usage=bool(payload.get("prevent_expired_usage", True)),
        default_supplier_id=int(payload.get("default_supplier_id") or 0) or None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    opening = _qty(payload.get("current_stock") or 0)
    if opening > 0:
        opening_batch = None
        if row.batch_tracking:
            opening_batch = ClinicInventoryBatch(
                tenant_id=tenant_id,
                item_id=row.id,
                batch_number=f"OPEN-{row.id}",
                quantity_received=opening,
                quantity_available=opening,
                purchase_price=row.average_cost,
            )
            db.session.add(opening_batch)
            db.session.flush()
        db.session.add(
            ClinicInventoryMovement(
                tenant_id=tenant_id,
                item_id=row.id,
                batch_id=opening_batch.id if opening_batch else None,
                movement_type="in",
                quantity=opening,
                stock_before=0,
                stock_after=opening,
                unit_cost=row.average_cost,
                reason="opening",
                reference_type="opening",
                notes="رصيد افتتاحي",
                created_by=actor_id,
            )
        )
    return inventory_item_dict(row)


def stock_in(tenant_id: int, item_id: int, payload: dict, actor_id=None) -> dict:
    item = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=item_id).first()
    if not item:
        raise ValueError("الصنف غير موجود")
    qty = _qty(payload.get("quantity"))
    if qty <= 0:
        raise ValueError("الكمية غير صالحة")
    before = _qty(item.current_stock)
    unit_cost = _money(payload.get("unit_cost") or payload.get("purchase_price") or item.last_purchase_cost or item.purchase_price)
    batch = None
    if item.batch_tracking or payload.get("batch_number"):
        batch_number = str(payload.get("batch_number") or "").strip()
        if not batch_number:
            raise ValueError("رقم الدفعة مطلوب")
        expiry = _parse_date(payload.get("expiry_date"), "تاريخ الانتهاء") if payload.get("expiry_date") else None
        if item.expiry_tracking and not expiry:
            raise ValueError("تاريخ الانتهاء مطلوب لهذا الصنف")
        batch = ClinicInventoryBatch(
            tenant_id=tenant_id,
            item_id=item.id,
            batch_number=batch_number,
            manufacturing_date=_parse_date(payload.get("manufacturing_date"), "تاريخ الإنتاج") if payload.get("manufacturing_date") else None,
            expiry_date=expiry,
            quantity_received=qty,
            quantity_available=qty,
            purchase_price=unit_cost,
            supplier_id=int(payload.get("supplier_id") or 0) or None,
            purchase_id=int(payload.get("purchase_id") or 0) or None,
        )
        db.session.add(batch)
        db.session.flush()
    after = before + qty
    old_cost = int(item.average_cost or item.purchase_price or 0)
    item.average_cost = int(round(((float(before) * old_cost) + (float(qty) * unit_cost)) / float(after))) if after else unit_cost
    item.last_purchase_cost = unit_cost
    item.purchase_price = unit_cost
    item.current_stock = after
    item.updated_by = actor_id
    item.updated_at = datetime.utcnow()
    db.session.add(
        ClinicInventoryMovement(
            tenant_id=tenant_id,
            item_id=item.id,
            batch_id=batch.id if batch else None,
            movement_type="in",
            quantity=qty,
            stock_before=before,
            stock_after=after,
            unit_cost=unit_cost,
            reason=str(payload.get("reason") or "receive"),
            branch_id=payload.get("branch_id"),
            reference_type=str(payload.get("reference_type") or "manual"),
            reference_id=int(payload.get("reference_id") or 0) or None,
            notes=str(payload.get("notes") or "").strip() or None,
            created_by=actor_id,
        )
    )
    db.session.flush()
    return inventory_item_dict(item)


def stock_out_fefo(tenant_id: int, item_id: int, qty: Decimal, *, reference_type=None, reference_id=None, actor_id=None, notes=None):
    """Issue stock FEFO. Locks the inventory item (and batches) to serialize concurrent consumers."""
    item_query = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=item_id)
    item_query = item_query.with_for_update()
    item = item_query.first()
    if not item:
        raise ValueError("الصنف غير موجود")
    need = _qty(qty)
    if need <= 0:
        return
    available = _qty(item.current_stock)
    if available < need:
        raise ValueError(f"مخزون غير كافٍ للصنف: {item.name}")
    remaining = need
    created_movements = []
    if item.batch_tracking:
        batches = (
            ClinicInventoryBatch.query.filter(
                ClinicInventoryBatch.tenant_id == tenant_id,
                ClinicInventoryBatch.item_id == item_id,
                ClinicInventoryBatch.quantity_available > 0,
                or_(ClinicInventoryBatch.expiry_date.is_(None), ClinicInventoryBatch.expiry_date >= _today()),
            )
            .order_by(ClinicInventoryBatch.expiry_date.asc(), ClinicInventoryBatch.id.asc())
            .with_for_update()
            .all()
        )
        for batch in batches:
            if remaining <= 0:
                break
            take = min(_qty(batch.quantity_available), remaining)
            batch.quantity_available = _qty(batch.quantity_available) - take
            remaining -= take
            movement = ClinicInventoryMovement(
                    tenant_id=tenant_id,
                    item_id=item.id,
                    batch_id=batch.id,
                    movement_type="out",
                    quantity=take,
                    unit_cost=batch.purchase_price or item.average_cost or 0,
                    reason=reference_type or "issue",
                    branch_id=item.branch_id,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    notes=notes,
                    created_by=actor_id,
                )
            db.session.add(movement)
            created_movements.append(movement)
        if remaining > 0:
            raise ValueError(f"مخزون الدفعات غير كافٍ: {item.name}")
    else:
        movement = ClinicInventoryMovement(
                tenant_id=tenant_id,
                item_id=item.id,
                movement_type="out",
                quantity=need,
                unit_cost=item.average_cost or item.purchase_price or 0,
                reason=reference_type or "issue",
                branch_id=item.branch_id,
                reference_type=reference_type,
                reference_id=reference_id,
                notes=notes,
                created_by=actor_id,
            )
        db.session.add(movement)
        created_movements.append(movement)
    before = _qty(item.current_stock)
    item.current_stock = before - need
    movements = [m for m in db.session.new if isinstance(m, ClinicInventoryMovement) and m.item_id == item.id]
    running = before
    for movement in movements:
        movement.stock_before = running
        running -= _qty(movement.quantity)
        movement.stock_after = running
    item.updated_at = datetime.utcnow()
    db.session.flush()
    # Supplier returns have their own AP / Inventory event; posting them here as
    # medical supplies cost would create false COGS.
    if reference_type != "purchase_return":
        from modules.clinics.accounting_service import ClinicAccountingPostingService
        for movement in created_movements:
            ClinicAccountingPostingService.post_inventory_consumption(movement.id, tenant_id, actor_id)


def list_movements(tenant_id: int, item_id: int | None = None, limit: int = 100, *, include_cost: bool = True) -> list[dict]:
    query = ClinicInventoryMovement.query.filter_by(tenant_id=tenant_id)
    if item_id:
        query = query.filter_by(item_id=int(item_id))
    rows = query.order_by(ClinicInventoryMovement.id.desc()).limit(limit).all()
    result = []
    for row in rows:
        item = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=row.item_id).first()
        payload = {
            "id": row.id,
            "item_id": row.item_id,
            "item_name": item.name if item else "",
            "batch_id": row.batch_id,
            "movement_type": row.movement_type,
            "quantity": _qty_float(row.quantity),
            "stock_before": _qty_float(row.stock_before),
            "stock_after": _qty_float(row.stock_after),
            "reason": row.reason or "",
            "reference_type": row.reference_type or "",
            "reference_id": row.reference_id,
            "notes": row.notes or "",
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
        if include_cost:
            payload["unit_cost"] = int(row.unit_cost or 0)
        result.append(payload)
    return result


def list_inventory_batches(
    tenant_id: int, item_id: int | None = None, status: str = "", *, include_cost: bool = True
) -> list[dict]:
    query = ClinicInventoryBatch.query.filter_by(tenant_id=tenant_id)
    if item_id:
        query = query.filter_by(item_id=int(item_id))
    today = _today()
    if status == "expired":
        query = query.filter(ClinicInventoryBatch.expiry_date < today, ClinicInventoryBatch.quantity_available > 0)
    elif status == "expiring":
        query = query.filter(
            ClinicInventoryBatch.expiry_date >= today,
            ClinicInventoryBatch.expiry_date <= today + timedelta(days=30),
            ClinicInventoryBatch.quantity_available > 0,
        )
    rows = query.order_by(ClinicInventoryBatch.expiry_date.asc(), ClinicInventoryBatch.id.desc()).all()
    items = {r.id: r for r in ClinicInventoryItem.query.filter_by(tenant_id=tenant_id).all()}
    result = []
    for b in rows:
        payload = {
            "id": b.id,
            "item_id": b.item_id,
            "item_name": items.get(b.item_id).name if items.get(b.item_id) else "",
            "batch_number": b.batch_number,
            "manufacturing_date": b.manufacturing_date.isoformat() if b.manufacturing_date else "",
            "expiry_date": b.expiry_date.isoformat() if b.expiry_date else "",
            "quantity_received": _qty_float(b.quantity_received),
            "quantity_available": _qty_float(b.quantity_available),
            "supplier_id": b.supplier_id,
            "purchase_id": b.purchase_id,
            "status": (
                "expired"
                if b.expiry_date and b.expiry_date < today
                else ("expiring" if b.expiry_date and b.expiry_date <= today + timedelta(days=30) else "available")
            ),
        }
        if include_cost:
            payload["unit_cost"] = int(b.purchase_price or 0)
        result.append(payload)
    return result


def inventory_center(tenant_id: int, params: dict, *, include_cost: bool = True) -> dict:
    rows = list_inventory(tenant_id, q=params.get("q", ""), low_only=False, include_cost=include_cost)
    category = str(params.get("category") or "").strip()
    status = str(params.get("status") or "").strip()
    if category:
        rows = [r for r in rows if r["category"] == category]
    if status:
        rows = [r for r in rows if r["status"] == status]
    sort = str(params.get("sort") or "name")
    reverse = str(params.get("direction") or "asc") == "desc"
    sort_keys = {
        "stock": lambda r: r["current_stock"],
        "value": lambda r: r.get("inventory_value", 0),
        "expiry": lambda r: r["nearest_expiry"] or "9999-12-31",
        "name": lambda r: r["name"],
    }
    rows.sort(key=sort_keys.get(sort, sort_keys["name"]), reverse=reverse)
    all_items = [
        inventory_item_dict(r, include_cost=include_cost)
        for r in ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, active=True).all()
    ]
    alerts = inventory_alerts(tenant_id)
    page = max(1, int(params.get("page") or 1))
    per_page = min(100, max(10, int(params.get("per_page") or 25)))
    total = len(rows)
    start = (page - 1) * per_page
    kpis = {
        "total_items": len(all_items),
        "low_stock": sum(1 for r in all_items if r["status"] in ("low", "critical")),
        "out_of_stock": sum(1 for r in all_items if r["status"] == "out"),
        "expiring_soon": len(alerts["expiring_soon"]),
        "expired": len(alerts["expired"]),
    }
    if include_cost:
        kpis["inventory_value"] = sum(r.get("inventory_value", 0) for r in all_items)
    return {
        "items": rows[start:start + per_page],
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
        "kpis": kpis,
        "categories": sorted({r["category"] for r in all_items if r["category"]}),
        "alerts": alerts,
        "recent_movements": list_movements(tenant_id, limit=8, include_cost=include_cost),
    }


def inventory_item_detail(tenant_id: int, item_id: int, *, include_cost: bool = True) -> dict:
    row = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=item_id).first()
    if not row:
        raise ValueError("الصنف غير موجود")
    return {
        "item": inventory_item_dict(row, include_cost=include_cost),
        "batches": list_inventory_batches(tenant_id, item_id, include_cost=include_cost),
        "movements": list_movements(tenant_id, item_id, 100, include_cost=include_cost),
    }


def update_inventory_item(tenant_id: int, item_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=item_id).first()
    if not row:
        raise ValueError("الصنف غير موجود")
    text_fields = ("name", "scientific_name", "sku", "barcode", "category", "description", "unit")
    for field in text_fields:
        if field in payload:
            value = str(payload.get(field) or "").strip()
            if field == "name" and not value:
                raise ValueError("اسم الصنف مطلوب")
            setattr(row, field, value or None)
    for field in ("minimum_stock", "maximum_stock", "reorder_point", "suggested_reorder_qty"):
        if field in payload:
            setattr(row, field, _qty(payload.get(field)))
    for field in ("batch_tracking", "expiry_tracking", "serial_tracking", "requires_cooling", "sensitive_item", "prevent_expired_usage", "active"):
        if field in payload:
            setattr(row, field, bool(payload.get(field)))
    if "default_supplier_id" in payload:
        row.default_supplier_id = int(payload.get("default_supplier_id") or 0) or None
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    return inventory_item_dict(row)


def issue_stock(tenant_id: int, item_id: int, payload: dict, actor_id=None) -> dict:
    qty = _qty(payload.get("quantity"))
    if qty <= 0:
        raise ValueError("الكمية غير صالحة")
    reason = str(payload.get("reason") or "internal_use").strip()
    stock_out_fefo(
        tenant_id, item_id, qty,
        reference_type=reason,
        reference_id=int(payload.get("reference_id") or 0) or None,
        actor_id=actor_id,
        notes=str(payload.get("notes") or "").strip() or None,
    )
    db.session.flush()
    return inventory_item_detail(tenant_id, item_id)


def inventory_alerts(tenant_id: int) -> dict:
    items = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, active=True).all()
    low = [inventory_item_dict(i) for i in items if _qty(i.current_stock) <= _qty(i.minimum_stock)]
    today = _today()
    batches = ClinicInventoryBatch.query.filter(
        ClinicInventoryBatch.tenant_id == tenant_id,
        ClinicInventoryBatch.quantity_available > 0,
        ClinicInventoryBatch.expiry_date.isnot(None),
    ).all()
    expired, soon = [], []
    for batch in batches:
        item = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=batch.item_id).first()
        payload = {
            "batch_id": batch.id,
            "item_name": item.name if item else "",
            "batch_number": batch.batch_number,
            "expiry_date": batch.expiry_date.isoformat(),
            "quantity_available": _qty_float(batch.quantity_available),
        }
        if batch.expiry_date < today:
            expired.append(payload)
        elif batch.expiry_date <= today + timedelta(days=30):
            soon.append(payload)
    return {"low_stock": low, "expired": expired, "expiring_soon": soon}


# ── Procedures + recipe deduction ──────────────────────────────────────────


def procedure_dict(row: ClinicProcedure, tenant_id: int | None = None) -> dict:
    recipe = []
    specialty_ids = []
    if tenant_id:
        specialty_ids = [item.specialty_id for item in ClinicProcedureSpecialty.query.filter_by(tenant_id=tenant_id, procedure_id=row.id).all()]
        for r in ClinicProcedureRecipeItem.query.filter_by(tenant_id=tenant_id, procedure_id=row.id).all():
            item = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=r.item_id).first()
            recipe.append(
                {
                    "id": r.id,
                    "item_id": r.item_id,
                    "item_name": item.name if item else "",
                    "quantity": _qty_float(r.quantity),
                }
            )
    return {
        "id": row.id,
        "name": row.name,
        "category": row.category or "",
        "price": row.price,
        "duration_minutes": row.duration_minutes,
        "description": row.description or "",
        "available_for_booking": bool(row.available_for_booking),
        "creates_charge": bool(row.creates_charge),
        "requires_room": bool(row.requires_room),
        "consumes_inventory": bool(row.consumes_inventory),
        "active": bool(row.active),
        "specialty_ids": specialty_ids,
        "recipe": recipe,
    }


def list_procedures(tenant_id: int, active_only: bool = True, specialty_id: int | None = None) -> list[dict]:
    query = ClinicProcedure.query.filter_by(tenant_id=tenant_id)
    if active_only:
        query = query.filter_by(active=True)
    result = [procedure_dict(r, tenant_id) for r in query.order_by(ClinicProcedure.name.asc()).all()]
    if specialty_id:
        specialty_id = int(specialty_id)
        for item in result:
            item["specialty_match"] = specialty_id in item["specialty_ids"]
        result.sort(key=lambda item: (0 if item["specialty_match"] else 1 if not item["specialty_ids"] else 2, item["name"]))
    return result


def set_procedure_specialties(tenant_id: int, procedure_id: int, specialty_ids) -> None:
    ids = sorted({int(value) for value in (specialty_ids or []) if value not in (None, "")})
    if ids and ClinicSpecialty.query.filter(ClinicSpecialty.tenant_id == tenant_id, ClinicSpecialty.id.in_(ids)).count() != len(ids):
        raise ValueError("أحد الاختصاصات غير تابع للعيادة")
    ClinicProcedureSpecialty.query.filter_by(tenant_id=tenant_id, procedure_id=procedure_id).delete(synchronize_session=False)
    for specialty_id in ids:
        db.session.add(ClinicProcedureSpecialty(tenant_id=tenant_id, procedure_id=procedure_id, specialty_id=specialty_id))


def create_procedure(tenant_id: int, payload: dict, actor_id=None) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("اسم الإجراء مطلوب")
    row = ClinicProcedure(
        tenant_id=tenant_id,
        name=name,
        category=str(payload.get("category") or "").strip() or None,
        price=_money(payload.get("price")),
        duration_minutes=max(5, int(payload.get("duration_minutes") or 15)),
        requires_room=bool(payload.get("requires_room", False)),
        consumes_inventory=bool(payload.get("consumes_inventory", False)),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    for recipe in payload.get("recipe") or []:
        item_id = int(recipe.get("item_id") or 0)
        if not item_id:
            continue
        db.session.add(
            ClinicProcedureRecipeItem(
                tenant_id=tenant_id,
                procedure_id=row.id,
                item_id=item_id,
                quantity=_qty(recipe.get("quantity") or 1),
            )
        )
    if payload.get("recipe"):
        row.consumes_inventory = True
    set_procedure_specialties(tenant_id, row.id, payload.get("specialty_ids") or [])
    db.session.flush()
    return procedure_dict(row, tenant_id)


def add_visit_procedure(tenant_id: int, visit_id: int, payload: dict, actor_id=None) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    procedure_id = int(payload.get("procedure_id") or 0)
    procedure = ClinicProcedure.query.filter_by(tenant_id=tenant_id, id=procedure_id).first()
    if not procedure:
        raise ValueError("الإجراء غير موجود")
    row = ClinicVisitProcedure(
        tenant_id=tenant_id,
        visit_id=visit_id,
        patient_id=visit.patient_id,
        doctor_id=visit.doctor_id,
        procedure_id=procedure_id,
        notes=str(payload.get("notes") or "").strip() or None,
        result=str(payload.get("result") or "").strip() or None,
        price=_money(payload.get("price") if payload.get("price") not in (None, "") else procedure.price),
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return list_visit_procedures(tenant_id, visit_id)


def list_visit_procedures(tenant_id: int, visit_id: int) -> list[dict]:
    rows = ClinicVisitProcedure.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all()
    result = []
    for row in rows:
        proc = ClinicProcedure.query.filter_by(tenant_id=tenant_id, id=row.procedure_id).first()
        result.append(
            {
                "id": row.id,
                "procedure_id": row.procedure_id,
                "procedure_name": proc.name if proc else "",
                "price": row.price,
                "notes": row.notes or "",
                "inventory_deducted": bool(row.inventory_deducted),
                "performed_at": row.performed_at.isoformat() if row.performed_at else "",
            }
        )
    return result


def deduct_procedure_inventory(tenant_id: int, visit_procedure: ClinicVisitProcedure, actor_id=None) -> None:
    if visit_procedure.inventory_deducted:
        return
    procedure = ClinicProcedure.query.filter_by(tenant_id=tenant_id, id=visit_procedure.procedure_id).first()
    if not procedure or not procedure.consumes_inventory:
        visit_procedure.inventory_deducted = True
        return
    recipe = ClinicProcedureRecipeItem.query.filter_by(tenant_id=tenant_id, procedure_id=procedure.id).all()
    for line in recipe:
        stock_out_fefo(
            tenant_id,
            line.item_id,
            _qty(line.quantity),
            reference_type="visit_procedure",
            reference_id=visit_procedure.id,
            actor_id=actor_id,
            notes=f"استهلاك إجراء {procedure.name}",
        )
    visit_procedure.inventory_deducted = True


def _visit_bill_line_dict(row: ClinicVisitBillLine) -> dict:
    return {
        "id": row.id,
        "description": row.description,
        "quantity": row.quantity,
        "unit_price": row.unit_price,
        "line_total": row.line_total,
        "line_type": row.line_type,
    }


def list_visit_bill_lines(tenant_id: int, visit_id: int) -> list[dict]:
    rows = (
        ClinicVisitBillLine.query.filter_by(tenant_id=tenant_id, visit_id=visit_id)
        .order_by(ClinicVisitBillLine.id.asc())
        .all()
    )
    return [_visit_bill_line_dict(r) for r in rows]


def add_visit_bill_line(tenant_id: int, visit_id: int, payload: dict, actor_id=None) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    if visit.status == "completed":
        raise ValueError("لا يمكن تعديل فاتورة زيارة مكتملة")
    description = str(payload.get("description") or "").strip()
    if not description:
        raise ValueError("وصف البند مطلوب")
    qty = max(1, int(payload.get("quantity") or 1))
    unit = _money(payload.get("unit_price"))
    row = ClinicVisitBillLine(
        tenant_id=tenant_id,
        visit_id=visit_id,
        description=description,
        quantity=qty,
        unit_price=unit,
        line_total=qty * unit,
        line_type=str(payload.get("line_type") or "other").strip() or "other",
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return _visit_bill_line_dict(row)


def delete_visit_bill_line(tenant_id: int, visit_id: int, line_id: int) -> None:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    if visit.status == "completed":
        raise ValueError("لا يمكن تعديل فاتورة زيارة مكتملة")
    row = ClinicVisitBillLine.query.filter_by(tenant_id=tenant_id, visit_id=visit_id, id=line_id).first()
    if not row:
        raise ValueError("البند غير موجود")
    db.session.delete(row)


def visit_treatment_bill_preview(tenant_id: int, visit_id: int, *, include_financial: bool = True) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    lines = []
    service_price = 0
    service_name = "رسوم الزيارة"
    if visit.service_id:
        svc = ClinicService.query.filter_by(tenant_id=tenant_id, id=visit.service_id).first()
        if svc:
            service_price = int(svc.price or 0)
            service_name = svc.name
    if service_price:
        lines.append(
            {
                "source": "service",
                "description": service_name,
                "quantity": 1,
                "unit_price": service_price,
                "line_total": service_price,
            }
        )
    for vp in ClinicVisitProcedure.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all():
        proc = ClinicProcedure.query.filter_by(tenant_id=tenant_id, id=vp.procedure_id).first()
        desc = proc.name if proc else f"إجراء {vp.procedure_id}"
        price = int(vp.price or 0)
        lines.append(
            {
                "source": "procedure",
                "id": vp.id,
                "description": desc,
                "quantity": 1,
                "unit_price": price,
                "line_total": price,
            }
        )
    for bl in ClinicVisitBillLine.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all():
        lines.append({"source": "extra", **_visit_bill_line_dict(bl)})
    subtotal = sum(int(l["line_total"] or 0) for l in lines)
    invoices = ClinicInvoice.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all()
    result = {
        "visit_id": visit_id,
        "status": visit.status,
        "lines": lines,
        "subtotal": subtotal,
        "discount": 0,
        "total": subtotal,
        "invoices": [
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "total": inv.total,
                "paid": inv.paid,
                "balance": inv.balance,
                "status": inv.status,
            }
            for inv in invoices
        ],
    }
    if not include_financial:
        for line in result["lines"]:
            line.pop("unit_price", None)
            line.pop("line_total", None)
        result.pop("subtotal", None)
        result.pop("discount", None)
        result.pop("total", None)
        result["invoices"] = [
            {"id": inv["id"], "invoice_number": inv["invoice_number"], "status": inv["status"]}
            for inv in result["invoices"]
        ]
    return result


def _apply_invoice_discount(inv: ClinicInvoice, discount: int) -> None:
    discount = max(0, int(discount or 0))
    if discount > inv.subtotal:
        discount = inv.subtotal
    inv.discount = discount
    inv.total = max(0, inv.subtotal - discount)
    inv.balance = max(0, inv.total - inv.paid)
    inv.status = "paid" if inv.balance == 0 else ("partial" if inv.paid else "open")


def complete_visit_extended(tenant_id: int, visit_id: int, actor_id=None, auto_invoice: bool = True, discount: int = 0, create_followup: bool = True, *, include_financial: bool = True) -> dict:
    """Complete visit and bill completed procedures; inventory is consumed at procedure completion."""
    from modules.clinics import service as core

    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    if visit.status == "completed":
        return core.get_visit_detail(tenant_id, visit_id, include_financial=include_financial)

    detail = core.complete_visit(tenant_id, visit_id, actor_id, auto_invoice=auto_invoice)

    # Append procedure lines to invoice if created
    inv = ClinicInvoice.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).order_by(ClinicInvoice.id.desc()).first()
    if inv:
        for vp in ClinicVisitProcedure.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all():
            if (vp.status or "requested") != "completed":
                continue
            exists = ClinicInvoiceItem.query.filter_by(
                tenant_id=tenant_id, invoice_id=inv.id, description=f"إجراء:{vp.procedure_id}"
            ).first()
            # Use procedure name in description; check by service-less lines matching price+visit
            proc = ClinicProcedure.query.filter_by(tenant_id=tenant_id, id=vp.procedure_id).first()
            desc = proc.name if proc else f"إجراء {vp.procedure_id}"
            already = any(
                i.description == desc and i.line_total == vp.price
                for i in ClinicInvoiceItem.query.filter_by(tenant_id=tenant_id, invoice_id=inv.id).all()
            )
            if already or exists:
                continue
            if vp.price <= 0:
                continue
            db.session.add(
                ClinicInvoiceItem(
                    tenant_id=tenant_id,
                    invoice_id=inv.id,
                    description=desc,
                    quantity=1,
                    unit_price=vp.price,
                    line_total=vp.price,
                )
            )
            inv.subtotal += vp.price
            inv.total += vp.price
            inv.balance = max(0, inv.total - inv.paid)
            inv.status = "paid" if inv.balance == 0 else ("partial" if inv.paid else "open")
        for bl in ClinicVisitBillLine.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all():
            db.session.add(
                ClinicInvoiceItem(
                    tenant_id=tenant_id,
                    invoice_id=inv.id,
                    description=bl.description,
                    quantity=bl.quantity,
                    unit_price=bl.unit_price,
                    line_total=bl.line_total,
                )
            )
            inv.subtotal += bl.line_total
            inv.total += bl.line_total
            inv.balance = max(0, inv.total - inv.paid)
            inv.status = "paid" if inv.balance == 0 else ("partial" if inv.paid else "open")
        if discount:
            _apply_invoice_discount(inv, discount)
        db.session.flush()
        from modules.clinics.accounting_service import ClinicAccountingPostingService
        ClinicAccountingPostingService.post_clinic_invoice(inv.id, tenant_id, actor_id)
        detail = core.get_visit_detail(tenant_id, visit_id, include_financial=include_financial)

    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if create_followup and visit and not ClinicFollowUp.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first():
        from modules.clinics.service_comms import create_followup_from_visit

        payload = {}
        if visit.follow_up_date:
            payload["due_date"] = visit.follow_up_date.isoformat()
        create_followup_from_visit(tenant_id, visit_id, payload, actor_id)

    if not include_financial and isinstance(detail, dict):
        detail = core.get_visit_detail(tenant_id, visit_id, include_financial=False)
    return detail


# ── Labs ───────────────────────────────────────────────────────────────────


def lab_test_dict(row: ClinicLabTest) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "code": row.code or "",
        "category": row.category or "",
        "price": row.price,
        "reference_notes": row.reference_notes or "",
        "active": bool(row.active),
    }


def list_lab_tests(tenant_id: int, active_only: bool = True) -> list[dict]:
    query = ClinicLabTest.query.filter_by(tenant_id=tenant_id)
    if active_only:
        query = query.filter_by(active=True)
    return [lab_test_dict(r) for r in query.order_by(ClinicLabTest.name.asc()).all()]


def create_lab_test(tenant_id: int, payload: dict, actor_id=None) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("اسم التحليل مطلوب")
    row = ClinicLabTest(
        tenant_id=tenant_id,
        name=name,
        code=str(payload.get("code") or "").strip() or None,
        category=str(payload.get("category") or "").strip() or None,
        price=_money(payload.get("price")),
        reference_notes=str(payload.get("reference_notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return lab_test_dict(row)


def lab_order_dict(row: ClinicLabOrder, tenant_id: int) -> dict:
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=row.patient_id).first()
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=row.doctor_id).first() if row.doctor_id else None
    items = ClinicLabOrderItem.query.filter_by(tenant_id=tenant_id, order_id=row.id).all()
    item_payload = []
    for it in items:
        test = ClinicLabTest.query.filter_by(tenant_id=tenant_id, id=it.test_id).first()
        item_payload.append(
            {
                "id": it.id,
                "test_id": it.test_id,
                "test_name": test.name if test else "",
                "status": it.status,
                "value": it.value or "",
                "unit": it.unit or "",
                "reference_range": it.reference_range or "",
                "abnormal_flag": it.abnormal_flag or "",
                "notes": it.notes or "",
            }
        )
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "patient_name": patient.full_name if patient else "",
        "visit_id": row.visit_id,
        "doctor_id": row.doctor_id,
        "doctor_name": doctor.full_name if doctor else "",
        "ordered_at": row.ordered_at.isoformat() if row.ordered_at else "",
        "priority": row.priority,
        "status": row.status,
        "notes": row.notes or "",
        "items": item_payload,
    }


def create_lab_order(tenant_id: int, payload: dict, actor_id=None) -> dict:
    patient_id = int(payload.get("patient_id") or 0)
    if not ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first():
        raise ValueError("المريض غير موجود")
    doctor_id = int(payload.get("doctor_id") or 0)
    if not doctor_id or not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
        raise ValueError("الطبيب الطالب مطلوب")
    test_ids = payload.get("test_ids") or []
    if not test_ids:
        raise ValueError("اختر تحليلاً واحداً على الأقل")
    row = ClinicLabOrder(
        tenant_id=tenant_id,
        patient_id=patient_id,
        visit_id=int(payload["visit_id"]) if payload.get("visit_id") else None,
        doctor_id=doctor_id,
        priority=str(payload.get("priority") or "normal"),
        status="requested",
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    for tid in test_ids:
        test = ClinicLabTest.query.filter_by(tenant_id=tenant_id, id=int(tid)).first()
        if not test:
            continue
        db.session.add(
            ClinicLabOrderItem(
                tenant_id=tenant_id,
                order_id=row.id,
                test_id=test.id,
                status="requested",
            )
        )
    db.session.flush()
    _audit(tenant_id, actor_id, "lab_order", row.id, "create", "طلب تحاليل")
    return lab_order_dict(row, tenant_id)


def list_lab_orders(tenant_id: int, status: str | None = None, visit_id: int | None = None) -> list[dict]:
    query = ClinicLabOrder.query.filter_by(tenant_id=tenant_id)
    if status:
        query = query.filter_by(status=status)
    if visit_id:
        query = query.filter_by(visit_id=int(visit_id))
    rows = query.order_by(ClinicLabOrder.id.desc()).limit(100).all()
    return [lab_order_dict(r, tenant_id) for r in rows]


def update_lab_result(tenant_id: int, item_id: int, payload: dict, actor_id=None) -> dict:
    item = ClinicLabOrderItem.query.filter_by(tenant_id=tenant_id, id=item_id).first()
    if not item:
        raise ValueError("بند التحليل غير موجود")
    item.value = str(payload.get("value") or "").strip() or None
    item.unit = str(payload.get("unit") or "").strip() or None
    item.reference_range = str(payload.get("reference_range") or "").strip() or None
    item.abnormal_flag = str(payload.get("abnormal_flag") or "normal").strip() or "normal"
    item.notes = str(payload.get("notes") or "").strip() or None
    item.status = "completed"
    item.result_at = datetime.utcnow()
    order = ClinicLabOrder.query.filter_by(tenant_id=tenant_id, id=item.order_id).first()
    if order:
        pending = ClinicLabOrderItem.query.filter(
            ClinicLabOrderItem.tenant_id == tenant_id,
            ClinicLabOrderItem.order_id == order.id,
            ClinicLabOrderItem.status != "completed",
        ).count()
        order.status = "result_ready" if pending == 0 else "processing"
        order.updated_at = datetime.utcnow()
        _audit(tenant_id, actor_id, "lab_order", order.id, "result", "إدخال نتيجة تحليل")
    db.session.flush()
    return lab_order_dict(order, tenant_id) if order else {}


# ── Radiology ──────────────────────────────────────────────────────────────


def radiology_dict(row: ClinicRadiologyOrder, tenant_id: int) -> dict:
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=row.patient_id).first()
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=row.doctor_id).first() if row.doctor_id else None
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "patient_name": patient.full_name if patient else "",
        "visit_id": row.visit_id,
        "doctor_id": row.doctor_id,
        "doctor_name": doctor.full_name if doctor else "",
        "modality": row.modality,
        "modality_label": dict(RADIOLOGY_MODALITIES).get(row.modality, row.modality),
        "body_part": row.body_part or "",
        "priority": row.priority,
        "status": row.status,
        "price": row.price,
        "report": row.report or "",
        "impression": row.impression or "",
        "ordered_at": row.ordered_at.isoformat() if row.ordered_at else "",
        "notes": row.notes or "",
    }


def create_radiology_order(tenant_id: int, payload: dict, actor_id=None) -> dict:
    patient_id = int(payload.get("patient_id") or 0)
    if not ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first():
        raise ValueError("المريض غير موجود")
    doctor_id = int(payload.get("doctor_id") or 0)
    if not doctor_id or not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
        raise ValueError("الطبيب الطالب مطلوب")
    modality = str(payload.get("modality") or "xray")
    if modality not in dict(RADIOLOGY_MODALITIES):
        modality = "other"
    row = ClinicRadiologyOrder(
        tenant_id=tenant_id,
        patient_id=patient_id,
        visit_id=int(payload["visit_id"]) if payload.get("visit_id") else None,
        doctor_id=doctor_id,
        status="requested",
        modality=modality,
        body_part=str(payload.get("body_part") or "").strip() or None,
        priority=str(payload.get("priority") or "normal"),
        price=_money(payload.get("price")),
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "radiology_order", row.id, "create", "طلب أشعة")
    return radiology_dict(row, tenant_id)


def list_radiology_orders(tenant_id: int, status: str | None = None, visit_id: int | None = None) -> list[dict]:
    query = ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id)
    if status:
        query = query.filter_by(status=status)
    if visit_id:
        query = query.filter_by(visit_id=int(visit_id))
    return [radiology_dict(r, tenant_id) for r in query.order_by(ClinicRadiologyOrder.id.desc()).limit(100).all()]


def update_radiology_result(tenant_id: int, order_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id, id=order_id).first()
    if not row:
        raise ValueError("طلب الأشعة غير موجود")
    if "report" in payload:
        row.report = str(payload.get("report") or "").strip() or None
    if "impression" in payload:
        row.impression = str(payload.get("impression") or "").strip() or None
    if "status" in payload:
        row.status = str(payload.get("status") or row.status)
    if row.status == "completed":
        row.reported_at = datetime.utcnow()
        if not row.performed_at:
            row.performed_at = datetime.utcnow()
    db.session.flush()
    return radiology_dict(row, tenant_id)


# ── Settlements / statements / reports / public queue ───────────────────────


def doctor_earnings(tenant_id: int, doctor_id: int, period_from: date, period_to: date) -> dict:
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
    if not doctor:
        raise ValueError("الطبيب غير موجود")
    invoices = ClinicInvoice.query.filter(
        ClinicInvoice.tenant_id == tenant_id,
        ClinicInvoice.doctor_id == doctor_id,
        ClinicInvoice.invoice_date >= period_from,
        ClinicInvoice.invoice_date <= period_to,
        ClinicInvoice.status != "void",
    ).all()
    visits = ClinicVisit.query.filter(
        ClinicVisit.tenant_id == tenant_id,
        ClinicVisit.doctor_id == doctor_id,
        ClinicVisit.visit_date >= period_from,
        ClinicVisit.visit_date <= period_to,
        ClinicVisit.status == "completed",
    ).count()
    gross = sum(i.total for i in invoices)
    pct = float(doctor.commission_pct or 0)
    doctor_share = int(round(gross * pct / 100.0))
    clinic_share = gross - doctor_share
    return {
        "doctor_id": doctor_id,
        "doctor_name": doctor.full_name,
        "period_from": period_from.isoformat(),
        "period_to": period_to.isoformat(),
        "visits_count": visits,
        "gross_revenue": gross,
        "commission_pct": pct,
        "doctor_share": doctor_share,
        "clinic_share": clinic_share,
    }


def create_settlement(tenant_id: int, payload: dict, actor_id=None) -> dict:
    doctor_id = int(payload.get("doctor_id") or 0)
    period_from = _parse_date(payload.get("period_from"), "من تاريخ")
    period_to = _parse_date(payload.get("period_to"), "إلى تاريخ")
    earnings = doctor_earnings(tenant_id, doctor_id, period_from, period_to)
    duplicate = ClinicDoctorSettlement.query.filter_by(
        tenant_id=tenant_id, doctor_id=doctor_id, period_from=period_from, period_to=period_to
    ).filter(ClinicDoctorSettlement.status != "cancelled").first()
    if duplicate:
        raise ValueError("توجد تسوية لهذا الطبيب ولنفس الفترة بالفعل")
    adjustments = _money(payload.get("adjustments"))
    paid_amount = _money(payload.get("paid_amount"))
    doctor_share = earnings["doctor_share"] + adjustments
    if paid_amount > doctor_share:
        raise ValueError("المبلغ المدفوع للطبيب أكبر من استحقاقه")
    balance = max(0, doctor_share - paid_amount)
    row = ClinicDoctorSettlement(
        tenant_id=tenant_id,
        doctor_id=doctor_id,
        period_from=period_from,
        period_to=period_to,
        visits_count=earnings["visits_count"],
        gross_revenue=earnings["gross_revenue"],
        doctor_share=doctor_share,
        clinic_share=earnings["clinic_share"],
        adjustments=adjustments,
        paid_amount=paid_amount,
        payment_method=str(payload.get("payment_method") or "cash").strip() or "cash",
        balance=balance,
        status="paid" if balance == 0 and paid_amount > 0 else "open",
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.post_doctor_settlement(row.id, tenant_id, actor_id)
    if paid_amount > 0:
        ClinicAccountingPostingService.post_doctor_settlement_payment(row.id, tenant_id, actor_id)
    return settlement_dict(row, tenant_id)


def settlement_dict(row: ClinicDoctorSettlement, tenant_id: int) -> dict:
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=row.doctor_id).first()
    return {
        "id": row.id,
        "doctor_id": row.doctor_id,
        "doctor_name": doctor.full_name if doctor else "",
        "period_from": row.period_from.isoformat(),
        "period_to": row.period_to.isoformat(),
        "visits_count": row.visits_count,
        "gross_revenue": row.gross_revenue,
        "doctor_share": row.doctor_share,
        "clinic_share": row.clinic_share,
        "adjustments": row.adjustments,
        "paid_amount": row.paid_amount,
        "balance": row.balance,
        "status": row.status,
        "notes": row.notes or "",
    }


def list_settlements(tenant_id: int) -> list[dict]:
    rows = ClinicDoctorSettlement.query.filter_by(tenant_id=tenant_id).order_by(ClinicDoctorSettlement.id.desc()).limit(100).all()
    return [settlement_dict(r, tenant_id) for r in rows]


def patient_statement(tenant_id: int, patient_id: int) -> dict:
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not patient:
        raise ValueError("المريض غير موجود")
    invoices = ClinicInvoice.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicInvoice.invoice_date.asc(), ClinicInvoice.id.asc()).all()
    payments = ClinicPayment.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicPayment.paid_at.asc(), ClinicPayment.id.asc()).all()
    lines = []
    for inv in invoices:
        lines.append(
            {
                "date": inv.invoice_date.isoformat(),
                "type": "invoice",
                "reference": inv.invoice_number,
                "debit": inv.total,
                "credit": 0,
                "sort": f"{inv.invoice_date.isoformat()}-A-{inv.id}",
            }
        )
    for pay in payments:
        lines.append(
            {
                "date": (pay.paid_at.date().isoformat() if pay.paid_at else ""),
                "type": "payment",
                "reference": f"PAY-{pay.id}",
                "debit": 0,
                "credit": pay.amount,
                "sort": f"{(pay.paid_at.date().isoformat() if pay.paid_at else '')}-B-{pay.id}",
            }
        )
    lines.sort(key=lambda x: x["sort"])
    balance = 0
    for line in lines:
        balance += line["debit"] - line["credit"]
        line["balance"] = balance
        del line["sort"]
    return {
        "patient": patient_dict(patient),
        "total_invoices": sum(i.total for i in invoices),
        "total_payments": sum(p.amount for p in payments),
        "outstanding_balance": balance,
        "lines": lines,
    }


def reports_summary(tenant_id: int, day: date | None = None) -> dict:
    from modules.clinics.service import dashboard

    day = day or _today()
    base = dashboard(tenant_id, day)
    by_doctor = []
    for doctor in ClinicDoctor.query.filter_by(tenant_id=tenant_id, active=True).all():
        visits = ClinicVisit.query.filter_by(
            tenant_id=tenant_id, doctor_id=doctor.id, visit_date=day, status="completed"
        ).count()
        revenue = (
            db.session.query(func.coalesce(func.sum(ClinicInvoice.total), 0))
            .filter(
                ClinicInvoice.tenant_id == tenant_id,
                ClinicInvoice.doctor_id == doctor.id,
                ClinicInvoice.invoice_date == day,
            )
            .scalar()
        )
        by_doctor.append(
            {
                "doctor_id": doctor.id,
                "doctor_name": doctor.full_name,
                "completed_visits": visits,
                "revenue": int(revenue or 0),
            }
        )
    alerts = inventory_alerts(tenant_id)
    return {
        **base,
        "by_doctor": by_doctor,
        "inventory_alerts": {
            "low_stock_count": len(alerts["low_stock"]),
            "expired_count": len(alerts["expired"]),
            "expiring_soon_count": len(alerts["expiring_soon"]),
        },
        "lab_open": ClinicLabOrder.query.filter(
            ClinicLabOrder.tenant_id == tenant_id,
            ClinicLabOrder.status.in_(("ordered", "processing", "sample_collected")),
        ).count(),
        "radiology_open": ClinicRadiologyOrder.query.filter(
            ClinicRadiologyOrder.tenant_id == tenant_id,
            ClinicRadiologyOrder.status.in_(("ordered", "processing")),
        ).count(),
    }


def public_queue_display(tenant_id: int, day: date | None = None) -> dict:
    """Privacy-safe queue board for waiting-room screens."""
    from modules.clinics.models import ClinicAuditLog
    from modules.clinics.service import settings_payload

    day = day or _today()
    now = datetime.utcnow()
    settings = settings_payload(tenant_id)
    doctors = {
        d.id: d
        for d in ClinicDoctor.query.filter_by(tenant_id=tenant_id, active=True).all()
    }
    rooms = {
        r.id: r
        for r in ClinicRoom.query.filter_by(tenant_id=tenant_id).all()
    }
    appts = (
        ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.appointment_date == day,
            ClinicAppointment.status.in_(("waiting", "arrived", "in_consultation", "called")),
        )
        .order_by(
            ClinicAppointment.queue_priority.desc(),
            ClinicAppointment.queue_number.asc(),
            ClinicAppointment.start_time.asc(),
        )
        .all()
    )
    tickets = []
    for a in appts:
        doctor = doctors.get(a.doctor_id) if a.doctor_id else None
        room = rooms.get(a.room_id) if a.room_id else None
        ticket_code = f"A-{int(a.queue_number):03d}" if a.queue_number else "—"
        short_name = ""
        if a.patient and a.patient.full_name:
            parts = str(a.patient.full_name).split()
            if len(parts) >= 2:
                short_name = f"{parts[0][0]}. {parts[-1]}"
            else:
                short_name = parts[0]
        tickets.append(
            {
                "appointment_id": a.id,
                "queue_number": a.queue_number,
                "ticket_code": ticket_code,
                "status": a.status,
                "doctor_id": a.doctor_id,
                "doctor_name": doctor.full_name if doctor else "",
                "doctor_color": (doctor.color if doctor else None) or "#0d9488",
                "room_name": room.name if room else "",
                "short_name": short_name,
                "priority": int(getattr(a, "queue_priority", 0) or 0),
            }
        )

    by_doctor = []
    for doc in sorted(doctors.values(), key=lambda d: d.full_name or ""):
        current = next(
            (t for t in tickets if t["doctor_id"] == doc.id and t["status"] == "in_consultation"),
            None,
        )
        upcoming = [
            t
            for t in tickets
            if t["doctor_id"] == doc.id and t["status"] in ("waiting", "arrived", "called")
        ][:6]
        by_doctor.append(
            {
                "doctor_id": doc.id,
                "doctor_name": doc.full_name,
                "specialty": doc.specialty or "",
                "color": doc.color or "#0d9488",
                "current": current,
                "upcoming": upcoming,
                "waiting_count": len(upcoming),
            }
        )

    current_tickets = [t for t in tickets if t["status"] == "in_consultation"]
    upcoming_tickets = [t for t in tickets if t["status"] in ("waiting", "arrived", "called")]

    last_call = None
    call_logs = (
        ClinicAuditLog.query.filter_by(tenant_id=tenant_id, entity_type="queue", action="call")
        .order_by(ClinicAuditLog.created_at.desc())
        .limit(8)
        .all()
    )
    recent_calls = []
    for log in call_logs:
        meta = {}
        if log.meta_json:
            try:
                import json

                meta = json.loads(log.meta_json) or {}
            except Exception:
                meta = {}
        item = {
            "appointment_id": log.entity_id,
            "queue_number": meta.get("queue_number"),
            "ticket_code": meta.get("ticket_code") or (
                f"A-{int(meta['queue_number']):03d}" if meta.get("queue_number") else "—"
            ),
            "doctor_name": meta.get("doctor_name") or "",
            "room_name": meta.get("room_name") or "",
            "called_at": log.created_at.isoformat() if log.created_at else "",
            "call_id": log.id,
        }
        recent_calls.append(item)
        if last_call is None:
            last_call = item

    pulse_version = (
        f"{len(tickets)}-{len(current_tickets)}-{len(upcoming_tickets)}-"
        f"{last_call['call_id'] if last_call else 0}-"
        f"{sum(t.get('queue_number') or 0 for t in tickets)}"
    )

    footer = (
        (settings.get("display_footer_message") or "").strip()
        or "يرجى متابعة رقم الدور على الشاشة."
    )

    return {
        "date": day.isoformat(),
        "now": now.isoformat(),
        "clinic_name": settings.get("clinic_name") or "Finora Clinics",
        "footer_message": footer,
        "pulse_version": pulse_version,
        "tickets": tickets,
        "current": current_tickets,
        "upcoming": upcoming_tickets[:6],
        "by_doctor": by_doctor,
        "last_call": last_call,
        "recent_calls": recent_calls[:5],
        "display_settings": {
            "sound_enabled": bool(settings.get("display_sound_enabled", True)),
            "voice_enabled": bool(settings.get("display_voice_enabled", False)),
            "volume": int(settings.get("display_volume") or 70),
            "show_short_name": bool(settings.get("display_show_short_name", False)),
        },
        "modalities": [{"key": k, "label": v} for k, v in RADIOLOGY_MODALITIES],
        "weekdays": list(WEEKDAY_LABELS),
    }
