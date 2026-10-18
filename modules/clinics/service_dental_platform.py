"""Dental sessions, image metadata, and operational reports over existing ledgers."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func

from extensions import db
from modules.clinics.models import (
    ClinicAppointment,
    ClinicAttachment,
    ClinicDentalImage,
    ClinicDentalSession,
    ClinicDentalTreatmentPlan,
    ClinicDentalTreatmentPlanItem,
    ClinicDentalTreatmentPlanItemLink,
    ClinicPatient,
    ClinicProcedure,
    ClinicVisit,
    ClinicVisitProcedure,
)
from modules.clinics.service import _audit
from modules.clinics.service_dental import validate_tooth_number
from modules.clinics.service_dental_treatment import link_item_procedure

SESSION_STATUSES = frozenset({"planned", "scheduled", "in_progress", "completed", "cancelled", "no_show"})
SESSION_TRANSITIONS = {
    "planned": {"scheduled", "in_progress", "no_show"},
    "scheduled": {"planned", "in_progress", "no_show"},
    "in_progress": set(),
    "no_show": {"planned", "scheduled"},
}
IMAGE_TYPES = frozenset({
    "xray", "panoramic", "opg", "periapical", "bitewing", "cbct",
    "cephalometric", "intraoral", "before", "after", "photo", "scan", "other",
})


def _dt(value, label: str):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise ValueError(f"{label} غير صالح") from exc


def _item_context(tenant_id: int, item_id: int):
    item = ClinicDentalTreatmentPlanItem.query.filter_by(
        tenant_id=tenant_id, id=item_id, archived_at=None
    ).first()
    if not item:
        raise ValueError("بند خطة العلاج غير موجود")
    plan = ClinicDentalTreatmentPlan.query.filter_by(
        tenant_id=tenant_id, id=item.plan_id, archived_at=None
    ).first()
    if not plan:
        raise ValueError("خطة العلاج غير موجودة")
    return item, plan


def _session_dict(row: ClinicDentalSession) -> dict:
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "treatment_plan_item_id": row.treatment_plan_item_id,
        "appointment_id": row.appointment_id,
        "visit_id": row.visit_id,
        "visit_procedure_id": row.visit_procedure_id,
        "session_number": row.session_number,
        "status": row.status,
        "scheduled_for": row.scheduled_for.isoformat() if row.scheduled_for else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "notes": row.notes or "",
        "next_recommendation": getattr(row, "next_recommendation", None) or "",
        "cancellation_reason": getattr(row, "cancellation_reason", None) or "",
    }


def list_sessions(tenant_id: int, *, plan_id=None, item_id=None, patient_id=None) -> dict:
    query = ClinicDentalSession.query.filter_by(tenant_id=tenant_id)
    if plan_id:
        query = query.filter_by(plan_id=int(plan_id))
    if item_id:
        query = query.filter_by(treatment_plan_item_id=int(item_id))
    if patient_id:
        plan_ids = db.session.query(ClinicDentalTreatmentPlan.id).filter_by(
            tenant_id=tenant_id, patient_id=int(patient_id)
        )
        query = query.filter(ClinicDentalSession.plan_id.in_(plan_ids))
    rows = query.order_by(
        ClinicDentalSession.scheduled_for.asc(), ClinicDentalSession.session_number.asc()
    ).all()
    now = datetime.utcnow()
    next_row = next(
        (r for r in rows if r.status in {"planned", "scheduled"} and (not r.scheduled_for or r.scheduled_for >= now)),
        None,
    )
    return {"items": [_session_dict(r) for r in rows], "next_session": _session_dict(next_row) if next_row else None}


def create_session(tenant_id: int, item_id: int, payload: dict, actor_id=None) -> dict:
    item, plan = _item_context(tenant_id, item_id)
    if plan.status in {"completed", "cancelled", "archived"} or item.status in {"completed", "cancelled"}:
        raise ValueError("لا يمكن إضافة جلسة إلى علاج مغلق")
    appointment_id = int(payload["appointment_id"]) if payload.get("appointment_id") else None
    visit_id = int(payload["visit_id"]) if payload.get("visit_id") else None
    appointment = None
    if appointment_id:
        appointment = ClinicAppointment.query.filter_by(
            tenant_id=tenant_id, id=appointment_id, patient_id=plan.patient_id
        ).first()
        if not appointment:
            raise ValueError("الموعد لا يخص مريض الخطة")
    if visit_id and not ClinicVisit.query.filter_by(
        tenant_id=tenant_id, id=visit_id, patient_id=plan.patient_id
    ).first():
        raise ValueError("الزيارة لا تخص مريض الخطة")
    status = str(payload.get("status") or ("scheduled" if payload.get("scheduled_for") else "planned")).lower()
    if status not in SESSION_STATUSES - {"completed"}:
        raise ValueError("حالة الجلسة غير صالحة")
    number = (
        db.session.query(func.max(ClinicDentalSession.session_number))
        .filter_by(tenant_id=tenant_id, treatment_plan_item_id=item.id)
        .scalar()
        or 0
    ) + 1
    row = ClinicDentalSession(
        tenant_id=tenant_id,
        plan_id=plan.id,
        treatment_plan_item_id=item.id,
        appointment_id=appointment_id,
        visit_id=visit_id,
        session_number=number,
        status=status,
        scheduled_for=_dt(payload.get("scheduled_for"), "موعد الجلسة"),
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    if appointment:
        appointment.treatment_plan_id = plan.id
        appointment.treatment_plan_item_id = item.id
        appointment.dental_session_id = row.id
        appointment.tooth_number = item.tooth_number
        appointment.tooth_numbers_json = getattr(item, "tooth_numbers_json", None) or json.dumps(
            [item.tooth_number] if item.tooth_number else [], ensure_ascii=False
        )
        appointment.updated_by = actor_id
    if item.status == "planned" and status in {"scheduled", "in_progress"}:
        item.status = "scheduled" if status == "scheduled" else "in_progress"
    _audit(tenant_id, actor_id, "dental_session", row.id, "create", f"إنشاء جلسة أسنان #{number}")
    return _session_dict(row)


def update_session(tenant_id: int, session_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicDentalSession.query.filter_by(tenant_id=tenant_id, id=session_id).first()
    if not row:
        raise ValueError("جلسة الأسنان غير موجودة")
    if row.status in {"completed", "cancelled"}:
        raise ValueError("لا يمكن تعديل جلسة مغلقة")
    _, plan = _item_context(tenant_id, row.treatment_plan_item_id)
    status = str(payload.get("status") or row.status).lower()
    if status not in SESSION_STATUSES - {"completed", "cancelled"}:
        raise ValueError("حالة الجلسة غير صالحة")
    if status != row.status and status not in SESSION_TRANSITIONS.get(row.status, set()):
        raise ValueError("انتقال حالة الجلسة غير مسموح")
    if "appointment_id" in payload:
        appointment_id = int(payload["appointment_id"]) if payload.get("appointment_id") else None
        appointment = None
        if appointment_id:
            appointment = ClinicAppointment.query.filter_by(
                tenant_id=tenant_id, id=appointment_id, patient_id=plan.patient_id
            ).first()
            if not appointment:
                raise ValueError("الموعد لا يخص مريض الخطة")
        row.appointment_id = appointment_id
        if appointment:
            item = ClinicDentalTreatmentPlanItem.query.filter_by(
                tenant_id=tenant_id, id=row.treatment_plan_item_id
            ).first()
            appointment.treatment_plan_id = plan.id
            appointment.treatment_plan_item_id = row.treatment_plan_item_id
            appointment.dental_session_id = row.id
            appointment.tooth_number = appointment.tooth_number or (item.tooth_number if item else None)
            if not getattr(appointment, "tooth_numbers_json", None):
                appointment.tooth_numbers_json = getattr(item, "tooth_numbers_json", None) or json.dumps(
                    [item.tooth_number] if item and item.tooth_number else [], ensure_ascii=False
                )
            appointment.updated_by = actor_id
    if "visit_id" in payload:
        visit_id = int(payload["visit_id"]) if payload.get("visit_id") else None
        if visit_id and not ClinicVisit.query.filter_by(
            tenant_id=tenant_id, id=visit_id, patient_id=plan.patient_id
        ).first():
            raise ValueError("الزيارة لا تخص مريض الخطة")
        row.visit_id = visit_id
    if "scheduled_for" in payload:
        row.scheduled_for = _dt(payload.get("scheduled_for"), "موعد الجلسة")
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "").strip() or None
    row.status = status
    if status == "in_progress":
        row.started_at = row.started_at or datetime.utcnow()
        item = ClinicDentalTreatmentPlanItem.query.filter_by(tenant_id=tenant_id, id=row.treatment_plan_item_id).first()
        if item and item.status not in {"completed", "cancelled"}:
            item.status = "in_progress"
        if plan.status in {"draft", "proposed", "accepted", "active"}:
            plan.status = "in_progress"
            plan.started_at = plan.started_at or datetime.utcnow()
    row.updated_by = actor_id
    _audit(tenant_id, actor_id, "dental_session", row.id, "update", "تحديث جلسة أسنان")
    return _session_dict(row)


def complete_session(tenant_id: int, session_id: int, payload: dict, actor_id=None) -> dict:
    query = ClinicDentalSession.query.filter_by(tenant_id=tenant_id, id=session_id)
    if db.session.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise ValueError("جلسة الأسنان غير موجودة")
    if row.status == "completed":
        return _session_dict(row)
    if row.status == "cancelled":
        raise ValueError("لا يمكن إكمال جلسة ملغاة")
    item, plan = _item_context(tenant_id, row.treatment_plan_item_id)
    visit_id = int(payload.get("visit_id") or row.visit_id or 0)
    visit = ClinicVisit.query.filter_by(
        tenant_id=tenant_id, id=visit_id, patient_id=plan.patient_id
    ).first()
    if not visit:
        raise ValueError("زيارة صحيحة مطلوبة لإكمال الجلسة")
    vp_id = payload.get("visit_procedure_id") or row.visit_procedure_id
    vp = None
    if vp_id:
        vp = ClinicVisitProcedure.query.filter_by(tenant_id=tenant_id, id=int(vp_id), visit_id=visit.id).first()
        if not vp or vp.patient_id != plan.patient_id:
            raise ValueError("إجراء الزيارة لا يخص هذه الجلسة")
    else:
        if not item.procedure_id:
            raise ValueError("حدد visit_procedure_id لبند بلا إجراء")
        procedure = ClinicProcedure.query.filter_by(tenant_id=tenant_id, id=item.procedure_id).first()
        if not procedure:
            raise ValueError("الإجراء غير موجود")
        vp = ClinicVisitProcedure(
            tenant_id=tenant_id,
            visit_id=visit.id,
            patient_id=plan.patient_id,
            doctor_id=visit.doctor_id,
            procedure_id=procedure.id,
            status="requested",
            price=int(payload.get("price") if payload.get("price") is not None else procedure.price or 0),
            created_by=actor_id,
        )
        db.session.add(vp)
        db.session.flush()
    # Reuse the canonical transition so recipe inventory is consumed exactly
    # once and the execution audit/status timestamps remain consistent.
    from modules.clinics.service_clinical_ops import transition_execution
    transition_execution(tenant_id, vp.id, {"status": "completed"}, actor_id)
    link_item_procedure(tenant_id, item.id, vp.id, actor_id)
    row.visit_id = visit.id
    row.visit_procedure_id = vp.id
    row.status = "completed"
    row.completed_at = datetime.utcnow()
    row.completed_by = actor_id
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "").strip() or None
    if "next_recommendation" in payload:
        row.next_recommendation = str(payload.get("next_recommendation") or "").strip() or None
    row.updated_by = actor_id
    completed_count = ClinicDentalSession.query.filter_by(
        tenant_id=tenant_id, treatment_plan_item_id=item.id, status="completed"
    ).count()
    is_final = bool(payload.get("is_final")) or completed_count >= int(item.estimated_sessions or 1)
    if is_final:
        item.status = "completed"
        item.completed_at = item.completed_at or datetime.utcnow()
        open_items = ClinicDentalTreatmentPlanItem.query.filter(
            ClinicDentalTreatmentPlanItem.tenant_id == tenant_id,
            ClinicDentalTreatmentPlanItem.plan_id == plan.id,
            ClinicDentalTreatmentPlanItem.archived_at.is_(None),
            ClinicDentalTreatmentPlanItem.status.notin_(("completed", "cancelled")),
            ClinicDentalTreatmentPlanItem.id != item.id,
        ).count()
        if not open_items:
            plan.status = "completed"
            plan.completed_at = plan.completed_at or datetime.utcnow()
    else:
        item.status = "in_progress"
        plan.status = "in_progress"
        next_row = ClinicDentalSession.query.filter(
            ClinicDentalSession.tenant_id == tenant_id,
            ClinicDentalSession.treatment_plan_item_id == item.id,
            ClinicDentalSession.session_number > row.session_number,
            ClinicDentalSession.status.notin_(("completed", "cancelled", "no_show")),
        ).order_by(ClinicDentalSession.session_number.asc()).first()
        if not next_row:
            next_row = ClinicDentalSession(
                tenant_id=tenant_id,
                plan_id=plan.id,
                treatment_plan_item_id=item.id,
                session_number=row.session_number + 1,
                status="planned",
                notes=row.next_recommendation,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.session.add(next_row)
            db.session.flush()
    _audit(
        tenant_id, actor_id, "dental_session", row.id, "complete", f"إكمال جلسة أسنان #{row.session_number}",
        meta={"visit_id": visit.id, "visit_procedure_id": vp.id, "final": is_final},
    )
    db.session.flush()
    result = _session_dict(row)
    result["next_session"] = _session_dict(next_row) if not is_final and next_row else None
    return result


def cancel_session(tenant_id: int, session_id: int, actor_id=None, payload: dict | None = None) -> dict:
    row = ClinicDentalSession.query.filter_by(tenant_id=tenant_id, id=session_id).first()
    if not row:
        raise ValueError("جلسة الأسنان غير موجودة")
    if row.status == "completed":
        raise ValueError("لا يمكن إلغاء جلسة مكتملة")
    if row.status != "cancelled":
        reason = str((payload or {}).get("cancellation_reason") or "").strip()
        if not reason:
            raise ValueError("سبب إلغاء الجلسة مطلوب")
        row.status = "cancelled"
        row.cancelled_at = datetime.utcnow()
        row.cancelled_by = actor_id
        row.cancellation_reason = reason
        if payload and "notes" in payload:
            row.notes = str(payload.get("notes") or "").strip() or row.notes
        row.updated_by = actor_id
        _audit(
            tenant_id, actor_id, "dental_session", row.id, "cancel", "إلغاء جلسة أسنان",
            meta={"cancellation_reason": reason},
        )
    return _session_dict(row)


def _image_dict(row: ClinicDentalImage) -> dict:
    attachment = ClinicAttachment.query.filter_by(tenant_id=row.tenant_id, id=row.attachment_id).first()
    return {
        "id": row.id,
        "attachment_id": row.attachment_id,
        "patient_id": row.patient_id,
        "visit_id": row.visit_id,
        "treatment_plan_id": getattr(row, "treatment_plan_id", None),
        "treatment_plan_item_id": row.treatment_plan_item_id,
        "dental_session_id": getattr(row, "dental_session_id", None),
        "tooth_number": row.tooth_number,
        "image_type": row.image_type,
        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
        "notes": row.notes or "",
        "archived": bool(row.archived_at),
        "file_name": attachment.file_name if attachment else "",
        "mime_type": attachment.mime_type if attachment else "",
    }


def create_image_metadata(tenant_id: int, payload: dict, actor_id=None) -> dict:
    attachment_id = int(payload.get("attachment_id") or 0)
    attachment = ClinicAttachment.query.filter_by(tenant_id=tenant_id, id=attachment_id).first()
    if not attachment:
        raise ValueError("المرفق غير موجود")
    if not str(attachment.mime_type or "").startswith("image/"):
        raise ValueError("المرفق ليس صورة")
    patient_id = int(payload.get("patient_id") or attachment.patient_id)
    if patient_id != attachment.patient_id:
        raise ValueError("الصورة لا تخص المريض")
    visit_id = int(payload["visit_id"]) if payload.get("visit_id") else attachment.visit_id
    if visit_id and not ClinicVisit.query.filter_by(
        tenant_id=tenant_id, id=visit_id, patient_id=patient_id
    ).first():
        raise ValueError("الزيارة لا تخص المريض")
    item_id = int(payload["treatment_plan_item_id"]) if payload.get("treatment_plan_item_id") else None
    plan_id = int(payload["treatment_plan_id"]) if payload.get("treatment_plan_id") else None
    session_id = int(payload["dental_session_id"]) if payload.get("dental_session_id") else None
    if item_id:
        _, plan = _item_context(tenant_id, item_id)
        if plan.patient_id != patient_id:
            raise ValueError("بند العلاج لا يخص المريض")
        if plan_id and plan_id != plan.id:
            raise ValueError("بند العلاج لا يخص الخطة المحددة")
        plan_id = plan.id
    if plan_id:
        plan = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id, id=plan_id).first()
        if not plan or plan.archived_at or plan.patient_id != patient_id:
            raise ValueError("خطة العلاج لا تخص المريض")
    if session_id:
        session = ClinicDentalSession.query.filter_by(tenant_id=tenant_id, id=session_id).first()
        if not session:
            raise ValueError("جلسة الأسنان غير موجودة")
        session_plan = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id, id=session.plan_id).first()
        if not session_plan or session_plan.patient_id != patient_id:
            raise ValueError("جلسة الأسنان لا تخص المريض")
        if item_id and item_id != session.treatment_plan_item_id:
            raise ValueError("الجلسة لا تخص بند العلاج المحدد")
        if plan_id and plan_id != session.plan_id:
            raise ValueError("الجلسة لا تخص الخطة المحددة")
        item_id = session.treatment_plan_item_id
        plan_id = session.plan_id
    image_type = str(payload.get("image_type") or "other").lower()
    if image_type not in IMAGE_TYPES:
        raise ValueError("نوع صورة الأسنان غير صالح")
    tooth = validate_tooth_number(str(payload["tooth_number"])) if payload.get("tooth_number") else None
    row = ClinicDentalImage(
        tenant_id=tenant_id, attachment_id=attachment.id, patient_id=patient_id,
        visit_id=visit_id, treatment_plan_id=plan_id, treatment_plan_item_id=item_id,
        dental_session_id=session_id, tooth_number=tooth,
        image_type=image_type, captured_at=_dt(payload.get("captured_at"), "تاريخ الصورة"),
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id, updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "dental_image", row.id, "create", "إضافة بيانات صورة أسنان")
    return _image_dict(row)


def list_images(tenant_id: int, params: dict | None = None) -> list[dict]:
    params = params or {}
    query = ClinicDentalImage.query.filter_by(tenant_id=tenant_id)
    if str(params.get("include_deleted") or "").lower() not in {"1", "true"}:
        query = query.filter(ClinicDentalImage.archived_at.is_(None))
    for key in ("patient_id", "visit_id", "treatment_plan_id", "treatment_plan_item_id", "dental_session_id", "attachment_id"):
        if params.get(key):
            query = query.filter(getattr(ClinicDentalImage, key) == int(params[key]))
    if params.get("tooth_number"):
        query = query.filter_by(tooth_number=validate_tooth_number(str(params["tooth_number"])))
    if params.get("image_type"):
        query = query.filter_by(image_type=str(params["image_type"]).lower())
    return [_image_dict(r) for r in query.order_by(ClinicDentalImage.created_at.desc()).all()]


def delete_image_metadata(tenant_id: int, image_id: int, actor_id=None) -> dict:
    row = ClinicDentalImage.query.filter_by(tenant_id=tenant_id, id=image_id).first()
    if not row:
        raise ValueError("صورة الأسنان غير موجودة")
    if not row.archived_at:
        row.archived_at = datetime.utcnow()
        row.updated_by = actor_id
        _audit(tenant_id, actor_id, "dental_image", row.id, "delete", "حذف بيانات صورة أسنان")
    return _image_dict(row)


def dental_reports(tenant_id: int, *, patient_id=None) -> dict:
    plans = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id)
    if patient_id:
        plans = plans.filter_by(patient_id=int(patient_id))
    plan_rows = plans.filter(ClinicDentalTreatmentPlan.archived_at.is_(None)).all()
    plan_ids = [p.id for p in plan_rows]
    items = ClinicDentalTreatmentPlanItem.query.filter(
        ClinicDentalTreatmentPlanItem.tenant_id == tenant_id,
        ClinicDentalTreatmentPlanItem.plan_id.in_(plan_ids or {-1}),
        ClinicDentalTreatmentPlanItem.archived_at.is_(None),
    ).all()
    links = ClinicDentalTreatmentPlanItemLink.query.filter(
        ClinicDentalTreatmentPlanItemLink.tenant_id == tenant_id,
        ClinicDentalTreatmentPlanItemLink.treatment_plan_item_id.in_([i.id for i in items] or {-1}),
    ).all()
    execution_count = len({link.visit_procedure_id for link in links})
    pending = [i for i in items if i.status not in {"completed", "cancelled"}]
    patients = {
        p.id: p for p in ClinicPatient.query.filter(
            ClinicPatient.tenant_id == tenant_id,
            ClinicPatient.id.in_({p.patient_id for p in plan_rows} or {-1}),
        ).all()
    }
    plans_by_id = {p.id: p for p in plan_rows}
    return {
        "overview": {
            "plan_count": len(plan_rows),
            "active_plan_count": sum(p.status in {"draft", "active"} for p in plan_rows),
            "treatment_count": len(items),
            "pending_treatment_count": len(pending),
            "completed_treatment_count": sum(i.status == "completed" for i in items),
            "execution_count": execution_count,
        },
        "pending_treatments": [
            {
                "item_id": item.id,
                "plan_id": item.plan_id,
                "patient_id": plans_by_id[item.plan_id].patient_id,
                "patient_name": patients.get(plans_by_id[item.plan_id].patient_id).full_name
                if patients.get(plans_by_id[item.plan_id].patient_id) else "",
                "tooth_number": item.tooth_number,
                "title": item.title,
                "priority": item.priority,
                "status": item.status,
                "estimated_sessions": item.estimated_sessions,
            }
            for item in pending
        ],
    }
