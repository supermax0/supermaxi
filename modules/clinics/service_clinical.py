"""Patient-centric medical record views backed by the existing clinic records."""
from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import or_

from extensions import db
from modules.clinics.models import (
    ClinicAttachment, ClinicDiagnosis, ClinicDoctor, ClinicLabOrder, ClinicLabOrderItem,
    ClinicLabTest, ClinicPatient, ClinicPrescription, ClinicPrescriptionItem,
    ClinicRadiologyOrder, ClinicVital, ClinicVisit, ClinicFollowUp,
    ClinicVisitProcedure, ClinicProcedure,
)
from modules.clinics.service import _audit, patient_dict, visit_dict
from modules.clinics.service_extras import attachment_dict


def recent_patients(tenant_id: int, q: str = "", limit: int = 12) -> list[dict]:
    query = ClinicPatient.query.filter_by(tenant_id=tenant_id).filter(ClinicPatient.status != "deleted")
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(or_(ClinicPatient.full_name.ilike(like), ClinicPatient.phone.ilike(like), ClinicPatient.file_number.ilike(like)))
    rows = query.order_by(ClinicPatient.updated_at.desc(), ClinicPatient.id.desc()).limit(min(30, limit)).all()
    result = []
    for row in rows:
        latest = ClinicVisit.query.filter_by(tenant_id=tenant_id, patient_id=row.id).order_by(ClinicVisit.visit_date.desc(), ClinicVisit.id.desc()).first()
        data = patient_dict(row)
        data["last_visit"] = latest.visit_date.isoformat() if latest and latest.visit_date else ""
        result.append(data)
    return result


def _doctor_name(tenant_id: int, doctor_id) -> str:
    if not doctor_id: return ""
    row = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
    return row.full_name if row else ""


def _diagnosis_dict(row: ClinicDiagnosis, tenant_id: int) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=row.visit_id).first()
    return {"id": row.id, "visit_id": row.visit_id, "title": row.title, "code": row.code or "", "notes": row.notes or "", "status": row.status or "active", "created_at": row.created_at.isoformat() if row.created_at else "", "updated_at": row.updated_at.isoformat() if row.updated_at else "", "doctor_name": _doctor_name(tenant_id, visit.doctor_id if visit else None)}


def _rx_dict(row: ClinicPrescription, tenant_id: int) -> dict:
    items = ClinicPrescriptionItem.query.filter_by(tenant_id=tenant_id, prescription_id=row.id).all()
    return {"id": row.id, "visit_id": row.visit_id, "doctor_name": _doctor_name(tenant_id, row.doctor_id), "status": row.status, "notes": row.notes or "", "created_at": row.created_at.isoformat() if row.created_at else "", "items": [{"id": i.id, "medicine_name": i.medicine_name, "dosage": i.dosage or "", "frequency": i.frequency or "", "duration": i.duration or "", "instructions": i.instructions or ""} for i in items]}


def _lab_dict(row: ClinicLabOrder, tenant_id: int) -> dict:
    items = []
    for item in ClinicLabOrderItem.query.filter_by(tenant_id=tenant_id, order_id=row.id).all():
        test = ClinicLabTest.query.filter_by(tenant_id=tenant_id, id=item.test_id).first()
        items.append({"id": item.id, "name": test.name if test else "", "status": item.status, "value": item.value or "", "unit": item.unit or "", "abnormal_flag": item.abnormal_flag or "", "result_at": item.result_at.isoformat() if item.result_at else ""})
    return {"id": row.id, "visit_id": row.visit_id, "doctor_name": _doctor_name(tenant_id, row.doctor_id), "ordered_at": row.ordered_at.isoformat() if row.ordered_at else "", "status": row.status, "notes": row.notes or "", "items": items}


def _radiology_dict(row: ClinicRadiologyOrder, tenant_id: int) -> dict:
    return {"id": row.id, "visit_id": row.visit_id, "doctor_name": _doctor_name(tenant_id, row.doctor_id), "modality": row.modality, "body_part": row.body_part or "", "status": row.status, "report": row.report or "", "impression": row.impression or "", "ordered_at": row.ordered_at.isoformat() if row.ordered_at else "", "reported_at": row.reported_at.isoformat() if row.reported_at else ""}


def clinical_record(tenant_id: int, patient_id: int, section: str = "overview", page: int = 1, per_page: int = 20, actor_id=None, filters=None) -> dict:
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).filter(ClinicPatient.status != "deleted").first()
    if not patient: raise ValueError("المريض غير موجود")
    page, per_page = max(1, page), min(50, max(1, per_page))
    visits_q = ClinicVisit.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
    filters = filters or {}
    if filters.get("doctor_id"):
        visits_q = visits_q.filter_by(doctor_id=int(filters["doctor_id"]))
    if filters.get("specialty_id"):
        visits_q = visits_q.filter_by(specialty_id=int(filters["specialty_id"]))
    if filters.get("date_from"):
        visits_q = visits_q.filter(ClinicVisit.visit_date >= date.fromisoformat(filters["date_from"]))
    if filters.get("date_to"):
        visits_q = visits_q.filter(ClinicVisit.visit_date <= date.fromisoformat(filters["date_to"]))
    matching_visits = {v.id for v in visits_q.all()} if any(filters.get(k) for k in ("doctor_id", "specialty_id", "date_from", "date_to")) else None
    latest_visit = visits_q.order_by(ClinicVisit.visit_date.desc(), ClinicVisit.id.desc()).first()
    current_visit = visits_q.filter(ClinicVisit.status.in_(("open", "in_consultation"))).order_by(ClinicVisit.id.desc()).first()
    base = {"patient": patient_dict(patient), "latest_visit": visit_dict(latest_visit) if latest_visit else None, "current_visit": visit_dict(current_visit) if current_visit else None, "section": section}
    if section == "vitals":
        query = ClinicVital.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        if matching_visits is not None:
            query = query.filter(ClinicVital.visit_id.in_(matching_visits))
        rows = query.order_by(ClinicVital.recorded_at.desc(), ClinicVital.id.desc()).limit(200).all()
        base["items"] = [{"recorded_at": r.recorded_at.isoformat(), "blood_pressure": r.blood_pressure,
                          **{k: float(getattr(r, k)) if getattr(r, k) is not None else None for k in ("weight_kg", "oxygen_sat", "temperature", "blood_glucose", "bmi", "height_cm", "respiratory_rate")}} for r in reversed(rows)]
    elif section == "overview":
        vital = ClinicVital.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicVital.recorded_at.desc()).first()
        diagnoses = ClinicDiagnosis.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicDiagnosis.created_at.desc()).limit(8).all()
        prescriptions = ClinicPrescription.query.filter_by(tenant_id=tenant_id, patient_id=patient_id, status="active").order_by(ClinicPrescription.created_at.desc()).limit(5).all()
        next_followup = visits_q.filter(ClinicVisit.follow_up_date >= date.today()).order_by(ClinicVisit.follow_up_date.asc()).first()
        base.update({"diagnoses": [_diagnosis_dict(x, tenant_id) for x in diagnoses], "prescriptions": [_rx_dict(x, tenant_id) for x in prescriptions], "vitals": ({"blood_pressure": vital.blood_pressure or "", "heart_rate": vital.heart_rate, "temperature": float(vital.temperature) if vital.temperature is not None else None, "weight_kg": float(vital.weight_kg) if vital.weight_kg is not None else None, "height_cm": float(vital.height_cm) if vital.height_cm is not None else None, "oxygen_sat": vital.oxygen_sat, "recorded_at": vital.recorded_at.isoformat() if vital.recorded_at else ""} if vital else None), "next_followup": next_followup.follow_up_date.isoformat() if next_followup and next_followup.follow_up_date else "", "last_lab": _lab_dict(ClinicLabOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicLabOrder.ordered_at.desc()).first(), tenant_id) if ClinicLabOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).first() else None, "last_radiology": _radiology_dict(ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicRadiologyOrder.ordered_at.desc()).first(), tenant_id) if ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).first() else None})
    else:
        mapping = {
            "visits": (visits_q.order_by(ClinicVisit.visit_date.desc(), ClinicVisit.id.desc()), lambda x: visit_dict(x)),
            "diagnoses": (ClinicDiagnosis.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicDiagnosis.created_at.desc()), lambda x: _diagnosis_dict(x, tenant_id)),
            "prescriptions": (ClinicPrescription.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicPrescription.created_at.desc()), lambda x: _rx_dict(x, tenant_id)),
            "labs": (ClinicLabOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicLabOrder.ordered_at.desc()), lambda x: _lab_dict(x, tenant_id)),
            "radiology": (ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicRadiologyOrder.ordered_at.desc()), lambda x: _radiology_dict(x, tenant_id)),
            "attachments": (ClinicAttachment.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).order_by(ClinicAttachment.uploaded_at.desc()), attachment_dict),
        }
        if section == "timeline":
            events = []
            for v in visits_q.order_by(ClinicVisit.visit_date.desc(), ClinicVisit.id.desc()).limit(100).all(): events.append({"type": "visit", "at": (v.started_at or datetime.combine(v.visit_date, datetime.min.time())).isoformat(), "data": visit_dict(v)})
            for x in ClinicDiagnosis.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).limit(100).all(): events.append({"type": "diagnosis", "at": x.created_at.isoformat(), "data": _diagnosis_dict(x, tenant_id)})
            for x in ClinicPrescription.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).limit(100).all(): events.append({"type": "prescription", "at": x.created_at.isoformat(), "data": _rx_dict(x, tenant_id)})
            for x in ClinicLabOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).limit(100).all(): events.append({"type": "lab", "at": x.ordered_at.isoformat(), "data": _lab_dict(x, tenant_id)})
            for x in ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).limit(100).all(): events.append({"type": "radiology", "at": x.ordered_at.isoformat(), "data": _radiology_dict(x, tenant_id)})
            for x in ClinicAttachment.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).limit(100).all(): events.append({"type": "attachment", "at": x.uploaded_at.isoformat(), "data": attachment_dict(x)})
            for x in ClinicFollowUp.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).limit(100).all():
                events.append({"type": "followup", "at": x.created_at.isoformat(), "data": {"id": x.id, "visit_id": x.visit_id, "status": x.status, "due_date": x.due_date.isoformat(), "notes": x.notes or "", "outcome": x.outcome or ""}})
                if x.last_attempt_at:
                    events.append({"type": "followup", "at": x.last_attempt_at.isoformat(), "data": {"id": x.id, "visit_id": x.visit_id, "status": x.status, "notes": x.outcome or x.notes or "", "event": "contact"}})
            for x in ClinicVisitProcedure.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).limit(100).all():
                proc = ClinicProcedure.query.filter_by(tenant_id=tenant_id, id=x.procedure_id).first()
                events.append({"type": "procedure", "at": (x.completed_at or x.started_at or x.performed_at).isoformat(), "data": {"id": x.id, "visit_id": x.visit_id, "status": x.status, "procedure_name": proc.name if proc else "إجراء طبي", "notes": x.notes or ""}})
            events.sort(key=lambda x: x["at"], reverse=True)
            if matching_visits is not None:
                events = [x for x in events if (x["data"].get("id") if x["type"] == "visit" else x["data"].get("visit_id")) in matching_visits]
            if filters.get("event_type"):
                events = [x for x in events if x["type"] == filters["event_type"]]
            total = len(events); base.update({"items": events[(page-1)*per_page:page*per_page], "total": total, "page": page, "pages": max(1, (total+per_page-1)//per_page)})
        elif section in mapping:
            query, serializer = mapping[section]
            if matching_visits is not None and section != "visits":
                model = query.column_descriptions[0]["entity"]
                query = query.filter(model.visit_id.in_(matching_visits))
            total = query.count(); rows = query.offset((page-1)*per_page).limit(per_page).all()
            base.update({"items": [serializer(x) for x in rows], "total": total, "page": page, "pages": max(1, (total+per_page-1)//per_page)})
    _audit(tenant_id, actor_id, "clinical_record", patient_id, "view", f"فتح السجل الطبي للمريض {patient.full_name}")
    return base
