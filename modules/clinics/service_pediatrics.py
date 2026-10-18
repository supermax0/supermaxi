"""Pediatric clinical tools — profile, growth (via ClinicVital), vaccinations, development."""
from __future__ import annotations

import json
from datetime import date, datetime

from extensions import db
from modules.clinics.models import (
    ClinicDoctor,
    ClinicPatient,
    ClinicPediatricDevelopmentRecord,
    ClinicPediatricProfile,
    ClinicPediatricVaccinationRecord,
    ClinicVisit,
    ClinicVital,
)
from modules.clinics.service import _audit, _parse_date

DELIVERY_TYPES = frozenset({"vaginal", "cesarean", "assisted", "other", "unknown"})
FEEDING_TYPES = frozenset({"breastfeeding", "formula", "mixed", "complementary", "other"})
VAX_STATUSES = frozenset({"recorded", "administered", "reported_by_parent", "not_given", "unknown"})
VAX_SOURCES = frozenset({"clinic", "parent_report", "external_card", "external_document", "other"})
DEV_DOMAINS = ("gross_motor", "fine_motor", "language", "social", "cognitive")
DEV_STATUSES = frozenset({"not_assessed", "documented", "concern_noted"})

DELIVERY_AR = {
    "vaginal": "طبيعي", "cesarean": "قيصري", "assisted": "مساعد", "other": "أخرى", "unknown": "غير معروف",
}
FEEDING_AR = {
    "breastfeeding": "رضاعة طبيعية", "formula": "حليب صناعي", "mixed": "مختلط",
    "complementary": "أغذية تكميلية", "other": "أخرى",
}
VAX_STATUS_AR = {
    "recorded": "مسجّل", "administered": "مُعطى", "reported_by_parent": "حسب الأهل",
    "not_given": "لم يُعطَ", "unknown": "غير معروف",
}
VAX_SOURCE_AR = {
    "clinic": "العيادة", "parent_report": "تقرير الأهل", "external_card": "بطاقة خارجية",
    "external_document": "مستند خارجي", "other": "أخرى",
}
DOMAIN_AR = {
    "gross_motor": "الحركة الكبرى", "fine_motor": "الحركة الدقيقة", "language": "اللغة",
    "social": "التفاعل الاجتماعي", "cognitive": "الإدراك",
}
DEV_STATUS_AR = {
    "not_assessed": "لم يُقيَّم", "documented": "موثّق", "concern_noted": "ملاحظة سريرية",
}


def _patient(tenant_id: int, patient_id: int) -> ClinicPatient:
    row = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not row:
        raise ValueError("المريض غير موجود")
    return row


def _age_at(dob: date | None, when: date | datetime | None) -> dict:
    if not dob or not when:
        return {"age_days": None, "age_months": None, "age_years": None, "age_label": ""}
    target = when.date() if isinstance(when, datetime) else when
    if target < dob:
        return {"age_days": None, "age_months": None, "age_years": None, "age_label": ""}
    days = (target - dob).days
    years = target.year - dob.year - ((target.month, target.day) < (dob.month, dob.day))
    months = (target.year - dob.year) * 12 + target.month - dob.month - (1 if target.day < dob.day else 0)
    return {
        "age_days": days,
        "age_months": months,
        "age_years": years,
        "age_label": f"{years}س {months % 12}ش" if years or months else f"{days} يوم",
    }


def _num(raw):
    if raw in (None, ""):
        return None
    return float(raw)


def _profile_dict(row: ClinicPediatricProfile | None) -> dict:
    if not row:
        return {
            "exists": False,
            "gestational_age_weeks": None,
            "birth_weight": None,
            "birth_length": None,
            "birth_head_circumference": None,
            "delivery_type": None,
            "delivery_label_ar": "",
            "nicu_admission": False,
            "nicu_days": None,
            "neonatal_complications": "",
            "feeding_type": None,
            "feeding_label_ar": "",
            "feeding_notes": "",
            "weaning_status": "",
        }
    return {
        "exists": True,
        "id": row.id,
        "gestational_age_weeks": float(row.gestational_age_weeks) if row.gestational_age_weeks is not None else None,
        "birth_weight": float(row.birth_weight) if row.birth_weight is not None else None,
        "birth_length": float(row.birth_length) if row.birth_length is not None else None,
        "birth_head_circumference": float(row.birth_head_circumference) if row.birth_head_circumference is not None else None,
        "delivery_type": row.delivery_type,
        "delivery_label_ar": DELIVERY_AR.get(row.delivery_type or "", ""),
        "nicu_admission": bool(row.nicu_admission),
        "nicu_days": row.nicu_days,
        "neonatal_complications": row.neonatal_complications or "",
        "feeding_type": row.feeding_type,
        "feeding_label_ar": FEEDING_AR.get(row.feeding_type or "", ""),
        "feeding_notes": row.feeding_notes or "",
        "weaning_status": row.weaning_status or "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_or_empty_profile(tenant_id: int, patient_id: int) -> ClinicPediatricProfile | None:
    return ClinicPediatricProfile.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).first()


def get_pediatric_profile(tenant_id: int, patient_id: int) -> dict:
    patient = _patient(tenant_id, patient_id)
    row = get_or_empty_profile(tenant_id, patient_id)
    data = _profile_dict(row)
    data["patient_id"] = patient_id
    data["date_of_birth"] = patient.date_of_birth.isoformat() if patient.date_of_birth else None
    data["current_age"] = _age_at(patient.date_of_birth, date.today())
    return data


def upsert_pediatric_profile(tenant_id: int, patient_id: int, payload: dict, actor_id=None) -> dict:
    patient = _patient(tenant_id, patient_id)
    row = get_or_empty_profile(tenant_id, patient_id)
    created = row is None
    if created:
        row = ClinicPediatricProfile(tenant_id=tenant_id, patient_id=patient.id, created_by=actor_id)
        db.session.add(row)
    old = _profile_dict(row) if not created else {}

    if "gestational_age_weeks" in payload:
        ga = _num(payload.get("gestational_age_weeks"))
        if ga is not None and (ga < 20 or ga > 45):
            raise ValueError("عمر الحمل غير صالح")
        row.gestational_age_weeks = ga
    for field, attr, hi in (
        ("birth_weight", "birth_weight", 10),
        ("birth_length", "birth_length", 80),
        ("birth_head_circumference", "birth_head_circumference", 60),
    ):
        if field in payload:
            value = _num(payload.get(field))
            if value is not None and (value <= 0 or value > hi):
                raise ValueError(f"قيمة {field} غير صالحة")
            setattr(row, attr, value)
    if "delivery_type" in payload:
        dtype = str(payload.get("delivery_type") or "").strip().lower() or None
        if dtype and dtype not in DELIVERY_TYPES:
            raise ValueError("نوع الولادة غير صالح")
        row.delivery_type = dtype
    if "nicu_admission" in payload:
        row.nicu_admission = bool(payload.get("nicu_admission"))
    if "nicu_days" in payload:
        days = payload.get("nicu_days")
        row.nicu_days = int(days) if days not in (None, "") else None
        if row.nicu_days is not None and row.nicu_days < 0:
            raise ValueError("أيام العناية المركزة غير صالحة")
    if "neonatal_complications" in payload:
        row.neonatal_complications = str(payload.get("neonatal_complications") or "").strip() or None
    if "feeding_type" in payload:
        ftype = str(payload.get("feeding_type") or "").strip().lower() or None
        if ftype and ftype not in FEEDING_TYPES:
            raise ValueError("نوع التغذية غير صالح")
        row.feeding_type = ftype
    if "feeding_notes" in payload:
        row.feeding_notes = str(payload.get("feeding_notes") or "").strip() or None
    if "weaning_status" in payload:
        row.weaning_status = str(payload.get("weaning_status") or "").strip() or None
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    db.session.flush()
    _audit(
        tenant_id, actor_id, "pediatric_profile", row.id,
        "create" if created else "update",
        "تحديث الملف الطبي للأطفال" if not created else "إنشاء الملف الطبي للأطفال",
        meta={"patient_id": patient_id, "old": old, "new": _profile_dict(row)},
    )
    return get_pediatric_profile(tenant_id, patient_id)


def get_pediatric_growth(tenant_id: int, patient_id: int) -> dict:
    patient = _patient(tenant_id, patient_id)
    rows = (
        ClinicVital.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicVital.recorded_at.asc(), ClinicVital.id.asc())
        .all()
    )
    history = []
    for v in rows:
        if all(getattr(v, k) is None for k in ("weight_kg", "height_cm", "bmi", "head_circumference_cm")):
            continue
        age = _age_at(patient.date_of_birth, v.recorded_at)
        history.append({
            "id": v.id,
            "visit_id": v.visit_id,
            "recorded_at": v.recorded_at.isoformat() if v.recorded_at else None,
            "weight_kg": float(v.weight_kg) if v.weight_kg is not None else None,
            "height_cm": float(v.height_cm) if v.height_cm is not None else None,
            "bmi": float(v.bmi) if v.bmi is not None else None,
            "head_circumference_cm": float(v.head_circumference_cm) if v.head_circumference_cm is not None else None,
            **age,
        })
    latest = None
    if history:
        # latest by recorded_at already ascending — take last with any measurement
        latest = history[-1]
    ped_visits = (
        ClinicVisit.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicVisit.visit_date.desc(), ClinicVisit.id.desc())
        .limit(20)
        .all()
    )
    return {
        "patient_id": patient_id,
        "units": {"weight": "kg", "height": "cm", "head_circumference": "cm", "temperature": "°C"},
        "latest": latest,
        "history": list(reversed(history)),  # newest first for table
        "series": history,  # chronological for charts
        "percentile_available": False,
        "visits": [
            {
                "id": v.id,
                "visit_date": v.visit_date.isoformat() if v.visit_date else None,
                "status": v.status,
                "doctor_name": (
                    ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=v.doctor_id).first().full_name
                    if v.doctor_id else ""
                ),
            }
            for v in ped_visits
        ],
    }


def _vax_dict(row: ClinicPediatricVaccinationRecord) -> dict:
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "vaccine_name": row.vaccine_name,
        "dose_label": row.dose_label or "",
        "dose_number": row.dose_number,
        "scheduled_date": row.scheduled_date.isoformat() if row.scheduled_date else None,
        "administered_date": row.administered_date.isoformat() if row.administered_date else None,
        "status": row.status,
        "status_label_ar": VAX_STATUS_AR.get(row.status, row.status),
        "source": row.source,
        "source_label_ar": VAX_SOURCE_AR.get(row.source, row.source),
        "notes": row.notes or "",
        "attachment_id": row.attachment_id,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_vaccinations(tenant_id: int, patient_id: int) -> dict:
    _patient(tenant_id, patient_id)
    rows = (
        ClinicPediatricVaccinationRecord.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(ClinicPediatricVaccinationRecord.archived_at.is_(None))
        .order_by(
            ClinicPediatricVaccinationRecord.administered_date.desc(),
            ClinicPediatricVaccinationRecord.id.desc(),
        )
        .all()
    )
    return {"patient_id": patient_id, "items": [_vax_dict(r) for r in rows]}


def add_vaccination(tenant_id: int, patient_id: int, payload: dict, actor_id=None) -> dict:
    patient = _patient(tenant_id, patient_id)
    name = str(payload.get("vaccine_name") or "").strip()
    if not name:
        raise ValueError("اسم اللقاح مطلوب")
    status = str(payload.get("status") or "recorded").strip().lower()
    if status not in VAX_STATUSES:
        raise ValueError("حالة التطعيم غير صالحة")
    source = str(payload.get("source") or "clinic").strip().lower()
    if source not in VAX_SOURCES:
        raise ValueError("مصدر التطعيم غير صالح")
    administered = _parse_date(payload.get("administered_date")) if payload.get("administered_date") else None
    scheduled = _parse_date(payload.get("scheduled_date")) if payload.get("scheduled_date") else None
    if administered and patient.date_of_birth and administered < patient.date_of_birth:
        raise ValueError("تاريخ التطعيم قبل تاريخ الميلاد")
    row = ClinicPediatricVaccinationRecord(
        tenant_id=tenant_id,
        patient_id=patient_id,
        vaccine_name=name,
        dose_label=str(payload.get("dose_label") or "").strip() or None,
        dose_number=int(payload["dose_number"]) if payload.get("dose_number") not in (None, "") else None,
        scheduled_date=scheduled,
        administered_date=administered,
        status=status,
        source=source,
        notes=str(payload.get("notes") or "").strip() or None,
        attachment_id=int(payload["attachment_id"]) if payload.get("attachment_id") not in (None, "", 0, "0") else None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "pediatric_vaccination", row.id, "create", f"إضافة تطعيم: {name}",
           meta={"patient_id": patient_id})
    return list_vaccinations(tenant_id, patient_id)


def update_vaccination(tenant_id: int, vax_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicPediatricVaccinationRecord.query.filter_by(tenant_id=tenant_id, id=vax_id).first()
    if not row or row.archived_at:
        raise ValueError("سجل التطعيم غير موجود")
    patient = _patient(tenant_id, row.patient_id)
    old = _vax_dict(row)
    if "vaccine_name" in payload:
        name = str(payload.get("vaccine_name") or "").strip()
        if not name:
            raise ValueError("اسم اللقاح مطلوب")
        row.vaccine_name = name
    if "dose_label" in payload:
        row.dose_label = str(payload.get("dose_label") or "").strip() or None
    if "dose_number" in payload:
        row.dose_number = int(payload["dose_number"]) if payload.get("dose_number") not in (None, "") else None
    if "scheduled_date" in payload:
        row.scheduled_date = _parse_date(payload.get("scheduled_date")) if payload.get("scheduled_date") else None
    if "administered_date" in payload:
        administered = _parse_date(payload.get("administered_date")) if payload.get("administered_date") else None
        if administered and patient.date_of_birth and administered < patient.date_of_birth:
            raise ValueError("تاريخ التطعيم قبل تاريخ الميلاد")
        row.administered_date = administered
    if "status" in payload:
        status = str(payload.get("status") or "").strip().lower()
        if status not in VAX_STATUSES:
            raise ValueError("حالة التطعيم غير صالحة")
        row.status = status
    if "source" in payload:
        source = str(payload.get("source") or "").strip().lower()
        if source not in VAX_SOURCES:
            raise ValueError("مصدر التطعيم غير صالح")
        row.source = source
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "").strip() or None
    if "attachment_id" in payload:
        row.attachment_id = int(payload["attachment_id"]) if payload.get("attachment_id") not in (None, "", 0, "0") else None
    if payload.get("archive") in (True, "true", 1, "1"):
        row.archived_at = datetime.utcnow()
        action = "archive"
    else:
        action = "update"
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    _audit(tenant_id, actor_id, "pediatric_vaccination", row.id, action, f"{action} تطعيم #{row.id}",
           meta={"old": old, "new": _vax_dict(row)})
    return list_vaccinations(tenant_id, row.patient_id)


def _dev_dict(row: ClinicPediatricDevelopmentRecord, doctor_name: str = "") -> dict:
    domains = {}
    if row.domains_json:
        try:
            domains = json.loads(row.domains_json) or {}
        except json.JSONDecodeError:
            domains = {}
    normalized = {}
    for key in DEV_DOMAINS:
        entry = domains.get(key) or {}
        status = entry.get("status") or "not_assessed"
        normalized[key] = {
            "status": status,
            "status_label_ar": DEV_STATUS_AR.get(status, status),
            "label_ar": DOMAIN_AR[key],
            "notes": entry.get("notes") or "",
        }
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "visit_id": row.visit_id,
        "doctor_id": row.doctor_id,
        "doctor_name": doctor_name,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        "domains": normalized,
        "notes": row.notes or "",
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
    }


def list_development(tenant_id: int, patient_id: int) -> dict:
    _patient(tenant_id, patient_id)
    rows = (
        ClinicPediatricDevelopmentRecord.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(ClinicPediatricDevelopmentRecord.archived_at.is_(None))
        .order_by(ClinicPediatricDevelopmentRecord.recorded_at.desc(), ClinicPediatricDevelopmentRecord.id.desc())
        .all()
    )
    doctors = {
        d.id: d.full_name
        for d in ClinicDoctor.query.filter(
            ClinicDoctor.tenant_id == tenant_id,
            ClinicDoctor.id.in_({r.doctor_id for r in rows if r.doctor_id} or {-1}),
        ).all()
    }
    return {
        "patient_id": patient_id,
        "items": [_dev_dict(r, doctors.get(r.doctor_id, "")) for r in rows],
        "domain_labels": DOMAIN_AR,
    }


def add_development(tenant_id: int, patient_id: int, payload: dict, actor_id=None) -> dict:
    patient = _patient(tenant_id, patient_id)
    visit_id = payload.get("visit_id")
    visit_id = int(visit_id) if visit_id not in (None, "", 0, "0") else None
    doctor_id = payload.get("doctor_id")
    doctor_id = int(doctor_id) if doctor_id not in (None, "", 0, "0") else None
    if visit_id:
        visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id, patient_id=patient.id).first()
        if not visit:
            raise ValueError("الزيارة غير موجودة")
        if visit.status == "completed" and not payload.get("allow_completed"):
            # Allow reading history; new records after complete only via explicit override not used in V1
            raise ValueError("لا يمكن إضافة سجل تطور بعد إكمال الزيارة")
        if doctor_id is None:
            doctor_id = visit.doctor_id
    domains_in = payload.get("domains") or {}
    domains = {}
    for key in DEV_DOMAINS:
        entry = domains_in.get(key) or {}
        status = str(entry.get("status") or "not_assessed").strip().lower()
        if status not in DEV_STATUSES:
            raise ValueError(f"حالة مجال {key} غير صالحة")
        domains[key] = {
            "status": status,
            "notes": str(entry.get("notes") or "").strip(),
        }
    row = ClinicPediatricDevelopmentRecord(
        tenant_id=tenant_id,
        patient_id=patient_id,
        visit_id=visit_id,
        doctor_id=doctor_id,
        domains_json=json.dumps(domains, ensure_ascii=False),
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "pediatric_development", row.id, "create",
           "إضافة سجل تطور للأطفال", meta={"patient_id": patient_id, "visit_id": visit_id})
    return list_development(tenant_id, patient_id)


def update_development(tenant_id: int, record_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicPediatricDevelopmentRecord.query.filter_by(tenant_id=tenant_id, id=record_id).first()
    if not row or row.archived_at:
        raise ValueError("سجل التطور غير موجود")
    if row.visit_id:
        visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=row.visit_id).first()
        if visit and visit.status == "completed":
            raise ValueError("لا يمكن تعديل سجل تطور مرتبط بزيارة مكتملة")
    old = _dev_dict(row)
    if "domains" in payload:
        domains_in = payload.get("domains") or {}
        domains = {}
        for key in DEV_DOMAINS:
            entry = domains_in.get(key) or {}
            status = str(entry.get("status") or "not_assessed").strip().lower()
            if status not in DEV_STATUSES:
                raise ValueError(f"حالة مجال {key} غير صالحة")
            domains[key] = {"status": status, "notes": str(entry.get("notes") or "").strip()}
        row.domains_json = json.dumps(domains, ensure_ascii=False)
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "").strip() or None
    if payload.get("archive") in (True, "true", 1, "1"):
        row.archived_at = datetime.utcnow()
        action = "archive"
    else:
        action = "update"
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    _audit(tenant_id, actor_id, "pediatric_development", row.id, action,
           f"{action} سجل تطور #{row.id}", meta={"old": old, "new": _dev_dict(row)})
    return list_development(tenant_id, row.patient_id)


def get_pediatric_context(tenant_id: int, patient_id: int) -> dict:
    """Bulk payload for doctor workspace / patient pediatric tab."""
    profile = get_pediatric_profile(tenant_id, patient_id)
    growth = get_pediatric_growth(tenant_id, patient_id)
    vaccinations = list_vaccinations(tenant_id, patient_id)
    development = list_development(tenant_id, patient_id)
    return {
        "patient_id": patient_id,
        "pediatric_profile": profile,
        "latest_growth": growth.get("latest"),
        "growth_history": growth.get("history") or [],
        "growth_series": growth.get("series") or [],
        "growth_units": growth.get("units"),
        "vaccinations": vaccinations.get("items") or [],
        "development_history": development.get("items") or [],
        "percentile_available": False,
        "permissions": {"can_edit": True},
        "catalog": {
            "delivery_types": [{"code": k, "label_ar": v} for k, v in DELIVERY_AR.items()],
            "feeding_types": [{"code": k, "label_ar": v} for k, v in FEEDING_AR.items()],
            "vax_statuses": [{"code": k, "label_ar": v} for k, v in VAX_STATUS_AR.items()],
            "vax_sources": [{"code": k, "label_ar": v} for k, v in VAX_SOURCE_AR.items()],
            "dev_domains": [{"code": k, "label_ar": v} for k, v in DOMAIN_AR.items()],
            "dev_statuses": [{"code": k, "label_ar": v} for k, v in DEV_STATUS_AR.items()],
        },
    }
