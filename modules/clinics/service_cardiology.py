"""Cardiology clinical tools — profile, ECG, Echo on Phase F longitudinal foundation.

No automatic ECG/Echo interpretation, risk scoring, or medication recommendations.
"""
from __future__ import annotations

import json
from datetime import datetime

from extensions import db
from modules.clinics.models import (
    ClinicAttachment,
    ClinicCardiologyECG,
    ClinicCardiologyEcho,
    ClinicCardiologyProfile,
    ClinicPatient,
    ClinicRadiologyOrder,
    ClinicVisit,
)
from modules.clinics.service import _audit, _parse_date
from modules.clinics.service_internal_medicine import (
    CONDITION_AR,
    compare_visits,
    get_lab_trends,
    get_vital_trends,
    list_chronic_conditions,
    list_patient_medications,
)

SMOKING = frozenset({"never", "former", "current", "unknown"})
SMOKING_AR = {
    "never": "غير مدخن",
    "former": "سابق",
    "current": "حالياً",
    "unknown": "غير معروف",
}
DEVICE_TYPES = frozenset({"none", "pacemaker", "icd", "crt", "other"})
DEVICE_AR = {
    "none": "لا يوجد",
    "pacemaker": "منظم ضربات",
    "icd": "ICD",
    "crt": "CRT",
    "other": "أخرى",
}

CARDIAC_CONDITION_CODES = frozenset({
    "coronary_artery_disease", "heart_failure", "arrhythmia", "atrial_fibrillation",
    "valvular_disease", "congenital_heart_disease", "peripheral_vascular_disease",
    "hypertension", "hyperlipidemia", "heart_disease", "diabetes",
    "chronic_kidney_disease", "obesity",
})

CARDIO_LAB_KEYS = [
    "troponin", "bnp", "ldl", "hdl", "triglycerides", "creatinine",
    "potassium", "sodium", "hemoglobin", "hba1c",
]


def _patient(tenant_id: int, patient_id: int) -> ClinicPatient:
    row = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not row:
        raise ValueError("المريض غير موجود")
    return row


def _visit(tenant_id: int, visit_id: int | None) -> ClinicVisit | None:
    if not visit_id:
        return None
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=int(visit_id)).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    return visit


def _assert_open_visit(visit: ClinicVisit | None):
    if visit and visit.status == "completed":
        raise ValueError("الزيارة مكتملة — التعديل غير متاح في المسار العادي")


def _attachment(tenant_id: int, patient_id: int, attachment_id) -> int | None:
    if attachment_id in (None, "", 0, "0"):
        return None
    row = ClinicAttachment.query.filter_by(
        tenant_id=tenant_id, id=int(attachment_id), patient_id=patient_id
    ).first()
    if not row:
        raise ValueError("المرفق غير موجود أو لا يخص هذا المريض")
    return row.id


def _profile_dict(row: ClinicCardiologyProfile | None, patient_id: int) -> dict:
    if not row:
        return {
            "exists": False,
            "patient_id": patient_id,
            "family_cardiac_history": "",
            "smoking_status": None,
            "smoking_status_label_ar": "",
            "smoking_notes": "",
            "previous_mi_date": None,
            "previous_pci_notes": "",
            "previous_cabg_notes": "",
            "device_type": None,
            "device_type_label_ar": "",
            "device_implant_date": None,
            "device_history": "",
            "other_cardiac_history": "",
        }
    return {
        "exists": True,
        "id": row.id,
        "patient_id": row.patient_id,
        "family_cardiac_history": row.family_cardiac_history or "",
        "smoking_status": row.smoking_status,
        "smoking_status_label_ar": SMOKING_AR.get(row.smoking_status or "", ""),
        "smoking_notes": row.smoking_notes or "",
        "previous_mi_date": row.previous_mi_date.isoformat() if row.previous_mi_date else None,
        "previous_pci_notes": row.previous_pci_notes or "",
        "previous_cabg_notes": row.previous_cabg_notes or "",
        "device_type": row.device_type,
        "device_type_label_ar": DEVICE_AR.get(row.device_type or "", ""),
        "device_implant_date": row.device_implant_date.isoformat() if row.device_implant_date else None,
        "device_history": row.device_history or "",
        "other_cardiac_history": row.other_cardiac_history or "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_cardiology_profile(tenant_id: int, patient_id: int) -> dict:
    _patient(tenant_id, patient_id)
    row = ClinicCardiologyProfile.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).first()
    return _profile_dict(row, patient_id)


def upsert_cardiology_profile(tenant_id: int, patient_id: int, payload: dict, actor_id=None) -> dict:
    _patient(tenant_id, patient_id)
    row = ClinicCardiologyProfile.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).first()
    created = False
    if not row:
        row = ClinicCardiologyProfile(tenant_id=tenant_id, patient_id=patient_id, created_by=actor_id)
        db.session.add(row)
        created = True
    old = _profile_dict(row if not created else None, patient_id)
    if "family_cardiac_history" in payload:
        row.family_cardiac_history = str(payload.get("family_cardiac_history") or "").strip() or None
    if "smoking_status" in payload:
        status = str(payload.get("smoking_status") or "").strip().lower() or None
        if status and status not in SMOKING:
            raise ValueError("حالة التدخين غير صالحة")
        row.smoking_status = status
    if "smoking_notes" in payload:
        row.smoking_notes = str(payload.get("smoking_notes") or "").strip() or None
    if "previous_mi_date" in payload:
        raw = payload.get("previous_mi_date")
        row.previous_mi_date = _parse_date(raw, "تاريخ احتشاء سابق") if raw not in (None, "") else None
    for key in ("previous_pci_notes", "previous_cabg_notes", "device_history", "other_cardiac_history"):
        if key in payload:
            setattr(row, key, str(payload.get(key) or "").strip() or None)
    if "device_type" in payload:
        dtype = str(payload.get("device_type") or "").strip().lower() or None
        if dtype and dtype not in DEVICE_TYPES:
            raise ValueError("نوع الجهاز غير صالح")
        row.device_type = dtype
    if "device_implant_date" in payload:
        raw = payload.get("device_implant_date")
        row.device_implant_date = _parse_date(raw, "تاريخ الزرع") if raw not in (None, "") else None
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    db.session.flush()
    new = _profile_dict(row, patient_id)
    _audit(
        tenant_id, actor_id, "cardiology_profile", row.id,
        "create" if created else "update",
        "ملف القلب",
        meta={"old": old, "new": new},
    )
    return new


def _ecg_dict(row: ClinicCardiologyECG) -> dict:
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "visit_id": row.visit_id,
        "doctor_id": row.doctor_id,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        "heart_rate": row.heart_rate,
        "rhythm": row.rhythm or "",
        "axis": row.axis or "",
        "pr_interval_ms": row.pr_interval_ms,
        "qrs_duration_ms": row.qrs_duration_ms,
        "qtc_ms": row.qtc_ms,
        "st_t_notes": row.st_t_notes or "",
        "interpretation": row.interpretation or "",
        "notes": row.notes or "",
        "attachment_id": row.attachment_id,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "auto_interpretation": False,
    }


def list_ecgs(tenant_id: int, patient_id: int, *, limit=20) -> dict:
    _patient(tenant_id, patient_id)
    rows = (
        ClinicCardiologyECG.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(ClinicCardiologyECG.archived_at.is_(None))
        .order_by(ClinicCardiologyECG.recorded_at.desc(), ClinicCardiologyECG.id.desc())
        .limit(limit)
        .all()
    )
    return {"patient_id": patient_id, "items": [_ecg_dict(r) for r in rows]}


def create_ecg(tenant_id: int, patient_id: int, payload: dict, actor_id=None, doctor_id=None) -> dict:
    _patient(tenant_id, patient_id)
    visit = _visit(tenant_id, payload.get("visit_id"))
    if visit and visit.patient_id != patient_id:
        raise ValueError("الزيارة لا تخص هذا المريض")
    _assert_open_visit(visit)
    row = ClinicCardiologyECG(
        tenant_id=tenant_id,
        patient_id=patient_id,
        visit_id=visit.id if visit else None,
        doctor_id=int(doctor_id) if doctor_id not in (None, "", 0, "0") else (visit.doctor_id if visit else None),
        recorded_at=datetime.utcnow(),
        heart_rate=int(payload["heart_rate"]) if payload.get("heart_rate") not in (None, "") else None,
        rhythm=str(payload.get("rhythm") or "").strip() or None,
        axis=str(payload.get("axis") or "").strip() or None,
        pr_interval_ms=int(payload["pr_interval_ms"]) if payload.get("pr_interval_ms") not in (None, "") else None,
        qrs_duration_ms=int(payload["qrs_duration_ms"]) if payload.get("qrs_duration_ms") not in (None, "") else None,
        qtc_ms=int(payload["qtc_ms"]) if payload.get("qtc_ms") not in (None, "") else None,
        st_t_notes=str(payload.get("st_t_notes") or "").strip() or None,
        interpretation=str(payload.get("interpretation") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip() or None,
        attachment_id=_attachment(tenant_id, patient_id, payload.get("attachment_id")),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "cardiology_ecg", row.id, "create", "تسجيل تخطيط قلب", meta=_ecg_dict(row))
    return list_ecgs(tenant_id, patient_id)


def update_ecg(tenant_id: int, ecg_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicCardiologyECG.query.filter_by(tenant_id=tenant_id, id=ecg_id).first()
    if not row or row.archived_at:
        raise ValueError("تخطيط القلب غير موجود")
    visit = _visit(tenant_id, row.visit_id) if row.visit_id else None
    _assert_open_visit(visit)
    old = _ecg_dict(row)
    for key in ("rhythm", "axis", "st_t_notes", "interpretation", "notes"):
        if key in payload:
            setattr(row, key, str(payload.get(key) or "").strip() or None)
    for key in ("heart_rate", "pr_interval_ms", "qrs_duration_ms", "qtc_ms"):
        if key in payload:
            setattr(row, key, int(payload[key]) if payload.get(key) not in (None, "") else None)
    if "attachment_id" in payload:
        row.attachment_id = _attachment(tenant_id, row.patient_id, payload.get("attachment_id"))
    action = "update"
    if payload.get("archive") in (True, "true", 1, "1"):
        row.archived_at = datetime.utcnow()
        action = "archive"
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    _audit(tenant_id, actor_id, "cardiology_ecg", row.id, action, f"{action} ECG", meta={"old": old, "new": _ecg_dict(row)})
    return list_ecgs(tenant_id, row.patient_id)


def _echo_dict(row: ClinicCardiologyEcho) -> dict:
    extra = {}
    if row.other_measurements_json:
        try:
            extra = json.loads(row.other_measurements_json) or {}
        except json.JSONDecodeError:
            extra = {}
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "visit_id": row.visit_id,
        "doctor_id": row.doctor_id,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        "lvef_percent": float(row.lvef_percent) if row.lvef_percent is not None else None,
        "lv_notes": row.lv_notes or "",
        "rv_notes": row.rv_notes or "",
        "la_notes": row.la_notes or "",
        "ra_notes": row.ra_notes or "",
        "valve_notes": row.valve_notes or "",
        "pericardium_notes": row.pericardium_notes or "",
        "other_measurements": extra,
        "impression": row.impression or "",
        "notes": row.notes or "",
        "radiology_order_id": row.radiology_order_id,
        "attachment_id": row.attachment_id,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "auto_classification": False,
    }


def list_echos(tenant_id: int, patient_id: int, *, limit=20) -> dict:
    _patient(tenant_id, patient_id)
    rows = (
        ClinicCardiologyEcho.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(ClinicCardiologyEcho.archived_at.is_(None))
        .order_by(ClinicCardiologyEcho.recorded_at.desc(), ClinicCardiologyEcho.id.desc())
        .limit(limit)
        .all()
    )
    return {"patient_id": patient_id, "items": [_echo_dict(r) for r in rows]}


def create_echo(tenant_id: int, patient_id: int, payload: dict, actor_id=None, doctor_id=None) -> dict:
    _patient(tenant_id, patient_id)
    visit = _visit(tenant_id, payload.get("visit_id"))
    if visit and visit.patient_id != patient_id:
        raise ValueError("الزيارة لا تخص هذا المريض")
    _assert_open_visit(visit)
    rad_id = payload.get("radiology_order_id")
    if rad_id not in (None, "", 0, "0"):
        rad = ClinicRadiologyOrder.query.filter_by(
            tenant_id=tenant_id, id=int(rad_id), patient_id=patient_id
        ).first()
        if not rad:
            raise ValueError("طلب الأشعة غير موجود")
        rad_id = rad.id
    else:
        rad_id = None
    lvef = payload.get("lvef_percent")
    lvef_val = float(lvef) if lvef not in (None, "") else None
    if lvef_val is not None and (lvef_val < 0 or lvef_val > 100):
        raise ValueError("قيمة الكسر القذفي غير صالحة")
    extra = payload.get("other_measurements") if isinstance(payload.get("other_measurements"), dict) else {}
    row = ClinicCardiologyEcho(
        tenant_id=tenant_id,
        patient_id=patient_id,
        visit_id=visit.id if visit else None,
        doctor_id=int(doctor_id) if doctor_id not in (None, "", 0, "0") else (visit.doctor_id if visit else None),
        recorded_at=datetime.utcnow(),
        lvef_percent=lvef_val,
        lv_notes=str(payload.get("lv_notes") or "").strip() or None,
        rv_notes=str(payload.get("rv_notes") or "").strip() or None,
        la_notes=str(payload.get("la_notes") or "").strip() or None,
        ra_notes=str(payload.get("ra_notes") or "").strip() or None,
        valve_notes=str(payload.get("valve_notes") or "").strip() or None,
        pericardium_notes=str(payload.get("pericardium_notes") or "").strip() or None,
        other_measurements_json=json.dumps(extra, ensure_ascii=False) if extra else None,
        impression=str(payload.get("impression") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip() or None,
        radiology_order_id=rad_id,
        attachment_id=_attachment(tenant_id, patient_id, payload.get("attachment_id")),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "cardiology_echo", row.id, "create", "تسجيل إيكو", meta=_echo_dict(row))
    return list_echos(tenant_id, patient_id)


def update_echo(tenant_id: int, echo_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicCardiologyEcho.query.filter_by(tenant_id=tenant_id, id=echo_id).first()
    if not row or row.archived_at:
        raise ValueError("سجل الإيكو غير موجود")
    visit = _visit(tenant_id, row.visit_id) if row.visit_id else None
    _assert_open_visit(visit)
    old = _echo_dict(row)
    for key in ("lv_notes", "rv_notes", "la_notes", "ra_notes", "valve_notes", "pericardium_notes", "impression", "notes"):
        if key in payload:
            setattr(row, key, str(payload.get(key) or "").strip() or None)
    if "lvef_percent" in payload:
        raw = payload.get("lvef_percent")
        val = float(raw) if raw not in (None, "") else None
        if val is not None and (val < 0 or val > 100):
            raise ValueError("قيمة الكسر القذفي غير صالحة")
        row.lvef_percent = val
    if "other_measurements" in payload and isinstance(payload.get("other_measurements"), dict):
        row.other_measurements_json = json.dumps(payload["other_measurements"], ensure_ascii=False)
    if "attachment_id" in payload:
        row.attachment_id = _attachment(tenant_id, row.patient_id, payload.get("attachment_id"))
    action = "update"
    if payload.get("archive") in (True, "true", 1, "1"):
        row.archived_at = datetime.utcnow()
        action = "archive"
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    _audit(tenant_id, actor_id, "cardiology_echo", row.id, action, f"{action} Echo", meta={"old": old, "new": _echo_dict(row)})
    return list_echos(tenant_id, row.patient_id)


def _risk_factors(patient: ClinicPatient, conditions: list[dict], vitals: dict, profile: dict) -> list[dict]:
    codes = {c["condition_code"] for c in conditions if c.get("status") in ("active", "controlled")}
    latest = vitals.get("latest") or {}
    factors = []

    def add(code, label, present, source):
        factors.append({"code": code, "label_ar": label, "present": present, "source": source})

    add("hypertension", "ارتفاع ضغط الدم", "hypertension" in codes, "chronic_condition")
    add("diabetes", "السكري", "diabetes" in codes, "chronic_condition")
    add("hyperlipidemia", "اضطراب الدهون", "hyperlipidemia" in codes, "chronic_condition")
    add("ckd", "أمراض الكلى المزمنة", "chronic_kidney_disease" in codes, "chronic_condition")
    add("known_cad", "مرض شرايين تاجية معروف",
        bool(codes & {"coronary_artery_disease", "heart_disease"}), "chronic_condition")
    smoking = profile.get("smoking_status")
    add("smoking", "التدخين", smoking in ("current", "former"), "cardiology_profile")
    bmi = latest.get("bmi")
    add("obesity", "السمنة", (bmi is not None and float(bmi) >= 30) or "obesity" in codes, "vitals_or_condition")
    family = bool((profile.get("family_cardiac_history") or "").strip())
    add("family_history", "تاريخ عائلي قلبي", family, "cardiology_profile")
    return factors


def get_cardiology_context(tenant_id: int, patient_id: int, visit_id=None) -> dict:
    patient = _patient(tenant_id, patient_id)
    profile = get_cardiology_profile(tenant_id, patient_id)
    conditions_full = list_chronic_conditions(tenant_id, patient_id)
    cardiac = [
        c for c in (conditions_full.get("active") or [])
        if c.get("condition_code") in CARDIAC_CONDITION_CODES
        or c.get("condition_code") == "other"
    ]
    meds = list_patient_medications(tenant_id, patient_id)
    vitals = get_vital_trends(tenant_id, patient_id, "6m")
    labs = get_lab_trends(tenant_id, patient_id, analytes=CARDIO_LAB_KEYS, range_key="1y")
    ecgs = list_ecgs(tenant_id, patient_id, limit=5)
    echos = list_echos(tenant_id, patient_id, limit=5)
    from modules.clinics.models import ClinicFollowUp, ClinicVisit

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
    next_fu = None
    for f in (
        ClinicFollowUp.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicFollowUp.due_date.asc())
        .limit(10)
        .all()
    ):
        if f.status in ("due", "pending", "scheduled", "open"):
            next_fu = {"id": f.id, "due_date": f.due_date.isoformat() if f.due_date else None, "status": f.status}
            break

    latest = vitals.get("latest") or {}
    latest_ecg = (ecgs.get("items") or [None])[0]
    latest_echo = (echos.get("items") or [None])[0]
    summary = {
        "cardiac_conditions": cardiac,
        "latest_bp": latest.get("blood_pressure"),
        "latest_pulse": latest.get("heart_rate"),
        "latest_weight": latest.get("weight_kg"),
        "latest_spo2": latest.get("oxygen_sat"),
        "latest_ecg": {
            "id": latest_ecg["id"],
            "recorded_at": latest_ecg["recorded_at"],
            "rhythm": latest_ecg["rhythm"],
            "heart_rate": latest_ecg["heart_rate"],
            "interpretation": latest_ecg["interpretation"],
        } if latest_ecg else None,
        "latest_echo": {
            "id": latest_echo["id"],
            "recorded_at": latest_echo["recorded_at"],
            "lvef_percent": latest_echo["lvef_percent"],
            "impression": latest_echo["impression"],
        } if latest_echo else None,
        "current_medications": meds.get("active") or [],
        "next_followup": next_fu,
        "allergies": patient.allergies or "",
    }
    compact = {k: v for k, v in summary.items() if v not in (None, "", [], {})}

    return {
        "patient_id": patient_id,
        "visit_id": visit_id,
        "profile": profile,
        "summary": compact,
        "risk_factors": _risk_factors(patient, conditions_full.get("active") or [], vitals, profile),
        "conditions": {"items": cardiac, "all": conditions_full.get("items") or []},
        "medications": {"active": meds.get("active") or [], "items": meds.get("items") or []},
        "vital_trends_summary": {
            "latest": latest,
            "counts": {k: len(v) for k, v in (vitals.get("series") or {}).items()},
            "preset": ["systolic", "diastolic", "heart_rate", "weight_kg", "oxygen_sat"],
        },
        "relevant_labs": labs.get("latest") or {},
        "recent_ecgs": ecgs.get("items") or [],
        "recent_echos": echos.get("items") or [],
        "recent_visits": recent_visits,
        "next_followup": next_fu,
        "permissions": {"can_edit": True},
        "risk_scoring_available": False,
        "auto_ecg_interpretation": False,
        "auto_echo_classification": False,
        "catalog": {
            "smoking": [{"code": k, "label_ar": v} for k, v in SMOKING_AR.items()],
            "devices": [{"code": k, "label_ar": v} for k, v in DEVICE_AR.items()],
            "cardiac_conditions": [
                {"code": k, "label_ar": CONDITION_AR.get(k, k)} for k in sorted(CARDIAC_CONDITION_CODES)
            ],
        },
        "engines": {
            "vital_trends": "service_internal_medicine.get_vital_trends",
            "lab_trends": "service_internal_medicine.get_lab_trends",
            "medications": "ClinicPatientMedication",
            "conditions": "ClinicChronicCondition",
            "visit_comparison": "service_internal_medicine.compare_visits",
        },
    }


def get_visit_cardiology_context(tenant_id: int, visit_id: int) -> dict:
    visit = _visit(tenant_id, visit_id)
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    ctx = get_cardiology_context(tenant_id, visit.patient_id, visit_id=visit_id)
    if visit.status == "completed":
        ctx["permissions"] = {"can_edit": False}
    return ctx


def cardiology_visit_comparison(tenant_id: int, patient_id: int, visit_ids: list[int]) -> dict:
    """Reuse Phase F comparison engine; attach recent ECG/Echo summaries per visit."""
    base = compare_visits(tenant_id, patient_id, visit_ids)
    ids = [c["visit_id"] for c in base.get("visits") or []]
    ecgs = {
        e.visit_id: e
        for e in ClinicCardiologyECG.query.filter(
            ClinicCardiologyECG.tenant_id == tenant_id,
            ClinicCardiologyECG.patient_id == patient_id,
            ClinicCardiologyECG.visit_id.in_(ids or [-1]),
            ClinicCardiologyECG.archived_at.is_(None),
        ).all()
    }
    echos = {
        e.visit_id: e
        for e in ClinicCardiologyEcho.query.filter(
            ClinicCardiologyEcho.tenant_id == tenant_id,
            ClinicCardiologyEcho.patient_id == patient_id,
            ClinicCardiologyEcho.visit_id.in_(ids or [-1]),
            ClinicCardiologyEcho.archived_at.is_(None),
        ).all()
    }
    for card in base.get("visits") or []:
        ecg = ecgs.get(card["visit_id"])
        echo = echos.get(card["visit_id"])
        card["ecg"] = _ecg_dict(ecg) if ecg else None
        card["echo"] = _echo_dict(echo) if echo else None
    base["engine"] = "service_internal_medicine.compare_visits"
    return base
