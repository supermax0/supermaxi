"""Internal Medicine longitudinal tools — chronic registry, meds, vital/lab trends.

No automatic diagnosis, risk scoring, dose calculation, or treatment recommendations.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from extensions import db
from modules.clinics.models import (
    ClinicChronicCondition,
    ClinicDiagnosis,
    ClinicFollowUp,
    ClinicLabOrder,
    ClinicLabOrderItem,
    ClinicLabTest,
    ClinicPatient,
    ClinicPatientMedication,
    ClinicPrescription,
    ClinicPrescriptionItem,
    ClinicVisit,
    ClinicVital,
)
from modules.clinics.service import _audit, _parse_date

CONDITION_CODES = frozenset({
    "diabetes", "hypertension", "hyperlipidemia", "thyroid_disease",
    "chronic_kidney_disease", "chronic_liver_disease", "asthma", "copd",
    "heart_disease", "anemia", "obesity", "other",
    # Cardiology-oriented codes (shared registry — Phase G)
    "coronary_artery_disease", "heart_failure", "arrhythmia", "atrial_fibrillation",
    "valvular_disease", "congenital_heart_disease", "peripheral_vascular_disease",
})
CONDITION_AR = {
    "diabetes": "السكري",
    "hypertension": "ارتفاع ضغط الدم",
    "hyperlipidemia": "اضطراب الدهون",
    "thyroid_disease": "أمراض الغدة الدرقية",
    "chronic_kidney_disease": "أمراض الكلى المزمنة",
    "chronic_liver_disease": "أمراض الكبد المزمنة",
    "asthma": "الربو",
    "copd": "COPD",
    "heart_disease": "أمراض القلب",
    "anemia": "فقر الدم",
    "obesity": "السمنة",
    "other": "أخرى",
    "coronary_artery_disease": "أمراض الشرايين التاجية",
    "heart_failure": "قصور القلب",
    "arrhythmia": "اضطراب النظم",
    "atrial_fibrillation": "الرجفان الأذيني",
    "valvular_disease": "أمراض الصمامات",
    "congenital_heart_disease": "أمراض القلب الخلقية",
    "peripheral_vascular_disease": "أمراض الأوعية الطرفية",
}
STATUS_CODES = frozenset({"active", "controlled", "inactive", "resolved", "unknown"})
STATUS_AR = {
    "active": "نشط", "controlled": "متحكم به", "inactive": "غير نشط",
    "resolved": "محلول", "unknown": "غير معروف",
}
SEVERITY_CODES = frozenset({"mild", "moderate", "severe", "unspecified"})
SEVERITY_AR = {"mild": "خفيف", "moderate": "متوسط", "severe": "شديد", "unspecified": "غير محدد"}
MED_STATUSES = frozenset({"active", "stopped", "historical"})
MED_STATUS_AR = {"active": "فعال", "stopped": "موقوف", "historical": "تاريخي"}
SOURCES = frozenset({"clinician", "diagnosis_promote", "prescription", "external", "other"})

RANGE_DAYS = {"30d": 30, "3m": 90, "6m": 180, "1y": 365, "all": None}

# Analyte keyword → labels (match against ClinicLabTest.name/code, case-insensitive)
ANALYTE_ALIASES = {
    "hba1c": ["hba1c", "hb a1c", "a1c", "سكر تراكمي", "هيموغلوبين سكري"],
    "fasting_glucose": ["fasting glucose", "fbs", "fpg", "سكر صائم", "جلوكوز صائم"],
    "creatinine": ["creatinine", "creat", "كرياتينين"],
    "egfr": ["egfr", "gfr", "معدل الترشيح"],
    "tsh": ["tsh", "هرمون محفز الدرقية"],
    "free_t4": ["free t4", "ft4", "t4 حر", "ثيروكسين حر"],
    "ldl": ["ldl", "كوليسترول ضار"],
    "hdl": ["hdl", "كوليسترول نافع"],
    "triglycerides": ["triglyceride", "tg", "دهون ثلاثية", "ثلاثي الغليسريد"],
    "total_cholesterol": ["total cholesterol", "cholesterol", "كوليسترول كلي"],
    "hemoglobin": ["hemoglobin", "hb", "hgb", "هيموغلوبين"],
    "alt": ["alt", "sgpt", "ألانين"],
    "ast": ["ast", "sgot", "أسبارتات"],
    "alp": ["alp", "alkaline", "فوسفاتاز"],
    "bilirubin": ["bilirubin", "بيليروبين"],
    "troponin": ["troponin", "trop", "تروبونين"],
    "bnp": ["bnp", "nt-probnp", "ntprobnp", "pro-bnp", "probnp"],
    "potassium": ["potassium", "k+", "k ", "بوتاسيوم"],
    "sodium": ["sodium", "na+", "na ", "صوديوم"],
}

DISEASE_LAB_KEYS = {
    "diabetes": ["hba1c", "fasting_glucose"],
    "hypertension": ["creatinine", "egfr"],
    "chronic_kidney_disease": ["creatinine", "egfr"],
    "thyroid_disease": ["tsh", "free_t4"],
    "hyperlipidemia": ["ldl", "hdl", "triglycerides", "total_cholesterol"],
    "chronic_liver_disease": ["alt", "ast", "alp", "bilirubin"],
    "anemia": ["hemoglobin"],
    "coronary_artery_disease": ["troponin", "ldl", "hdl", "hemoglobin"],
    "heart_failure": ["bnp", "creatinine", "sodium", "potassium"],
    "heart_disease": ["troponin", "bnp", "ldl"],
    "arrhythmia": ["potassium", "sodium"],
    "atrial_fibrillation": ["potassium", "creatinine"],
}


def _patient(tenant_id: int, patient_id: int) -> ClinicPatient:
    row = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not row:
        raise ValueError("المريض غير موجود")
    return row


def _parse_bp(raw: str | None) -> tuple[int | None, int | None]:
    if not raw:
        return None, None
    m = re.match(r"^\s*(\d{2,3})\s*/\s*(\d{2,3})\s*$", str(raw))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _range_start(range_key: str) -> datetime | None:
    days = RANGE_DAYS.get(range_key or "6m", 180)
    if days is None:
        return None
    return datetime.utcnow() - timedelta(days=days)


def _detail(row: ClinicChronicCondition) -> dict:
    if not row.detail_json:
        return {}
    try:
        return json.loads(row.detail_json) or {}
    except json.JSONDecodeError:
        return {}


def _condition_dict(row: ClinicChronicCondition) -> dict:
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "condition_code": row.condition_code,
        "condition_label_ar": CONDITION_AR.get(row.condition_code, row.condition_name),
        "condition_name": row.condition_name,
        "diagnosis_date": row.diagnosis_date.isoformat() if row.diagnosis_date else None,
        "status": row.status,
        "status_label_ar": STATUS_AR.get(row.status or "", row.status or ""),
        "severity": row.severity,
        "severity_label_ar": SEVERITY_AR.get(row.severity or "", ""),
        "source": row.source,
        "notes": row.notes or "",
        "detail": _detail(row),
        "linked_diagnosis_id": row.linked_diagnosis_id,
        "created_by_doctor_id": row.created_by_doctor_id,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_chronic_conditions(tenant_id: int, patient_id: int, *, include_archived=False) -> dict:
    _patient(tenant_id, patient_id)
    q = ClinicChronicCondition.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
    if not include_archived:
        q = q.filter(ClinicChronicCondition.archived_at.is_(None))
    rows = q.order_by(ClinicChronicCondition.updated_at.desc(), ClinicChronicCondition.id.desc()).all()
    active = [r for r in rows if r.status in ("active", "controlled") and not r.archived_at]
    return {
        "patient_id": patient_id,
        "items": [_condition_dict(r) for r in rows],
        "active": [_condition_dict(r) for r in active],
        "catalog": {
            "codes": [{"code": k, "label_ar": v} for k, v in CONDITION_AR.items()],
            "statuses": [{"code": k, "label_ar": v} for k, v in STATUS_AR.items()],
            "severities": [{"code": k, "label_ar": v} for k, v in SEVERITY_AR.items()],
        },
    }


def create_chronic_condition(tenant_id: int, patient_id: int, payload: dict, actor_id=None, doctor_id=None) -> dict:
    _patient(tenant_id, patient_id)
    code = str(payload.get("condition_code") or "other").strip().lower()
    if code not in CONDITION_CODES:
        code = "other"
    name = str(payload.get("condition_name") or CONDITION_AR.get(code, "أخرى")).strip()
    if not name:
        raise ValueError("اسم الحالة مطلوب")
    status = str(payload.get("status") or "active").strip().lower()
    if status not in STATUS_CODES:
        raise ValueError("حالة المرض غير صالحة")
    severity = str(payload.get("severity") or "").strip().lower() or None
    if severity and severity not in SEVERITY_CODES:
        raise ValueError("شدة المرض غير صالحة")
    source = str(payload.get("source") or "clinician").strip().lower()
    if source not in SOURCES:
        source = "clinician"
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
    diag_id = payload.get("linked_diagnosis_id")
    diag_id = int(diag_id) if diag_id not in (None, "", 0, "0") else None
    if diag_id:
        if not ClinicDiagnosis.query.filter_by(tenant_id=tenant_id, id=diag_id).first():
            raise ValueError("التشخيص غير موجود")
    row = ClinicChronicCondition(
        tenant_id=tenant_id,
        patient_id=patient_id,
        condition_code=code,
        condition_name=name,
        diagnosis_date=_parse_date(payload.get("diagnosis_date"), "تاريخ التشخيص")
        if payload.get("diagnosis_date") not in (None, "") else None,
        status=status,
        severity=severity,
        source=source,
        notes=str(payload.get("notes") or "").strip() or None,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        linked_diagnosis_id=diag_id,
        created_by_doctor_id=int(doctor_id) if doctor_id not in (None, "", 0, "0") else None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "chronic_condition", row.id, "create",
           f"إضافة مرض مزمن: {name}", meta=_condition_dict(row))
    return list_chronic_conditions(tenant_id, patient_id)


def update_chronic_condition(tenant_id: int, condition_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicChronicCondition.query.filter_by(tenant_id=tenant_id, id=condition_id).first()
    if not row or row.archived_at:
        raise ValueError("المرض المزمن غير موجود")
    old = _condition_dict(row)
    if "condition_name" in payload:
        name = str(payload.get("condition_name") or "").strip()
        if not name:
            raise ValueError("اسم الحالة مطلوب")
        row.condition_name = name
    if "condition_code" in payload:
        code = str(payload.get("condition_code") or "other").strip().lower()
        row.condition_code = code if code in CONDITION_CODES else "other"
    if "status" in payload:
        status = str(payload.get("status") or "").strip().lower()
        if status not in STATUS_CODES:
            raise ValueError("حالة المرض غير صالحة")
        row.status = status
    if "severity" in payload:
        severity = str(payload.get("severity") or "").strip().lower() or None
        if severity and severity not in SEVERITY_CODES:
            raise ValueError("شدة المرض غير صالحة")
        row.severity = severity
    if "diagnosis_date" in payload:
        raw = payload.get("diagnosis_date")
        row.diagnosis_date = _parse_date(raw, "تاريخ التشخيص") if raw not in (None, "") else None
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "").strip() or None
    if "detail" in payload and isinstance(payload.get("detail"), dict):
        merged = _detail(row)
        merged.update(payload["detail"])
        row.detail_json = json.dumps(merged, ensure_ascii=False)
    action = "update"
    if payload.get("archive") in (True, "true", 1, "1"):
        row.archived_at = datetime.utcnow()
        action = "archive"
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    if old.get("status") != row.status:
        action = "status_change" if action == "update" else action
    _audit(tenant_id, actor_id, "chronic_condition", row.id, action,
           f"{action} مرض مزمن #{row.id}", meta={"old": old, "new": _condition_dict(row)})
    return list_chronic_conditions(tenant_id, row.patient_id)


def promote_diagnosis_to_chronic(tenant_id: int, patient_id: int, diagnosis_id: int, payload: dict, actor_id=None, doctor_id=None) -> dict:
    diag = ClinicDiagnosis.query.filter_by(tenant_id=tenant_id, id=diagnosis_id).first()
    if not diag:
        raise ValueError("التشخيص غير موجود")
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=diag.visit_id).first() if diag.visit_id else None
    if visit and visit.patient_id != patient_id:
        raise ValueError("التشخيص لا يخص هذا المريض")
    body = {
        "condition_code": payload.get("condition_code") or "other",
        "condition_name": payload.get("condition_name") or diag.title or diag.code or "مرض مزمن",
        "diagnosis_date": payload.get("diagnosis_date") or (visit.visit_date.isoformat() if visit and visit.visit_date else None),
        "status": payload.get("status") or "active",
        "notes": payload.get("notes") or "",
        "source": "diagnosis_promote",
        "linked_diagnosis_id": diagnosis_id,
    }
    result = create_chronic_condition(tenant_id, patient_id, body, actor_id, doctor_id=doctor_id or (visit.doctor_id if visit else None))
    _audit(tenant_id, actor_id, "chronic_condition", diagnosis_id, "promote_diagnosis",
           f"ترقية تشخيص #{diagnosis_id} إلى مرض مزمن", meta=body)
    return result


def _med_dict(row: ClinicPatientMedication) -> dict:
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "drug_name": row.drug_name,
        "dose_text": row.dose_text or "",
        "frequency": row.frequency or "",
        "route": row.route or "",
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "status": row.status,
        "status_label_ar": MED_STATUS_AR.get(row.status or "", row.status or ""),
        "source": row.source,
        "notes": row.notes or "",
        "prescription_item_id": row.prescription_item_id,
    }


def list_patient_medications(tenant_id: int, patient_id: int) -> dict:
    _patient(tenant_id, patient_id)
    rows = (
        ClinicPatientMedication.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(ClinicPatientMedication.archived_at.is_(None))
        .order_by(ClinicPatientMedication.status.asc(), ClinicPatientMedication.updated_at.desc())
        .all()
    )
    # Also surface recent prescription items as history hints (not auto-promoted).
    rx_items = (
        db.session.query(ClinicPrescriptionItem, ClinicPrescription)
        .join(ClinicPrescription, ClinicPrescriptionItem.prescription_id == ClinicPrescription.id)
        .join(ClinicVisit, ClinicPrescription.visit_id == ClinicVisit.id)
        .filter(ClinicVisit.tenant_id == tenant_id, ClinicVisit.patient_id == patient_id)
        .order_by(ClinicPrescription.created_at.desc())
        .limit(40)
        .all()
    )
    history = [
        {
            "medicine_name": item.medicine_name,
            "dosage": item.dosage or "",
            "frequency": item.frequency or "",
            "duration": item.duration or "",
            "visit_id": rx.visit_id,
            "at": rx.created_at.isoformat() if rx.created_at else None,
        }
        for item, rx in rx_items
    ]
    return {
        "patient_id": patient_id,
        "items": [_med_dict(r) for r in rows],
        "active": [_med_dict(r) for r in rows if r.status == "active"],
        "prescription_history": history,
        "catalog": {"statuses": [{"code": k, "label_ar": v} for k, v in MED_STATUS_AR.items()]},
    }


def upsert_patient_medication(tenant_id: int, patient_id: int, payload: dict, actor_id=None, doctor_id=None, medication_id=None) -> dict:
    _patient(tenant_id, patient_id)
    name = str(payload.get("drug_name") or "").strip()
    if not name and not medication_id:
        raise ValueError("اسم الدواء مطلوب")
    if medication_id:
        row = ClinicPatientMedication.query.filter_by(tenant_id=tenant_id, id=medication_id, patient_id=patient_id).first()
        if not row or row.archived_at:
            raise ValueError("الدواء غير موجود")
        old = _med_dict(row)
        action = "update"
    else:
        row = ClinicPatientMedication(
            tenant_id=tenant_id,
            patient_id=patient_id,
            drug_name=name,
            created_by_doctor_id=int(doctor_id) if doctor_id not in (None, "", 0, "0") else None,
            created_by=actor_id,
        )
        db.session.add(row)
        old = None
        action = "create"
    if "drug_name" in payload and name:
        row.drug_name = name
    for key in ("dose_text", "frequency", "route", "notes"):
        if key in payload:
            setattr(row, key, str(payload.get(key) or "").strip() or None)
    if "status" in payload:
        status = str(payload.get("status") or "active").strip().lower()
        if status not in MED_STATUSES:
            raise ValueError("حالة الدواء غير صالحة")
        row.status = status
    if "start_date" in payload:
        raw = payload.get("start_date")
        row.start_date = _parse_date(raw, "تاريخ البدء") if raw not in (None, "") else None
    if "end_date" in payload:
        raw = payload.get("end_date")
        row.end_date = _parse_date(raw, "تاريخ الإيقاف") if raw not in (None, "") else None
    if payload.get("archive") in (True, "true", 1, "1"):
        row.archived_at = datetime.utcnow()
        action = "archive"
    row.source = str(payload.get("source") or row.source or "clinician").strip().lower() or "clinician"
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    db.session.flush()
    _audit(tenant_id, actor_id, "patient_medication", row.id, action,
           f"{action} دواء مريض", meta={"old": old, "new": _med_dict(row)})
    return list_patient_medications(tenant_id, patient_id)


def get_vital_trends(tenant_id: int, patient_id: int, range_key: str = "6m") -> dict:
    _patient(tenant_id, patient_id)
    q = ClinicVital.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
    start = _range_start(range_key)
    if start:
        q = q.filter(ClinicVital.recorded_at >= start)
    rows = q.order_by(ClinicVital.recorded_at.asc()).limit(500).all()
    series = {
        "systolic": [], "diastolic": [], "weight_kg": [], "bmi": [],
        "blood_glucose": [], "heart_rate": [], "oxygen_sat": [], "respiratory_rate": [],
    }
    latest = None
    for r in rows:
        at = r.recorded_at.isoformat() if r.recorded_at else None
        sys, dia = _parse_bp(r.blood_pressure)
        point = {"at": at, "visit_id": r.visit_id}
        if sys is not None:
            series["systolic"].append({**point, "value": sys})
        if dia is not None:
            series["diastolic"].append({**point, "value": dia})
        if r.weight_kg is not None:
            series["weight_kg"].append({**point, "value": float(r.weight_kg)})
        if r.bmi is not None:
            series["bmi"].append({**point, "value": float(r.bmi)})
        if r.blood_glucose is not None:
            series["blood_glucose"].append({**point, "value": float(r.blood_glucose)})
        if r.heart_rate is not None:
            series["heart_rate"].append({**point, "value": r.heart_rate})
        if r.oxygen_sat is not None:
            series["oxygen_sat"].append({**point, "value": r.oxygen_sat})
        if r.respiratory_rate is not None:
            series["respiratory_rate"].append({**point, "value": r.respiratory_rate})
        latest = {
            "recorded_at": at,
            "blood_pressure": r.blood_pressure,
            "systolic": sys,
            "diastolic": dia,
            "weight_kg": float(r.weight_kg) if r.weight_kg is not None else None,
            "bmi": float(r.bmi) if r.bmi is not None else None,
            "blood_glucose": float(r.blood_glucose) if r.blood_glucose is not None else None,
            "heart_rate": r.heart_rate,
            "oxygen_sat": r.oxygen_sat,
            "respiratory_rate": r.respiratory_rate,
        }
    return {
        "patient_id": patient_id,
        "range": range_key,
        "latest": latest,
        "series": series,
        "auto_labels": False,
    }


def _match_analyte(name: str, code: str | None) -> str | None:
    blob = f"{name or ''} {code or ''}".lower()
    for key, aliases in ANALYTE_ALIASES.items():
        if any(a.lower() in blob for a in aliases):
            return key
    return None


def get_lab_trends(tenant_id: int, patient_id: int, analytes: list[str] | None = None, range_key: str = "1y") -> dict:
    """Reusable longitudinal lab series — no unit conversion across incompatible units."""
    _patient(tenant_id, patient_id)
    wanted = set(analytes or list(ANALYTE_ALIASES.keys()))
    start = _range_start(range_key)
    orders_q = ClinicLabOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
    if start:
        orders_q = orders_q.filter(ClinicLabOrder.ordered_at >= start)
    orders = orders_q.order_by(ClinicLabOrder.ordered_at.asc()).limit(200).all()
    if not orders:
        return {"patient_id": patient_id, "range": range_key, "series": {}, "latest": {}}
    order_ids = [o.id for o in orders]
    items = ClinicLabOrderItem.query.filter(
        ClinicLabOrderItem.tenant_id == tenant_id,
        ClinicLabOrderItem.order_id.in_(order_ids),
    ).all()
    tests = {
        t.id: t
        for t in ClinicLabTest.query.filter(
            ClinicLabTest.tenant_id == tenant_id,
            ClinicLabTest.id.in_({i.test_id for i in items} or {-1}),
        ).all()
    }
    order_at = {o.id: o.ordered_at for o in orders}
    series: dict[str, dict[str, list]] = {}
    latest: dict[str, dict] = {}
    for item in items:
        test = tests.get(item.test_id)
        if not test:
            continue
        key = _match_analyte(test.name, test.code)
        if not key or key not in wanted:
            continue
        try:
            value = float(str(item.value).replace(",", "."))
        except (TypeError, ValueError):
            continue
        unit = (item.unit or "").strip() or "unknown"
        bucket = series.setdefault(key, {})
        unit_series = bucket.setdefault(unit, [])
        at = order_at.get(item.order_id)
        point = {
            "at": at.isoformat() if at else None,
            "value": value,
            "unit": unit,
            "reference_range": item.reference_range or "",
            "flag": item.abnormal_flag or "",
            "test_name": test.name,
            "order_id": item.order_id,
        }
        unit_series.append(point)
        prev = latest.get(key)
        if not prev or (at and (not prev.get("_at") or at >= prev["_at"])):
            latest[key] = {**point, "_at": at}
    for key in latest:
        latest[key].pop("_at", None)
    return {
        "patient_id": patient_id,
        "range": range_key,
        "series": series,
        "latest": latest,
        "unit_conversion": False,
        "auto_flags": False,
    }


def compare_visits(tenant_id: int, patient_id: int, visit_ids: list[int]) -> dict:
    _patient(tenant_id, patient_id)
    ids = [int(v) for v in visit_ids if v not in (None, "", 0, "0")][:4]
    if len(ids) < 2:
        raise ValueError("اختر زيارتين على الأقل للمقارنة")
    visits = (
        ClinicVisit.query.filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.patient_id == patient_id,
            ClinicVisit.id.in_(ids),
        )
        .order_by(ClinicVisit.visit_date.asc(), ClinicVisit.id.asc())
        .all()
    )
    if len(visits) < 2:
        raise ValueError("الزيارات غير متاحة")
    visit_map = {v.id: v for v in visits}
    vitals = ClinicVital.query.filter(
        ClinicVital.tenant_id == tenant_id, ClinicVital.visit_id.in_(ids)
    ).all()
    vitals_by = {}
    for v in vitals:
        vitals_by.setdefault(v.visit_id, v)
    diags = ClinicDiagnosis.query.filter(
        ClinicDiagnosis.tenant_id == tenant_id, ClinicDiagnosis.visit_id.in_(ids)
    ).all()
    diags_by: dict[int, list] = {}
    for d in diags:
        diags_by.setdefault(d.visit_id, []).append({"code": d.code or "", "title": d.title or ""})
    rxs = ClinicPrescription.query.filter(
        ClinicPrescription.tenant_id == tenant_id, ClinicPrescription.visit_id.in_(ids)
    ).all()
    rx_ids = [r.id for r in rxs]
    items = ClinicPrescriptionItem.query.filter(
        ClinicPrescriptionItem.prescription_id.in_(rx_ids or {-1})
    ).all() if rx_ids else []
    items_by_rx: dict[int, list] = {}
    for i in items:
        items_by_rx.setdefault(i.prescription_id, []).append(
            {"medicine_name": i.medicine_name, "dosage": i.dosage or "", "frequency": i.frequency or ""}
        )
    rx_by_visit = {r.visit_id: items_by_rx.get(r.id, []) for r in rxs}

    cards = []
    for vid in ids:
        v = visit_map.get(vid)
        if not v:
            continue
        vital = vitals_by.get(vid)
        sys, dia = _parse_bp(vital.blood_pressure) if vital else (None, None)
        cards.append({
            "visit_id": vid,
            "visit_date": v.visit_date.isoformat() if v.visit_date else None,
            "doctor_id": v.doctor_id,
            "chief_complaint": v.chief_complaint or "",
            "clinical_notes": (v.clinical_notes or "")[:500],
            "status": v.status,
            "follow_up_date": v.follow_up_date.isoformat() if v.follow_up_date else None,
            "vitals": {
                "blood_pressure": vital.blood_pressure if vital else None,
                "systolic": sys,
                "diastolic": dia,
                "weight_kg": float(vital.weight_kg) if vital and vital.weight_kg is not None else None,
                "bmi": float(vital.bmi) if vital and vital.bmi is not None else None,
                "blood_glucose": float(vital.blood_glucose) if vital and vital.blood_glucose is not None else None,
                "heart_rate": vital.heart_rate if vital else None,
            } if vital else None,
            "diagnoses": diags_by.get(vid, []),
            "medications": rx_by_visit.get(vid, []),
        })
    return {"patient_id": patient_id, "visits": cards}


def _disease_packs(conditions: list[dict], labs: dict, vitals: dict) -> list[dict]:
    packs = []
    codes = {c["condition_code"] for c in conditions if c.get("status") in ("active", "controlled")}
    lab_latest = labs.get("latest") or {}
    vital_latest = vitals.get("latest") or {}
    for code in codes:
        keys = DISEASE_LAB_KEYS.get(code) or []
        packs.append({
            "condition_code": code,
            "label_ar": CONDITION_AR.get(code, code),
            "related_labs": {k: lab_latest[k] for k in keys if k in lab_latest},
            "related_vitals": {
                "blood_pressure": vital_latest.get("blood_pressure"),
                "weight_kg": vital_latest.get("weight_kg"),
                "bmi": vital_latest.get("bmi"),
                "blood_glucose": vital_latest.get("blood_glucose"),
                "oxygen_sat": vital_latest.get("oxygen_sat"),
                "respiratory_rate": vital_latest.get("respiratory_rate"),
            },
            "auto_scoring": False,
        })
    return packs


def get_internal_medicine_context(tenant_id: int, patient_id: int, visit_id=None) -> dict:
    patient = _patient(tenant_id, patient_id)
    conditions = list_chronic_conditions(tenant_id, patient_id)
    meds = list_patient_medications(tenant_id, patient_id)
    vitals = get_vital_trends(tenant_id, patient_id, "6m")
    # Summary labs only (not full history)
    lab_keys = set()
    for c in conditions.get("active") or []:
        lab_keys.update(DISEASE_LAB_KEYS.get(c["condition_code"]) or [])
    if not lab_keys:
        lab_keys = {"hba1c", "creatinine", "tsh", "ldl", "hemoglobin"}
    labs = get_lab_trends(tenant_id, patient_id, analytes=sorted(lab_keys), range_key="1y")

    visits = (
        ClinicVisit.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicVisit.visit_date.desc(), ClinicVisit.id.desc())
        .limit(12)
        .all()
    )
    recent_visits = [
        {
            "id": v.id,
            "visit_date": v.visit_date.isoformat() if v.visit_date else None,
            "doctor_id": v.doctor_id,
            "chief_complaint": v.chief_complaint or "",
            "status": v.status,
        }
        for v in visits
    ]
    fus = (
        ClinicFollowUp.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicFollowUp.due_date.asc())
        .limit(10)
        .all()
    )
    next_fu = None
    for f in fus:
        if f.status in ("due", "pending", "scheduled", "open"):
            next_fu = {"id": f.id, "due_date": f.due_date.isoformat() if f.due_date else None, "status": f.status}
            break

    latest = vitals.get("latest") or {}
    summary = {
        "active_conditions": conditions.get("active") or [],
        "current_medications": meds.get("active") or [],
        "latest_bp": latest.get("blood_pressure"),
        "latest_weight": latest.get("weight_kg"),
        "latest_bmi": latest.get("bmi"),
        "latest_glucose": latest.get("blood_glucose"),
        "next_followup": next_fu,
        "allergies": patient.allergies or "",
    }
    alerts = []
    if not latest:
        alerts.append({"code": "no_recent_vitals", "message": "لا توجد علامات حيوية مسجّلة حديثاً"})
    if not next_fu:
        alerts.append({"code": "no_followup", "message": "لا توجد متابعة مجدولة"})
    for c in conditions.get("active") or []:
        if not c.get("diagnosis_date"):
            alerts.append({
                "code": "missing_diagnosis_date",
                "message": f"تاريخ التشخيص غير محدد لـ {c.get('condition_name') or c.get('condition_label_ar')}",
            })
            break
    # Drop empty summary noise
    compact = {k: v for k, v in summary.items() if v not in (None, "", [], {})}

    return {
        "patient_id": patient_id,
        "visit_id": visit_id,
        "summary": compact,
        "alerts": alerts,
        "conditions": conditions,
        "medications": meds,
        "vital_trends_summary": {
            "latest": latest,
            "counts": {k: len(v) for k, v in (vitals.get("series") or {}).items()},
        },
        "important_recent_labs": labs.get("latest") or {},
        "disease_packs": _disease_packs(conditions.get("active") or [], labs, vitals),
        "recent_visits": recent_visits,
        "next_followup": next_fu,
        "permissions": {"can_edit": True},
        "risk_scoring_available": False,
        "auto_recommendations": False,
        "catalog": conditions.get("catalog"),
    }


def get_visit_internal_medicine_context(tenant_id: int, visit_id: int) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    return get_internal_medicine_context(tenant_id, visit.patient_id, visit_id=visit_id)
