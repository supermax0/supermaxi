"""Gynecology & Obstetrics clinical tools — profile, pregnancy episodes, observations.

No automatic risk scoring, ultrasound interpretation, or medication safety.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from extensions import db
from modules.clinics.models import (
    ClinicFollowUp,
    ClinicGynecologyProfile,
    ClinicLabOrder,
    ClinicLabOrderItem,
    ClinicLabTest,
    ClinicPatient,
    ClinicPregnancy,
    ClinicPregnancyObservation,
    ClinicRadiologyOrder,
    ClinicVisit,
    ClinicVital,
)
from modules.clinics.service import _audit, _parse_date

PREGNANCY_STATUSES = frozenset({"active", "completed", "ended", "cancelled_record", "archived"})
DATING_METHODS = frozenset({"lmp", "ultrasound", "clinical", "external_record", "other"})
OUTCOMES = frozenset({"live_birth", "pregnancy_loss", "stillbirth", "ectopic", "other", "unknown"})
DELIVERY_TYPES = frozenset({"vaginal", "cesarean", "assisted", "other", "unknown"})

STATUS_AR = {
    "active": "نشط",
    "completed": "مكتمل",
    "ended": "منتهٍ",
    "cancelled_record": "سجل ملغى",
    "archived": "مؤرشف",
}
DATING_AR = {
    "lmp": "آخر دورة (LMP)",
    "ultrasound": "موجات فوق صوتية",
    "clinical": "تقدير سريري",
    "external_record": "سجل خارجي",
    "other": "أخرى",
}
OUTCOME_AR = {
    "live_birth": "ولادة حية",
    "pregnancy_loss": "فقدان حمل",
    "stillbirth": "ولادة ميتة",
    "ectopic": "حمل منتبذ",
    "other": "أخرى",
    "unknown": "غير معروف",
}
DELIVERY_AR = {
    "vaginal": "طبيعي",
    "cesarean": "قيصري",
    "assisted": "مساعد",
    "other": "أخرى",
    "unknown": "غير معروف",
}

LMP_TO_EDD_DAYS = 280


def _patient(tenant_id: int, patient_id: int) -> ClinicPatient:
    row = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not row:
        raise ValueError("المريض غير موجود")
    return row


def _num(raw):
    if raw in (None, ""):
        return None
    return float(raw)


def _int(raw, field="القيمة"):
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} غير صالح") from exc


def suggest_edd_from_lmp(lmp: date) -> date:
    """Naegele-style suggestion: LMP + 280 days. Not authoritative until clinician confirms."""
    return lmp + timedelta(days=LMP_TO_EDD_DAYS)


def gestational_age_on(on_date: date, *, lmp: date | None = None, edd: date | None = None) -> dict | None:
    """Derive gestational age from confirmed dating reference."""
    if not on_date:
        return None
    ref_lmp = lmp
    if ref_lmp is None and edd is not None:
        ref_lmp = edd - timedelta(days=LMP_TO_EDD_DAYS)
    if ref_lmp is None:
        return None
    total = (on_date - ref_lmp).days
    if total < 0:
        return {
            "weeks": 0,
            "days": 0,
            "total_days": total,
            "label": "قبل تاريخ المرجع",
            "before_reference": True,
        }
    weeks, rem = divmod(total, 7)
    return {
        "weeks": weeks,
        "days": rem,
        "total_days": total,
        "label": f"{weeks} أسابيع + {rem} أيام",
        "before_reference": False,
    }


def _validate_pregnancy_dates(lmp, edd, started_at, ended_at):
    if lmp and edd and edd < lmp:
        raise ValueError("موعد الولادة المتوقع لا يمكن أن يسبق آخر دورة")
    if lmp and ended_at and ended_at < lmp:
        raise ValueError("تاريخ إنهاء الحمل لا يمكن أن يسبق آخر دورة")
    if started_at and ended_at and ended_at < started_at:
        raise ValueError("تاريخ الإنهاء لا يمكن أن يسبق تاريخ البدء")
    if lmp and started_at and started_at < (lmp - timedelta(days=14)):
        # Conservative: allow small lead, reject extreme inversion
        raise ValueError("تواريخ الحمل غير متسقة مع آخر دورة")


def _profile_dict(row: ClinicGynecologyProfile | None) -> dict:
    if not row:
        return {
            "exists": False,
            "menarche_age": None,
            "cycle_regular": None,
            "cycle_length_days": None,
            "bleeding_duration_days": None,
            "last_menstrual_period": None,
            "menstrual_notes": "",
            "contraception_notes": "",
            "gynecologic_history": "",
            "previous_gynecologic_surgeries": "",
        }
    return {
        "exists": True,
        "id": row.id,
        "menarche_age": row.menarche_age,
        "cycle_regular": row.cycle_regular,
        "cycle_length_days": row.cycle_length_days,
        "bleeding_duration_days": row.bleeding_duration_days,
        "last_menstrual_period": row.last_menstrual_period.isoformat() if row.last_menstrual_period else None,
        "menstrual_notes": row.menstrual_notes or "",
        "contraception_notes": row.contraception_notes or "",
        "gynecologic_history": row.gynecologic_history or "",
        "previous_gynecologic_surgeries": row.previous_gynecologic_surgeries or "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_gynecology_profile(tenant_id: int, patient_id: int) -> dict:
    _patient(tenant_id, patient_id)
    row = ClinicGynecologyProfile.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).first()
    return _profile_dict(row)


def upsert_gynecology_profile(tenant_id: int, patient_id: int, payload: dict, actor_id=None) -> dict:
    _patient(tenant_id, patient_id)
    row = ClinicGynecologyProfile.query.filter_by(tenant_id=tenant_id, patient_id=patient_id).first()
    created = False
    if not row:
        row = ClinicGynecologyProfile(tenant_id=tenant_id, patient_id=patient_id, created_by=actor_id)
        db.session.add(row)
        created = True
    old = _profile_dict(row) if not created else None

    if "menarche_age" in payload:
        age = _int(payload.get("menarche_age"), "عمر الحيض")
        if age is not None and (age < 8 or age > 20):
            raise ValueError("عمر الحيض خارج النطاق المقبول (8–20)")
        row.menarche_age = age
    if "cycle_regular" in payload:
        val = payload.get("cycle_regular")
        if val in (None, ""):
            row.cycle_regular = None
        else:
            row.cycle_regular = val in (True, "true", 1, "1", "yes")
    if "cycle_length_days" in payload:
        days = _int(payload.get("cycle_length_days"), "طول الدورة")
        if days is not None and (days < 15 or days > 60):
            raise ValueError("طول الدورة خارج النطاق المقبول")
        row.cycle_length_days = days
    if "bleeding_duration_days" in payload:
        days = _int(payload.get("bleeding_duration_days"), "مدة النزف")
        if days is not None and (days < 1 or days > 20):
            raise ValueError("مدة النزف خارج النطاق المقبول")
        row.bleeding_duration_days = days
    if "last_menstrual_period" in payload:
        raw = payload.get("last_menstrual_period")
        row.last_menstrual_period = _parse_date(raw, "آخر دورة") if raw not in (None, "") else None
    for key in ("menstrual_notes", "contraception_notes", "gynecologic_history", "previous_gynecologic_surgeries"):
        if key in payload:
            setattr(row, key, str(payload.get(key) or "").strip() or None)

    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    db.session.flush()
    action = "create" if created else "update"
    _audit(
        tenant_id,
        actor_id,
        "gynecology_profile",
        row.id,
        action,
        f"{action} الملف النسائي للمريض #{patient_id}",
        meta={"old": old, "new": _profile_dict(row)},
    )
    return _profile_dict(row)


def _pregnancy_dict(row: ClinicPregnancy, *, on_date: date | None = None) -> dict:
    on = on_date or date.today()
    ga = gestational_age_on(on, lmp=row.lmp_date, edd=row.edd_date)
    suggested = suggest_edd_from_lmp(row.lmp_date).isoformat() if row.lmp_date else None
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "created_by_doctor_id": row.created_by_doctor_id,
        "status": row.status,
        "status_label_ar": STATUS_AR.get(row.status or "", row.status or ""),
        "lmp_date": row.lmp_date.isoformat() if row.lmp_date else None,
        "edd_date": row.edd_date.isoformat() if row.edd_date else None,
        "edd_suggested_from_lmp": suggested,
        "dating_method": row.dating_method,
        "dating_method_label_ar": DATING_AR.get(row.dating_method or "", ""),
        "gravida_at_start": row.gravida_at_start,
        "para_at_start": row.para_at_start,
        "abortions_at_start": row.abortions_at_start,
        "gpa_label": (
            f"G{row.gravida_at_start or '—'} P{row.para_at_start or '—'} A{row.abortions_at_start or '—'}"
        ),
        "notes": row.notes or "",
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "outcome": row.outcome,
        "outcome_label_ar": OUTCOME_AR.get(row.outcome or "", ""),
        "delivery_type": row.delivery_type,
        "delivery_type_label_ar": DELIVERY_AR.get(row.delivery_type or "", ""),
        "gestational_duration_weeks": row.gestational_duration_weeks,
        "gestational_age": ga,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_pregnancies(tenant_id: int, patient_id: int) -> dict:
    _patient(tenant_id, patient_id)
    rows = (
        ClinicPregnancy.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(ClinicPregnancy.archived_at.is_(None))
        .order_by(ClinicPregnancy.created_at.desc(), ClinicPregnancy.id.desc())
        .all()
    )
    active = [r for r in rows if r.status == "active"]
    previous = [r for r in rows if r.status != "active"]
    return {
        "patient_id": patient_id,
        "active": [_pregnancy_dict(r) for r in active],
        "previous": [_pregnancy_dict(r) for r in previous],
        "items": [_pregnancy_dict(r) for r in rows],
        "multiple_active": len(active) > 1,
    }


def create_pregnancy(tenant_id: int, patient_id: int, payload: dict, actor_id=None, doctor_id=None) -> dict:
    patient = _patient(tenant_id, patient_id)
    existing_active = (
        ClinicPregnancy.query.filter_by(tenant_id=tenant_id, patient_id=patient_id, status="active")
        .filter(ClinicPregnancy.archived_at.is_(None))
        .count()
    )
    if existing_active and not payload.get("allow_multiple_active"):
        raise ValueError("يوجد حمل نشط بالفعل — أنهِ السجل الحالي أو أكّد السماح بسجل إضافي")

    lmp = _parse_date(payload.get("lmp_date"), "آخر دورة") if payload.get("lmp_date") not in (None, "") else None
    edd_raw = payload.get("edd_date")
    edd = _parse_date(edd_raw, "موعد الولادة المتوقع") if edd_raw not in (None, "") else None
    if edd is None and lmp is not None and payload.get("use_suggested_edd") in (True, "true", 1, "1"):
        edd = suggest_edd_from_lmp(lmp)

    dating = str(payload.get("dating_method") or ("lmp" if lmp else "other")).strip().lower()
    if dating not in DATING_METHODS:
        raise ValueError("طريقة التأريخ غير صالحة")

    started = _parse_date(payload.get("started_at"), "تاريخ البدء") if payload.get("started_at") not in (None, "") else (lmp or date.today())
    _validate_pregnancy_dates(lmp, edd, started, None)

    g = _int(payload.get("gravida_at_start"), "Gravida")
    p = _int(payload.get("para_at_start"), "Para")
    a = _int(payload.get("abortions_at_start"), "Abortions")
    for label, val in (("Gravida", g), ("Para", p), ("Abortions", a)):
        if val is not None and val < 0:
            raise ValueError(f"{label} لا يمكن أن يكون سالباً")

    row = ClinicPregnancy(
        tenant_id=tenant_id,
        patient_id=patient.id,
        created_by_doctor_id=int(doctor_id) if doctor_id not in (None, "", 0, "0") else None,
        status="active",
        lmp_date=lmp,
        edd_date=edd,
        dating_method=dating,
        gravida_at_start=g,
        para_at_start=p,
        abortions_at_start=a,
        notes=str(payload.get("notes") or "").strip() or None,
        started_at=started,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(
        tenant_id,
        actor_id,
        "pregnancy",
        row.id,
        "create",
        f"تسجيل حمل للمريض #{patient_id}",
        meta=_pregnancy_dict(row),
    )
    return _pregnancy_dict(row)


def get_pregnancy(tenant_id: int, pregnancy_id: int) -> dict:
    row = ClinicPregnancy.query.filter_by(tenant_id=tenant_id, id=pregnancy_id).first()
    if not row or row.archived_at:
        raise ValueError("سجل الحمل غير موجود")
    return _pregnancy_dict(row)


def update_pregnancy(tenant_id: int, pregnancy_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicPregnancy.query.filter_by(tenant_id=tenant_id, id=pregnancy_id).first()
    if not row or row.archived_at:
        raise ValueError("سجل الحمل غير موجود")
    old = _pregnancy_dict(row)
    dating_changed = False

    if "lmp_date" in payload:
        raw = payload.get("lmp_date")
        row.lmp_date = _parse_date(raw, "آخر دورة") if raw not in (None, "") else None
        dating_changed = True
    if "edd_date" in payload:
        raw = payload.get("edd_date")
        row.edd_date = _parse_date(raw, "موعد الولادة المتوقع") if raw not in (None, "") else None
        dating_changed = True
    if payload.get("use_suggested_edd") in (True, "true", 1, "1") and row.lmp_date:
        row.edd_date = suggest_edd_from_lmp(row.lmp_date)
        dating_changed = True
    if "dating_method" in payload:
        dating = str(payload.get("dating_method") or "").strip().lower()
        if dating and dating not in DATING_METHODS:
            raise ValueError("طريقة التأريخ غير صالحة")
        row.dating_method = dating or None
        dating_changed = True
    for key, label in (
        ("gravida_at_start", "Gravida"),
        ("para_at_start", "Para"),
        ("abortions_at_start", "Abortions"),
        ("gestational_duration_weeks", "مدة الحمل"),
    ):
        if key in payload:
            val = _int(payload.get(key), label)
            if val is not None and val < 0:
                raise ValueError(f"{label} لا يمكن أن يكون سالباً")
            setattr(row, key, val)
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "").strip() or None
    if "started_at" in payload:
        raw = payload.get("started_at")
        row.started_at = _parse_date(raw, "تاريخ البدء") if raw not in (None, "") else None
    if "delivery_type" in payload:
        dt = str(payload.get("delivery_type") or "").strip().lower()
        if dt and dt not in DELIVERY_TYPES:
            raise ValueError("نوع الولادة غير صالح")
        row.delivery_type = dt or None

    close = payload.get("close") or payload.get("status") in ("completed", "ended", "cancelled_record")
    if close or "outcome" in payload or "ended_at" in payload:
        if "ended_at" in payload or close:
            raw = payload.get("ended_at")
            row.ended_at = (
                _parse_date(raw, "تاريخ الإنهاء")
                if raw not in (None, "")
                else (row.ended_at or date.today())
            )
        if "outcome" in payload:
            outcome = str(payload.get("outcome") or "").strip().lower()
            if outcome and outcome not in OUTCOMES:
                raise ValueError("نتيجة الحمل غير صالحة")
            row.outcome = outcome or None
        if close:
            status = str(payload.get("status") or "completed").strip().lower()
            if status not in PREGNANCY_STATUSES - {"active"}:
                status = "completed"
            row.status = status

    if payload.get("archive") in (True, "true", 1, "1"):
        row.status = "archived"
        row.archived_at = datetime.utcnow()

    _validate_pregnancy_dates(row.lmp_date, row.edd_date, row.started_at, row.ended_at)
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    db.session.flush()
    action = "archive" if row.archived_at and not old.get("archived_at") else ("close" if close else "update")
    if dating_changed:
        action = "dating_update" if action == "update" else action
    _audit(
        tenant_id,
        actor_id,
        "pregnancy",
        row.id,
        action,
        f"{action} سجل حمل #{row.id}",
        meta={"old": old, "new": _pregnancy_dict(row)},
    )
    return _pregnancy_dict(row)


def _obs_dict(row: ClinicPregnancyObservation) -> dict:
    us = {}
    if row.ultrasound_json:
        try:
            us = json.loads(row.ultrasound_json) or {}
        except json.JSONDecodeError:
            us = {}
    ga_label = ""
    if row.gestational_age_weeks is not None:
        ga_label = f"{row.gestational_age_weeks} أسابيع + {row.gestational_age_days or 0} أيام"
    return {
        "id": row.id,
        "pregnancy_id": row.pregnancy_id,
        "visit_id": row.visit_id,
        "doctor_id": row.doctor_id,
        "gestational_age_weeks": row.gestational_age_weeks,
        "gestational_age_days": row.gestational_age_days,
        "gestational_age_label": ga_label,
        "fundal_height_cm": float(row.fundal_height_cm) if row.fundal_height_cm is not None else None,
        "fetal_heart_rate": row.fetal_heart_rate,
        "fetal_movement_notes": row.fetal_movement_notes or "",
        "presentation": row.presentation or "",
        "edema_notes": row.edema_notes or "",
        "clinical_notes": row.clinical_notes or "",
        "ultrasound": us,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
    }


def list_observations(tenant_id: int, pregnancy_id: int) -> dict:
    preg = ClinicPregnancy.query.filter_by(tenant_id=tenant_id, id=pregnancy_id).first()
    if not preg or preg.archived_at:
        raise ValueError("سجل الحمل غير موجود")
    rows = (
        ClinicPregnancyObservation.query.filter_by(tenant_id=tenant_id, pregnancy_id=pregnancy_id)
        .filter(ClinicPregnancyObservation.archived_at.is_(None))
        .order_by(ClinicPregnancyObservation.created_at.desc(), ClinicPregnancyObservation.id.desc())
        .all()
    )
    return {"pregnancy_id": pregnancy_id, "items": [_obs_dict(r) for r in rows]}


def add_observation(tenant_id: int, pregnancy_id: int, payload: dict, actor_id=None) -> dict:
    preg = ClinicPregnancy.query.filter_by(tenant_id=tenant_id, id=pregnancy_id).first()
    if not preg or preg.archived_at:
        raise ValueError("سجل الحمل غير موجود")
    visit_id = payload.get("visit_id")
    visit_id = int(visit_id) if visit_id not in (None, "", 0, "0") else None
    doctor_id = payload.get("doctor_id")
    doctor_id = int(doctor_id) if doctor_id not in (None, "", 0, "0") else None
    visit_date = date.today()
    if visit_id:
        visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id, patient_id=preg.patient_id).first()
        if not visit:
            raise ValueError("الزيارة غير موجودة")
        if visit.status == "completed" and not payload.get("allow_completed"):
            raise ValueError("لا يمكن إضافة ملاحظة حمل بعد إكمال الزيارة")
        if doctor_id is None:
            doctor_id = visit.doctor_id
        visit_date = visit.visit_date if getattr(visit, "visit_date", None) else (
            visit.created_at.date() if visit.created_at else date.today()
        )

    weeks = _int(payload.get("gestational_age_weeks"), "أسابيع الحمل")
    days = _int(payload.get("gestational_age_days"), "أيام الحمل")
    if weeks is None and days is None:
        ga = gestational_age_on(visit_date, lmp=preg.lmp_date, edd=preg.edd_date)
        if ga and not ga.get("before_reference"):
            weeks, days = ga["weeks"], ga["days"]
    if days is not None and (days < 0 or days > 6):
        raise ValueError("أيام عمر الحمل يجب أن تكون بين 0 و 6")
    if weeks is not None and (weeks < 0 or weeks > 45):
        raise ValueError("أسابيع عمر الحمل خارج النطاق المقبول")

    us = payload.get("ultrasound")
    us_json = json.dumps(us, ensure_ascii=False) if isinstance(us, dict) and us else None

    row = ClinicPregnancyObservation(
        tenant_id=tenant_id,
        pregnancy_id=pregnancy_id,
        visit_id=visit_id,
        doctor_id=doctor_id,
        gestational_age_weeks=weeks,
        gestational_age_days=days if days is not None else 0 if weeks is not None else None,
        fundal_height_cm=_num(payload.get("fundal_height_cm")),
        fetal_heart_rate=_int(payload.get("fetal_heart_rate"), "نبض الجنين"),
        fetal_movement_notes=str(payload.get("fetal_movement_notes") or "").strip() or None,
        presentation=str(payload.get("presentation") or "").strip() or None,
        edema_notes=str(payload.get("edema_notes") or "").strip() or None,
        clinical_notes=str(payload.get("clinical_notes") or "").strip() or None,
        ultrasound_json=us_json,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(
        tenant_id,
        actor_id,
        "pregnancy_observation",
        row.id,
        "create",
        f"ملاحظة حمل #{pregnancy_id}",
        meta=_obs_dict(row),
    )
    return list_observations(tenant_id, pregnancy_id)


def update_observation(tenant_id: int, observation_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicPregnancyObservation.query.filter_by(tenant_id=tenant_id, id=observation_id).first()
    if not row or row.archived_at:
        raise ValueError("ملاحظة الحمل غير موجودة")
    if row.visit_id:
        visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=row.visit_id).first()
        if visit and visit.status == "completed":
            raise ValueError("لا يمكن تعديل ملاحظة مرتبطة بزيارة مكتملة")
    old = _obs_dict(row)
    if "gestational_age_weeks" in payload:
        row.gestational_age_weeks = _int(payload.get("gestational_age_weeks"), "أسابيع الحمل")
    if "gestational_age_days" in payload:
        days = _int(payload.get("gestational_age_days"), "أيام الحمل")
        if days is not None and (days < 0 or days > 6):
            raise ValueError("أيام عمر الحمل يجب أن تكون بين 0 و 6")
        row.gestational_age_days = days
    if "fundal_height_cm" in payload:
        row.fundal_height_cm = _num(payload.get("fundal_height_cm"))
    if "fetal_heart_rate" in payload:
        row.fetal_heart_rate = _int(payload.get("fetal_heart_rate"), "نبض الجنين")
    for key in ("fetal_movement_notes", "presentation", "edema_notes", "clinical_notes"):
        if key in payload:
            setattr(row, key, str(payload.get(key) or "").strip() or None)
    if "ultrasound" in payload:
        us = payload.get("ultrasound")
        row.ultrasound_json = json.dumps(us, ensure_ascii=False) if isinstance(us, dict) and us else None
    if payload.get("archive") in (True, "true", 1, "1"):
        row.archived_at = datetime.utcnow()
        action = "archive"
    else:
        action = "update"
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    _audit(
        tenant_id,
        actor_id,
        "pregnancy_observation",
        row.id,
        action,
        f"{action} ملاحظة حمل #{row.id}",
        meta={"old": old, "new": _obs_dict(row)},
    )
    return list_observations(tenant_id, row.pregnancy_id)


def _pregnancy_window(preg: ClinicPregnancy) -> tuple[date | None, date | None]:
    start = preg.started_at or preg.lmp_date or (preg.created_at.date() if preg.created_at else None)
    end = preg.ended_at or date.today()
    return start, end


def _vital_trends(tenant_id: int, patient_id: int, preg: ClinicPregnancy | None) -> dict:
    q = ClinicVital.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
    if preg:
        start, end = _pregnancy_window(preg)
        if start:
            q = q.filter(ClinicVital.recorded_at >= datetime.combine(start, datetime.min.time()))
        if end:
            q = q.filter(ClinicVital.recorded_at <= datetime.combine(end, datetime.max.time()))
    rows = q.order_by(ClinicVital.recorded_at.asc()).limit(200).all()
    weight, bp = [], []
    for r in rows:
        d = r.recorded_at.date() if r.recorded_at else None
        ga = gestational_age_on(d, lmp=preg.lmp_date, edd=preg.edd_date) if preg and d else None
        base = {
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
            "visit_id": r.visit_id,
            "gestational_age": ga,
        }
        if r.weight_kg is not None:
            weight.append({**base, "weight_kg": float(r.weight_kg)})
        if r.blood_pressure:
            bp.append({**base, "blood_pressure": r.blood_pressure})
    return {"weight": weight, "blood_pressure": bp}


def _labs_for_pregnancy(tenant_id: int, patient_id: int, preg: ClinicPregnancy | None) -> list:
    q = ClinicLabOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
    if preg:
        start, end = _pregnancy_window(preg)
        if start:
            q = q.filter(ClinicLabOrder.ordered_at >= datetime.combine(start, datetime.min.time()))
        if end:
            q = q.filter(ClinicLabOrder.ordered_at <= datetime.combine(end, datetime.max.time()))
    orders = q.order_by(ClinicLabOrder.ordered_at.desc()).limit(40).all()
    if not orders:
        return []
    order_ids = [o.id for o in orders]
    items = ClinicLabOrderItem.query.filter(
        ClinicLabOrderItem.tenant_id == tenant_id,
        ClinicLabOrderItem.order_id.in_(order_ids),
    ).all()
    test_ids = {i.test_id for i in items}
    tests = {
        t.id: t.name or t.code or f"#{t.id}"
        for t in ClinicLabTest.query.filter(
            ClinicLabTest.tenant_id == tenant_id, ClinicLabTest.id.in_(test_ids or {-1})
        ).all()
    }
    by_order: dict[int, list] = {}
    for i in items:
        by_order.setdefault(i.order_id, []).append(
            {"test": tests.get(i.test_id, f"#{i.test_id}"), "value": i.value, "status": i.status}
        )
    return [
        {
            "id": o.id,
            "ordered_at": o.ordered_at.isoformat() if o.ordered_at else None,
            "status": o.status,
            "visit_id": o.visit_id,
            "items": by_order.get(o.id, []),
        }
        for o in orders
    ]


def _radiology_for_pregnancy(tenant_id: int, patient_id: int, preg: ClinicPregnancy | None) -> list:
    q = ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
    if preg:
        start, end = _pregnancy_window(preg)
        if start:
            q = q.filter(ClinicRadiologyOrder.ordered_at >= datetime.combine(start, datetime.min.time()))
        if end:
            q = q.filter(ClinicRadiologyOrder.ordered_at <= datetime.combine(end, datetime.max.time()))
    rows = q.order_by(ClinicRadiologyOrder.ordered_at.desc()).limit(40).all()
    out = []
    for r in rows:
        modality = (r.modality or "").lower()
        is_us = "us" in modality or "ultra" in modality or modality in ("ultrasound", "sono", "sonography")
        out.append(
            {
                "id": r.id,
                "ordered_at": r.ordered_at.isoformat() if r.ordered_at else None,
                "modality": r.modality,
                "body_part": r.body_part or "",
                "status": r.status,
                "impression": r.impression or "",
                "is_ultrasound": is_us,
                "visit_id": r.visit_id,
            }
        )
    return out


def _followups(tenant_id: int, patient_id: int) -> list:
    rows = (
        ClinicFollowUp.query.filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicFollowUp.due_date.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": r.id,
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "status": r.status,
            "notes": r.notes or "",
            "visit_id": r.visit_id,
        }
        for r in rows
    ]


def build_pregnancy_timeline(tenant_id: int, pregnancy_id: int) -> dict:
    preg = ClinicPregnancy.query.filter_by(tenant_id=tenant_id, id=pregnancy_id).first()
    if not preg or preg.archived_at:
        raise ValueError("سجل الحمل غير موجود")
    events = []
    events.append(
        {
            "type": "pregnancy_created",
            "at": preg.created_at.isoformat() if preg.created_at else None,
            "title": "تسجيل الحمل",
            "detail": preg.gpa_label if hasattr(preg, "gpa_label") else "",
            "week": None,
        }
    )
    # Fix detail without fake attr
    events[0]["detail"] = (
        f"G{preg.gravida_at_start or '—'} P{preg.para_at_start or '—'} A{preg.abortions_at_start or '—'}"
    )

    for obs in (
        ClinicPregnancyObservation.query.filter_by(tenant_id=tenant_id, pregnancy_id=pregnancy_id)
        .filter(ClinicPregnancyObservation.archived_at.is_(None))
        .all()
    ):
        at = obs.created_at
        d = at.date() if at else None
        ga = gestational_age_on(d, lmp=preg.lmp_date, edd=preg.edd_date) if d else None
        week = obs.gestational_age_weeks if obs.gestational_age_weeks is not None else (ga or {}).get("weeks")
        events.append(
            {
                "type": "antenatal_observation",
                "at": at.isoformat() if at else None,
                "title": "زيارة/ملاحظة حمل",
                "detail": obs.clinical_notes or obs.presentation or "",
                "week": week,
                "observation_id": obs.id,
                "visit_id": obs.visit_id,
            }
        )

    start, end = _pregnancy_window(preg)
    visits_q = ClinicVisit.query.filter_by(tenant_id=tenant_id, patient_id=preg.patient_id)
    if start:
        visits_q = visits_q.filter(ClinicVisit.created_at >= datetime.combine(start, datetime.min.time()))
    if end:
        visits_q = visits_q.filter(ClinicVisit.created_at <= datetime.combine(end, datetime.max.time()))
    for v in visits_q.order_by(ClinicVisit.created_at.asc()).limit(50).all():
        at = v.created_at
        d = getattr(v, "visit_date", None) or (at.date() if at else None)
        ga = gestational_age_on(d, lmp=preg.lmp_date, edd=preg.edd_date) if d else None
        events.append(
            {
                "type": "visit",
                "at": at.isoformat() if at else None,
                "title": "زيارة",
                "detail": v.chief_complaint or v.status or "",
                "week": (ga or {}).get("weeks"),
                "visit_id": v.id,
            }
        )

    for lab in _labs_for_pregnancy(tenant_id, preg.patient_id, preg):
        d = date.fromisoformat(lab["ordered_at"][:10]) if lab.get("ordered_at") else None
        ga = gestational_age_on(d, lmp=preg.lmp_date, edd=preg.edd_date) if d else None
        events.append(
            {
                "type": "lab",
                "at": lab.get("ordered_at"),
                "title": "تحليل مخبري",
                "detail": lab.get("status") or "",
                "week": (ga or {}).get("weeks"),
                "lab_order_id": lab["id"],
            }
        )
    for rad in _radiology_for_pregnancy(tenant_id, preg.patient_id, preg):
        d = date.fromisoformat(rad["ordered_at"][:10]) if rad.get("ordered_at") else None
        ga = gestational_age_on(d, lmp=preg.lmp_date, edd=preg.edd_date) if d else None
        events.append(
            {
                "type": "ultrasound" if rad.get("is_ultrasound") else "radiology",
                "at": rad.get("ordered_at"),
                "title": "أشعة / موجات" if rad.get("is_ultrasound") else "أشعة",
                "detail": rad.get("body_part") or rad.get("modality") or "",
                "week": (ga or {}).get("weeks"),
                "radiology_id": rad["id"],
            }
        )
    for fu in _followups(tenant_id, preg.patient_id):
        events.append(
            {
                "type": "followup",
                "at": fu.get("due_date"),
                "title": "متابعة",
                "detail": fu.get("notes") or fu.get("status") or "",
                "week": None,
                "followup_id": fu["id"],
            }
        )

    if preg.ended_at:
        events.append(
            {
                "type": "pregnancy_closed",
                "at": preg.ended_at.isoformat(),
                "title": "إنهاء سجل الحمل",
                "detail": OUTCOME_AR.get(preg.outcome or "", preg.outcome or ""),
                "week": preg.gestational_duration_weeks,
            }
        )

    events.sort(key=lambda e: e.get("at") or "")
    by_week: dict[str, list] = {}
    for ev in events:
        key = f"week_{ev['week']}" if ev.get("week") is not None else "other"
        by_week.setdefault(key, []).append(ev)
    return {
        "pregnancy_id": pregnancy_id,
        "events": events,
        "by_week": by_week,
    }


def get_pregnancy_context(tenant_id: int, pregnancy_id: int) -> dict:
    preg_row = ClinicPregnancy.query.filter_by(tenant_id=tenant_id, id=pregnancy_id).first()
    if not preg_row or preg_row.archived_at:
        raise ValueError("سجل الحمل غير موجود")
    preg = _pregnancy_dict(preg_row)
    alerts = []
    if not preg_row.edd_date:
        alerts.append({"code": "missing_edd", "message": "موعد الولادة المتوقع غير محدد"})
    if not preg_row.lmp_date and preg_row.dating_method == "lmp":
        alerts.append({"code": "missing_lmp", "message": "آخر دورة غير مسجّلة رغم اختيار التأريخ بها"})
    return {
        "pregnancy": preg,
        "observations": list_observations(tenant_id, pregnancy_id).get("items") or [],
        "vital_trends": _vital_trends(tenant_id, preg_row.patient_id, preg_row),
        "labs": _labs_for_pregnancy(tenant_id, preg_row.patient_id, preg_row),
        "radiology": _radiology_for_pregnancy(tenant_id, preg_row.patient_id, preg_row),
        "ultrasound_history": [
            r for r in _radiology_for_pregnancy(tenant_id, preg_row.patient_id, preg_row) if r.get("is_ultrasound")
        ],
        "followups": _followups(tenant_id, preg_row.patient_id),
        "timeline": build_pregnancy_timeline(tenant_id, pregnancy_id),
        "alerts": alerts,
        "permissions": {"can_edit": True},
    }


def get_visit_gynecology_context(tenant_id: int, visit_id: int) -> dict:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    return get_gynecology_context(tenant_id, visit.patient_id, visit_id=visit_id, doctor_id=visit.doctor_id)


def get_gynecology_context(tenant_id: int, patient_id: int, visit_id=None, doctor_id=None) -> dict:
    """Bulk payload for doctor workspace / patient gynecology section."""
    profile = get_gynecology_profile(tenant_id, patient_id)
    pregnancies = list_pregnancies(tenant_id, patient_id)
    active_list = pregnancies.get("active") or []
    active = None
    selection_required = False
    if len(active_list) == 1:
        active = active_list[0]
    elif len(active_list) > 1:
        selection_required = True
        active = None

    current_observation = None
    pregnancy_context = None
    if active and not selection_required:
        pregnancy_context = get_pregnancy_context(tenant_id, active["id"])
        if visit_id:
            for obs in pregnancy_context.get("observations") or []:
                if obs.get("visit_id") == visit_id:
                    current_observation = obs
                    break

    next_fu = None
    fus = _followups(tenant_id, patient_id)
    for fu in fus:
        if fu.get("status") in ("due", "pending", "scheduled", "open"):
            next_fu = fu
            break
    if next_fu is None and fus:
        next_fu = fus[0]

    summary = None
    if active:
        summary = {
            "lmp": active.get("lmp_date"),
            "edd": active.get("edd_date"),
            "gestational_age": active.get("gestational_age"),
            "gpa": active.get("gpa_label"),
            "next_followup": next_fu,
            "alerts": (pregnancy_context or {}).get("alerts") or [],
        }

    return {
        "patient_id": patient_id,
        "visit_id": visit_id,
        "profile": profile,
        "active_pregnancy": active,
        "active_pregnancies": active_list,
        "previous_pregnancies": pregnancies.get("previous") or [],
        "multiple_active": pregnancies.get("multiple_active"),
        "selection_required": selection_required,
        "current_observation": current_observation,
        "pregnancy_context": pregnancy_context,
        "summary": summary,
        "followups": fus,
        "permissions": {"can_edit": True},
        "catalog": {
            "statuses": [{"code": k, "label_ar": v} for k, v in STATUS_AR.items()],
            "dating_methods": [{"code": k, "label_ar": v} for k, v in DATING_AR.items()],
            "outcomes": [{"code": k, "label_ar": v} for k, v in OUTCOME_AR.items()],
            "delivery_types": [{"code": k, "label_ar": v} for k, v in DELIVERY_AR.items()],
        },
        "risk_scoring_available": False,
        "fetal_percentiles_available": False,
    }
