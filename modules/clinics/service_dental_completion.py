"""Dental completion layer — events, service seed, billing, dashboard, search."""
from __future__ import annotations

import json
from datetime import datetime

from extensions import db
from modules.clinics.models import (
    ClinicAppointment,
    ClinicDentalSession,
    ClinicDentalToothEvent,
    ClinicDentalTreatmentPlan,
    ClinicDentalTreatmentPlanItem,
    ClinicInvoice,
    ClinicInvoiceItem,
    ClinicProcedure,
    ClinicProcedureSpecialty,
    ClinicService,
    ClinicServiceSpecialty,
    ClinicSettings,
    ClinicSpecialty,
    ClinicVisit,
)
from modules.clinics.service import _advisory_transaction_lock, _audit, _next_invoice_number, _today, invoice_dict
from modules.clinics.service_dental import STATUS_LABELS_AR, validate_tooth_number

DEFAULT_DENTAL_CONFIG = {
    "enabled": True,
    "tooth_numbering": "fdi",
    "enable_primary_teeth": True,
    "enable_tooth_surfaces": True,
    "enable_treatment_payments": True,
    "default_sessions": 1,
}

DENTAL_SERVICE_SEED = (
    ("كشفية أسنان", 15, 15000, False, False, False, 1),
    ("تنظيف الأسنان", 30, 40000, False, False, False, 1),
    ("حشوة", 30, 50000, True, False, False, 1),
    ("حشوة تجميلية", 30, 60000, True, False, False, 1),
    ("علاج عصب", 45, 150000, True, False, True, 3),
    ("قلع", 30, 40000, True, False, False, 1),
    ("قلع جراحي", 45, 80000, True, False, False, 1),
    ("تاج", 45, 200000, True, False, True, 2),
    ("جسر", 60, 350000, False, True, True, 2),
    ("زراعة", 60, 500000, True, False, True, 3),
    ("تركيب", 45, 180000, True, False, False, 1),
    ("تقويم", 30, 100000, False, True, True, 12),
    ("تبييض", 30, 80000, False, False, False, 1),
    ("أشعة بانوراما", 15, 25000, False, False, False, 1),
    ("متابعة أسنان", 15, 10000, False, False, False, 1),
)

INVOICE_MODES = frozenset({"full", "selected", "session", "custom"})


def normalize_dental_config(raw) -> dict:
    config = dict(DEFAULT_DENTAL_CONFIG)
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            data = {}
    if not isinstance(data, dict):
        return config
    numbering = str(data.get("tooth_numbering") or "fdi").strip().lower()
    if numbering not in {"fdi", "universal", "palmer"}:
        numbering = "fdi"
    config.update({
        "enabled": data.get("enabled", True) is not False,
        "tooth_numbering": numbering,
        "enable_primary_teeth": data.get("enable_primary_teeth", True) is not False,
        "enable_tooth_surfaces": data.get("enable_tooth_surfaces", True) is not False,
        "enable_treatment_payments": data.get("enable_treatment_payments", True) is not False,
        "default_sessions": max(1, int(data.get("default_sessions") or 1)),
    })
    return config


def dental_config_for_tenant(tenant_id: int) -> dict:
    settings = ClinicSettings.query.filter_by(tenant_id=tenant_id).first()
    return normalize_dental_config(getattr(settings, "dental_config_json", None) if settings else None)


def record_tooth_event(
    tenant_id: int,
    *,
    patient_id: int,
    visit_id: int | None,
    doctor_id: int | None,
    tooth_number: str,
    condition_code: str,
    surfaces: list | None = None,
    notes: str | None = None,
    event_type: str = "condition_change",
    is_active: bool = False,
    finding_key: str | None = None,
    supersedes_event_id: int | None = None,
    actor_id=None,
) -> ClinicDentalToothEvent:
    tooth = validate_tooth_number(tooth_number)
    row = ClinicDentalToothEvent(
        tenant_id=tenant_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        visit_id=visit_id,
        tooth_number=tooth,
        condition_code=str(condition_code or "other"),
        surfaces_json=json.dumps(surfaces or [], ensure_ascii=False),
        notes=(notes or "").strip() or None,
        event_type=str(event_type or "condition_change"),
        is_active=bool(is_active),
        finding_key=finding_key,
        supersedes_event_id=supersedes_event_id,
        event_date=datetime.utcnow(),
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def list_tooth_events(tenant_id: int, patient_id: int, tooth_number: str | None = None, limit: int = 50) -> list[dict]:
    query = ClinicDentalToothEvent.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
    if tooth_number:
        query = query.filter_by(tooth_number=validate_tooth_number(tooth_number))
    rows = query.order_by(ClinicDentalToothEvent.event_date.desc(), ClinicDentalToothEvent.id.desc()).limit(max(1, min(200, int(limit or 50)))).all()
    return [_event_dict(row) for row in rows]


def _event_dict(row: ClinicDentalToothEvent) -> dict:
    surfaces = []
    if row.surfaces_json:
        try:
            surfaces = json.loads(row.surfaces_json) or []
        except json.JSONDecodeError:
            surfaces = []
    return {
        "id": row.id,
        "tooth_number": row.tooth_number,
        "condition_code": row.condition_code,
        "condition_label_ar": STATUS_LABELS_AR.get(row.condition_code, row.condition_code),
        "surfaces": surfaces,
        "notes": row.notes or "",
        "event_type": row.event_type,
        "is_active": bool(getattr(row, "is_active", False)),
        "finding_key": getattr(row, "finding_key", None),
        "supersedes_event_id": getattr(row, "supersedes_event_id", None),
        "event_date": row.event_date.isoformat() if row.event_date else None,
        "visit_id": row.visit_id,
        "doctor_id": row.doctor_id,
    }


def seed_dental_services(tenant_id: int, actor_id=None) -> list[dict]:
    specialty = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, code="dentistry").first()
    created = []
    for name, duration, price, requires_tooth, allows_multiple, requires_sessions, sessions in DENTAL_SERVICE_SEED:
        procedure = ClinicProcedure.query.filter_by(tenant_id=tenant_id, name=name).first()
        if not procedure:
            procedure = ClinicProcedure(
                tenant_id=tenant_id,
                name=name,
                category="أسنان",
                price=price,
                duration_minutes=duration,
                active=True,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.session.add(procedure)
            db.session.flush()
        if specialty and not ClinicProcedureSpecialty.query.filter_by(
            tenant_id=tenant_id, procedure_id=procedure.id, specialty_id=specialty.id
        ).first():
            db.session.add(ClinicProcedureSpecialty(
                tenant_id=tenant_id, procedure_id=procedure.id, specialty_id=specialty.id
            ))
        row = ClinicService.query.filter_by(tenant_id=tenant_id, name=name).first()
        if not row:
            row = ClinicService(
                tenant_id=tenant_id,
                name=name,
                category="أسنان",
                duration_minutes=duration,
                price=price,
                requires_tooth=requires_tooth,
                allows_multiple_teeth=allows_multiple,
                requires_sessions=requires_sessions,
                default_sessions=sessions,
                default_procedure_id=procedure.id,
                active=True,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.session.add(row)
            db.session.flush()
            created.append(row)
        elif not getattr(row, "default_procedure_id", None):
            # Link the shared execution definition without resetting a user's
            # edited price, duration, tooth, or session settings.
            row.default_procedure_id = procedure.id
        if specialty and not ClinicServiceSpecialty.query.filter_by(
            tenant_id=tenant_id, service_id=row.id, specialty_id=specialty.id
        ).first():
            db.session.add(ClinicServiceSpecialty(
                tenant_id=tenant_id, service_id=row.id, specialty_id=specialty.id
            ))
    db.session.flush()
    if created:
        _audit(tenant_id, actor_id, "service", created[0].id, "seed", f"تهيئة {len(created)} خدمات أسنان")
    return [{"id": row.id, "name": row.name} for row in created]


def apply_service_scope(row: ClinicService, payload: dict) -> None:
    if "requires_tooth" in payload:
        row.requires_tooth = bool(payload.get("requires_tooth"))
    if "allows_multiple_teeth" in payload:
        row.allows_multiple_teeth = bool(payload.get("allows_multiple_teeth"))
    if "requires_sessions" in payload:
        row.requires_sessions = bool(payload.get("requires_sessions"))
    if "default_sessions" in payload:
        row.default_sessions = max(1, int(payload.get("default_sessions") or 1))
    if "default_procedure_id" in payload:
        procedure_id = int(payload.get("default_procedure_id") or 0) or None
        if procedure_id and not ClinicProcedure.query.filter_by(
            tenant_id=row.tenant_id, id=procedure_id, active=True
        ).first():
            raise ValueError("الإجراء الافتراضي غير موجود")
        row.default_procedure_id = procedure_id
    if row.requires_sessions and int(row.default_sessions or 0) < 1:
        raise ValueError("عدد الجلسات الافتراضي يجب أن يكون 1 على الأقل")


def validate_service_tooth(service: ClinicService | None, tooth_number) -> str | None:
    if not service:
        return None
    tooth = str(tooth_number or "").strip() or None
    if service.requires_tooth and not tooth:
        raise ValueError("هذه الخدمة تتطلب تحديد السن")
    if tooth:
        return validate_tooth_number(tooth)
    return None


def appointment_dental_fields(tenant_id: int, payload: dict, service: ClinicService | None) -> dict:
    raw_teeth = payload.get("tooth_numbers")
    if isinstance(raw_teeth, str):
        try:
            raw_teeth = json.loads(raw_teeth)
        except (TypeError, ValueError):
            raw_teeth = [part.strip() for part in raw_teeth.split(",")]
    teeth = []
    for raw in raw_teeth or []:
        tooth_value = validate_tooth_number(str(raw))
        if tooth_value not in teeth:
            teeth.append(tooth_value)
    tooth = validate_service_tooth(service, payload.get("tooth_number") or (teeth[0] if teeth else None))
    if tooth and tooth not in teeth:
        teeth.insert(0, tooth)
    if service and len(teeth) > 1 and not service.allows_multiple_teeth:
        raise ValueError("هذه الخدمة لا تسمح بتحديد أكثر من سن")
    item_id = payload.get("treatment_plan_item_id")
    item_id = int(item_id) if item_id not in (None, "", 0, "0") else None
    plan_id = int(payload.get("treatment_plan_id") or 0) or None
    session_id = int(payload.get("dental_session_id") or 0) or None
    patient_id = int(payload.get("patient_id") or 0)
    if item_id:
        item = ClinicDentalTreatmentPlanItem.query.filter_by(tenant_id=tenant_id, id=item_id).first()
        if not item or item.archived_at:
            raise ValueError("بند خطة العلاج غير موجود")
        item_plan = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id, id=item.plan_id).first()
        if not item_plan or (patient_id and item_plan.patient_id != patient_id):
            raise ValueError("بند خطة العلاج لا يخص المريض")
        if plan_id and plan_id != item.plan_id:
            raise ValueError("بند العلاج لا يخص الخطة المحددة")
        plan_id = item.plan_id
        if not tooth and item.tooth_number:
            tooth = item.tooth_number
        try:
            item_teeth = json.loads(getattr(item, "tooth_numbers_json", None) or "[]")
        except (TypeError, ValueError):
            item_teeth = []
        if not teeth:
            teeth = item_teeth or ([item.tooth_number] if item.tooth_number else [])
    if plan_id:
        plan = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id, id=plan_id).first()
        if not plan or plan.archived_at or (patient_id and plan.patient_id != patient_id):
            raise ValueError("خطة العلاج لا تخص المريض")
    if session_id:
        session = ClinicDentalSession.query.filter_by(tenant_id=tenant_id, id=session_id).first()
        if not session:
            raise ValueError("جلسة الأسنان غير موجودة")
        session_item = ClinicDentalTreatmentPlanItem.query.filter_by(
            tenant_id=tenant_id, id=session.treatment_plan_item_id
        ).first()
        session_plan = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id, id=session.plan_id).first()
        if not session_item or not session_plan or (patient_id and session_plan.patient_id != patient_id):
            raise ValueError("جلسة الأسنان لا تخص المريض")
        if item_id and item_id != session.treatment_plan_item_id:
            raise ValueError("الجلسة لا تخص بند العلاج المحدد")
        if plan_id and plan_id != session.plan_id:
            raise ValueError("الجلسة لا تخص الخطة المحددة")
        item_id = session.treatment_plan_item_id
        plan_id = session.plan_id
        if not teeth:
            try:
                teeth = json.loads(getattr(session_item, "tooth_numbers_json", None) or "[]")
            except (TypeError, ValueError):
                teeth = []
            if not teeth and session_item.tooth_number:
                teeth = [session_item.tooth_number]
        tooth = tooth or (teeth[0] if teeth else None)
    return {
        "tooth_number": tooth,
        "tooth_numbers_json": json.dumps(teeth, ensure_ascii=False),
        "treatment_plan_id": plan_id,
        "treatment_plan_item_id": item_id,
        "dental_session_id": session_id,
    }


def visit_complete_preflight(tenant_id: int, visit_id: int) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    open_sessions = ClinicDentalSession.query.filter_by(
        tenant_id=tenant_id, visit_id=visit_id
    ).filter(ClinicDentalSession.status.in_(("planned", "scheduled", "in_progress", "waiting"))).all()
    active_items = (
        ClinicDentalTreatmentPlanItem.query
        .join(ClinicDentalTreatmentPlan, ClinicDentalTreatmentPlan.id == ClinicDentalTreatmentPlanItem.plan_id)
        .filter(
            ClinicDentalTreatmentPlan.tenant_id == tenant_id,
            ClinicDentalTreatmentPlan.patient_id == visit.patient_id,
            ClinicDentalTreatmentPlan.archived_at.is_(None),
            ClinicDentalTreatmentPlan.status.in_(("draft", "proposed", "accepted", "active", "in_progress")),
            ClinicDentalTreatmentPlanItem.archived_at.is_(None),
            ClinicDentalTreatmentPlanItem.status.notin_(("completed", "cancelled")),
        )
        .all()
    )
    invoice = ClinicInvoice.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first()
    warnings = []
    if open_sessions:
        warnings.append("توجد جلسات أسنان مفتوحة مرتبطة بهذه الزيارة")
    if active_items:
        warnings.append("خطة العلاج ما زالت تحتوي بنوداً غير مكتملة — ستبقى الخطة قيد التنفيذ")
    if not invoice:
        warnings.append("لا توجد فاتورة لهذه الزيارة بعد — يمكن إنهاء الزيارة دون فاتورة")
    return {
        "visit_id": visit_id,
        "can_complete": True,
        "open_session_count": len(open_sessions),
        "open_sessions": [
            {"id": row.id, "session_number": row.session_number, "status": row.status}
            for row in open_sessions
        ],
        "active_treatment_count": len(active_items),
        "has_invoice": bool(invoice),
        "invoice_required": False,
        "warnings": warnings,
        "message": "يمكن إنهاء الزيارة. خطة العلاج تبقى مفتوحة إن لم تكتمل.",
    }


def patient_active_treatments(tenant_id: int, patient_id: int) -> dict:
    plans = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).filter(
        ClinicDentalTreatmentPlan.archived_at.is_(None),
        ClinicDentalTreatmentPlan.status.in_(("draft", "proposed", "accepted", "active", "in_progress")),
    ).all()
    plan_ids = [row.id for row in plans]
    items = []
    if plan_ids:
        items = (
            ClinicDentalTreatmentPlanItem.query.filter(
                ClinicDentalTreatmentPlanItem.tenant_id == tenant_id,
                ClinicDentalTreatmentPlanItem.plan_id.in_(plan_ids),
                ClinicDentalTreatmentPlanItem.archived_at.is_(None),
                ClinicDentalTreatmentPlanItem.status.notin_(("completed", "cancelled")),
            )
            .order_by(ClinicDentalTreatmentPlanItem.sort_order.asc(), ClinicDentalTreatmentPlanItem.id.asc())
            .all()
        )
    upcoming = (
        ClinicAppointment.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(
            ClinicAppointment.appointment_date >= _today(),
            ClinicAppointment.status.notin_(("cancelled", "rescheduled", "no_show", "completed")),
        )
        .order_by(ClinicAppointment.appointment_date.asc(), ClinicAppointment.start_time.asc())
        .first()
    )
    return {
        "active_plan_count": len(plans),
        "items": [
            {
                "id": item.id,
                "plan_id": item.plan_id,
                "tooth_number": item.tooth_number,
                "title": item.title,
                "status": item.status,
                "estimated_sessions": int(item.estimated_sessions or 1),
            }
            for item in items
        ],
        "upcoming_appointment": {
            "id": upcoming.id,
            "date": upcoming.appointment_date.isoformat(),
            "time": upcoming.start_time.strftime("%H:%M") if upcoming.start_time else "",
            "tooth_number": getattr(upcoming, "tooth_number", None),
        } if upcoming else None,
    }


def create_invoice_from_treatment_plan(
    tenant_id: int,
    plan_id: int,
    payload: dict,
    actor_id=None,
) -> dict:
    plan = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id, id=plan_id).first()
    if not plan or plan.archived_at:
        raise ValueError("خطة العلاج غير موجودة")
    _advisory_transaction_lock("dental-plan-invoice", tenant_id, plan.id)
    mode = str(payload.get("mode") or "full").strip().lower()
    if mode not in INVOICE_MODES:
        raise ValueError("نوع الفاتورة غير صالح")
    visit_id = int(payload["visit_id"]) if payload.get("visit_id") not in (None, "", 0, "0") else None
    if visit_id:
        visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id, patient_id=plan.patient_id).first()
        if not visit:
            raise ValueError("الزيارة غير مرتبطة بهذه الخطة")
    items = (
        ClinicDentalTreatmentPlanItem.query.filter_by(tenant_id=tenant_id, plan_id=plan.id)
        .filter(ClinicDentalTreatmentPlanItem.archived_at.is_(None))
        .filter(ClinicDentalTreatmentPlanItem.status != "cancelled")
        .order_by(ClinicDentalTreatmentPlanItem.sort_order.asc())
        .all()
    )
    session_row = None
    if mode == "selected":
        wanted = {int(value) for value in (payload.get("item_ids") or []) if value not in (None, "", 0, "0")}
        items = [row for row in items if row.id in wanted]
        if not items:
            raise ValueError("اختر بنوداً لإنشاء الفاتورة")
    elif mode == "session":
        session_id = int(payload.get("session_id") or 0)
        session_row = ClinicDentalSession.query.filter_by(tenant_id=tenant_id, id=session_id, plan_id=plan.id).first()
        if not session_row:
            raise ValueError("الجلسة غير موجودة")
        items = [row for row in items if row.id == session_row.treatment_plan_item_id]
    elif mode == "custom":
        amount = max(0, int(payload.get("custom_amount") or 0))
        if amount <= 0:
            raise ValueError("أدخل مبلغاً صالحاً")
        items = []
    lines = []
    if mode == "custom":
        amount = max(0, int(payload.get("custom_amount") or 0))
        lines.append({
            "description": f"دفعة على خطة علاج #{plan.id}",
            "quantity": 1,
            "unit_price": amount,
            "line_total": amount,
            "treatment_plan_item_id": None,
            "dental_session_id": None,
            "service_id": None,
        })
    else:
        for row in items:
            item_total = max(
                0,
                int(round(int(row.estimated_price or 0) * float(getattr(row, "quantity", 1) or 1)))
                - int(getattr(row, "discount", 0) or 0),
            )
            price = item_total
            if mode == "session" and session_row and int(row.estimated_sessions or 1) > 1:
                duplicate_session = ClinicInvoiceItem.query.filter_by(
                    tenant_id=tenant_id, dental_session_id=session_row.id
                ).first()
                if duplicate_session:
                    continue
                price = int(round(item_total / max(1, int(row.estimated_sessions or 1))))
            elif mode in {"full", "selected"}:
                billed = sum(
                    int(line.line_total or 0)
                    for line in ClinicInvoiceItem.query.filter_by(
                        tenant_id=tenant_id, treatment_plan_item_id=row.id
                    ).all()
                )
                price = max(0, item_total - billed)
            if price <= 0:
                continue
            tooth = f"السن {row.tooth_number} · " if row.tooth_number else ""
            lines.append({
                "description": f"{tooth}{row.title}",
                "quantity": 1,
                "unit_price": price,
                "line_total": price,
                "treatment_plan_item_id": row.id,
                "dental_session_id": session_row.id if session_row else None,
                "service_id": getattr(row, "service_id", None),
            })
    if not lines:
        existing_plan_invoice = (
            ClinicInvoice.query.filter_by(tenant_id=tenant_id, treatment_plan_id=plan.id)
            .order_by(ClinicInvoice.id.desc())
            .first()
        )
        if existing_plan_invoice:
            return invoice_dict(existing_plan_invoice)
        raise ValueError("لا توجد بنود قابلة للفوترة في هذا الاختيار")
    existing = None
    if visit_id:
        existing = ClinicInvoice.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first()
    if existing:
        inv = existing
    else:
        _advisory_transaction_lock("clinic-invoice-number", tenant_id)
        visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first() if visit_id else None
        inv = ClinicInvoice(
            tenant_id=tenant_id,
            branch_id=visit.branch_id if visit else None,
            visit_id=visit_id,
            appointment_id=visit.appointment_id if visit else None,
            patient_id=plan.patient_id,
            doctor_id=plan.created_by_doctor_id,
            invoice_number=_next_invoice_number(tenant_id),
            invoice_date=_today(),
            subtotal=0,
            discount=0,
            total=0,
            paid=0,
            balance=0,
            status="open",
            treatment_plan_id=plan.id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.session.add(inv)
        db.session.flush()
    for line in lines:
        db.session.add(ClinicInvoiceItem(
            tenant_id=tenant_id,
            invoice_id=inv.id,
            service_id=line["service_id"],
            description=line["description"],
            quantity=line["quantity"],
            unit_price=line["unit_price"],
            line_total=line["line_total"],
            treatment_plan_item_id=line["treatment_plan_item_id"],
            dental_session_id=line["dental_session_id"],
        ))
    items_total = sum(int(row.line_total or 0) for row in ClinicInvoiceItem.query.filter_by(tenant_id=tenant_id, invoice_id=inv.id).all())
    inv.treatment_plan_id = plan.id
    inv.subtotal = items_total
    inv.total = max(0, items_total - int(inv.discount or 0))
    inv.balance = max(0, inv.total - int(inv.paid or 0))
    inv.status = "paid" if inv.balance <= 0 else "open"
    inv.updated_by = actor_id
    db.session.flush()
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.post_clinic_invoice(inv.id, tenant_id, actor_id)
    _audit(
        tenant_id, actor_id, "invoice", inv.id, "create",
        f"فاتورة من خطة علاج #{plan.id}",
        meta={"treatment_plan_id": plan.id, "mode": mode, "visit_id": visit_id},
    )
    return invoice_dict(inv)


def dashboard_dental_widgets(tenant_id: int, day, *, doctor_id=None, include_financial: bool = False) -> dict:
    config = dental_config_for_tenant(tenant_id)
    settings = ClinicSettings.query.filter_by(tenant_id=tenant_id).first()
    specialty = None
    if settings and settings.primary_specialty_id:
        specialty = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, id=settings.primary_specialty_id).first()
    dental_context = bool(config["enabled"] and (not specialty or specialty.code in {"dentistry", "dental"}))
    sessions_q = ClinicDentalSession.query.filter_by(tenant_id=tenant_id)
    if doctor_id:
        plan_ids = db.session.query(ClinicDentalTreatmentPlan.id).filter_by(
            tenant_id=tenant_id, created_by_doctor_id=int(doctor_id)
        )
        sessions_q = sessions_q.filter(ClinicDentalSession.plan_id.in_(plan_ids))
    today_sessions = [
        row for row in sessions_q.filter(ClinicDentalSession.status != "cancelled").all()
        if row.scheduled_for and row.scheduled_for.date() == day
    ]
    plans_q = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id).filter(
        ClinicDentalTreatmentPlan.archived_at.is_(None),
        ClinicDentalTreatmentPlan.status.in_(("draft", "proposed", "accepted", "active", "in_progress")),
    )
    if doctor_id:
        plans_q = plans_q.filter_by(created_by_doctor_id=int(doctor_id))
    plans = plans_q.all()
    plan_ids = [row.id for row in plans]
    pending = []
    if plan_ids:
        pending = ClinicDentalTreatmentPlanItem.query.filter(
            ClinicDentalTreatmentPlanItem.tenant_id == tenant_id,
            ClinicDentalTreatmentPlanItem.plan_id.in_(plan_ids),
            ClinicDentalTreatmentPlanItem.archived_at.is_(None),
            ClinicDentalTreatmentPlanItem.status.notin_(("completed", "cancelled")),
        ).all()
    upcoming = ClinicAppointment.query.filter_by(tenant_id=tenant_id).filter(
        ClinicAppointment.appointment_date >= day,
        ClinicAppointment.status.notin_(("cancelled", "rescheduled", "no_show", "completed")),
        ClinicAppointment.specialty_code_snapshot.in_(("dentistry", "dental")),
    )
    if doctor_id:
        upcoming = upcoming.filter_by(doctor_id=int(doctor_id))
    upcoming_count = upcoming.count()
    estimated = sum(int(item.estimated_price or 0) for item in pending)
    payload = {
        "enabled": dental_context or bool(plans or today_sessions or pending),
        "sessions_today": len(today_sessions),
        "active_plans": len(plans),
        "incomplete_treatments": len(pending),
        "upcoming_appointments": upcoming_count,
    }
    if include_financial:
        payload.update({"estimated_outstanding": estimated, "pending_value": estimated})
    return payload


def search_dental(tenant_id: int, query: str, limit: int = 8) -> dict:
    q = str(query or "").strip()
    if len(q) < 2:
        return {"treatment_plans": [], "treatments": []}
    like = f"%{q}%"
    plans = (
        ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id)
        .filter(ClinicDentalTreatmentPlan.archived_at.is_(None))
        .filter(ClinicDentalTreatmentPlan.name.ilike(like))
        .order_by(ClinicDentalTreatmentPlan.updated_at.desc())
        .limit(limit)
        .all()
    )
    items_q = ClinicDentalTreatmentPlanItem.query.filter_by(tenant_id=tenant_id).filter(
        ClinicDentalTreatmentPlanItem.archived_at.is_(None),
        ClinicDentalTreatmentPlanItem.title.ilike(like),
    )
    if q.isdigit() and len(q) <= 4:
        items_q = ClinicDentalTreatmentPlanItem.query.filter_by(tenant_id=tenant_id).filter(
            ClinicDentalTreatmentPlanItem.archived_at.is_(None),
            db.or_(
                ClinicDentalTreatmentPlanItem.title.ilike(like),
                ClinicDentalTreatmentPlanItem.tooth_number == q,
            ),
        )
    items = items_q.order_by(ClinicDentalTreatmentPlanItem.updated_at.desc()).limit(limit).all()
    plan_map = {
        row.id: row.patient_id
        for row in ClinicDentalTreatmentPlan.query.filter(
            ClinicDentalTreatmentPlan.tenant_id == tenant_id,
            ClinicDentalTreatmentPlan.id.in_({item.plan_id for item in items} or {-1}),
        ).all()
    }
    return {
        "treatment_plans": [
            {
                "id": row.id,
                "name": row.name,
                "status": row.status,
                "patient_id": row.patient_id,
                "href": f"/clinics/patients/{row.patient_id}",
            }
            for row in plans
        ],
        "treatments": [
            {
                "id": row.id,
                "title": row.title,
                "tooth_number": row.tooth_number,
                "status": row.status,
                "plan_id": row.plan_id,
                "href": f"/clinics/patients/{plan_map.get(row.plan_id) or ''}",
            }
            for row in items
        ],
    }
