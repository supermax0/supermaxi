"""Dental treatment plan — patient-level clinical intent (not billing/execution)."""
from __future__ import annotations

import json
from datetime import datetime

from extensions import db
from modules.clinics.models import (
    ClinicDentalTreatmentPlan,
    ClinicDentalTreatmentOption,
    ClinicDentalTreatmentPlanItem,
    ClinicDentalTreatmentPlanItemLink,
    ClinicDoctor,
    ClinicInvoice,
    ClinicPatient,
    ClinicProcedure,
    ClinicSpecialty,
    ClinicVisit,
    ClinicVisitProcedure,
)
from modules.clinics.service import _audit, _money
from modules.clinics.service_dental import validate_tooth_number

PLAN_STATUSES = frozenset({"draft", "proposed", "accepted", "active", "in_progress", "completed", "cancelled", "archived"})
PLAN_TRANSITIONS = {
    "draft": {"proposed", "accepted", "active", "cancelled", "archived"},
    "proposed": {"draft", "accepted", "active", "cancelled", "archived"},
    "accepted": {"active", "cancelled", "archived"},
    "active": {"in_progress", "completed", "cancelled", "archived"},
    "in_progress": {"active", "completed", "cancelled", "archived"},
    "completed": {"archived"},
    "cancelled": {"archived"},
    "archived": set(),
}
ITEM_STATUSES = frozenset({"planned", "scheduled", "in_progress", "completed", "cancelled", "deferred"})
OPTION_STATUSES = frozenset({"proposed", "selected", "declined", "cancelled"})
OPTION_TYPES = frozenset({"recommended", "alternative"})
PRIORITIES = frozenset({"urgent", "high", "normal", "low"})
PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}

PLAN_STATUS_AR = {
    "draft": "مسودة",
    "proposed": "مقترحة",
    "accepted": "مقبولة",
    "active": "نشطة",
    "in_progress": "قيد التنفيذ",
    "completed": "مكتملة",
    "cancelled": "ملغاة",
    "archived": "مؤرشفة",
}
ITEM_STATUS_AR = {
    "planned": "مخطط",
    "scheduled": "مجدول",
    "in_progress": "قيد التنفيذ",
    "completed": "مكتمل",
    "cancelled": "ملغى",
    "deferred": "مؤجل",
}
PRIORITY_AR = {
    "urgent": "عاجل",
    "high": "مرتفع",
    "normal": "عادي",
    "low": "منخفض",
}


def _patient(tenant_id: int, patient_id: int) -> ClinicPatient:
    row = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    if not row:
        raise ValueError("المريض غير موجود")
    return row


def _plan(tenant_id: int, plan_id: int) -> ClinicDentalTreatmentPlan:
    row = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id, id=plan_id).first()
    if not row or row.archived_at:
        raise ValueError("خطة العلاج غير موجودة")
    return row


def _item(tenant_id: int, item_id: int) -> ClinicDentalTreatmentPlanItem:
    row = ClinicDentalTreatmentPlanItem.query.filter_by(tenant_id=tenant_id, id=item_id).first()
    if not row or row.archived_at:
        raise ValueError("بند خطة العلاج غير موجود")
    return row


def _doctor_name(tenant_id: int, doctor_id) -> str:
    if not doctor_id:
        return ""
    row = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
    return row.full_name if row else ""


def _normalize_tooth(raw) -> str | None:
    if raw in (None, "", "null"):
        return None
    return validate_tooth_number(str(raw))


def _normalize_teeth(raw, fallback=None) -> list[str]:
    if raw in (None, ""):
        raw = [fallback] if fallback not in (None, "") else []
    elif isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            raw = decoded if isinstance(decoded, list) else raw.split(",")
        except (TypeError, ValueError):
            raw = raw.split(",")
    if not isinstance(raw, (list, tuple, set)):
        raise ValueError("قائمة الأسنان غير صالحة")
    teeth = []
    for value in raw:
        if value in (None, ""):
            continue
        tooth = validate_tooth_number(str(value).strip())
        if tooth not in teeth:
            teeth.append(tooth)
    return teeth


def _item_teeth(row: ClinicDentalTreatmentPlanItem) -> list[str]:
    try:
        teeth = json.loads(getattr(row, "tooth_numbers_json", None) or "[]")
    except (TypeError, ValueError):
        teeth = []
    if not isinstance(teeth, list):
        teeth = []
    if row.tooth_number and row.tooth_number not in teeth:
        teeth.insert(0, row.tooth_number)
    return teeth


def _option_dict(row: ClinicDentalTreatmentOption) -> dict:
    return {
        "id": row.id,
        "treatment_plan_id": row.treatment_plan_id,
        "title": row.title,
        "description": row.description or "",
        "option_type": row.option_type,
        "is_recommended": bool(row.is_recommended),
        "status": row.status,
        "sort_order": int(row.sort_order or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _active_items(tenant_id: int, plan_id: int) -> list[ClinicDentalTreatmentPlanItem]:
    return (
        ClinicDentalTreatmentPlanItem.query
        .filter_by(tenant_id=tenant_id, plan_id=plan_id)
        .filter(ClinicDentalTreatmentPlanItem.archived_at.is_(None))
        .all()
    )


def _bulk_links(tenant_id: int, item_ids: list[int]) -> dict[int, list[ClinicDentalTreatmentPlanItemLink]]:
    if not item_ids:
        return {}
    rows = ClinicDentalTreatmentPlanItemLink.query.filter(
        ClinicDentalTreatmentPlanItemLink.tenant_id == tenant_id,
        ClinicDentalTreatmentPlanItemLink.treatment_plan_item_id.in_(item_ids),
    ).all()
    out: dict[int, list] = {}
    for row in rows:
        out.setdefault(row.treatment_plan_item_id, []).append(row)
    return out


def _execution_finance(tenant_id: int, links: list[ClinicDentalTreatmentPlanItemLink]) -> dict:
    """Derive billed/paid from linked visit procedures + visit invoices (no duplicated ledger)."""
    if not links:
        return {"actual_billed": 0, "paid": 0, "remaining": 0, "actual_sessions": 0, "executions": []}
    vp_ids = [link.visit_procedure_id for link in links]
    procs = {
        row.id: row
        for row in ClinicVisitProcedure.query.filter(
            ClinicVisitProcedure.tenant_id == tenant_id,
            ClinicVisitProcedure.id.in_(vp_ids),
        ).all()
    }
    visit_ids = {p.visit_id for p in procs.values()}
    invoices = ClinicInvoice.query.filter(
        ClinicInvoice.tenant_id == tenant_id,
        ClinicInvoice.visit_id.in_(visit_ids or {-1}),
    ).all()
    inv_by_visit: dict[int, list] = {}
    for inv in invoices:
        if inv.visit_id:
            inv_by_visit.setdefault(inv.visit_id, []).append(inv)

    catalog = {
        row.id: row.name
        for row in ClinicProcedure.query.filter(
            ClinicProcedure.tenant_id == tenant_id,
            ClinicProcedure.id.in_({p.procedure_id for p in procs.values()} or {-1}),
        ).all()
    }
    visits = {
        v.id: v
        for v in ClinicVisit.query.filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.id.in_(visit_ids or {-1}),
        ).all()
    }

    # Sum billed from procedure prices; allocate invoice paid by share of visit procedure totals.
    visit_linked_totals: dict[int, int] = {}
    for vp in procs.values():
        visit_linked_totals[vp.visit_id] = visit_linked_totals.get(vp.visit_id, 0) + int(vp.price or 0)

    actual_billed = sum(int(vp.price or 0) for vp in procs.values())
    paid = 0
    for visit_id, linked_total in visit_linked_totals.items():
        if linked_total <= 0:
            continue
        for inv in inv_by_visit.get(visit_id, []):
            inv_total = int(inv.total or 0) or linked_total
            share = min(1.0, linked_total / inv_total) if inv_total else 0
            paid += int(round(int(inv.paid or 0) * share))

    executions = []
    for link in links:
        vp = procs.get(link.visit_procedure_id)
        visit = visits.get(vp.visit_id) if vp else None
        executions.append({
            "link_id": link.id,
            "visit_procedure_id": link.visit_procedure_id,
            "visit_id": vp.visit_id if vp else None,
            "visit_date": visit.visit_date.isoformat() if visit and visit.visit_date else None,
            "procedure_name": catalog.get(vp.procedure_id, "") if vp else "",
            "price": int(vp.price or 0) if vp else 0,
            "status": vp.status if vp else "",
            "linked_at": link.linked_at.isoformat() if link.linked_at else None,
        })
    remaining = max(0, actual_billed - paid)
    return {
        "actual_billed": actual_billed,
        "paid": paid,
        "remaining": remaining,
        "actual_sessions": len(procs),
        "executions": executions,
    }


def _item_dict(
    row: ClinicDentalTreatmentPlanItem,
    *,
    procedure_name: str = "",
    finance: dict | None = None,
    include_financial: bool = True,
) -> dict:
    finance = finance or {
        "actual_billed": 0, "paid": 0, "remaining": 0, "actual_sessions": 0, "executions": [],
    }
    data = {
        "id": row.id,
        "plan_id": row.plan_id,
        "tooth_number": row.tooth_number,
        "tooth_numbers": _item_teeth(row),
        "whole_mouth": bool(getattr(row, "whole_mouth", False)),
        "treatment_option_id": getattr(row, "treatment_option_id", None),
        "procedure_id": row.procedure_id,
        "service_id": getattr(row, "service_id", None),
        "procedure_name": procedure_name,
        "title": row.title or procedure_name or "علاج",
        "description": row.description or "",
        "priority": row.priority,
        "priority_label_ar": PRIORITY_AR.get(row.priority, row.priority),
        "status": row.status,
        "status_label_ar": ITEM_STATUS_AR.get(row.status, row.status),
        "estimated_sessions": int(row.estimated_sessions or 1),
        "quantity": float(getattr(row, "quantity", 1) or 1),
        "actual_sessions": finance["actual_sessions"],
        "sessions_label": f"{finance['actual_sessions']} / {int(row.estimated_sessions or 1)}",
        "sort_order": int(row.sort_order or 0),
        "notes": row.notes or "",
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "cancellation_reason": getattr(row, "cancellation_reason", None) or "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "executions": finance["executions"] if include_financial else [
            {k: v for k, v in ex.items() if k != "price"} for ex in finance["executions"]
        ],
    }
    if include_financial:
        data["estimated_price"] = int(row.estimated_price or 0)
        data["discount"] = int(getattr(row, "discount", 0) or 0)
        data["actual_billed"] = finance["actual_billed"]
        data["paid"] = finance["paid"]
        data["remaining"] = finance["remaining"]
    return data


def _plan_summary(items: list[dict], include_financial: bool) -> dict:
    applicable = [i for i in items if i["status"] not in {"cancelled"}]
    completed = [i for i in applicable if i["status"] == "completed"]
    in_progress = [i for i in applicable if i["status"] == "in_progress"]
    summary = {
        "item_count": len(applicable),
        "completed_count": len(completed),
        "in_progress_count": len(in_progress),
        "remaining_count": max(0, len(applicable) - len(completed)),
        "progress_ratio": (len(completed) / len(applicable)) if applicable else 0,
    }
    if include_financial:
        summary["estimated_subtotal"] = sum(
            int(round(int(i.get("estimated_price") or 0) * float(i.get("quantity") or 1)))
            for i in applicable
        )
        summary["estimated_discount"] = sum(int(i.get("discount") or 0) for i in applicable)
        summary["estimated_total"] = max(0, summary["estimated_subtotal"] - summary["estimated_discount"])
        summary["actual_billed"] = sum(int(i.get("actual_billed") or 0) for i in applicable)
        summary["paid"] = sum(int(i.get("paid") or 0) for i in applicable)
        summary["remaining"] = sum(int(i.get("remaining") or 0) for i in applicable)
    return summary


def plan_detail(tenant_id: int, plan_id: int, *, include_financial: bool = True) -> dict:
    plan = ClinicDentalTreatmentPlan.query.filter_by(tenant_id=tenant_id, id=plan_id).first()
    if not plan:
        raise ValueError("خطة العلاج غير موجودة")
    items = _active_items(tenant_id, plan.id)
    links_by_item = _bulk_links(tenant_id, [i.id for i in items])
    proc_ids = {i.procedure_id for i in items if i.procedure_id}
    catalog = {
        row.id: row.name
        for row in ClinicProcedure.query.filter(
            ClinicProcedure.tenant_id == tenant_id,
            ClinicProcedure.id.in_(proc_ids or {-1}),
        ).all()
    }
    item_dicts = []
    for row in items:
        finance = _execution_finance(tenant_id, links_by_item.get(row.id, []))
        item_dicts.append(
            _item_dict(
                row,
                procedure_name=catalog.get(row.procedure_id, ""),
                finance=finance,
                include_financial=include_financial,
            )
        )
    item_dicts.sort(
        key=lambda i: (PRIORITY_RANK.get(i["priority"], 9), i["sort_order"], i["id"])
    )
    options = (
        ClinicDentalTreatmentOption.query
        .filter_by(tenant_id=tenant_id, treatment_plan_id=plan.id)
        .order_by(ClinicDentalTreatmentOption.sort_order.asc(), ClinicDentalTreatmentOption.id.asc())
        .all()
    )
    summary = _plan_summary(item_dicts, include_financial)
    plan_discount = int(getattr(plan, "estimated_discount", 0) or 0)
    if include_financial:
        summary["plan_discount"] = plan_discount
        summary["estimated_total"] = max(0, int(summary.get("estimated_total") or 0) - plan_discount)
    return {
        "plan": {
            "id": plan.id,
            "patient_id": plan.patient_id,
            "created_by_doctor_id": plan.created_by_doctor_id,
            "doctor_name": _doctor_name(tenant_id, plan.created_by_doctor_id),
            "specialty_id": plan.specialty_id,
            "source_visit_id": plan.source_visit_id,
            "name": plan.name,
            "notes": plan.notes or "",
            "status": plan.status,
            "status_label_ar": PLAN_STATUS_AR.get(plan.status, plan.status),
            "started_at": plan.started_at.isoformat() if plan.started_at else None,
            "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
            "accepted_at": plan.accepted_at.isoformat() if getattr(plan, "accepted_at", None) else None,
            "accepted_by": getattr(plan, "accepted_by", None),
            "selected_option_id": getattr(plan, "selected_option_id", None),
            "acceptance_method": getattr(plan, "acceptance_method", None),
            "signature_attachment_id": getattr(plan, "signature_attachment_id", None),
            **({"estimated_discount": int(getattr(plan, "estimated_discount", 0) or 0)} if include_financial else {}),
            "cancellation_reason": getattr(plan, "cancellation_reason", None) or "",
            "archived_at": plan.archived_at.isoformat() if plan.archived_at else None,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        },
        "items": item_dicts,
        "options": [_option_dict(row) for row in options],
        "summary": summary,
        "permissions": {
            "can_edit": plan.status in {"draft", "proposed", "accepted", "active", "in_progress"} and not plan.archived_at,
            "include_financial": include_financial,
        },
    }


def list_patient_plans(tenant_id: int, patient_id: int, *, include_financial: bool = True) -> dict:
    _patient(tenant_id, patient_id)
    rows = (
        ClinicDentalTreatmentPlan.query
        .filter_by(tenant_id=tenant_id, patient_id=patient_id)
        .order_by(ClinicDentalTreatmentPlan.updated_at.desc(), ClinicDentalTreatmentPlan.id.desc())
        .all()
    )
    plans = []
    active = None
    for row in rows:
        detail = plan_detail(tenant_id, row.id, include_financial=include_financial)
        plans.append(detail)
        if active is None and row.status in {"accepted", "active", "in_progress"} and not row.archived_at:
            active = detail
    if active is None:
        for detail in plans:
            if detail["plan"]["status"] == "draft" and not detail["plan"]["archived_at"]:
                active = detail
                break
    return {
        "patient_id": patient_id,
        "active_plan": active,
        "plans": plans,
    }


def create_plan(tenant_id: int, patient_id: int, payload: dict, actor_id=None) -> dict:
    patient = _patient(tenant_id, patient_id)
    doctor_id = payload.get("created_by_doctor_id") or payload.get("doctor_id")
    doctor_id = int(doctor_id) if doctor_id not in (None, "", 0, "0") else None
    if doctor_id and not ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first():
        raise ValueError("الطبيب غير موجود")
    specialty_id = payload.get("specialty_id")
    specialty_id = int(specialty_id) if specialty_id not in (None, "", 0, "0") else None
    if specialty_id is None:
        dentistry = ClinicSpecialty.query.filter_by(tenant_id=tenant_id, code="dentistry").first()
        specialty_id = dentistry.id if dentistry else None
    source_visit_id = payload.get("source_visit_id")
    source_visit_id = int(source_visit_id) if source_visit_id not in (None, "", 0, "0") else None
    if source_visit_id:
        visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=source_visit_id, patient_id=patient.id).first()
        if not visit:
            raise ValueError("الزيارة المصدر غير موجودة")
        if doctor_id is None:
            doctor_id = visit.doctor_id
        if specialty_id is None:
            specialty_id = visit.specialty_id
    name = str(payload.get("name") or "خطة علاج الأسنان").strip() or "خطة علاج الأسنان"
    notes = str(payload.get("notes") or "").strip() or None
    status = str(payload.get("status") or "draft").strip().lower()
    if status not in PLAN_STATUSES:
        raise ValueError("حالة الخطة غير صالحة")
    row = ClinicDentalTreatmentPlan(
        tenant_id=tenant_id,
        patient_id=patient.id,
        created_by_doctor_id=doctor_id,
        specialty_id=specialty_id,
        source_visit_id=source_visit_id,
        name=name,
        notes=notes,
        status=status,
        started_at=datetime.utcnow() if status == "active" else None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(
        tenant_id, actor_id, "dental_treatment_plan", row.id, "create",
        f"إنشاء خطة علاج: {name}",
        meta={"patient_id": patient.id, "status": status},
    )
    return plan_detail(tenant_id, row.id, include_financial=True)


def create_treatment_option(
    tenant_id: int, plan_id: int, payload: dict, actor_id=None,
    *, include_financial: bool = True,
) -> dict:
    plan = _plan(tenant_id, plan_id)
    if plan.status in {"completed", "cancelled", "archived"}:
        raise ValueError("لا يمكن إضافة خيار إلى خطة مغلقة")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("عنوان خيار العلاج مطلوب")
    option_type = str(payload.get("option_type") or "alternative").strip().lower()
    if option_type not in OPTION_TYPES:
        raise ValueError("نوع خيار العلاج غير صالح")
    status = str(payload.get("status") or "proposed").strip().lower()
    if status not in OPTION_STATUSES:
        raise ValueError("حالة خيار العلاج غير صالحة")
    recommended = bool(payload.get("is_recommended")) or option_type == "recommended"
    if recommended:
        ClinicDentalTreatmentOption.query.filter_by(
            tenant_id=tenant_id, treatment_plan_id=plan.id, is_recommended=True
        ).update({"is_recommended": False}, synchronize_session=False)
    count = ClinicDentalTreatmentOption.query.filter_by(
        tenant_id=tenant_id, treatment_plan_id=plan.id
    ).count()
    row = ClinicDentalTreatmentOption(
        tenant_id=tenant_id,
        treatment_plan_id=plan.id,
        title=title,
        description=str(payload.get("description") or "").strip() or None,
        option_type="recommended" if recommended else option_type,
        is_recommended=recommended,
        status=status,
        sort_order=int(payload.get("sort_order") if payload.get("sort_order") not in (None, "") else count),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "dental_treatment_option", row.id, "create", f"إضافة خيار علاج: {title}")
    return plan_detail(tenant_id, plan.id, include_financial=include_financial)


def update_treatment_option(
    tenant_id: int, option_id: int, payload: dict, actor_id=None,
    *, include_financial: bool = True,
) -> dict:
    row = ClinicDentalTreatmentOption.query.filter_by(tenant_id=tenant_id, id=option_id).first()
    if not row:
        raise ValueError("خيار العلاج غير موجود")
    plan = _plan(tenant_id, row.treatment_plan_id)
    if "title" in payload:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("عنوان خيار العلاج مطلوب")
        row.title = title
    if "description" in payload:
        row.description = str(payload.get("description") or "").strip() or None
    if "option_type" in payload:
        option_type = str(payload.get("option_type") or "").strip().lower()
        if option_type not in OPTION_TYPES:
            raise ValueError("نوع خيار العلاج غير صالح")
        row.option_type = option_type
    if "status" in payload:
        status = str(payload.get("status") or "").strip().lower()
        if status not in OPTION_STATUSES:
            raise ValueError("حالة خيار العلاج غير صالحة")
        row.status = status
    if "sort_order" in payload:
        row.sort_order = int(payload.get("sort_order") or 0)
    if "is_recommended" in payload:
        recommended = bool(payload.get("is_recommended"))
        if recommended:
            ClinicDentalTreatmentOption.query.filter(
                ClinicDentalTreatmentOption.tenant_id == tenant_id,
                ClinicDentalTreatmentOption.treatment_plan_id == plan.id,
                ClinicDentalTreatmentOption.id != row.id,
            ).update({"is_recommended": False}, synchronize_session=False)
        row.is_recommended = recommended
        if recommended:
            row.option_type = "recommended"
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    _audit(tenant_id, actor_id, "dental_treatment_option", row.id, "update", f"تحديث خيار علاج #{row.id}")
    return plan_detail(tenant_id, plan.id, include_financial=include_financial)


def accept_plan(
    tenant_id: int, plan_id: int, payload: dict, actor_id=None,
    *, include_financial: bool = True,
) -> dict:
    plan = _plan(tenant_id, plan_id)
    if plan.status in {"completed", "cancelled", "archived"}:
        raise ValueError("لا يمكن قبول خطة مغلقة")
    option_id = int(payload.get("selected_option_id") or 0) or None
    option = None
    if option_id:
        option = ClinicDentalTreatmentOption.query.filter_by(
            tenant_id=tenant_id, id=option_id, treatment_plan_id=plan.id
        ).first()
        if not option or option.status == "cancelled":
            raise ValueError("خيار العلاج المحدد غير موجود")
        ClinicDentalTreatmentOption.query.filter(
            ClinicDentalTreatmentOption.tenant_id == tenant_id,
            ClinicDentalTreatmentOption.treatment_plan_id == plan.id,
            ClinicDentalTreatmentOption.id != option.id,
            ClinicDentalTreatmentOption.status == "proposed",
        ).update({"status": "declined"}, synchronize_session=False)
        option.status = "selected"
    signature_id = int(payload.get("signature_attachment_id") or 0) or None
    if signature_id:
        from modules.clinics.models import ClinicAttachment
        signature = ClinicAttachment.query.filter_by(
            tenant_id=tenant_id, id=signature_id, patient_id=plan.patient_id
        ).first()
        if not signature:
            raise ValueError("ملف التوقيع لا يخص مريض الخطة")
    method = str(payload.get("acceptance_method") or "verbal").strip().lower()
    if method not in {"verbal", "written", "digital", "signature"}:
        raise ValueError("طريقة الموافقة غير صالحة")
    plan.accepted_at = datetime.utcnow()
    plan.accepted_by = actor_id
    plan.selected_option_id = option.id if option else None
    plan.acceptance_method = method
    plan.signature_attachment_id = signature_id
    plan.status = "active" if payload.get("activate") is True else "accepted"
    if plan.status == "active":
        plan.started_at = plan.started_at or datetime.utcnow()
    plan.updated_by = actor_id
    plan.updated_at = datetime.utcnow()
    _audit(
        tenant_id, actor_id, "dental_treatment_plan", plan.id, "accept", "قبول خطة العلاج",
        meta={"selected_option_id": plan.selected_option_id, "acceptance_method": method},
    )
    return plan_detail(tenant_id, plan.id, include_financial=include_financial)


def update_plan(
    tenant_id: int,
    plan_id: int,
    payload: dict,
    actor_id=None,
    *,
    include_financial: bool = True,
) -> dict:
    plan = _plan(tenant_id, plan_id)
    old = {"status": plan.status, "name": plan.name, "notes": plan.notes or ""}
    if "name" in payload:
        plan.name = str(payload.get("name") or "").strip() or plan.name
    if "notes" in payload:
        plan.notes = str(payload.get("notes") or "").strip() or None
    if "estimated_discount" in payload:
        plan.estimated_discount = max(0, int(_money(payload.get("estimated_discount") or 0)))
    if "status" in payload:
        new_status = str(payload.get("status") or "").strip().lower()
        if new_status not in PLAN_STATUSES:
            raise ValueError("حالة الخطة غير صالحة")
        if new_status != plan.status and new_status not in PLAN_TRANSITIONS.get(plan.status, set()):
            raise ValueError(
                f"لا يمكن نقل الخطة من {PLAN_STATUS_AR.get(plan.status, plan.status)} "
                f"إلى {PLAN_STATUS_AR.get(new_status, new_status)}"
            )
        if new_status == "cancelled":
            reason = str(payload.get("cancellation_reason") or "").strip()
            if not reason:
                raise ValueError("سبب إلغاء الخطة مطلوب")
            plan.cancellation_reason = reason
        if new_status == "completed":
            items = _active_items(tenant_id, plan.id)
            open_items = [i for i in items if i.status not in {"completed", "cancelled"}]
            if open_items and not payload.get("confirm_incomplete"):
                raise ValueError("يوجد علاج غير مكتمل ضمن الخطة")
            if open_items:
                _audit(
                    tenant_id, actor_id, "dental_treatment_plan", plan.id, "complete_override",
                    "إكمال خطة مع بنود غير مكتملة",
                    meta={"open_item_ids": [i.id for i in open_items]},
                )
            plan.completed_at = datetime.utcnow()
        if new_status == "active" and not plan.started_at:
            plan.started_at = datetime.utcnow()
        if new_status == "archived":
            plan.archived_at = datetime.utcnow()
        plan.status = new_status
    plan.updated_by = actor_id
    plan.updated_at = datetime.utcnow()
    _audit(
        tenant_id, actor_id, "dental_treatment_plan", plan.id, "update",
        f"تحديث خطة علاج #{plan.id}",
        meta={
            "old": old,
            "new": {
                "status": plan.status,
                "name": plan.name,
                "notes": plan.notes or "",
                "cancellation_reason": getattr(plan, "cancellation_reason", None),
            },
        },
    )
    return plan_detail(tenant_id, plan.id, include_financial=include_financial)


def add_plan_item(
    tenant_id: int,
    plan_id: int,
    payload: dict,
    actor_id=None,
    *,
    include_financial: bool = True,
) -> dict:
    plan = _plan(tenant_id, plan_id)
    if plan.status in {"completed", "cancelled", "archived"}:
        raise ValueError("لا يمكن إضافة بنود لخطة مغلقة")
    procedure_id = payload.get("procedure_id")
    procedure_id = int(procedure_id) if procedure_id not in (None, "", 0, "0") else None
    procedure = None
    if procedure_id:
        procedure = ClinicProcedure.query.filter_by(tenant_id=tenant_id, id=procedure_id).first()
        if not procedure:
            raise ValueError("الإجراء غير موجود")
    from modules.clinics.models import ClinicService
    from modules.clinics.service_dental_completion import validate_service_tooth
    service_id = payload.get("service_id")
    service_id = int(service_id) if service_id not in (None, "", 0, "0") else None
    service = None
    if service_id:
        service = ClinicService.query.filter_by(tenant_id=tenant_id, id=service_id).first()
        if not service:
            raise ValueError("الخدمة غير موجودة")
        if not procedure_id and getattr(service, "default_procedure_id", None):
            procedure_id = int(service.default_procedure_id)
            procedure = ClinicProcedure.query.filter_by(
                tenant_id=tenant_id, id=procedure_id, active=True
            ).first()
            if not procedure:
                raise ValueError("الإجراء الافتراضي لخدمة الأسنان غير متاح")
        validate_service_tooth(service, payload.get("tooth_number") or (payload.get("tooth_numbers") or [None])[0])
        if service.requires_sessions:
            payload.setdefault("estimated_sessions", service.default_sessions or 1)
    whole_mouth = bool(payload.get("whole_mouth"))
    teeth = [] if whole_mouth else _normalize_teeth(payload.get("tooth_numbers"), payload.get("tooth_number"))
    if service and service.requires_tooth and not teeth and not whole_mouth:
        raise ValueError("هذه الخدمة تتطلب تحديد السن")
    if service and len(teeth) > 1 and not service.allows_multiple_teeth:
        raise ValueError("هذه الخدمة لا تسمح بتحديد أكثر من سن")
    if service and whole_mouth and service.requires_tooth and not service.allows_multiple_teeth:
        raise ValueError("هذه الخدمة مخصصة لسن واحد")
    tooth_number = teeth[0] if teeth else None
    title = str(payload.get("title") or (procedure.name if procedure else "") or (service.name if service else "")).strip()
    description = str(payload.get("description") or "").strip() or None
    if not title and not procedure_id:
        raise ValueError("حدد إجراءً أو عنواناً للبند")
    priority = str(payload.get("priority") or "normal").strip().lower()
    if priority not in PRIORITIES:
        raise ValueError("أولوية غير صالحة")
    status = str(payload.get("status") or "planned").strip().lower()
    if status not in ITEM_STATUSES:
        raise ValueError("حالة البند غير صالحة")
    estimated_sessions = max(1, int(payload.get("estimated_sessions") or 1))
    if "estimated_price" in payload and payload.get("estimated_price") not in (None, ""):
        estimated_price = int(_money(payload.get("estimated_price")))
    elif procedure is not None:
        estimated_price = int(procedure.price or 0)
    elif service is not None:
        estimated_price = int(service.price or 0)
    else:
        estimated_price = 0
    quantity = max(0.01, float(payload.get("quantity") or 1))
    discount = max(0, int(_money(payload.get("discount") or 0)))
    option_id = int(payload.get("treatment_option_id") or 0) or None
    if option_id and not ClinicDentalTreatmentOption.query.filter_by(
        tenant_id=tenant_id, id=option_id, treatment_plan_id=plan.id
    ).first():
        raise ValueError("خيار العلاج لا يخص هذه الخطة")
    existing = _active_items(tenant_id, plan.id)
    duplicate = next((item for item in existing if (
        item.status not in {"completed", "cancelled"}
        and (service_id and item.service_id == service_id or procedure_id and item.procedure_id == procedure_id or (not service_id and not procedure_id and item.title == title))
        and bool(getattr(item, "whole_mouth", False)) == whole_mouth
        and set(_item_teeth(item)) == set(teeth)
    )), None)
    if duplicate and not bool(payload.get("allow_duplicate")):
        target = "الفم كاملاً" if whole_mouth else ("، ".join(teeth) or "عام")
        raise ValueError(f"يوجد علاج فعال مطابق ({title}) لـ {target} ضمن الخطة الحالية")
    sort_order = int(payload.get("sort_order") if payload.get("sort_order") not in (None, "") else len(existing))
    row = ClinicDentalTreatmentPlanItem(
        tenant_id=tenant_id,
        plan_id=plan.id,
        treatment_option_id=option_id,
        tooth_number=tooth_number,
        tooth_numbers_json=json.dumps(teeth, ensure_ascii=False),
        whole_mouth=whole_mouth,
        procedure_id=procedure_id,
        service_id=service_id,
        title=title or (procedure.name if procedure else (service.name if service else "علاج")),
        description=description,
        priority=priority,
        status=status,
        estimated_sessions=estimated_sessions,
        estimated_price=estimated_price,
        quantity=quantity,
        discount=discount,
        sort_order=sort_order,
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    if plan.status == "draft" and payload.get("activate_plan"):
        plan.status = "active"
        plan.started_at = plan.started_at or datetime.utcnow()
    plan.updated_at = datetime.utcnow()
    plan.updated_by = actor_id
    _audit(
        tenant_id, actor_id, "dental_treatment_plan_item", row.id, "create",
        f"إضافة بند علاج: {row.title}",
        meta={"plan_id": plan.id, "tooth_numbers": teeth, "whole_mouth": whole_mouth, "procedure_id": procedure_id},
    )
    return plan_detail(tenant_id, plan.id, include_financial=include_financial)


def update_plan_item(
    tenant_id: int,
    item_id: int,
    payload: dict,
    actor_id=None,
    *,
    include_financial: bool = True,
) -> dict:
    row = _item(tenant_id, item_id)
    plan = _plan(tenant_id, row.plan_id)
    old = {
        "status": row.status,
        "priority": row.priority,
        "estimated_sessions": row.estimated_sessions,
        "estimated_price": row.estimated_price,
        "tooth_number": row.tooth_number,
        "notes": row.notes or "",
        "title": row.title,
    }
    if "tooth_number" in payload:
        teeth = _normalize_teeth(payload.get("tooth_numbers"), payload.get("tooth_number"))
        row.tooth_number = teeth[0] if teeth else None
        row.tooth_numbers_json = json.dumps(teeth, ensure_ascii=False)
    elif "tooth_numbers" in payload:
        teeth = _normalize_teeth(payload.get("tooth_numbers"))
        row.tooth_number = teeth[0] if teeth else None
        row.tooth_numbers_json = json.dumps(teeth, ensure_ascii=False)
    if "whole_mouth" in payload:
        row.whole_mouth = bool(payload.get("whole_mouth"))
        if row.whole_mouth:
            row.tooth_number = None
            row.tooth_numbers_json = "[]"
    if "procedure_id" in payload:
        procedure_id = payload.get("procedure_id")
        procedure_id = int(procedure_id) if procedure_id not in (None, "", 0, "0") else None
        if procedure_id and not ClinicProcedure.query.filter_by(tenant_id=tenant_id, id=procedure_id).first():
            raise ValueError("الإجراء غير موجود")
        row.procedure_id = procedure_id
    if "title" in payload:
        row.title = str(payload.get("title") or "").strip() or row.title
    if "description" in payload:
        row.description = str(payload.get("description") or "").strip() or None
    if "priority" in payload:
        priority = str(payload.get("priority") or "").strip().lower()
        if priority not in PRIORITIES:
            raise ValueError("أولوية غير صالحة")
        row.priority = priority
    if "status" in payload:
        status = str(payload.get("status") or "").strip().lower()
        if status not in ITEM_STATUSES:
            raise ValueError("حالة البند غير صالحة")
        row.status = status
        if status == "completed":
            row.completed_at = datetime.utcnow()
        elif status != "completed":
            row.completed_at = None
    if "estimated_sessions" in payload:
        row.estimated_sessions = max(1, int(payload.get("estimated_sessions") or 1))
    if "estimated_price" in payload and payload.get("estimated_price") not in (None, ""):
        row.estimated_price = int(_money(payload.get("estimated_price")))
    if "quantity" in payload:
        row.quantity = max(0.01, float(payload.get("quantity") or 1))
    if "discount" in payload:
        row.discount = max(0, int(_money(payload.get("discount") or 0)))
    if "treatment_option_id" in payload:
        option_id = int(payload.get("treatment_option_id") or 0) or None
        if option_id and not ClinicDentalTreatmentOption.query.filter_by(
            tenant_id=tenant_id, id=option_id, treatment_plan_id=plan.id
        ).first():
            raise ValueError("خيار العلاج لا يخص هذه الخطة")
        row.treatment_option_id = option_id
    if "sort_order" in payload and payload.get("sort_order") not in (None, ""):
        row.sort_order = int(payload.get("sort_order"))
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "").strip() or None
    if payload.get("archive") in (True, "true", 1, "1"):
        row.archived_at = datetime.utcnow()
        action = "archive"
    else:
        action = "update"
    if row.status == "completed":
        row.completed_by = actor_id
    if row.status == "cancelled":
        reason = str(payload.get("cancellation_reason") or "").strip()
        if not reason:
            raise ValueError("سبب إلغاء العلاج مطلوب")
        row.cancelled_by = actor_id
        row.cancellation_reason = reason
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    plan.updated_at = datetime.utcnow()
    plan.updated_by = actor_id
    _audit(
        tenant_id, actor_id, "dental_treatment_plan_item", row.id, action,
        f"{'أرشفة' if action == 'archive' else 'تحديث'} بند علاج #{row.id}",
        meta={"old": old, "new": {
            "status": row.status, "priority": row.priority,
            "estimated_sessions": row.estimated_sessions, "estimated_price": row.estimated_price,
            "tooth_number": row.tooth_number, "notes": row.notes or "", "title": row.title,
        }},
    )
    return plan_detail(tenant_id, plan.id, include_financial=include_financial)


def link_item_procedure(
    tenant_id: int,
    item_id: int,
    visit_procedure_id: int,
    actor_id=None,
    *,
    include_financial: bool = True,
) -> dict:
    row = _item(tenant_id, item_id)
    plan = _plan(tenant_id, row.plan_id)
    vp = ClinicVisitProcedure.query.filter_by(tenant_id=tenant_id, id=int(visit_procedure_id)).first()
    if not vp:
        raise ValueError("إجراء الزيارة غير موجود")
    visit = ClinicVisit.query.filter_by(tenant_id=tenant_id, id=vp.visit_id).first()
    if not visit or visit.patient_id != plan.patient_id:
        raise ValueError("الإجراء لا يخص مريض هذه الخطة")
    existing = ClinicDentalTreatmentPlanItemLink.query.filter_by(
        tenant_id=tenant_id,
        treatment_plan_item_id=row.id,
        visit_procedure_id=vp.id,
    ).first()
    if existing:
        return plan_detail(tenant_id, plan.id, include_financial=include_financial)
    # Prefer FOR UPDATE when available (PostgreSQL); SQLite ignores gracefully via plain get.
    locked = (
        ClinicDentalTreatmentPlanItem.query
        .filter_by(tenant_id=tenant_id, id=row.id)
        .with_for_update()
        .first()
    )
    if locked:
        row = locked
    # Re-check after lock
    existing = ClinicDentalTreatmentPlanItemLink.query.filter_by(
        tenant_id=tenant_id,
        treatment_plan_item_id=row.id,
        visit_procedure_id=vp.id,
    ).first()
    if existing:
        return plan_detail(tenant_id, plan.id, include_financial=include_financial)
    link = ClinicDentalTreatmentPlanItemLink(
        tenant_id=tenant_id,
        treatment_plan_item_id=row.id,
        visit_procedure_id=vp.id,
        linked_by=actor_id,
    )
    db.session.add(link)
    db.session.flush()
    if row.status == "planned":
        row.status = "in_progress"
        row.updated_by = actor_id
    plan.updated_at = datetime.utcnow()
    _audit(
        tenant_id, actor_id, "dental_treatment_plan_item_link", link.id, "link",
        f"ربط إجراء زيارة #{vp.id} ببند خطة #{row.id}",
        meta={"item_id": row.id, "visit_procedure_id": vp.id, "visit_id": vp.visit_id},
    )
    return plan_detail(tenant_id, plan.id, include_financial=include_financial)


def tooth_plan_context(tenant_id: int, patient_id: int, tooth_number: str, *, include_financial: bool = True) -> dict:
    tooth = validate_tooth_number(tooth_number)
    listed = list_patient_plans(tenant_id, patient_id, include_financial=include_financial)
    active = listed.get("active_plan")
    items = []
    if active:
        items = [i for i in active["items"] if i.get("tooth_number") == tooth]
    return {"tooth_number": tooth, "active_plan": active, "items": items}


def print_plan_payload(tenant_id: int, plan_id: int, *, include_financial: bool = True) -> dict:
    """Patient-facing print data — no cost/commission/audit internals."""
    from modules.clinics.service import get_or_create_settings

    detail = plan_detail(tenant_id, plan_id, include_financial=include_financial)
    plan = detail["plan"]
    patient = _patient(tenant_id, plan["patient_id"])
    settings = get_or_create_settings(tenant_id)
    payload = {
        "clinic_name": getattr(settings, "clinic_name", None) or "عيادة",
        "clinic_logo": getattr(settings, "public_logo_url", None),
        "patient_name": patient.full_name,
        "patient_file": patient.file_number,
        "doctor_name": plan["doctor_name"],
        "plan_name": plan["name"],
        "plan_date": (plan["created_at"] or "")[:10],
        "status_label_ar": plan["status_label_ar"],
        "accepted_at": plan.get("accepted_at"),
        "acceptance_method": plan.get("acceptance_method"),
        "selected_option_id": plan.get("selected_option_id"),
        "signature_attachment_id": plan.get("signature_attachment_id"),
        "include_financial": include_financial,
        "options": detail.get("options", []),
        "items": [
            {
                "tooth_number": "الفم كاملاً" if i.get("whole_mouth") else ("، ".join(i.get("tooth_numbers") or []) or "—"),
                "title": i["title"],
                "priority_label_ar": i["priority_label_ar"],
                "status_label_ar": i["status_label_ar"],
                "estimated_sessions": i["estimated_sessions"],
                "notes": i.get("notes") or "",
                **({"estimated_price": i.get("estimated_price", 0), "discount": i.get("discount", 0)} if include_financial else {}),
            }
            for i in detail["items"]
            if i["status"] != "cancelled"
        ],
    }
    if include_financial:
        payload.update({
            "estimated_subtotal": detail["summary"].get("estimated_subtotal", 0),
            "estimated_discount": detail["summary"].get("estimated_discount", 0) + detail["summary"].get("plan_discount", 0),
            "estimated_total": detail["summary"].get("estimated_total", 0),
            "actual_billed": detail["summary"].get("actual_billed", 0),
            "paid": detail["summary"].get("paid", 0),
            "remaining": detail["summary"].get("remaining", 0),
        })
    return payload
