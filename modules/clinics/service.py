"""Core clinic workflow services."""
from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import case, func, or_, text

from extensions import db
from modules.clinics.models import (
    APPOINTMENT_STATUSES,
    CLINIC_TYPES,
    ClinicAppointment,
    ClinicAppointmentStatusHistory,
    ClinicAuditLog,
    ClinicDiagnosis,
    ClinicDoctor,
    ClinicInvoice,
    ClinicInvoiceItem,
    ClinicPatient,
    ClinicPayment,
    ClinicPrescription,
    ClinicPrescriptionItem,
    ClinicRoom,
    ClinicService,
    ClinicSettings,
    ClinicSpecialty,
    ClinicVisit,
    ClinicVital,
)


def _today() -> date:
    return date.today()


def _parse_date(value, label="التاريخ") -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} مطلوب")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"{label} غير صالح") from exc


def _parse_time(value, label="الوقت") -> time:
    if isinstance(value, time):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} مطلوب")
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"{label} غير صالح")


def _money(value) -> int:
    try:
        return max(0, int(round(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def _audit(tenant_id: int, actor_id, entity_type: str, entity_id, action: str, summary: str, meta=None, branch_id=None):
    db.session.add(
        ClinicAuditLog(
            tenant_id=tenant_id,
            branch_id=branch_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            summary=summary,
            meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
            actor_id=actor_id,
        )
    )


def get_or_create_settings(tenant_id: int, actor_id=None) -> ClinicSettings:
    row = ClinicSettings.query.filter_by(tenant_id=tenant_id).first()
    if row:
        return row
    row = ClinicSettings(tenant_id=tenant_id, created_by=actor_id, updated_by=actor_id)
    db.session.add(row)
    db.session.flush()
    return row


def settings_payload(tenant_id: int) -> dict:
    row = get_or_create_settings(tenant_id)
    from modules.clinics.service_specialties import ORGANIZATION_MODES
    from modules.clinics.service_dental_completion import normalize_dental_config
    try:
        specialty_features = json.loads(row.specialty_features_json or "{}")
    except (TypeError, ValueError):
        specialty_features = {}
    return {
        "clinic_type": row.clinic_type,
        "clinic_type_label": dict(CLINIC_TYPES).get(row.clinic_type, row.clinic_type),
        "clinic_types": [{"key": k, "label": v} for k, v in CLINIC_TYPES],
        "organization_mode": getattr(row, "organization_mode", "solo_clinic") or "solo_clinic",
        "organization_mode_label": dict(ORGANIZATION_MODES).get(getattr(row, "organization_mode", "solo_clinic"), "عيادة طبيب واحد"),
        "organization_modes": [{"key": key, "label": label} for key, label in ORGANIZATION_MODES],
        "clinic_name": row.clinic_name or "",
        "default_currency": row.default_currency,
        "appointment_slot_minutes": row.appointment_slot_minutes,
        "allow_online_booking": bool(row.allow_online_booking),
        "queue_display_enabled": bool(row.queue_display_enabled),
        "doctor_commission_default_pct": float(row.doctor_commission_default_pct or 0),
        "doctor_availability_requires_attendance": bool(getattr(row, "doctor_availability_requires_attendance", False)),
        "language": row.language or "ar",
        "booking_welcome_text": row.booking_welcome_text or "",
        "whatsapp_notifications_enabled": bool(row.whatsapp_notifications_enabled),
        "default_followup_days": int(row.default_followup_days or 7),
        "reminder_hours_before": int(row.reminder_hours_before or 24),
        "booking_rate_limit_per_hour": int(row.booking_rate_limit_per_hour or 10),
        "booking_otp_enabled": bool(getattr(row, "booking_otp_enabled", False)),
        "booking_mode": getattr(row, "booking_mode", "direct") or "direct",
        "minimum_booking_notice_hours": int(getattr(row, "minimum_booking_notice_hours", 2) or 0),
        "maximum_advance_booking_days": int(getattr(row, "maximum_advance_booking_days", 60) or 60),
        "allow_same_day_booking": bool(getattr(row, "allow_same_day_booking", True)),
        "allow_public_reschedule": bool(getattr(row, "allow_public_reschedule", True)),
        "allow_public_cancellation": bool(getattr(row, "allow_public_cancellation", True)),
        "cancellation_deadline_hours": int(getattr(row, "cancellation_deadline_hours", 4) or 0),
        "max_active_appointments_per_patient": int(getattr(row, "max_active_appointments_per_patient", 3) or 1),
        "public_show_prices": bool(getattr(row, "public_show_prices", False)),
        "clinic_whatsapp_number": getattr(row, "clinic_whatsapp_number", None) or "",
        "public_profile_enabled": bool(getattr(row, "public_profile_enabled", True)),
        "public_chat_enabled": bool(getattr(row, "public_chat_enabled", True)),
        "public_logo_url": getattr(row, "public_logo_url", None) or "",
        "public_location": getattr(row, "public_location", None) or "",
        "public_working_hours": getattr(row, "public_working_hours", None) or "",
        "specialty_pack_seeded": bool(getattr(row, "specialty_pack_seeded", False)),
        "primary_specialty_id": getattr(row, "primary_specialty_id", None),
        "specialty_features": specialty_features,
        "dental_config": normalize_dental_config(getattr(row, "dental_config_json", None)),
        "display_sound_enabled": bool(getattr(row, "display_sound_enabled", True)),
        "display_voice_enabled": bool(getattr(row, "display_voice_enabled", False)),
        "display_volume": max(0, min(100, int(getattr(row, "display_volume", 70) or 70))),
        "display_show_short_name": bool(getattr(row, "display_show_short_name", False)),
        "display_footer_message": getattr(row, "display_footer_message", None) or "",
    }


# Legacy clinic_type values that actually mean organization shape (deprecated).
_LEGACY_ORG_FROM_CLINIC_TYPE = {
    "single_doctor": "solo_clinic",
    "multi_doctor": "multi_doctor_clinic",
    "medical_center": "medical_center",
}


def update_settings(tenant_id: int, payload: dict, actor_id=None) -> dict:
    row = get_or_create_settings(tenant_id, actor_id)
    # organization_mode is the source of truth for facility shape.
    if "organization_mode" in payload:
        from modules.clinics.service_specialties import ORGANIZATION_MODES
        organization_mode = str(payload.get("organization_mode") or "solo_clinic").strip()
        if organization_mode not in {key for key, _ in ORGANIZATION_MODES}:
            raise ValueError("نوع المنشأة غير مدعوم")
        row.organization_mode = organization_mode
    # clinic_type is deprecated: accept only when explicitly sent (compat / packs).
    # Never let specialty-like clinic_type override organization_mode, and map
    # legacy org-shaped clinic_type values into organization_mode instead.
    if "clinic_type" in payload:
        clinic_type = str(payload.get("clinic_type") or "").strip()
        allowed = {k for k, _ in CLINIC_TYPES}
        if clinic_type and clinic_type not in allowed:
            raise ValueError("نوع العيادة غير مدعوم")
        if clinic_type in _LEGACY_ORG_FROM_CLINIC_TYPE:
            if "organization_mode" not in payload:
                row.organization_mode = _LEGACY_ORG_FROM_CLINIC_TYPE[clinic_type]
            # Keep a neutral specialty hint; org shape lives in organization_mode.
            if row.clinic_type in _LEGACY_ORG_FROM_CLINIC_TYPE:
                row.clinic_type = "general_practice"
        elif clinic_type:
            row.clinic_type = clinic_type
    row.clinic_name = (payload.get("clinic_name") or row.clinic_name or "").strip() or None
    row.appointment_slot_minutes = max(5, int(payload.get("appointment_slot_minutes") or row.appointment_slot_minutes or 15))
    row.allow_online_booking = bool(payload.get("allow_online_booking", row.allow_online_booking))
    row.queue_display_enabled = bool(payload.get("queue_display_enabled", row.queue_display_enabled))
    if "doctor_commission_default_pct" in payload:
        row.doctor_commission_default_pct = float(payload.get("doctor_commission_default_pct") or 0)
    if "doctor_availability_requires_attendance" in payload:
        row.doctor_availability_requires_attendance = bool(payload.get("doctor_availability_requires_attendance"))
    if "booking_welcome_text" in payload:
        row.booking_welcome_text = str(payload.get("booking_welcome_text") or "").strip() or None
    if "whatsapp_notifications_enabled" in payload:
        row.whatsapp_notifications_enabled = bool(payload.get("whatsapp_notifications_enabled"))
    if "default_followup_days" in payload:
        row.default_followup_days = max(1, int(payload.get("default_followup_days") or 7))
    if "reminder_hours_before" in payload:
        row.reminder_hours_before = max(1, int(payload.get("reminder_hours_before") or 24))
    if "booking_rate_limit_per_hour" in payload:
        row.booking_rate_limit_per_hour = max(1, int(payload.get("booking_rate_limit_per_hour") or 10))
    if "booking_otp_enabled" in payload:
        row.booking_otp_enabled = bool(payload.get("booking_otp_enabled"))
    if "booking_mode" in payload:
        mode = str(payload.get("booking_mode") or "direct")
        if mode not in ("direct", "approval"):
            raise ValueError("وضع الحجز غير صحيح")
        row.booking_mode = mode
    for field, minimum, default in (
        ("minimum_booking_notice_hours", 0, 2),
        ("maximum_advance_booking_days", 1, 60),
        ("cancellation_deadline_hours", 0, 4),
        ("max_active_appointments_per_patient", 1, 3),
    ):
        if field in payload:
            setattr(row, field, max(minimum, int(payload.get(field) or default)))
    for field in ("allow_same_day_booking", "allow_public_reschedule", "allow_public_cancellation", "public_show_prices", "public_profile_enabled", "public_chat_enabled"):
        if field in payload:
            setattr(row, field, bool(payload.get(field)))
    if "clinic_whatsapp_number" in payload:
        row.clinic_whatsapp_number = str(payload.get("clinic_whatsapp_number") or "").strip() or None
    for field, limit in (("public_logo_url", 500), ("public_location", 300), ("public_working_hours", 300)):
        if field in payload:
            setattr(row, field, str(payload.get(field) or "").strip()[:limit] or None)
    if "display_sound_enabled" in payload:
        row.display_sound_enabled = bool(payload.get("display_sound_enabled"))
    if "display_voice_enabled" in payload:
        row.display_voice_enabled = bool(payload.get("display_voice_enabled"))
    if "display_volume" in payload:
        try:
            row.display_volume = max(0, min(100, int(payload.get("display_volume"))))
        except (TypeError, ValueError):
            row.display_volume = 70
    if "display_show_short_name" in payload:
        row.display_show_short_name = bool(payload.get("display_show_short_name"))
    if "display_footer_message" in payload:
        row.display_footer_message = str(payload.get("display_footer_message") or "").strip() or None
    if "primary_specialty_id" in payload:
        specialty_id = int(payload["primary_specialty_id"]) if payload.get("primary_specialty_id") else None
        if specialty_id and not ClinicSpecialty.query.filter_by(
            tenant_id=tenant_id, id=specialty_id, is_active=True
        ).first():
            raise ValueError("الاختصاص الرئيسي لا يتبع هذه المنشأة")
        row.primary_specialty_id = specialty_id
    if "specialty_features" in payload:
        feature_config = payload.get("specialty_features") or {}
        if not isinstance(feature_config, dict):
            raise ValueError("إعدادات ميزات الاختصاص غير صالحة")
        row.specialty_features_json = json.dumps(feature_config, ensure_ascii=False, sort_keys=True)
    if "dental_config" in payload:
        from modules.clinics.service_dental_completion import normalize_dental_config
        dental_config = payload.get("dental_config") or {}
        if not isinstance(dental_config, dict):
            raise ValueError("إعدادات الأسنان غير صالحة")
        row.dental_config_json = json.dumps(normalize_dental_config(dental_config), ensure_ascii=False, sort_keys=True)
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    _audit(tenant_id, actor_id, "settings", row.id, "update", "تحديث إعدادات العيادة")
    return settings_payload(tenant_id)


def _next_file_number(tenant_id: int) -> str:
    count = ClinicPatient.query.filter_by(tenant_id=tenant_id).count() + 1
    return f"P{count:05d}"


def patient_dict(row: ClinicPatient) -> dict:
    age = None
    if row.date_of_birth:
        today = _today()
        age = today.year - row.date_of_birth.year - (
            (today.month, today.day) < (row.date_of_birth.month, row.date_of_birth.day)
        )
    return {
        "id": row.id,
        "file_number": row.file_number,
        "full_name": row.full_name,
        "phone": row.phone or "",
        "secondary_phone": row.secondary_phone or "",
        "gender": row.gender or "",
        "date_of_birth": row.date_of_birth.isoformat() if row.date_of_birth else "",
        "age": age,
        "blood_type": row.blood_type or "",
        "national_id": row.national_id or "",
        "address": row.address or "",
        "city": row.city or "",
        "emergency_contact": row.emergency_contact or "",
        "emergency_phone": row.emergency_phone or "",
        "allergies": row.allergies or "",
        "chronic_conditions": row.chronic_conditions or "",
        "notes": row.notes or "",
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def list_patients(tenant_id: int, q: str = "", limit: int = 100) -> list[dict]:
    query = ClinicPatient.query.filter_by(tenant_id=tenant_id).filter(ClinicPatient.status != "deleted")
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        prefix = f"{term}%"
        query = query.filter(
            or_(
                ClinicPatient.full_name.ilike(like),
                ClinicPatient.phone.ilike(like),
                ClinicPatient.file_number.ilike(like),
                ClinicPatient.national_id.ilike(like),
            )
        )
        rank = case(
            (ClinicPatient.file_number == term, 0),
            (ClinicPatient.phone == term, 0),
            (ClinicPatient.national_id == term, 0),
            (ClinicPatient.file_number.ilike(prefix), 1),
            (ClinicPatient.phone.ilike(prefix), 1),
            (ClinicPatient.full_name.ilike(prefix), 2),
            else_=3,
        )
        query = query.order_by(rank, ClinicPatient.full_name.asc())
    else:
        query = query.order_by(ClinicPatient.created_at.desc())
    rows = query.limit(min(int(limit or 100), 300)).all()
    return [patient_dict(r) for r in rows]


def create_patient(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    name = str(payload.get("full_name") or "").strip()
    if not name:
        raise ValueError("اسم المريض مطلوب")
    phone = str(payload.get("phone") or "").strip() or None
    dob = None
    if payload.get("date_of_birth"):
        dob = _parse_date(payload.get("date_of_birth"), "تاريخ الميلاد")
    row = ClinicPatient(
        tenant_id=tenant_id,
        branch_id=branch_id,
        file_number=str(payload.get("file_number") or "").strip() or _next_file_number(tenant_id),
        full_name=name,
        phone=phone,
        secondary_phone=str(payload.get("secondary_phone") or "").strip() or None,
        gender=str(payload.get("gender") or "").strip() or None,
        date_of_birth=dob,
        blood_type=str(payload.get("blood_type") or "").strip() or None,
        national_id=str(payload.get("national_id") or "").strip() or None,
        address=str(payload.get("address") or "").strip() or None,
        city=str(payload.get("city") or "").strip() or None,
        emergency_contact=str(payload.get("emergency_contact") or "").strip() or None,
        emergency_phone=str(payload.get("emergency_phone") or "").strip() or None,
        allergies=str(payload.get("allergies") or "").strip() or None,
        chronic_conditions=str(payload.get("chronic_conditions") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "patient", row.id, "create", f"تسجيل مريض {row.full_name}", branch_id=branch_id)
    return patient_dict(row)


def update_patient(tenant_id: int, patient_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not row:
        raise ValueError("المريض غير موجود")
    name = str(payload.get("full_name") or row.full_name).strip()
    if not name:
        raise ValueError("اسم المريض مطلوب")
    row.full_name = name
    for field in (
        "phone",
        "secondary_phone",
        "gender",
        "blood_type",
        "national_id",
        "address",
        "city",
        "emergency_contact",
        "emergency_phone",
        "allergies",
        "chronic_conditions",
        "notes",
        "status",
    ):
        if field in payload:
            value = payload.get(field)
            setattr(row, field, (str(value).strip() or None) if value is not None else None)
    if "date_of_birth" in payload:
        row.date_of_birth = (
            _parse_date(payload.get("date_of_birth"), "تاريخ الميلاد")
            if payload.get("date_of_birth")
            else None
        )
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    _audit(tenant_id, actor_id, "patient", row.id, "update", f"تحديث مريض {row.full_name}")
    return patient_dict(row)


def get_patient(tenant_id: int, patient_id: int, *, include_clinical: bool = True) -> dict:
    row = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not row:
        raise ValueError("المريض غير موجود")
    visits = (
        ClinicVisit.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicVisit.visit_date.desc(), ClinicVisit.id.desc())
        .limit(20)
        .all()
    )
    appts = (
        ClinicAppointment.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicAppointment.appointment_date.desc(), ClinicAppointment.start_time.desc())
        .limit(20)
        .all()
    )
    from modules.clinics.models import ClinicSpecialty, ClinicVisitTemplate

    specialty_ids = {v.specialty_id for v in visits if v.specialty_id}
    template_ids = {v.visit_template_id for v in visits if v.visit_template_id}
    specialty_names = {
        s.id: s.name_ar
        for s in ClinicSpecialty.query.filter(
            ClinicSpecialty.tenant_id == tenant_id, ClinicSpecialty.id.in_(specialty_ids or {-1})
        ).all()
    } if specialty_ids else {}
    template_versions = {
        t.id: t.version
        for t in ClinicVisitTemplate.query.filter(
            ClinicVisitTemplate.tenant_id == tenant_id, ClinicVisitTemplate.id.in_(template_ids or {-1})
        ).all()
    } if template_ids else {}
    visit_rows = [
        visit_dict(
            v,
            specialty_name=specialty_names.get(v.specialty_id, ""),
            template_version=template_versions.get(v.visit_template_id),
        )
        for v in visits
    ]
    if not include_clinical:
        for item in visit_rows:
            item.pop("chief_complaint", None)
            item.pop("clinical_notes", None)
    return {
        "patient": patient_dict(row),
        "visits": visit_rows,
        "appointments": [appointment_dict(a) for a in appts],
    }


def doctor_dict(row: ClinicDoctor, specialties=None) -> dict:
    from modules.clinics.service_specialties import doctor_specialties
    specialties = doctor_specialties(row.tenant_id, row.id) if specialties is None else specialties
    primary = next((item for item in specialties if item["is_primary"]), specialties[0] if specialties else None)
    return {
        "id": row.id,
        "doctor_code": f"DR-{row.id:04d}",
        "employee_id": row.employee_id,
        "full_name": row.full_name,
        "specialty": row.specialty or "",
        "primary_specialty_id": primary["id"] if primary else None,
        "specialty_ids": [item["id"] for item in specialties],
        "specialties": specialties,
        "phone": row.phone or "",
        "photo_url": getattr(row, "photo_url", None) or "",
        "scientific_title": getattr(row, "scientific_title", None) or "",
        "license_number": row.license_number or "",
        "commission_pct": float(row.commission_pct or 0),
        "color": row.color or "#0D9488",
        "active": bool(row.active),
        "notes": row.notes or "",
    }


def list_doctors(tenant_id: int, active_only: bool = False) -> list[dict]:
    query = ClinicDoctor.query.filter_by(tenant_id=tenant_id)
    if active_only:
        query = query.filter_by(active=True)
    rows = query.order_by(ClinicDoctor.full_name.asc()).all()
    from modules.clinics.service_specialties import doctor_specialties_bulk
    specialties = doctor_specialties_bulk(tenant_id, [row.id for row in rows])
    return [doctor_dict(r, specialties.get(r.id, [])) for r in rows]


def _normalize_commission_pct(value) -> float:
    """Legacy doctor-wide commission must stay in the percentage range 0–100."""
    raw = 0 if value in (None, "") else value
    try:
        pct = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("نسبة العمولة غير صالحة") from exc
    if pct < 0 or pct > 100:
        raise ValueError("نسبة العمولة يجب أن تكون بين 0 و 100")
    return pct


def create_doctor(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    name = str(payload.get("full_name") or "").strip()
    if not name:
        raise ValueError("اسم الطبيب مطلوب")
    employee_id = int(payload.get("employee_id") or 0) or None
    if employee_id:
        from models.employee import Employee
        employee = Employee.query.filter_by(id=employee_id, tenant_id=tenant_id).first()
        if not employee:
            raise ValueError("سجل الموظف غير موجود")
        if ClinicDoctor.query.filter_by(tenant_id=tenant_id, employee_id=employee_id).first():
            raise ValueError("سجل الموظف مرتبط بطبيب آخر")
    row = ClinicDoctor(
        tenant_id=tenant_id,
        branch_id=branch_id,
        employee_id=employee_id,
        full_name=name,
        specialty=str(payload.get("specialty") or "").strip() or None,
        photo_url=str(payload.get("photo_url") or "").strip() or None,
        scientific_title=str(payload.get("scientific_title") or "").strip() or None,
        phone=str(payload.get("phone") or "").strip() or None,
        license_number=str(payload.get("license_number") or "").strip() or None,
        commission_pct=_normalize_commission_pct(payload.get("commission_pct")),
        color=str(payload.get("color") or "#0D9488").strip() or "#0D9488",
        active=bool(payload.get("active", True)),
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    if payload.get("primary_specialty_id") or payload.get("specialty_ids"):
        from modules.clinics.service_specialties import set_doctor_specialties
        set_doctor_specialties(tenant_id, row.id, payload.get("primary_specialty_id"), payload.get("specialty_ids") or [], actor_id)
    _audit(tenant_id, actor_id, "doctor", row.id, "create", f"إضافة طبيب {row.full_name}", branch_id=branch_id)
    result = doctor_dict(row)
    settings = get_or_create_settings(tenant_id)
    result["organization_upgrade_suggested"] = bool(
        getattr(settings, "organization_mode", "solo_clinic") == "solo_clinic"
        and ClinicDoctor.query.filter_by(tenant_id=tenant_id, active=True).count() > 1
    )
    return result


def update_doctor(tenant_id: int, doctor_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
    if not row:
        raise ValueError("الطبيب غير موجود")
    if "full_name" in payload:
        name = str(payload.get("full_name") or "").strip()
        if not name:
            raise ValueError("اسم الطبيب مطلوب")
        row.full_name = name
    for field in ("specialty", "phone", "license_number", "notes", "color", "photo_url", "scientific_title"):
        if field in payload:
            setattr(row, field, str(payload.get(field) or "").strip() or None)
    if "commission_pct" in payload:
        row.commission_pct = _normalize_commission_pct(payload.get("commission_pct"))
    if "active" in payload:
        row.active = bool(payload.get("active"))
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    if "primary_specialty_id" in payload or "specialty_ids" in payload:
        from modules.clinics.service_specialties import set_doctor_specialties
        set_doctor_specialties(tenant_id, row.id, payload.get("primary_specialty_id"), payload.get("specialty_ids") or [], actor_id)
    result = doctor_dict(row)
    settings = get_or_create_settings(tenant_id)
    result["organization_upgrade_suggested"] = bool(
        getattr(settings, "organization_mode", "solo_clinic") == "solo_clinic"
        and ClinicDoctor.query.filter_by(tenant_id=tenant_id, active=True).count() > 1
    )
    return result


def service_dict(row: ClinicService, *, specialty_ids=None, doctor_ids=None) -> dict:
    from modules.clinics.models import ClinicServiceSpecialty, ClinicDoctorService
    if specialty_ids is None:
        specialty_ids = [
            x.specialty_id
            for x in ClinicServiceSpecialty.query.filter_by(tenant_id=row.tenant_id, service_id=row.id).all()
        ]
    if doctor_ids is None:
        doctor_ids = [
            x.doctor_id
            for x in ClinicDoctorService.query.filter_by(tenant_id=row.tenant_id, service_id=row.id).all()
        ]
    return {
        "id": row.id,
        "name": row.name,
        "category": row.category or "",
        "duration_minutes": row.duration_minutes,
        "price": row.price,
        "doctor_commission_pct": float(row.doctor_commission_pct) if row.doctor_commission_pct is not None else None,
        "requires_room": bool(row.requires_room),
        "requires_tooth": bool(getattr(row, "requires_tooth", False)),
        "allows_multiple_teeth": bool(getattr(row, "allows_multiple_teeth", False)),
        "requires_sessions": bool(getattr(row, "requires_sessions", False)),
        "default_sessions": int(getattr(row, "default_sessions", 1) or 1),
        "default_procedure_id": getattr(row, "default_procedure_id", None),
        "active": bool(row.active),
        "description": row.description or "",
        "specialty_ids": list(specialty_ids),
        "doctor_ids": list(doctor_ids),
    }


def service_links_bulk(tenant_id: int, service_ids) -> dict[int, dict[str, list[int]]]:
    """Load service specialty/doctor links in two queries for list endpoints."""
    from modules.clinics.models import ClinicServiceSpecialty, ClinicDoctorService

    ids = [int(value) for value in service_ids]
    result = {service_id: {"specialty_ids": [], "doctor_ids": []} for service_id in ids}
    if not ids:
        return result
    for link in ClinicServiceSpecialty.query.filter(
        ClinicServiceSpecialty.tenant_id == tenant_id,
        ClinicServiceSpecialty.service_id.in_(ids),
    ).all():
        result.setdefault(link.service_id, {"specialty_ids": [], "doctor_ids": []})["specialty_ids"].append(link.specialty_id)
    for link in ClinicDoctorService.query.filter(
        ClinicDoctorService.tenant_id == tenant_id,
        ClinicDoctorService.service_id.in_(ids),
    ).all():
        result.setdefault(link.service_id, {"specialty_ids": [], "doctor_ids": []})["doctor_ids"].append(link.doctor_id)
    return result


def list_services(tenant_id: int, active_only: bool = False, specialty_id=None, doctor_id=None) -> list[dict]:
    query = ClinicService.query.filter_by(tenant_id=tenant_id)
    if active_only:
        query = query.filter_by(active=True)
    models = query.order_by(ClinicService.name.asc()).all()
    links = service_links_bulk(tenant_id, [row.id for row in models])
    rows = [
        service_dict(
            row,
            specialty_ids=links.get(row.id, {}).get("specialty_ids", []),
            doctor_ids=links.get(row.id, {}).get("doctor_ids", []),
        )
        for row in models
    ]
    return [r for r in rows if service_matches(r, specialty_id, doctor_id)]


def service_matches(service: dict, specialty_id=None, doctor_id=None) -> bool:
    """Match a service to selected specialty/doctor.

    - Specialty selected → an explicitly scoped service must include it.
      Empty specialty_ids means the service is shared across all specialties.
    - Doctor selected → if service lists doctors, the doctor must be included;
      empty doctor_ids means available to all doctors (within specialty rules).
    """
    specialty_ids = [int(x) for x in (service.get("specialty_ids") or []) if x not in (None, "")]
    doctor_ids = [int(x) for x in (service.get("doctor_ids") or []) if x not in (None, "")]
    sid = int(specialty_id) if specialty_id not in (None, "") else 0
    did = int(doctor_id) if doctor_id not in (None, "") else 0
    if sid and specialty_ids and sid not in specialty_ids:
        return False
    if did and doctor_ids and did not in doctor_ids:
        return False
    return True


def assert_service_selection(tenant_id, service_id, doctor_id=None, specialty_id=None):
    if not service_id:
        return
    row = ClinicService.query.filter_by(tenant_id=tenant_id, id=service_id, active=True).first()
    if not row or not service_matches(service_dict(row), specialty_id, doctor_id):
        raise ValueError("الخدمة غير متاحة للطبيب أو الاختصاص المحدد")


def _service_links(tenant_id, payload, service_id=None):
    from modules.clinics.models import ClinicSpecialty, ClinicServiceSpecialty, ClinicDoctorService
    validated = []
    for key, model, link, attr in (("specialty_ids", ClinicSpecialty, ClinicServiceSpecialty, "specialty_id"),
                                   ("doctor_ids", ClinicDoctor, ClinicDoctorService, "doctor_id")):
        if key not in payload:
            continue
        if not isinstance(payload[key], list):
            raise ValueError("اختصاصات وأطباء الخدمة يجب أن تكون قائمة")
        ids = {int(value) for value in payload[key]}
        if model.query.filter(model.tenant_id == tenant_id, model.id.in_(ids)).count() != len(ids):
            raise ValueError("طبيب أو اختصاص الخدمة غير موجود")
        validated.append((link, attr, ids))
    if service_id is not None:
        for link, attr, ids in validated:
            link.query.filter_by(tenant_id=tenant_id, service_id=service_id).delete(synchronize_session=False)
            for value in ids:
                db.session.add(link(tenant_id=tenant_id, service_id=service_id, **{attr: value}))
        db.session.flush()


DEFAULT_SERVICE_CATEGORIES = (
    "كشف",
    "متابعة",
    "إجراء",
    "علاج",
    "جراحة",
    "وقاية",
    "تجميل",
    "تشخيص",
    "أخرى",
)


def _service_usage_counts(tenant_id: int, service_ids: list[int]) -> dict[int, dict[str, int]]:
    if not service_ids:
        return {}
    appt_rows = (
        db.session.query(ClinicAppointment.service_id, func.count())
        .filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.service_id.in_(service_ids),
        )
        .group_by(ClinicAppointment.service_id)
        .all()
    )
    visit_rows = (
        db.session.query(ClinicVisit.service_id, func.count())
        .filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.service_id.in_(service_ids),
        )
        .group_by(ClinicVisit.service_id)
        .all()
    )
    appt_map = {sid: int(count) for sid, count in appt_rows if sid}
    visit_map = {sid: int(count) for sid, count in visit_rows if sid}
    return {
        sid: {
            "appointments": appt_map.get(sid, 0),
            "visits": visit_map.get(sid, 0),
            "total_usage": appt_map.get(sid, 0) + visit_map.get(sid, 0),
        }
        for sid in service_ids
    }


def create_service(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    _service_links(tenant_id, payload)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("اسم الخدمة مطلوب")
    if ClinicService.query.filter_by(tenant_id=tenant_id, name=name).first():
        raise ValueError("يوجد خدمة بنفس الاسم")
    row = ClinicService(
        tenant_id=tenant_id,
        branch_id=branch_id,
        name=name,
        category=str(payload.get("category") or "").strip() or None,
        duration_minutes=max(5, int(payload.get("duration_minutes") or 15)),
        price=_money(payload.get("price")),
        doctor_commission_pct=(
            float(payload["doctor_commission_pct"])
            if payload.get("doctor_commission_pct") not in (None, "")
            else None
        ),
        requires_room=bool(payload.get("requires_room", False)),
        active=bool(payload.get("active", True)),
        description=str(payload.get("description") or "").strip() or None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    from modules.clinics.service_dental_completion import apply_service_scope
    apply_service_scope(row, payload)
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "service", row.id, "create", f"إضافة خدمة {row.name}", branch_id=branch_id)
    _service_links(tenant_id, payload, row.id)
    return service_dict(row)


def update_service(tenant_id: int, service_id: int, payload: dict, actor_id=None) -> dict:
    _service_links(tenant_id, payload)
    row = ClinicService.query.filter_by(tenant_id=tenant_id, id=service_id).first()
    if not row:
        raise ValueError("الخدمة غير موجودة")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("اسم الخدمة مطلوب")
        dup = (
            ClinicService.query.filter_by(tenant_id=tenant_id, name=name)
            .filter(ClinicService.id != service_id)
            .first()
        )
        if dup:
            raise ValueError("يوجد خدمة بنفس الاسم")
        row.name = name
    if "category" in payload:
        row.category = str(payload.get("category") or "").strip() or None
    if "duration_minutes" in payload:
        row.duration_minutes = max(5, int(payload.get("duration_minutes") or 15))
    if "price" in payload:
        row.price = _money(payload.get("price"))
    if "doctor_commission_pct" in payload:
        raw = payload.get("doctor_commission_pct")
        row.doctor_commission_pct = float(raw) if raw not in (None, "") else None
    if "requires_room" in payload:
        row.requires_room = bool(payload.get("requires_room"))
    if "active" in payload:
        row.active = bool(payload.get("active"))
    if "description" in payload:
        row.description = str(payload.get("description") or "").strip() or None
    from modules.clinics.service_dental_completion import apply_service_scope
    apply_service_scope(row, payload)
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    _audit(tenant_id, actor_id, "service", row.id, "update", f"تحديث خدمة {row.name}")
    _service_links(tenant_id, payload, row.id)
    return service_dict(row)


def services_center(tenant_id: int, params: dict) -> dict:
    rows = ClinicService.query.filter_by(tenant_id=tenant_id).order_by(ClinicService.name.asc()).all()
    usage = _service_usage_counts(tenant_id, [r.id for r in rows])
    items = []
    for row in rows:
        item = service_dict(row)
        item.update(usage.get(row.id, {"appointments": 0, "visits": 0, "total_usage": 0}))
        items.append(item)

    q = str(params.get("q") or "").strip().lower()
    category = str(params.get("category") or "").strip()
    status = str(params.get("status") or "").strip()
    if q:
        items = [
            item
            for item in items
            if q in item["name"].lower()
            or q in (item["category"] or "").lower()
            or q in (item["description"] or "").lower()
        ]
    if category:
        items = [item for item in items if item["category"] == category]
    if status == "active":
        items = [item for item in items if item["active"]]
    elif status == "inactive":
        items = [item for item in items if not item["active"]]

    sort = str(params.get("sort") or "name")
    reverse = str(params.get("direction") or "asc") == "desc"
    sort_keys = {
        "name": lambda item: item["name"],
        "category": lambda item: item["category"] or "",
        "duration": lambda item: item["duration_minutes"],
        "price": lambda item: item["price"],
        "usage": lambda item: item["total_usage"],
    }
    items.sort(key=sort_keys.get(sort, sort_keys["name"]), reverse=reverse)

    all_items = [service_dict(r) for r in rows]
    active_items = [item for item in all_items if item["active"]]
    categories = sorted({item["category"] for item in all_items if item["category"]})
    for preset in DEFAULT_SERVICE_CATEGORIES:
        if preset not in categories:
            categories.append(preset)

    page = max(1, int(params.get("page") or 1))
    per_page = min(100, max(10, int(params.get("per_page") or 25)))
    total = len(items)
    start = (page - 1) * per_page

    return {
        "items": items[start : start + per_page],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": max(1, (total + per_page - 1) // per_page),
        },
        "kpis": {
            "total": len(all_items),
            "active": len(active_items),
            "inactive": len(all_items) - len(active_items),
            "categories": len({item["category"] for item in all_items if item["category"]}),
            "avg_price": round(sum(item["price"] for item in active_items) / len(active_items)) if active_items else 0,
            "avg_duration": round(sum(item["duration_minutes"] for item in active_items) / len(active_items)) if active_items else 0,
        },
        "filters": {
            "categories": categories,
            "presets": list(DEFAULT_SERVICE_CATEGORIES),
        },
    }


def room_dict(row: ClinicRoom) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "room_type": row.room_type,
        "active": bool(row.active),
    }


def list_rooms(tenant_id: int, active_only: bool = True) -> list[dict]:
    query = ClinicRoom.query.filter_by(tenant_id=tenant_id)
    if active_only:
        query = query.filter_by(active=True)
    return [room_dict(r) for r in query.order_by(ClinicRoom.name.asc()).all()]


def create_room(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("اسم الغرفة مطلوب")
    row = ClinicRoom(
        tenant_id=tenant_id,
        branch_id=branch_id,
        name=name,
        room_type=str(payload.get("room_type") or "consultation").strip() or "consultation",
        active=bool(payload.get("active", True)),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return room_dict(row)


def appointment_dict(row: ClinicAppointment) -> dict:
    patient = row.patient
    doctor = row.doctor
    service = row.service
    room = None
    if row.room_id:
        room = ClinicRoom.query.filter_by(tenant_id=row.tenant_id, id=row.room_id).first()
    age = None
    if patient and patient.date_of_birth:
        today = _today()
        age = today.year - patient.date_of_birth.year - (
            (today.month, today.day) < (patient.date_of_birth.month, patient.date_of_birth.day)
        )
    try:
        tooth_numbers = json.loads(getattr(row, "tooth_numbers_json", None) or "[]")
    except (TypeError, ValueError):
        tooth_numbers = []
    dental_parts = []
    dental_session = getattr(row, "dental_session", None)
    treatment_item = getattr(row, "treatment_plan_item", None)
    if dental_session:
        session_label = f"الجلسة {int(dental_session.session_number or 1)}"
        if treatment_item:
            session_label += f" من {int(treatment_item.estimated_sessions or 1)}"
        dental_parts.append(session_label)
    if treatment_item:
        dental_parts.append(treatment_item.title or "علاج أسنان")
    display_teeth = tooth_numbers or ([row.tooth_number] if getattr(row, "tooth_number", None) else [])
    if display_teeth:
        dental_parts.append(f"الأسنان {'، '.join(display_teeth)}")
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "patient_name": patient.full_name if patient else "",
        "patient_phone": patient.phone if patient else "",
        "patient_file": patient.file_number if patient else "",
        "patient_gender": patient.gender if patient else "",
        "patient_age": age,
        "doctor_id": row.doctor_id,
        "doctor_name": doctor.full_name if doctor else "",
        "doctor_color": doctor.color if doctor else "#0D9488",
        "service_id": row.service_id,
        "specialty_id": getattr(row, "specialty_id", None),
        "specialty_code": getattr(row, "specialty_code_snapshot", None),
        "workspace": getattr(row, "workspace_snapshot", None),
        "service_name": service.name if service else "",
        "service_price": service.price if service else 0,
        "room_id": row.room_id,
        "room_name": room.name if room else "",
        "appointment_date": row.appointment_date.isoformat() if row.appointment_date else "",
        "start_time": row.start_time.strftime("%H:%M") if row.start_time else "",
        "end_time": row.end_time.strftime("%H:%M") if row.end_time else "",
        "appointment_type": row.appointment_type,
        "status": row.status,
        "queue_number": row.queue_number,
        "queue_priority": int(getattr(row, "queue_priority", 0) or 0),
        "is_emergency": bool(int(getattr(row, "queue_priority", 0) or 0) >= 2),
        "is_priority": bool(int(getattr(row, "queue_priority", 0) or 0) >= 1),
        "payment_status": row.payment_status,
        "notes": row.notes or "",
        "source": getattr(row, "source", None) or "reception",
        "checked_in_at": row.checked_in_at.isoformat() if row.checked_in_at else "",
        "treatment_plan_id": getattr(row, "treatment_plan_id", None),
        "treatment_plan_item_id": getattr(row, "treatment_plan_item_id", None),
        "dental_session_id": getattr(row, "dental_session_id", None),
        "tooth_number": getattr(row, "tooth_number", None),
        "tooth_numbers": tooth_numbers,
        "dental_session_number": int(dental_session.session_number or 1) if dental_session else None,
        "dental_treatment_title": treatment_item.title if treatment_item else None,
        "dental_label": " · ".join(dental_parts) or None,
    }


def _assert_no_conflict(tenant_id: int, doctor_id: int | None, day: date, start: time, end: time | None, exclude_id=None):
    if not doctor_id or not end:
        return
    query = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.doctor_id == doctor_id,
        ClinicAppointment.appointment_date == day,
        ClinicAppointment.status.notin_(("cancelled", "rescheduled", "no_show")),
    )
    if exclude_id:
        query = query.filter(ClinicAppointment.id != exclude_id)
    for other in query.all():
        other_end = other.end_time or other.start_time
        if other.start_time < end and start < other_end:
            raise ValueError("تعارض في موعد الطبيب — اختر وقتاً آخر")


def _lock_appointment_day(tenant_id: int, doctor_id: int | None, day: date) -> None:
    """Serialize booking decisions per doctor/day on PostgreSQL.

    The lock lives for the database transaction and closes the race between the
    final availability check and insert. SQLite test/development databases keep
    their native write serialization.
    """
    if not doctor_id:
        return
    bind = db.session.get_bind()
    if bind and bind.dialect.name == "postgresql":
        raw = f"clinic-slot:{tenant_id}:{doctor_id}:{day.isoformat()}".encode("utf-8")
        key = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF
        db.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _advisory_transaction_lock(namespace: str, *parts: object) -> None:
    """Take a deterministic PostgreSQL transaction lock; no-op elsewhere."""
    bind = db.session.get_bind()
    if bind and bind.dialect.name == "postgresql":
        raw = ":".join((namespace, *(str(part) for part in parts))).encode("utf-8")
        key = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF
        db.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _locked_visit(tenant_id: int, visit_id: int) -> ClinicVisit | None:
    query = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id)
    if db.session.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    return query.first()


def create_appointment(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    patient_id = int(payload.get("patient_id") or 0)
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not patient:
        raise ValueError("المريض غير موجود")
    day = _parse_date(payload.get("appointment_date") or _today().isoformat(), "تاريخ الموعد")
    start = _parse_time(payload.get("start_time"), "وقت الموعد")
    settings = get_or_create_settings(tenant_id)
    doctor_id = int(payload["doctor_id"]) if payload.get("doctor_id") else None
    service_id = int(payload["service_id"]) if payload.get("service_id") else None
    service_row = ClinicService.query.filter_by(tenant_id=tenant_id, id=service_id).first() if service_id else None
    duration = int(
        payload.get("duration_minutes")
        or (service_row.duration_minutes if service_row else 0)
        or settings.appointment_slot_minutes
        or 15
    )
    end = (datetime.combine(day, start) + timedelta(minutes=duration)).time()
    from modules.clinics.service_specialties import assert_doctor_specialty, primary_specialty_id
    specialty_id = int(payload["specialty_id"]) if payload.get("specialty_id") else primary_specialty_id(tenant_id, doctor_id)
    if doctor_id and not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
        raise ValueError("الطبيب غير موجود")
    if service_id and not service_row:
        raise ValueError("الخدمة غير موجودة")
    from modules.clinics.service_dental_completion import appointment_dental_fields
    dental_fields = appointment_dental_fields(tenant_id, payload, service_row)
    assert_doctor_specialty(tenant_id, doctor_id, specialty_id)
    assert_service_selection(tenant_id, service_id, doctor_id, specialty_id)
    _lock_appointment_day(tenant_id, doctor_id, day)
    _assert_no_conflict(tenant_id, doctor_id, day, start, end)
    try:
        from modules.clinics.service_ops import assert_doctor_available

        assert_doctor_available(tenant_id, doctor_id, day, start, end)
    except ImportError:
        pass
    status = str(payload.get("status") or "confirmed").strip()
    if status not in APPOINTMENT_STATUSES:
        status = "confirmed"
    row = ClinicAppointment(
        tenant_id=tenant_id,
        branch_id=branch_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        service_id=service_id,
        specialty_id=specialty_id,
        room_id=int(payload["room_id"]) if payload.get("room_id") else None,
        appointment_date=day,
        start_time=start,
        end_time=end,
        appointment_type=str(payload.get("appointment_type") or "visit").strip() or "visit",
        source=str(payload.get("source") or "reception").strip() or "reception",
        status=status,
        notes=str(payload.get("notes") or "").strip() or None,
        treatment_plan_id=dental_fields["treatment_plan_id"],
        treatment_plan_item_id=dental_fields["treatment_plan_item_id"],
        dental_session_id=dental_fields["dental_session_id"],
        tooth_number=dental_fields["tooth_number"],
        tooth_numbers_json=dental_fields["tooth_numbers_json"],
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    from modules.clinics.service_specialty_registry import apply_specialty_snapshot
    apply_specialty_snapshot(tenant_id, row)
    db.session.add(
        ClinicAppointmentStatusHistory(
            tenant_id=tenant_id,
            appointment_id=row.id,
            from_status=None,
            to_status=status,
            note="إنشاء موعد",
            changed_by=actor_id,
        )
    )
    _audit(tenant_id, actor_id, "appointment", row.id, "create", f"موعد لـ {patient.full_name}", branch_id=branch_id)
    return appointment_dict(row)


def list_appointments(tenant_id: int, day: date | None = None, doctor_id=None, status=None) -> list[dict]:
    day = day or _today()
    query = ClinicAppointment.query.filter_by(tenant_id=tenant_id, appointment_date=day)
    if doctor_id:
        query = query.filter_by(doctor_id=int(doctor_id))
    if status:
        query = query.filter_by(status=str(status))
    rows = query.order_by(ClinicAppointment.start_time.asc()).all()
    return [appointment_dict(r) for r in rows]


def list_appointments_range(
    tenant_id: int,
    start_date: date,
    end_date: date,
    doctor_id=None,
    room_id=None,
) -> list[dict]:
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    query = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.appointment_date >= start_date,
        ClinicAppointment.appointment_date <= end_date,
        ClinicAppointment.status.notin_(("cancelled", "rescheduled")),
    )
    if doctor_id:
        query = query.filter_by(doctor_id=int(doctor_id))
    if room_id:
        query = query.filter_by(room_id=int(room_id))
    rows = query.order_by(ClinicAppointment.appointment_date.asc(), ClinicAppointment.start_time.asc()).all()
    return [appointment_dict(r) for r in rows]


def reschedule_appointment(tenant_id: int, appointment_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=appointment_id).first()
    if not row:
        raise ValueError("الموعد غير موجود")
    if row.status in ("completed", "cancelled"):
        raise ValueError("لا يمكن إعادة جدولة موعد مكتمل أو ملغى")
    day = _parse_date(payload.get("appointment_date") or row.appointment_date.isoformat(), "تاريخ الموعد")
    start = _parse_time(payload.get("start_time") or row.start_time.strftime("%H:%M"), "وقت الموعد")
    settings = get_or_create_settings(tenant_id)
    duration = int(payload.get("duration_minutes") or 0)
    if not duration:
        if row.end_time and row.start_time:
            duration = int(
                (datetime.combine(row.appointment_date, row.end_time) - datetime.combine(row.appointment_date, row.start_time)).seconds
                / 60
            ) or settings.appointment_slot_minutes
        else:
            duration = settings.appointment_slot_minutes or 15
    end = (datetime.combine(day, start) + timedelta(minutes=duration)).time()
    doctor_id = int(payload["doctor_id"]) if payload.get("doctor_id") else row.doctor_id
    service_id = int(payload["service_id"]) if payload.get("service_id") not in (None, "") else row.service_id
    if payload.get("specialty_id") not in (None, ""):
        specialty_id = int(payload["specialty_id"])
    else:
        specialty_id = row.specialty_id
    identity_changed = (doctor_id, specialty_id, service_id) != (row.doctor_id, row.specialty_id, row.service_id)
    if identity_changed and ClinicVisit.query.filter_by(tenant_id=tenant_id, appointment_id=row.id).first():
        raise ValueError("لا يمكن تغيير طبيب أو اختصاص أو خدمة الموعد بعد بدء الزيارة")
    if doctor_id or specialty_id or service_id:
        from modules.clinics.service_specialties import assert_doctor_specialty, primary_specialty_id
        if doctor_id and not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
            raise ValueError("الطبيب غير موجود")
        if doctor_id and not specialty_id:
            specialty_id = primary_specialty_id(tenant_id, doctor_id)
        if doctor_id and specialty_id:
            assert_doctor_specialty(tenant_id, doctor_id, specialty_id)
        assert_service_selection(tenant_id, service_id, doctor_id, specialty_id)
    _lock_appointment_day(tenant_id, doctor_id, day)
    _assert_no_conflict(tenant_id, doctor_id, day, start, end, exclude_id=row.id)
    try:
        from modules.clinics.service_ops import assert_doctor_available

        assert_doctor_available(tenant_id, doctor_id, day, start, end)
    except ImportError:
        pass
    old = f"{row.appointment_date.isoformat()} {row.start_time.strftime('%H:%M')}"
    row.appointment_date = day
    row.start_time = start
    row.end_time = end
    row.doctor_id = doctor_id
    row.specialty_id = specialty_id
    row.service_id = service_id
    if identity_changed:
        from modules.clinics.service_specialty_registry import apply_specialty_snapshot
        row.specialty_code_snapshot = None
        row.workspace_snapshot = None
        apply_specialty_snapshot(tenant_id, row)
    if payload.get("room_id") is not None:
        row.room_id = int(payload["room_id"]) if payload.get("room_id") else None
    if row.status not in ("pending", "confirmed", "arrived", "waiting"):
        row.status = "confirmed"
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    db.session.add(
        ClinicAppointmentStatusHistory(
            tenant_id=tenant_id,
            appointment_id=row.id,
            from_status=row.status,
            to_status=row.status,
            note=f"إعادة جدولة من {old}",
            changed_by=actor_id,
        )
    )
    _audit(tenant_id, actor_id, "appointment", row.id, "reschedule", f"من {old}")
    db.session.flush()
    return appointment_dict(row)


def _next_queue_number(tenant_id: int, day: date) -> int:
    current = (
        db.session.query(func.max(ClinicAppointment.queue_number))
        .filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.appointment_date == day,
        )
        .scalar()
    )
    return int(current or 0) + 1


def change_appointment_status(
    tenant_id: int,
    appointment_id: int,
    to_status: str,
    actor_id=None,
    note: str | None = None,
) -> dict:
    row = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=appointment_id).first()
    if not row:
        raise ValueError("الموعد غير موجود")
    to_status = str(to_status or "").strip()
    if to_status not in APPOINTMENT_STATUSES:
        raise ValueError("حالة الموعد غير صالحة")
    from_status = row.status
    if from_status == to_status:
        return appointment_dict(row)
    row.status = to_status
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    if to_status in ("arrived", "waiting") and not row.checked_in_at:
        row.checked_in_at = datetime.utcnow()
        if not row.queue_number:
            row.queue_number = _next_queue_number(tenant_id, row.appointment_date)
    if to_status == "cancelled":
        row.cancelled_reason = note or row.cancelled_reason
    db.session.add(
        ClinicAppointmentStatusHistory(
            tenant_id=tenant_id,
            appointment_id=row.id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            changed_by=actor_id,
        )
    )
    _audit(
        tenant_id,
        actor_id,
        "appointment",
        row.id,
        "status",
        f"تغيير حالة الموعد من {from_status} إلى {to_status}",
    )
    return appointment_dict(row)


def patch_appointment(tenant_id: int, appointment_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=appointment_id).first()
    if not row:
        raise ValueError("الموعد غير موجود")
    if "doctor_id" in payload or "specialty_id" in payload:
        from modules.clinics.service_specialties import assert_doctor_specialty, primary_specialty_id
        doctor_id = int(payload.get("doctor_id") or row.doctor_id) if (payload.get("doctor_id") or row.doctor_id) else None
        if not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
            raise ValueError("الطبيب غير موجود")
        specialty_id = (int(payload["specialty_id"]) if payload.get("specialty_id")
                        else row.specialty_id or primary_specialty_id(tenant_id, doctor_id))
        assert_doctor_specialty(tenant_id, doctor_id, specialty_id)
        assert_service_selection(tenant_id, row.service_id, doctor_id, specialty_id)
        if (doctor_id, specialty_id) != (row.doctor_id, row.specialty_id):
            if row.status == "completed" or ClinicVisit.query.filter_by(tenant_id=tenant_id, appointment_id=row.id).first():
                raise ValueError("لا يمكن تغيير طبيب أو اختصاص الموعد بعد بدء الزيارة")
        row.doctor_id = doctor_id
        row.specialty_id = specialty_id
        from modules.clinics.service_specialty_registry import apply_specialty_snapshot
        # Safe here: identity changes are rejected once a visit exists.
        row.specialty_code_snapshot = None
        row.workspace_snapshot = None
        apply_specialty_snapshot(tenant_id, row)
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "").strip() or None
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    db.session.flush()
    _audit(tenant_id, actor_id, "appointment", row.id, "update", "تحديث موعد")
    return appointment_dict(row)


def _normalize_phone(phone: str) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def find_patient_by_phone(tenant_id: int, phone: str) -> dict | None:
    digits = _normalize_phone(phone)
    if len(digits) < 7:
        return None
    rows = ClinicPatient.query.filter_by(tenant_id=tenant_id).filter(
        ClinicPatient.phone.isnot(None)
    ).all()
    for row in rows:
        if _normalize_phone(row.phone or "") == digits:
            return patient_dict(row)
        if row.secondary_phone and _normalize_phone(row.secondary_phone) == digits:
            return patient_dict(row)
    return None


def find_similar_patients(
    tenant_id: int,
    full_name: str,
    date_of_birth: date | None = None,
    limit: int = 5,
) -> list[dict]:
    name = str(full_name or "").strip()
    if len(name) < 2:
        return []
    like = f"%{name}%"
    query = ClinicPatient.query.filter_by(tenant_id=tenant_id).filter(
        ClinicPatient.status != "deleted",
        ClinicPatient.full_name.ilike(like),
    )
    if date_of_birth:
        query = query.filter(ClinicPatient.date_of_birth == date_of_birth)
    rows = query.order_by(ClinicPatient.created_at.desc()).limit(min(limit, 10)).all()
    return [patient_dict(r) for r in rows]


def get_appointment(tenant_id: int, appointment_id: int) -> dict:
    row = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=appointment_id).first()
    if not row:
        raise ValueError("الموعد غير موجود")
    return appointment_dict(row)


def reorder_waiting_queue(
    tenant_id: int,
    day: date,
    ordered_ids: list[int],
    actor_id=None,
) -> list[dict]:
    if not ordered_ids:
        raise ValueError("ترتيب الطابور مطلوب")
    rows = {
        r.id: r
        for r in ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.appointment_date == day,
            ClinicAppointment.status.in_(("arrived", "waiting")),
        ).all()
    }
    for idx, appt_id in enumerate(ordered_ids, start=1):
        row = rows.get(int(appt_id))
        if not row:
            continue
        row.queue_number = idx
        row.updated_by = actor_id
        row.updated_at = datetime.utcnow()
    db.session.flush()
    _audit(tenant_id, actor_id, "queue", day.isoformat(), "reorder", "إعادة ترتيب قائمة الانتظار")
    waiting = [
        appointment_dict(r)
        for r in sorted(
            rows.values(),
            key=lambda x: (
                -(int(getattr(x, "queue_priority", 0) or 0)),
                x.queue_number or 999,
                x.start_time.strftime("%H:%M") if x.start_time else "",
            ),
        )
    ]
    return waiting


def set_appointment_emergency(
    tenant_id: int,
    appointment_id: int,
    emergency: bool,
    actor_id=None,
) -> dict:
    return set_queue_priority(
        tenant_id,
        appointment_id,
        2 if emergency else 0,
        actor_id,
        reason="emergency_toggle",
    )


def set_queue_priority(
    tenant_id: int,
    appointment_id: int,
    priority: int,
    actor_id=None,
    reason: str | None = None,
) -> dict:
    row = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=appointment_id).first()
    if not row:
        raise ValueError("الموعد غير موجود")
    if row.status not in ("arrived", "waiting"):
        raise ValueError("يمكن تعيين الأولوية فقط للمرضى في الانتظار")
    try:
        priority = max(0, min(2, int(priority)))
    except (TypeError, ValueError):
        raise ValueError("قيمة الأولوية غير صالحة")
    old_priority = int(getattr(row, "queue_priority", 0) or 0)
    row.queue_priority = priority
    if priority > 0:
        if not row.queue_number:
            row.queue_number = _next_queue_number(tenant_id, row.appointment_date)
        min_num = (
            db.session.query(func.min(ClinicAppointment.queue_number))
            .filter(
                ClinicAppointment.tenant_id == tenant_id,
                ClinicAppointment.appointment_date == row.appointment_date,
                ClinicAppointment.status.in_(("arrived", "waiting")),
                ClinicAppointment.id != row.id,
            )
            .scalar()
        )
        row.queue_number = max(1, int(min_num or 1) - 1) if min_num and int(min_num) > 1 else 1
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    labels = {0: "عادي", 1: "أولوية", 2: "طارئ"}
    _audit(
        tenant_id,
        actor_id,
        "appointment",
        row.id,
        "priority",
        f"تغيير أولوية — {row.patient.full_name if row.patient else ''}: {labels.get(old_priority)} → {labels.get(priority)}",
        meta={
            "patient_id": row.patient_id,
            "old_priority": old_priority,
            "new_priority": priority,
            "reason": (reason or "").strip() or None,
        },
    )
    return appointment_dict(row)


def recall_queue_patient(tenant_id: int, appointment_id: int, actor_id=None) -> dict:
    row = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=appointment_id).first()
    if not row:
        raise ValueError("الموعد غير موجود")
    if row.status not in ("arrived", "waiting", "in_consultation", "called"):
        raise ValueError("لا يمكن نداء هذا الموعد حالياً")
    doctor = row.doctor
    room = ClinicRoom.query.filter_by(tenant_id=tenant_id, id=row.room_id).first() if row.room_id else None
    ticket_code = f"A-{int(row.queue_number):03d}" if row.queue_number else "—"
    meta = {
        "queue_number": row.queue_number,
        "ticket_code": ticket_code,
        "doctor_name": doctor.full_name if doctor else "",
        "room_name": room.name if room else "",
        "patient_id": row.patient_id,
        "status": row.status,
    }
    _audit(
        tenant_id,
        actor_id,
        "queue",
        row.id,
        "call",
        f"نداء الدور {ticket_code}",
        meta=meta,
        branch_id=row.branch_id,
    )
    db.session.flush()
    return {
        "ok": True,
        "appointment_id": row.id,
        "queue_number": row.queue_number,
        "ticket_code": ticket_code,
        "doctor_name": meta["doctor_name"],
        "room_name": meta["room_name"],
        "called_at": datetime.utcnow().isoformat(),
    }


def enqueue_walkin(
    tenant_id: int,
    payload: dict,
    actor_id=None,
    branch_id=None,
) -> dict:
    """Add a walk-in patient directly to the waiting queue."""
    patient_id = int(payload.get("patient_id") or 0)
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not patient:
        raise ValueError("المريض غير موجود")
    doctor_id = int(payload["doctor_id"]) if payload.get("doctor_id") else None
    if not doctor_id:
        raise ValueError("اختيار الطبيب مطلوب")
    if not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
        raise ValueError("الطبيب غير موجود")
    day = _parse_date(payload.get("appointment_date") or _today().isoformat(), "تاريخ الموعد")
    now = datetime.utcnow()
    start = now.time().replace(second=0, microsecond=0)
    settings = get_or_create_settings(tenant_id)
    duration = int(payload.get("duration_minutes") or settings.appointment_slot_minutes or 15)
    end = (datetime.combine(day, start) + timedelta(minutes=duration)).time()
    try:
        priority = max(0, min(2, int(payload.get("queue_priority") or 0)))
    except (TypeError, ValueError):
        priority = 0
    service_id = int(payload["service_id"]) if payload.get("service_id") else None
    from modules.clinics.service_specialties import assert_doctor_specialty, primary_specialty_id
    specialty_id = int(payload["specialty_id"]) if payload.get("specialty_id") else primary_specialty_id(tenant_id, doctor_id)
    assert_doctor_specialty(tenant_id, doctor_id, specialty_id)
    assert_service_selection(tenant_id, service_id, doctor_id, specialty_id)
    row = ClinicAppointment(
        tenant_id=tenant_id,
        branch_id=branch_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        service_id=service_id,
        specialty_id=specialty_id,
        room_id=int(payload["room_id"]) if payload.get("room_id") else None,
        appointment_date=day,
        start_time=start,
        end_time=end,
        appointment_type=str(payload.get("appointment_type") or "walkin").strip() or "walkin",
        source=str(payload.get("source") or "walkin").strip() or "walkin",
        status="waiting",
        notes=str(payload.get("notes") or payload.get("chief_complaint") or "").strip() or None,
        queue_priority=priority,
        queue_number=_next_queue_number(tenant_id, day),
        checked_in_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    from modules.clinics.service_specialty_registry import apply_specialty_snapshot
    apply_specialty_snapshot(tenant_id, row)
    db.session.add(
        ClinicAppointmentStatusHistory(
            tenant_id=tenant_id,
            appointment_id=row.id,
            from_status=None,
            to_status="waiting",
            note="إضافة مريض للانتظار (walk-in)",
            changed_by=actor_id,
        )
    )
    _audit(
        tenant_id,
        actor_id,
        "appointment",
        row.id,
        "enqueue",
        f"إضافة للانتظار — {patient.full_name}",
        branch_id=branch_id,
    )
    return appointment_dict(row)


def visit_dict(row: ClinicVisit, *, specialty_name: str | None = None, template_version: int | None = None) -> dict:
    patient = row.patient
    doctor = row.doctor
    from modules.clinics.models import ClinicSpecialty, ClinicVisitTemplate
    if specialty_name is None and row.specialty_id:
        specialty = ClinicSpecialty.query.filter_by(tenant_id=row.tenant_id, id=row.specialty_id).first()
        specialty_name = specialty.name_ar if specialty else ""
    elif specialty_name is None:
        specialty_name = ""
    if template_version is None and row.visit_template_id:
        template = ClinicVisitTemplate.query.filter_by(tenant_id=row.tenant_id, id=row.visit_template_id).first()
        template_version = template.version if template else None
    patient_age = None
    if patient and patient.date_of_birth:
        today = _today()
        patient_age = today.year - patient.date_of_birth.year - (
            (today.month, today.day) < (patient.date_of_birth.month, patient.date_of_birth.day)
        )
    return {
        "id": row.id,
        "appointment_id": row.appointment_id,
        "patient_id": row.patient_id,
        "patient_name": patient.full_name if patient else "",
        "patient_file": patient.file_number if patient else "",
        "patient_phone": patient.phone if patient else "",
        "patient_gender": patient.gender if patient else "",
        "patient_age": patient_age,
        "allergies": patient.allergies if patient else "",
        "chronic_conditions": patient.chronic_conditions if patient else "",
        "doctor_id": row.doctor_id,
        "doctor_name": doctor.full_name if doctor else "",
        "doctor_title": (getattr(doctor, "scientific_title", None) or "") if doctor else "",
        "doctor_license": (doctor.license_number or "") if doctor else "",
        "doctor_specialty": (doctor.specialty or "") if doctor else "",
        "service_id": row.service_id,
        "specialty_id": getattr(row, "specialty_id", None),
        "specialty_code": getattr(row, "specialty_code_snapshot", None),
        "workspace": getattr(row, "workspace_snapshot", None),
        "visit_template_id": getattr(row, "visit_template_id", None),
        "specialty_name": specialty_name or "",
        "template_version": template_version,
        "visit_date": row.visit_date.isoformat() if row.visit_date else "",
        "started_at": row.started_at.isoformat() if row.started_at else "",
        "completed_at": row.completed_at.isoformat() if row.completed_at else "",
        "status": row.status,
        "chief_complaint": row.chief_complaint or "",
        "clinical_notes": row.clinical_notes or "",
        "follow_up_date": row.follow_up_date.isoformat() if row.follow_up_date else "",
    }


def start_visit_from_appointment(tenant_id: int, appointment_id: int, actor_id=None) -> dict:
    appt = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=appointment_id).first()
    if not appt:
        raise ValueError("الموعد غير موجود")
    existing = ClinicVisit.query.filter_by(tenant_id=tenant_id, appointment_id=appointment_id).first()
    if existing:
        return visit_dict(existing)
    if appt.status not in ("arrived", "waiting", "confirmed", "in_consultation"):
        change_appointment_status(tenant_id, appointment_id, "waiting", actor_id, "بدء الزيارة")
    change_appointment_status(tenant_id, appointment_id, "in_consultation", actor_id, "دخول الطبيب")
    row = ClinicVisit(
        tenant_id=tenant_id,
        branch_id=appt.branch_id,
        appointment_id=appt.id,
        patient_id=appt.patient_id,
        doctor_id=appt.doctor_id,
        service_id=appt.service_id,
        specialty_id=getattr(appt, "specialty_id", None),
        specialty_code_snapshot=getattr(appt, "specialty_code_snapshot", None),
        workspace_snapshot=getattr(appt, "workspace_snapshot", None),
        room_id=appt.room_id,
        visit_date=appt.appointment_date or _today(),
        started_at=datetime.utcnow(),
        status="open",
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    from modules.clinics.service_specialties import assign_visit_specialty
    assign_visit_specialty(tenant_id, row, getattr(appt, "specialty_id", None))
    from modules.clinics.service_specialty_registry import apply_specialty_snapshot
    apply_specialty_snapshot(tenant_id, row)
    _audit(tenant_id, actor_id, "visit", row.id, "start", "بدء زيارة طبية")
    return visit_dict(row)


def create_walkin_visit(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    patient_id = int(payload.get("patient_id") or 0)
    if not ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first():
        raise ValueError("المريض غير موجود")
    row = ClinicVisit(
        tenant_id=tenant_id,
        branch_id=branch_id,
        patient_id=patient_id,
        doctor_id=int(payload["doctor_id"]) if payload.get("doctor_id") else None,
        service_id=int(payload["service_id"]) if payload.get("service_id") else None,
        visit_date=_today(),
        started_at=datetime.utcnow(),
        status="open",
        chief_complaint=str(payload.get("chief_complaint") or "").strip() or None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    from modules.clinics.service_specialties import assign_visit_specialty
    assign_visit_specialty(tenant_id, row, payload.get("specialty_id"))
    from modules.clinics.service_specialty_registry import apply_specialty_snapshot
    apply_specialty_snapshot(tenant_id, row)
    return visit_dict(row)


def get_visit_detail(tenant_id: int, visit_id: int, *, include_financial: bool = True) -> dict:
    row = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not row:
        raise ValueError("الزيارة غير موجودة")
    vitals = (
        ClinicVital.query.filter_by(tenant_id=tenant_id, visit_id=visit_id)
        .order_by(ClinicVital.recorded_at.desc())
        .all()
    )
    diagnoses = ClinicDiagnosis.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all()
    rx = ClinicPrescription.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first()
    rx_items = []
    if rx:
        rx_items = ClinicPrescriptionItem.query.filter_by(tenant_id=tenant_id, prescription_id=rx.id).all()
    invoices = ClinicInvoice.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all()
    try:
        from modules.clinics.service_ops import list_visit_bill_lines, list_visit_procedures

        procedures = list_visit_procedures(tenant_id, visit_id)
        bill_lines = list_visit_bill_lines(tenant_id, visit_id)
    except Exception:
        procedures = []
        bill_lines = []
    result = {
        "visit": visit_dict(row),
        "vitals": [
            {
                "id": v.id,
                "blood_pressure": v.blood_pressure or "",
                "heart_rate": v.heart_rate,
                "temperature": float(v.temperature) if v.temperature is not None else None,
                "weight_kg": float(v.weight_kg) if v.weight_kg is not None else None,
                "height_cm": float(v.height_cm) if v.height_cm is not None else None,
                "oxygen_sat": v.oxygen_sat,
                "bmi": float(v.bmi) if v.bmi is not None else None,
                "respiratory_rate": v.respiratory_rate,
                "blood_glucose": float(v.blood_glucose) if v.blood_glucose is not None else None,
                "head_circumference_cm": float(v.head_circumference_cm) if getattr(v, "head_circumference_cm", None) is not None else None,
                "notes": v.notes or "",
                "recorded_at": v.recorded_at.isoformat() if v.recorded_at else "",
            }
            for v in vitals
        ],
        "diagnoses": [{"id": d.id, "code": d.code or "", "title": d.title, "notes": d.notes or ""} for d in diagnoses],
        "prescription": {
            "id": rx.id if rx else None,
            "notes": rx.notes if rx else "",
            "items": [
                {
                    "id": i.id,
                    "medicine_name": i.medicine_name,
                    "dosage": i.dosage or "",
                    "frequency": i.frequency or "",
                    "duration": i.duration or "",
                    "instructions": i.instructions or "",
                }
                for i in rx_items
            ],
        },
        "procedures": procedures,
        "bill_lines": bill_lines,
        "invoices": [invoice_dict(inv) for inv in invoices],
    }
    from modules.clinics.service_specialties import visit_template_context
    result.update(visit_template_context(tenant_id, visit_id))
    if not include_financial:
        result.pop("invoices", None)
        result.pop("bill_lines", None)
        for procedure in result.get("procedures") or []:
            for key in ("price", "total", "cost", "margin"):
                procedure.pop(key, None)
    return result


def update_visit(tenant_id: int, visit_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not row:
        raise ValueError("الزيارة غير موجودة")
    if row.status == "completed" and any(key in payload for key in ("specialty_id", "visit_template_id", "doctor_id")):
        raise ValueError("لا يمكن تغيير اختصاص أو نموذج أو طبيب زيارة مكتملة")
    if "visit_template_id" in payload:
        raise ValueError("لا يمكن تعيين نموذج الزيارة مباشرة")
    follow_up_date = row.follow_up_date
    if "follow_up_date" in payload:
        follow_up_date = _parse_date(payload["follow_up_date"], "موعد المتابعة") if payload.get("follow_up_date") else None
    if "specialty_id" in payload or "doctor_id" in payload:
        from modules.clinics.service_specialties import assign_visit_specialty
        doctor_id = int(payload.get("doctor_id") or row.doctor_id) if (payload.get("doctor_id") or row.doctor_id) else None
        specialty_id = payload.get("specialty_id") if "specialty_id" in payload else row.specialty_id
        assign_visit_specialty(tenant_id, row, specialty_id, doctor_id=doctor_id)
    for field in ("chief_complaint", "clinical_notes"):
        if field in payload:
            setattr(row, field, str(payload.get(field) or "").strip() or None)
    if "follow_up_date" in payload:
        row.follow_up_date = follow_up_date
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    return visit_dict(row)


def save_vitals(tenant_id: int, visit_id: int, payload: dict, actor_id=None) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")

    def _pos(name, raw, lo, hi):
        if raw in (None, ""):
            return None
        value = float(raw)
        if value <= 0 or value > hi:
            raise ValueError(f"قيمة {name} غير صالحة")
        return value

    weight = _pos("الوزن", payload.get("weight_kg"), 0, 500)
    height = _pos("الطول", payload.get("height_cm"), 0, 300)
    head = _pos("محيط الرأس", payload.get("head_circumference_cm"), 0, 100)
    bmi = float(payload["bmi"]) if payload.get("bmi") not in (None, "") else None
    if bmi is None and weight and height and height > 0:
        bmi = round(weight / ((height / 100) ** 2), 2)
    row = ClinicVital(
        tenant_id=tenant_id,
        visit_id=visit_id,
        patient_id=visit.patient_id,
        blood_pressure=str(payload.get("blood_pressure") or "").strip() or None,
        heart_rate=int(payload["heart_rate"]) if payload.get("heart_rate") not in (None, "") else None,
        temperature=float(payload["temperature"]) if payload.get("temperature") not in (None, "") else None,
        weight_kg=weight,
        height_cm=height,
        oxygen_sat=int(payload["oxygen_sat"]) if payload.get("oxygen_sat") not in (None, "") else None,
        bmi=bmi,
        respiratory_rate=int(payload["respiratory_rate"]) if payload.get("respiratory_rate") not in (None, "") else None,
        blood_glucose=float(payload["blood_glucose"]) if payload.get("blood_glucose") not in (None, "") else None,
        head_circumference_cm=head,
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return get_visit_detail(tenant_id, visit_id)


def add_diagnosis(tenant_id: int, visit_id: int, payload: dict, actor_id=None) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("التشخيص مطلوب")
    db.session.add(
        ClinicDiagnosis(
            tenant_id=tenant_id,
            visit_id=visit_id,
            patient_id=visit.patient_id,
            code=str(payload.get("code") or "").strip() or None,
            title=title,
            status=str(payload.get("status") or "active").strip() or "active",
            notes=str(payload.get("notes") or "").strip() or None,
            created_by=actor_id,
        )
    )
    db.session.flush()
    return get_visit_detail(tenant_id, visit_id)


def save_prescription(tenant_id: int, visit_id: int, payload: dict, actor_id=None) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    rx = ClinicPrescription.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first()
    if not rx:
        rx = ClinicPrescription(
            tenant_id=tenant_id,
            visit_id=visit_id,
            patient_id=visit.patient_id,
            doctor_id=visit.doctor_id,
            created_by=actor_id,
        )
        db.session.add(rx)
        db.session.flush()
    rx.notes = str(payload.get("notes") or "").strip() or None
    ClinicPrescriptionItem.query.filter_by(tenant_id=tenant_id, prescription_id=rx.id).delete()
    for item in payload.get("items") or []:
        name = str(item.get("medicine_name") or "").strip()
        if not name:
            continue
        db.session.add(
            ClinicPrescriptionItem(
                tenant_id=tenant_id,
                prescription_id=rx.id,
                medicine_name=name,
                dosage=str(item.get("dosage") or "").strip() or None,
                frequency=str(item.get("frequency") or "").strip() or None,
                duration=str(item.get("duration") or "").strip() or None,
                instructions=str(item.get("instructions") or "").strip() or None,
            )
        )
    db.session.flush()
    return get_visit_detail(tenant_id, visit_id)


def complete_visit(tenant_id: int, visit_id: int, actor_id=None, auto_invoice: bool = True) -> dict:
    visit = _locked_visit(tenant_id, visit_id)
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    if visit.status == "completed":
        return get_visit_detail(tenant_id, visit_id)
    from modules.clinics.service_specialties import validate_visit_completion
    validate_visit_completion(tenant_id, visit)
    visit.status = "completed"
    visit.completed_at = datetime.utcnow()
    visit.updated_by = actor_id
    if visit.appointment_id:
        change_appointment_status(tenant_id, visit.appointment_id, "completed", actor_id, "إكمال الزيارة")
    if auto_invoice and not ClinicInvoice.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first():
        create_invoice_for_visit(tenant_id, visit_id, actor_id)
    _audit(tenant_id, actor_id, "visit", visit_id, "complete", "إكمال الزيارة")
    return get_visit_detail(tenant_id, visit_id)


def invoice_dict(row: ClinicInvoice) -> dict:
    return {
        "id": row.id,
        "invoice_number": row.invoice_number,
        "patient_id": row.patient_id,
        "visit_id": row.visit_id,
        "doctor_id": row.doctor_id,
        "invoice_date": row.invoice_date.isoformat() if row.invoice_date else "",
        "subtotal": row.subtotal,
        "discount": row.discount,
        "total": row.total,
        "paid": row.paid,
        "balance": row.balance,
        "status": row.status,
        "notes": row.notes or "",
        "treatment_plan_id": getattr(row, "treatment_plan_id", None),
    }


def _next_invoice_number(tenant_id: int) -> str:
    count = ClinicInvoice.query.filter_by(tenant_id=tenant_id).count() + 1
    return f"CI-{count:05d}"


def create_invoice_for_visit(tenant_id: int, visit_id: int, actor_id=None) -> dict:
    visit = _locked_visit(tenant_id, visit_id)
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    existing = ClinicInvoice.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first()
    if existing:
        return invoice_dict(existing)
    _advisory_transaction_lock("clinic-invoice-number", tenant_id)
    # Recheck after waiting for the tenant invoice lock.
    existing = ClinicInvoice.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first()
    if existing:
        return invoice_dict(existing)
    price = 0
    description = "رسوم الزيارة"
    if visit.service_id:
        service = ClinicService.query.filter_by(tenant_id=tenant_id, id=visit.service_id).first()
        if service:
            price = service.price or 0
            description = service.name
    inv = ClinicInvoice(
        tenant_id=tenant_id,
        branch_id=visit.branch_id,
        visit_id=visit.id,
        appointment_id=visit.appointment_id,
        patient_id=visit.patient_id,
        doctor_id=visit.doctor_id,
        invoice_number=_next_invoice_number(tenant_id),
        invoice_date=_today(),
        subtotal=price,
        discount=0,
        total=price,
        paid=0,
        balance=price,
        status="open" if price else "paid",
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(inv)
    db.session.flush()
    db.session.add(
        ClinicInvoiceItem(
            tenant_id=tenant_id,
            invoice_id=inv.id,
            service_id=visit.service_id,
            description=description,
            quantity=1,
            unit_price=price,
            line_total=price,
        )
    )
    db.session.flush()
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.post_clinic_invoice(inv.id, tenant_id, actor_id)
    if visit.appointment_id and price:
        appt = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=visit.appointment_id).first()
        if appt:
            appt.payment_status = "unpaid"
    return invoice_dict(inv)


def list_invoices(tenant_id: int, day: date | None = None) -> list[dict]:
    query = ClinicInvoice.query.filter_by(tenant_id=tenant_id)
    if day:
        query = query.filter_by(invoice_date=day)
    rows = query.order_by(ClinicInvoice.id.desc()).limit(200).all()
    result = []
    for inv in rows:
        data = invoice_dict(inv)
        patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=inv.patient_id).first()
        data["patient_name"] = patient.full_name if patient else ""
        result.append(data)
    return result


def _locked_invoice(tenant_id: int, invoice_id: int) -> ClinicInvoice | None:
    query = ClinicInvoice.query.filter_by(tenant_id=tenant_id, id=invoice_id)
    if db.session.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    return query.first()


def receive_payment(tenant_id: int, invoice_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    inv = _locked_invoice(tenant_id, invoice_id)
    if not inv:
        raise ValueError("الفاتورة غير موجودة")
    amount = _money(payload.get("amount"))
    if amount <= 0:
        raise ValueError("مبلغ الدفع غير صالح")
    # Re-read balance under row lock so concurrent payments cannot overpay.
    if amount > float(inv.balance or 0):
        raise ValueError("المبلغ أكبر من الرصيد المتبقي")
    pay = ClinicPayment(
        tenant_id=tenant_id,
        branch_id=branch_id or inv.branch_id,
        invoice_id=inv.id,
        patient_id=inv.patient_id,
        amount=amount,
        method=str(payload.get("method") or "cash").strip() or "cash",
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(pay)
    inv.paid += amount
    inv.balance = max(0, inv.total - inv.paid)
    inv.status = "paid" if inv.balance == 0 else "partial"
    inv.updated_by = actor_id
    inv.updated_at = datetime.utcnow()
    if inv.appointment_id:
        appt = ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=inv.appointment_id).first()
        if appt:
            appt.payment_status = inv.status
    _audit(tenant_id, actor_id, "payment", pay.id, "create", f"تحصيل {amount}", branch_id=branch_id)
    db.session.flush()
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.post_clinic_payment(pay.id, tenant_id, actor_id)
    return invoice_dict(inv)


def void_invoice(tenant_id: int, invoice_id: int, actor_id=None) -> dict:
    """Void an unpaid invoice and preserve its accounting history by reversal."""
    inv = _locked_invoice(tenant_id, invoice_id)
    if not inv:
        raise ValueError("الفاتورة غير موجودة")
    if inv.status == "void":
        return invoice_dict(inv)
    if int(inv.paid or 0) > 0:
        raise ValueError("يجب استرجاع المدفوعات قبل إلغاء الفاتورة")
    inv.status = "void"
    inv.balance = 0
    inv.updated_by = actor_id
    inv.updated_at = datetime.utcnow()
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.reverse_posting(
        tenant_id, "clinic_invoice", inv.id,
        source_event_prefix="issued", reversal_event="voided", actor_id=actor_id,
    )
    _audit(tenant_id, actor_id, "invoice", inv.id, "void", f"إلغاء الفاتورة {inv.invoice_number}", branch_id=inv.branch_id)
    db.session.flush()
    return invoice_dict(inv)


def list_visits(tenant_id: int, day: date | None = None, status: str | None = None) -> list[dict]:
    day = day or _today()
    query = ClinicVisit.query.filter_by(tenant_id=tenant_id, visit_date=day)
    if status:
        query = query.filter_by(status=status)
    visits = query.order_by(ClinicVisit.id.desc()).all()
    from modules.clinics.models import ClinicSpecialty, ClinicVisitTemplate

    specialty_ids = {v.specialty_id for v in visits if v.specialty_id}
    template_ids = {v.visit_template_id for v in visits if v.visit_template_id}
    specialty_names = {
        s.id: s.name_ar
        for s in ClinicSpecialty.query.filter(
            ClinicSpecialty.tenant_id == tenant_id, ClinicSpecialty.id.in_(specialty_ids or {-1})
        ).all()
    } if specialty_ids else {}
    template_versions = {
        t.id: t.version
        for t in ClinicVisitTemplate.query.filter(
            ClinicVisitTemplate.tenant_id == tenant_id, ClinicVisitTemplate.id.in_(template_ids or {-1})
        ).all()
    } if template_ids else {}
    return [
        visit_dict(
            v,
            specialty_name=specialty_names.get(v.specialty_id, ""),
            template_version=template_versions.get(v.visit_template_id),
        )
        for v in visits
    ]


def reception_board(tenant_id: int, day: date | None = None, doctor_id=None) -> dict:
    day = day or _today()
    appointments = list_appointments(tenant_id, day=day, doctor_id=doctor_id)
    columns = {
        "pending": [],
        "confirmed": [],
        "arrived": [],
        "waiting": [],
        "in_consultation": [],
        "completed": [],
        "cancelled": [],
        "no_show": [],
    }
    for appt in appointments:
        key = appt["status"] if appt["status"] in columns else "pending"
        columns[key].append(appt)
    return {
        "date": day.isoformat(),
        "appointments": appointments,
        "columns": columns,
        "counts": {k: len(v) for k, v in columns.items()},
        "doctors": list_doctors(tenant_id, active_only=True),
        "services": list_services(tenant_id, active_only=True),
    }


def dashboard(tenant_id: int, day: date | None = None) -> dict:
    """Legacy summary — prefer service_dashboard.dashboard_snapshot."""
    from modules.clinics.service_dashboard import dashboard_snapshot

    return dashboard_snapshot(tenant_id, day)


def bootstrap(tenant_id: int) -> dict:
    from modules.clinics.service_specialties import list_specialties
    return {
        "settings": settings_payload(tenant_id),
        "doctors": list_doctors(tenant_id),
        "services": list_services(tenant_id),
        "rooms": list_rooms(tenant_id),
        "specialties": list_specialties(tenant_id),
        "statuses": list(APPOINTMENT_STATUSES),
        "status_labels": {
            "pending": "قيد الانتظار",
            "confirmed": "مؤكد",
            "arrived": "حضر",
            "waiting": "في الانتظار",
            "in_consultation": "عند الطبيب",
            "completed": "مكتمل",
            "cancelled": "ملغى",
            "rescheduled": "أُعيد جدولة",
            "no_show": "لم يحضر",
        },
    }
