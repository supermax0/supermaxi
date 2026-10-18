"""Interactive dental chart — patient-owned state with visit-scoped history."""
from __future__ import annotations

import json
from datetime import datetime

from extensions import db
from modules.clinics.models import (
    ClinicDentalRecord,
    ClinicDentalToothFinding,
    ClinicDentalToothEvent,
    ClinicDentalToothProcedure,
    ClinicDoctor,
    ClinicVisit,
    ClinicVisitProcedure,
)
from modules.clinics.service import _audit

PERMANENT_TEETH = tuple(
    f"{q}{n}" for q in (1, 2, 3, 4) for n in range(1, 9)
)
PRIMARY_TEETH = tuple(
    f"{q}{n}" for q in (5, 6, 7, 8) for n in range(1, 6)
)
ALL_TEETH = set(PERMANENT_TEETH) | set(PRIMARY_TEETH)

TOOTH_STATUS = frozenset({
    "healthy", "caries", "missing", "filled", "crown", "root_canal",
    "implant", "bridge", "fracture", "extracted", "extraction_planned",
    "inflammation", "mobility", "temporary_filling", "unerupted", "impacted",
    "other",
})
TOOTH_SURFACES = frozenset({
    "mesial", "distal", "occlusal", "buccal", "lingual", "incisal",
})
DENTITION_MODES = frozenset({"permanent", "primary", "mixed"})

STATUS_LABELS_AR = {
    "healthy": "طبيعي",
    "caries": "تسوس",
    "missing": "مفقود",
    "filled": "حشوة",
    "crown": "تاج",
    "root_canal": "علاج عصب",
    "implant": "زرعة",
    "bridge": "جسر",
    "fracture": "كسر",
    "extracted": "مقلوع",
    "extraction_planned": "مقرر قلع",
    "inflammation": "التهاب",
    "mobility": "حركة السن",
    "temporary_filling": "حشوة مؤقتة",
    "unerupted": "غير بازغ",
    "impacted": "منطمر",
    "other": "أخرى",
}


def validate_tooth_number(tooth_number: str) -> str:
    """Public FDI validator used by dental chart and treatment plan."""
    tooth = str(tooth_number or "").strip()
    _tooth_dentition(tooth)
    return tooth


def _tooth_dentition(tooth_number: str) -> str:
    if tooth_number in PERMANENT_TEETH:
        return "permanent"
    if tooth_number in PRIMARY_TEETH:
        return "primary"
    raise ValueError(f"رقم السن غير صالح: {tooth_number}")


def _parse_surfaces(raw) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("أسطح السن غير صالحة") from exc
    if not isinstance(raw, (list, tuple)):
        raise ValueError("أسطح السن يجب أن تكون قائمة")
    surfaces = []
    for item in raw:
        code = str(item or "").strip().lower()
        if not code:
            continue
        if code not in TOOTH_SURFACES:
            raise ValueError(f"سطح سن غير معروف: {code}")
        if code not in surfaces:
            surfaces.append(code)
    return surfaces


def _visit(tenant_id: int, visit_id: int) -> ClinicVisit:
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id).first()
    if not visit:
        raise ValueError("الزيارة غير موجودة")
    return visit


def _doctor_name(tenant_id: int, doctor_id) -> str:
    if not doctor_id:
        return ""
    row = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
    return row.full_name if row else ""


def _finding_dict(row: ClinicDentalToothFinding, *, procedures: list | None = None) -> dict:
    surfaces = []
    if row.surfaces_json:
        try:
            surfaces = json.loads(row.surfaces_json) or []
        except json.JSONDecodeError:
            surfaces = []
    return {
        "id": row.id,
        "tooth_number": row.tooth_number,
        "dentition": row.dentition,
        "status": row.status,
        "status_label_ar": STATUS_LABELS_AR.get(row.status, row.status),
        "surfaces": surfaces,
        "notes": row.notes or "",
        "visit_id": row.visit_id,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "procedures": procedures or [],
    }


def _ensure_record(visit: ClinicVisit, actor_id=None, dentition_mode: str | None = None) -> ClinicDentalRecord:
    record = ClinicDentalRecord.query.filter_by(tenant_id=visit.tenant_id, visit_id=visit.id).first()
    if record:
        if dentition_mode and dentition_mode in DENTITION_MODES and record.dentition_mode != dentition_mode:
            record.dentition_mode = dentition_mode
            record.updated_by = actor_id
            record.updated_at = datetime.utcnow()
        return record
    mode = dentition_mode if dentition_mode in DENTITION_MODES else "permanent"
    record = ClinicDentalRecord(
        tenant_id=visit.tenant_id,
        patient_id=visit.patient_id,
        visit_id=visit.id,
        doctor_id=visit.doctor_id,
        specialty_id=visit.specialty_id,
        dentition_mode=mode,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(record)
    db.session.flush()
    _audit(
        visit.tenant_id, actor_id, "dental_record", record.id, "create",
        f"إنشاء مخطط أسنان للزيارة {visit.id}",
        meta={"visit_id": visit.id, "patient_id": visit.patient_id},
    )
    return record


def _procedures_for_visit(tenant_id: int, visit_id: int) -> dict[str, list]:
    links = ClinicDentalToothProcedure.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).all()
    if not links:
        return {}
    proc_ids = {link.visit_procedure_id for link in links}
    procs = {
        row.id: row
        for row in ClinicVisitProcedure.query.filter(
            ClinicVisitProcedure.tenant_id == tenant_id,
            ClinicVisitProcedure.id.in_(proc_ids),
        ).all()
    }
    from modules.clinics.models import ClinicProcedure
    catalog = {
        row.id: row.name
        for row in ClinicProcedure.query.filter(
            ClinicProcedure.tenant_id == tenant_id,
            ClinicProcedure.id.in_({p.procedure_id for p in procs.values()}),
        ).all()
    }
    by_tooth: dict[str, list] = {}
    for link in links:
        vp = procs.get(link.visit_procedure_id)
        by_tooth.setdefault(link.tooth_number, []).append({
            "id": link.id,
            "visit_procedure_id": link.visit_procedure_id,
            "tooth_finding_id": link.tooth_finding_id,
            "procedure_name": catalog.get(vp.procedure_id, "") if vp else "",
            "price": float(vp.price or 0) if vp else 0,
        })
    return by_tooth


def _previous_by_tooth(tenant_id: int, patient_id: int, exclude_visit_id: int) -> dict[str, dict]:
    """Latest non-archived finding per tooth from earlier visits."""
    rows = (
        ClinicDentalToothFinding.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(ClinicDentalToothFinding.archived_at.is_(None))
        .filter(ClinicDentalToothFinding.visit_id != exclude_visit_id)
        .order_by(ClinicDentalToothFinding.updated_at.desc(), ClinicDentalToothFinding.id.desc())
        .all()
    )
    latest: dict[str, dict] = {}
    visit_ids = {row.visit_id for row in rows}
    visits = {
        v.id: v
        for v in ClinicVisit.query.filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.id.in_(visit_ids or {-1}),
        ).all()
    }
    for row in rows:
        if row.tooth_number in latest:
            continue
        visit = visits.get(row.visit_id)
        latest[row.tooth_number] = {
            "status": row.status,
            "status_label_ar": STATUS_LABELS_AR.get(row.status, row.status),
            "surfaces": json.loads(row.surfaces_json) if row.surfaces_json else [],
            "notes": row.notes or "",
            "visit_id": row.visit_id,
            "visit_date": visit.visit_date.isoformat() if visit and visit.visit_date else None,
            "doctor_name": _doctor_name(tenant_id, visit.doctor_id if visit else None),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    return latest


def _active_event_findings(tenant_id: int, patient_id: int) -> dict[str, list[dict]]:
    """Return concurrent active findings from append-only v29 events."""
    rows = (
        ClinicDentalToothEvent.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(
            db.or_(
                ClinicDentalToothEvent.is_active.is_(True),
                ClinicDentalToothEvent.event_type == "finding_resolved",
            )
        )
        .order_by(ClinicDentalToothEvent.event_date.asc(), ClinicDentalToothEvent.id.asc())
        .all()
    )
    resolved = {row.supersedes_event_id for row in rows if row.event_type == "finding_resolved" and row.supersedes_event_id}
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if not bool(getattr(row, "is_active", False)) or row.id in resolved:
            continue
        try:
            surfaces = json.loads(row.surfaces_json or "[]")
        except (TypeError, ValueError):
            surfaces = []
        grouped.setdefault(row.tooth_number, []).append({
            "id": row.id,
            "status": row.condition_code,
            "status_label_ar": STATUS_LABELS_AR.get(row.condition_code, row.condition_code),
            "surfaces": surfaces,
            "notes": row.notes or "",
            "visit_id": row.visit_id,
            "doctor_id": row.doctor_id,
            "event_date": row.event_date.isoformat() if row.event_date else None,
            "finding_key": row.finding_key,
        })
    return grouped


def _latest_patient_finding_rows(tenant_id: int, patient_id: int) -> dict[str, ClinicDentalToothFinding]:
    """Latest saved projection per tooth across all accessible patient visits."""
    rows = (
        ClinicDentalToothFinding.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(ClinicDentalToothFinding.archived_at.is_(None))
        .order_by(ClinicDentalToothFinding.updated_at.desc(), ClinicDentalToothFinding.id.desc())
        .all()
    )
    latest: dict[str, ClinicDentalToothFinding] = {}
    for row in rows:
        latest.setdefault(row.tooth_number, row)
    return latest


def _patient_dentition_mode(tenant_id: int, patient_id: int) -> str:
    record = (
        ClinicDentalRecord.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicDentalRecord.updated_at.desc(), ClinicDentalRecord.id.desc())
        .first()
    )
    return record.dentition_mode if record and record.dentition_mode in DENTITION_MODES else "permanent"


def _chart_catalog() -> dict:
    return {
        "permanent": list(PERMANENT_TEETH),
        "primary": list(PRIMARY_TEETH),
        "statuses": [
            {"code": code, "label_ar": STATUS_LABELS_AR[code]}
            for code in (
                "healthy", "caries", "filled", "crown", "root_canal", "missing",
                "implant", "bridge", "fracture", "extracted", "extraction_planned",
                "inflammation", "mobility", "temporary_filling", "unerupted",
                "impacted", "other",
            )
        ],
        "surfaces": list(TOOTH_SURFACES),
    }


def _patient_chart_teeth(
    tenant_id: int,
    patient_id: int,
    *,
    procedures: dict[str, list] | None = None,
) -> list[dict]:
    """Build the patient's current odontogram without losing visit provenance."""
    procedures = procedures or {}
    latest_rows = _latest_patient_finding_rows(tenant_id, patient_id)
    active_events = _active_event_findings(tenant_id, patient_id)
    teeth_by_number: dict[str, dict] = {}

    for tooth_number, row in latest_rows.items():
        item = _finding_dict(row, procedures=procedures.get(tooth_number, []))
        concurrent = active_events.get(tooth_number, [])
        item["findings"] = concurrent or [{
            "id": row.id,
            "status": row.status,
            "status_label_ar": STATUS_LABELS_AR.get(row.status, row.status),
            "surfaces": item["surfaces"],
            "notes": item["notes"],
            "visit_id": row.visit_id,
            "legacy": True,
        }]
        if concurrent:
            latest = concurrent[-1]
            item["status"] = latest["status"]
            item["status_label_ar"] = latest["status_label_ar"]
            item["notes"] = latest.get("notes", "")
            item["visit_id"] = latest.get("visit_id")
        item["visual_statuses"] = list(dict.fromkeys(f["status"] for f in item["findings"]))
        item["surfaces"] = list(
            dict.fromkeys(surface for finding in item["findings"] for surface in finding.get("surfaces", []))
        )
        teeth_by_number[tooth_number] = item

    for tooth_number, concurrent in active_events.items():
        if tooth_number in teeth_by_number:
            continue
        latest = concurrent[-1]
        teeth_by_number[tooth_number] = {
            "tooth_number": tooth_number,
            "dentition": _tooth_dentition(tooth_number),
            "status": latest["status"],
            "status_label_ar": latest["status_label_ar"],
            "surfaces": list(
                dict.fromkeys(surface for finding in concurrent for surface in finding.get("surfaces", []))
            ),
            "notes": latest.get("notes", ""),
            "visit_id": latest.get("visit_id"),
            "procedures": procedures.get(tooth_number, []),
            "findings": concurrent,
            "visual_statuses": list(dict.fromkeys(finding["status"] for finding in concurrent)),
        }
    return list(teeth_by_number.values())


def get_visit_dental_chart(tenant_id: int, visit_id: int) -> dict:
    visit = _visit(tenant_id, visit_id)
    record = ClinicDentalRecord.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first()
    procs = _procedures_for_visit(tenant_id, visit_id)
    teeth = _patient_chart_teeth(tenant_id, visit.patient_id, procedures=procs)
    previous = _previous_by_tooth(tenant_id, visit.patient_id, visit_id)
    editable = visit.status == "open"
    return {
        "visit_id": visit.id,
        "patient_id": visit.patient_id,
        "record_id": record.id if record else None,
        "dentition_mode": record.dentition_mode if record else _patient_dentition_mode(tenant_id, visit.patient_id),
        "has_chart": bool(teeth),
        "scope": "patient",
        "teeth": teeth,
        "history_summary": previous,
        "catalog": _chart_catalog(),
        "permissions": {
            "can_edit": editable,
            "read_only_reason": None if editable else "الزيارة مكتملة — المخطط للقراءة فقط",
        },
    }


def get_patient_dental_chart(tenant_id: int, patient_id: int) -> dict:
    """Return the persistent current odontogram directly from the patient file."""
    from modules.clinics.models import ClinicPatient

    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not patient:
        raise ValueError("المريض غير موجود")
    teeth = _patient_chart_teeth(tenant_id, patient_id)
    return {
        "visit_id": None,
        "patient_id": patient_id,
        "record_id": None,
        "dentition_mode": _patient_dentition_mode(tenant_id, patient_id),
        "has_chart": bool(teeth),
        "scope": "patient",
        "teeth": teeth,
        "history_summary": {},
        "catalog": _chart_catalog(),
        "permissions": {
            "can_edit": False,
            "read_only_reason": "مخطط ملف المريض للعرض — التعديل يتم من زيارة مفتوحة",
        },
    }


def add_active_tooth_finding(
    tenant_id: int, visit_id: int, tooth_number: str, payload: dict, actor_id=None,
) -> dict:
    """Append a concurrent finding while keeping the legacy current projection compatible."""
    visit = _visit(tenant_id, visit_id)
    if visit.status != "open":
        raise ValueError("لا يمكن إضافة finding بعد إكمال الزيارة")
    tooth = validate_tooth_number(tooth_number)
    status = str(payload.get("status") or "").strip().lower()
    if status not in TOOTH_STATUS or status == "healthy":
        raise ValueError("اختر finding سريري صالح")
    surfaces = _parse_surfaces(payload.get("surfaces"))
    notes = str(payload.get("notes") or "").strip() or None
    record = _ensure_record(visit, actor_id, str(payload.get("dentition_mode") or "").lower() or None)
    projection = ClinicDentalToothFinding.query.filter_by(
        tenant_id=tenant_id, dental_record_id=record.id, tooth_number=tooth
    ).first()
    if not projection:
        projection = ClinicDentalToothFinding(
            tenant_id=tenant_id, patient_id=visit.patient_id, visit_id=visit.id,
            dental_record_id=record.id, tooth_number=tooth, dentition=_tooth_dentition(tooth),
            created_by=actor_id,
        )
        db.session.add(projection)
    projection.status = status
    projection.surfaces_json = json.dumps(surfaces, ensure_ascii=False)
    projection.notes = notes
    projection.archived_at = None
    projection.updated_by = actor_id
    projection.updated_at = datetime.utcnow()
    from modules.clinics.service_dental_completion import record_tooth_event
    event = record_tooth_event(
        tenant_id, patient_id=visit.patient_id, visit_id=visit.id, doctor_id=visit.doctor_id,
        tooth_number=tooth, condition_code=status, surfaces=surfaces, notes=notes,
        event_type="finding_added", is_active=True, actor_id=actor_id,
    )
    event.finding_key = f"finding-{event.id}"
    _audit(
        tenant_id, actor_id, "dental_finding", event.id, "create",
        f"إضافة finding للسن {tooth}", meta={"status": status, "surfaces": surfaces},
    )
    return get_visit_dental_chart(tenant_id, visit_id)


def resolve_active_tooth_finding(
    tenant_id: int, visit_id: int, tooth_number: str, event_id: int, payload: dict, actor_id=None,
) -> dict:
    visit = _visit(tenant_id, visit_id)
    if visit.status != "open":
        raise ValueError("لا يمكن إنهاء finding بعد إكمال الزيارة")
    tooth = validate_tooth_number(tooth_number)
    event = ClinicDentalToothEvent.query.filter_by(
        tenant_id=tenant_id, id=int(event_id), patient_id=visit.patient_id,
        tooth_number=tooth, is_active=True,
    ).first()
    if not event:
        raise ValueError("الـ finding غير موجود")
    already = ClinicDentalToothEvent.query.filter_by(
        tenant_id=tenant_id, supersedes_event_id=event.id, event_type="finding_resolved"
    ).first()
    if not already:
        from modules.clinics.service_dental_completion import record_tooth_event
        record_tooth_event(
            tenant_id, patient_id=visit.patient_id, visit_id=visit.id, doctor_id=visit.doctor_id,
            tooth_number=tooth, condition_code=event.condition_code, surfaces=[],
            notes=str(payload.get("notes") or "").strip() or None,
            event_type="finding_resolved", supersedes_event_id=event.id, actor_id=actor_id,
        )
        _audit(tenant_id, actor_id, "dental_finding", event.id, "resolve", f"إنهاء finding للسن {tooth}")
    return get_visit_dental_chart(tenant_id, visit_id)


def upsert_tooth_finding(
    tenant_id: int,
    visit_id: int,
    tooth_number: str,
    payload: dict,
    actor_id=None,
) -> dict:
    visit = _visit(tenant_id, visit_id)
    if visit.status == "completed":
        raise ValueError("لا يمكن تعديل مخطط الأسنان بعد إكمال الزيارة")
    tooth_number = str(tooth_number or "").strip()
    dentition = _tooth_dentition(tooth_number)

    status = str(payload.get("status") or "healthy").strip().lower()
    if status not in TOOTH_STATUS:
        raise ValueError("حالة السن غير صالحة")
    surfaces = _parse_surfaces(payload.get("surfaces"))
    notes = str(payload.get("notes") or "").strip() or None
    dentition_mode = str(payload.get("dentition_mode") or "").strip().lower() or None
    if dentition_mode and dentition_mode not in DENTITION_MODES:
        raise ValueError("وضع الإطباق غير صالح")

    if payload.get("archive") in (True, "true", 1, "1"):
        return archive_tooth_finding(tenant_id, visit_id, tooth_number, actor_id)

    record = _ensure_record(visit, actor_id, dentition_mode)
    row = ClinicDentalToothFinding.query.filter_by(
        tenant_id=tenant_id,
        dental_record_id=record.id,
        tooth_number=tooth_number,
    ).first()

    old_meta = None
    if row and not row.archived_at:
        old_meta = {
            "status": row.status,
            "surfaces": json.loads(row.surfaces_json) if row.surfaces_json else [],
            "notes": row.notes or "",
        }

    if not row:
        row = ClinicDentalToothFinding(
            tenant_id=tenant_id,
            patient_id=visit.patient_id,
            visit_id=visit.id,
            dental_record_id=record.id,
            tooth_number=tooth_number,
            dentition=dentition,
            created_by=actor_id,
        )
        db.session.add(row)
        action = "create"
    else:
        action = "update"
        row.archived_at = None

    row.dentition = dentition
    row.status = status
    row.surfaces_json = json.dumps(surfaces, ensure_ascii=False)
    row.notes = notes
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    db.session.flush()

    link_id = payload.get("link_visit_procedure_id")
    if link_id not in (None, "", 0, "0"):
        link_procedure_to_tooth(
            tenant_id, visit_id, tooth_number, int(link_id), actor_id, finding_id=row.id
        )

    _audit(
        tenant_id, actor_id, "dental_finding", row.id, action,
        f"{'تسجيل' if action == 'create' else 'تحديث'} سن {tooth_number}",
        meta={
            "visit_id": visit_id,
            "patient_id": visit.patient_id,
            "tooth_number": tooth_number,
            "old": old_meta,
            "new": {"status": status, "surfaces": surfaces, "notes": notes or ""},
        },
    )
    active_before = _active_event_findings(tenant_id, visit.patient_id).get(tooth_number, [])
    if active_before:
        from modules.clinics.service_dental_completion import record_tooth_event
        for active in active_before:
            record_tooth_event(
                tenant_id, patient_id=visit.patient_id, visit_id=visit.id, doctor_id=visit.doctor_id,
                tooth_number=tooth_number, condition_code=active["status"], surfaces=[],
                event_type="finding_resolved", supersedes_event_id=active["id"], actor_id=actor_id,
            )
        if status != "healthy":
            event = record_tooth_event(
                tenant_id, patient_id=visit.patient_id, visit_id=visit.id, doctor_id=visit.doctor_id,
                tooth_number=tooth_number, condition_code=status, surfaces=surfaces, notes=notes,
                event_type="finding_added", is_active=True, actor_id=actor_id,
            )
            event.finding_key = f"finding-{event.id}"
    elif not old_meta or old_meta.get("status") != status or old_meta.get("surfaces") != surfaces:
        from modules.clinics.service_dental_completion import record_tooth_event
        record_tooth_event(
            tenant_id, patient_id=visit.patient_id, visit_id=visit.id, doctor_id=visit.doctor_id,
            tooth_number=tooth_number, condition_code=status, surfaces=surfaces, notes=notes,
            event_type="condition_change", actor_id=actor_id,
        )
    return get_visit_dental_chart(tenant_id, visit_id)


def archive_tooth_finding(tenant_id: int, visit_id: int, tooth_number: str, actor_id=None) -> dict:
    visit = _visit(tenant_id, visit_id)
    if visit.status == "completed":
        raise ValueError("لا يمكن تعديل مخطط الأسنان بعد إكمال الزيارة")
    tooth_number = str(tooth_number or "").strip()
    _tooth_dentition(tooth_number)
    record = ClinicDentalRecord.query.filter_by(tenant_id=tenant_id, visit_id=visit_id).first()
    if not record:
        return get_visit_dental_chart(tenant_id, visit_id)
    row = ClinicDentalToothFinding.query.filter_by(
        tenant_id=tenant_id, dental_record_id=record.id, tooth_number=tooth_number
    ).first()
    if row and not row.archived_at:
        row.archived_at = datetime.utcnow()
        row.updated_by = actor_id
        _audit(
            tenant_id, actor_id, "dental_finding", row.id, "archive",
            f"أرشفة إيجاد سن {tooth_number}",
            meta={"visit_id": visit_id, "tooth_number": tooth_number},
        )
    return get_visit_dental_chart(tenant_id, visit_id)


def link_procedure_to_tooth(
    tenant_id: int,
    visit_id: int,
    tooth_number: str,
    visit_procedure_id: int,
    actor_id=None,
    finding_id=None,
) -> dict:
    visit = _visit(tenant_id, visit_id)
    if visit.status == "completed":
        raise ValueError("لا يمكن ربط إجراء بعد إكمال الزيارة")
    tooth_number = str(tooth_number or "").strip()
    _tooth_dentition(tooth_number)
    vp = ClinicVisitProcedure.query.filter_by(
        tenant_id=tenant_id, id=visit_procedure_id, visit_id=visit_id
    ).first()
    if not vp:
        raise ValueError("إجراء الزيارة غير موجود")
    existing = ClinicDentalToothProcedure.query.filter_by(
        tenant_id=tenant_id,
        visit_id=visit_id,
        tooth_number=tooth_number,
        visit_procedure_id=visit_procedure_id,
    ).first()
    if existing:
        return {"id": existing.id, "already_linked": True}
    if finding_id is None:
        finding = ClinicDentalToothFinding.query.filter_by(
            tenant_id=tenant_id, visit_id=visit_id, tooth_number=tooth_number
        ).filter(ClinicDentalToothFinding.archived_at.is_(None)).first()
        finding_id = finding.id if finding else None
    row = ClinicDentalToothProcedure(
        tenant_id=tenant_id,
        visit_id=visit_id,
        tooth_finding_id=finding_id,
        tooth_number=tooth_number,
        visit_procedure_id=visit_procedure_id,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(
        tenant_id, actor_id, "dental_tooth_procedure", row.id, "link",
        f"ربط إجراء #{visit_procedure_id} بالسن {tooth_number}",
        meta={"visit_id": visit_id, "visit_procedure_id": visit_procedure_id, "tooth_number": tooth_number},
    )
    return {"id": row.id, "already_linked": False}


def get_patient_dental_history(tenant_id: int, patient_id: int) -> dict:
    from modules.clinics.models import ClinicPatient

    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not patient:
        raise ValueError("المريض غير موجود")

    findings = (
        ClinicDentalToothFinding.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .filter(ClinicDentalToothFinding.archived_at.is_(None))
        .order_by(ClinicDentalToothFinding.updated_at.desc(), ClinicDentalToothFinding.id.desc())
        .all()
    )
    visit_ids = {row.visit_id for row in findings}
    visits = {
        v.id: v
        for v in ClinicVisit.query.filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.id.in_(visit_ids or {-1}),
        ).all()
    }
    # Drop findings whose visits are outside doctor scope (query returns empty).
    accessible_visit_ids = set(visits.keys())

    history = []
    current: dict[str, dict] = {}
    for row in findings:
        if row.visit_id not in accessible_visit_ids:
            continue
        visit = visits[row.visit_id]
        entry = {
            **_finding_dict(row),
            "visit_date": visit.visit_date.isoformat() if visit.visit_date else None,
            "doctor_name": _doctor_name(tenant_id, visit.doctor_id),
            "visit_status": visit.status,
        }
        history.append(entry)
        if row.tooth_number not in current:
            current[row.tooth_number] = entry

    return {
        "patient_id": patient_id,
        "current_state": list(current.values()),
        "history": history,
        "status_labels": STATUS_LABELS_AR,
    }
