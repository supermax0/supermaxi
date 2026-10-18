"""Tenant-safe prescription quick-fill templates for the existing editor."""
from sqlalchemy import or_

from extensions import db
from modules.clinics.models import (
    ClinicDoctor, ClinicPrescriptionTemplate, ClinicPrescriptionTemplateItem,
    ClinicSpecialty, ClinicVisit,
)
from modules.clinics.service import _audit


def _dict(row):
    items = ClinicPrescriptionTemplateItem.query.filter_by(tenant_id=row.tenant_id, template_id=row.id).order_by(ClinicPrescriptionTemplateItem.sort_order, ClinicPrescriptionTemplateItem.id).all()
    return {"id": row.id, "name": row.name, "scope_type": row.scope_type,
            "specialty_id": row.specialty_id, "doctor_id": row.doctor_id,
            "notes": row.notes or "", "active": bool(row.active),
            "items": [{"medicine_name": item.medicine_name, "dosage": item.dosage or "",
                       "frequency": item.frequency or "", "duration": item.duration or "",
                       "instructions": item.instructions or ""} for item in items]}


def list_for_visit(tenant_id, visit_id):
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    rows = ClinicPrescriptionTemplate.query.filter(
        ClinicPrescriptionTemplate.tenant_id == tenant_id,
        ClinicPrescriptionTemplate.active.is_(True),
        or_(ClinicPrescriptionTemplate.scope_type == "clinic",
            (ClinicPrescriptionTemplate.scope_type == "specialty") & (ClinicPrescriptionTemplate.specialty_id == visit.specialty_id),
            (ClinicPrescriptionTemplate.scope_type == "doctor") & (ClinicPrescriptionTemplate.doctor_id == visit.doctor_id)),
    ).order_by(ClinicPrescriptionTemplate.name).all()
    return [_dict(row) for row in rows]


def _validate_scope(tenant_id, payload, restricted_doctor_id=None):
    scope = str(payload.get("scope_type") or ("doctor" if restricted_doctor_id else "clinic"))
    if scope not in {"clinic", "specialty", "doctor"}:
        raise ValueError("نطاق القالب غير صالح")
    specialty_id = int(payload["specialty_id"]) if scope == "specialty" and payload.get("specialty_id") else None
    doctor_id = int(payload["doctor_id"]) if scope == "doctor" and payload.get("doctor_id") else None
    if restricted_doctor_id:
        if scope != "doctor" or doctor_id not in (None, int(restricted_doctor_id)):
            raise ValueError("يمكن للطبيب إنشاء قوالبه الشخصية فقط")
        doctor_id = int(restricted_doctor_id)
    if scope == "specialty" and not ClinicSpecialty.query.filter_by(tenant_id=tenant_id, id=specialty_id).first():
        raise ValueError("الاختصاص غير موجود")
    if scope == "doctor" and not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
        raise ValueError("الطبيب غير موجود")
    return scope, specialty_id, doctor_id


def create_template(tenant_id, payload, actor_id=None, restricted_doctor_id=None):
    name = str(payload.get("name") or "").strip()
    items = payload.get("items") or []
    if not name or not isinstance(items, list) or not items:
        raise ValueError("اسم القالب ودواء واحد على الأقل مطلوبان")
    scope, specialty_id, doctor_id = _validate_scope(tenant_id, payload, restricted_doctor_id)
    row = ClinicPrescriptionTemplate(tenant_id=tenant_id, name=name, scope_type=scope,
                                     specialty_id=specialty_id, doctor_id=doctor_id,
                                     notes=str(payload.get("notes") or "").strip() or None, created_by=actor_id)
    db.session.add(row); db.session.flush()
    for index, item in enumerate(items):
        medicine = str(item.get("medicine_name") or "").strip()
        if not medicine:
            raise ValueError("اسم الدواء مطلوب في جميع بنود القالب")
        db.session.add(ClinicPrescriptionTemplateItem(tenant_id=tenant_id, template_id=row.id,
            medicine_name=medicine, dosage=str(item.get("dosage") or "").strip() or None,
            frequency=str(item.get("frequency") or "").strip() or None,
            duration=str(item.get("duration") or "").strip() or None,
            instructions=str(item.get("instructions") or "").strip() or None, sort_order=index))
    _audit(tenant_id, actor_id, "prescription_template", row.id, "create", f"إنشاء قالب وصفة {name}")
    db.session.flush()
    return _dict(row)


def archive_template(tenant_id, template_id, actor_id=None, restricted_doctor_id=None):
    row = ClinicPrescriptionTemplate.query.filter_by(tenant_id=tenant_id, id=template_id).first()
    if not row:
        raise ValueError("قالب الوصفة غير موجود")
    if restricted_doctor_id and (row.scope_type != "doctor" or row.doctor_id != int(restricted_doctor_id)):
        raise ValueError("لا يمكنك أرشفة قالب طبيب آخر")
    row.active = False
    _audit(tenant_id, actor_id, "prescription_template", row.id, "archive", f"أرشفة قالب وصفة {row.name}")
    return _dict(row)
