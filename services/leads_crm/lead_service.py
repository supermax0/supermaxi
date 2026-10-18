"""Lead CRUD and listing service."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import or_, func
from sqlalchemy.orm import selectinload

from extensions import db
from models.core.leads.models import (
    BusinessActivity,
    BusinessLead,
    BusinessLeadPhone,
    LeadAuditLog,
    LeadDuplicateCandidate,
    LeadInteraction,
    LeadNote,
    LeadSourceRecord,
    LeadStatusConfig,
)
from services.leads_crm.audit_service import log_lead_action
from services.leads_crm.deduplication import detect_duplicate, find_phone_owner
from utils.leads_crm.name_normalize import normalize_business_name
from utils.leads_crm.phone_normalize import normalize_iraq_phone, phone_display, phone_lookup_key


from services.leads_crm.helpers import actor_superadmin_id as _actor_id


def lead_to_dict(lead: BusinessLead, include_timeline: bool = False) -> dict[str, Any]:
    primary = lead.primary_phone
    data = {
        "id": lead.id,
        "business_name": lead.business_name,
        "activity_id": lead.activity_id,
        "activity_name": lead.activity.name_ar if lead.activity else "",
        "owner_name": lead.owner_name,
        "governorate": lead.governorate,
        "city": lead.city,
        "district": lead.district,
        "area": lead.area,
        "full_address": lead.full_address,
        "latitude": lead.latitude,
        "longitude": lead.longitude,
        "website": lead.website,
        "instagram_url": lead.instagram_url,
        "facebook_url": lead.facebook_url,
        "tiktok_url": lead.tiktok_url,
        "status": lead.status,
        "priority": lead.priority,
        "assigned_to_superadmin_id": lead.assigned_to_superadmin_id,
        "last_contact_at": lead.last_contact_at.isoformat() if lead.last_contact_at else None,
        "next_follow_up_at": lead.next_follow_up_at.isoformat() if lead.next_follow_up_at else None,
        "trial_started_at": lead.trial_started_at.isoformat() if lead.trial_started_at else None,
        "trial_ends_at": lead.trial_ends_at.isoformat() if lead.trial_ends_at else None,
        "finora_company_id": lead.finora_company_id,
        "estimated_value": float(lead.estimated_value or 0),
        "monthly_subscription_value": float(lead.monthly_subscription_value or 0),
        "source_primary": lead.source_primary,
        "lead_score": lead.lead_score,
        "duplicate_status": lead.duplicate_status,
        "phones": [
            {
                "id": p.id,
                "phone_original": p.phone_original,
                "normalized_phone": p.normalized_phone,
                "display": phone_display(p.normalized_phone),
                "is_primary": p.is_primary,
                "is_whatsapp": p.is_whatsapp,
            }
            for p in lead.phones
        ],
        "primary_phone": phone_display(primary.normalized_phone) if primary else "",
        "sources": [{"id": s.id, "source_name": s.source_name, "source_detail": s.source_detail} for s in lead.sources],
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
    }
    if include_timeline:
        data["interactions"] = [
            {
                "id": i.id,
                "interaction_type": i.interaction_type,
                "result_status": i.result_status,
                "note": i.note,
                "contacted_at": i.contacted_at.isoformat() if i.contacted_at else None,
            }
            for i in lead.interactions.order_by(LeadInteraction.contacted_at.desc()).limit(50)
        ]
        data["notes"] = [
            {"id": n.id, "body": n.body, "created_at": n.created_at.isoformat()}
            for n in lead.notes.order_by(LeadNote.created_at.desc()).limit(50)
        ]
        data["audit_logs"] = [
            {
                "id": a.id,
                "action": a.action,
                "details_json": a.details_json,
                "created_at": a.created_at.isoformat(),
            }
            for a in LeadAuditLog.query.filter_by(lead_id=lead.id).order_by(LeadAuditLog.created_at.desc()).limit(100)
        ]
    return data


def list_leads(
    *,
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    activity_id: int | None = None,
    governorate: str | None = None,
    city: str | None = None,
    district: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assigned_to: int | None = None,
    source: str | None = None,
    duplicate_status: str | None = None,
    has_phone: bool | None = None,
    sort: str = "created_at",
    order: str = "desc",
) -> dict[str, Any]:
    q = BusinessLead.query.options(
        selectinload(BusinessLead.phones),
        selectinload(BusinessLead.activity),
    ).filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
    )

    if search:
        term = f"%{search.strip()}%"
        phone_key = phone_lookup_key(normalize_iraq_phone(search) or search)
        filters = [
            BusinessLead.business_name.ilike(term),
            BusinessLead.city.ilike(term),
            BusinessLead.governorate.ilike(term),
            BusinessLead.district.ilike(term),
            BusinessLead.area.ilike(term),
        ]
        if phone_key:
            filters.append(
                BusinessLead.id.in_(
                    db.session.query(BusinessLeadPhone.lead_id).filter(
                        or_(
                            BusinessLeadPhone.normalized_phone.ilike(f"%{phone_key}%"),
                            BusinessLeadPhone.phone_original.ilike(term),
                        )
                    )
                )
            )
        q = q.filter(or_(*filters))

    if activity_id:
        q = q.filter(BusinessLead.activity_id == activity_id)
    if governorate:
        q = q.filter(BusinessLead.governorate == governorate)
    if city:
        q = q.filter(BusinessLead.city.ilike(f"%{city}%"))
    if district:
        q = q.filter(BusinessLead.district.ilike(f"%{district}%"))
    if status:
        q = q.filter(BusinessLead.status == status)
    if priority:
        q = q.filter(BusinessLead.priority == priority)
    if assigned_to:
        q = q.filter(BusinessLead.assigned_to_superadmin_id == assigned_to)
    if source:
        q = q.filter(BusinessLead.source_primary == source)
    if duplicate_status:
        q = q.filter(BusinessLead.duplicate_status == duplicate_status)
    if has_phone is True:
        q = q.filter(BusinessLead.phones.any())
    elif has_phone is False:
        q = q.filter(~BusinessLead.phones.any())

    sort_col = getattr(BusinessLead, sort, BusinessLead.created_at)
    if order == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return {
        "leads": [lead_to_dict(l) for l in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
        "per_page": per_page,
    }


def create_lead(data: dict[str, Any], *, allow_possible_duplicate: bool = False) -> tuple[BusinessLead | None, dict[str, Any]]:
    business_name = (data.get("business_name") or "").strip()
    if not business_name:
        return None, {"error": "اسم الشركة مطلوب"}

    activity_id = data.get("activity_id")
    if not activity_id:
        return None, {"error": "النشاط مطلوب"}
    if not BusinessActivity.query.get(activity_id):
        return None, {"error": "النشاط غير موجود"}

    phones_raw = data.get("phones") or []
    if isinstance(phones_raw, str):
        phones_raw = [phones_raw]
    if data.get("phone"):
        phones_raw = [data["phone"]] + list(phones_raw)

    dup = detect_duplicate(
        business_name=business_name,
        phone=phones_raw[0] if phones_raw else None,
        governorate=data.get("governorate"),
        district=data.get("district"),
        full_address=data.get("full_address"),
    )
    if dup.level == "EXACT":
        existing = BusinessLead.query.get(dup.lead_id)
        return None, {
            "error": "duplicate_phone",
            "duplicate": dup,
            "existing_lead": lead_to_dict(existing) if existing else None,
        }
    if dup.level in ("STRONG", "POSSIBLE") and not allow_possible_duplicate:
        return None, {
            "error": "possible_duplicate",
            "duplicate": dup,
            "existing_lead": lead_to_dict(BusinessLead.query.get(dup.lead_id)) if dup.lead_id else None,
        }

    lead = BusinessLead(
        activity_id=activity_id,
        business_name=business_name,
        normalized_business_name=normalize_business_name(business_name),
        owner_name=data.get("owner_name"),
        governorate=data.get("governorate"),
        city=data.get("city"),
        district=data.get("district"),
        area=data.get("area"),
        full_address=data.get("full_address"),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        website=data.get("website"),
        instagram_url=data.get("instagram_url"),
        facebook_url=data.get("facebook_url"),
        tiktok_url=data.get("tiktok_url"),
        status=data.get("status") or "NEW",
        priority=data.get("priority") or "MEDIUM",
        assigned_to_superadmin_id=data.get("assigned_to_superadmin_id"),
        source_primary=data.get("source_primary"),
        preferred_contact_method=data.get("preferred_contact_method"),
        created_by=_actor_id(),
        updated_by=_actor_id(),
        duplicate_status=dup.level if dup.level != "NONE" else "NONE",
    )
    db.session.add(lead)
    db.session.flush()

    for idx, raw_phone in enumerate(phones_raw):
        norm = normalize_iraq_phone(raw_phone)
        if not norm:
            continue
        if find_phone_owner(norm):
            db.session.rollback()
            return None, {"error": "duplicate_phone", "phone": raw_phone}
        db.session.add(
            BusinessLeadPhone(
                lead_id=lead.id,
                phone_original=str(raw_phone).strip(),
                normalized_phone=norm,
                is_primary=(idx == 0),
                is_whatsapp=data.get("is_whatsapp", False),
            )
        )

    if data.get("source_primary"):
        db.session.add(
            LeadSourceRecord(lead_id=lead.id, source_name=data["source_primary"])
        )

    if dup.level in ("STRONG", "POSSIBLE") and dup.lead_id:
        db.session.add(
            LeadDuplicateCandidate(
                lead_id=dup.lead_id,
                candidate_lead_id=lead.id,
                duplicate_level=dup.level,
                duplicate_score=dup.score,
                duplicate_reason=dup.reason,
            )
        )

    log_lead_action(lead.id, "lead_created", _actor_id(), {"business_name": business_name})
    try:
        from services.leads_crm.scoring_service import refresh_lead_score
        refresh_lead_score(lead.id)
    except Exception:
        pass
    db.session.commit()
    return lead, {"ok": True}


def update_lead(lead_id: int, data: dict[str, Any]) -> tuple[BusinessLead | None, dict[str, Any]]:
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead:
        return None, {"error": "Lead غير موجود"}

    if "business_name" in data:
        lead.business_name = data["business_name"].strip()
        lead.normalized_business_name = normalize_business_name(lead.business_name)

    for field in (
        "owner_name", "governorate", "city", "district", "area", "full_address",
        "website", "instagram_url", "facebook_url", "tiktok_url",
        "status", "priority", "assigned_to_superadmin_id", "source_primary",
        "preferred_contact_method", "estimated_value", "monthly_subscription_value",
        "latitude", "longitude", "next_follow_up_at", "last_contact_at",
        "trial_started_at", "trial_ends_at", "finora_company_id",
    ):
        if field in data:
            setattr(lead, field, data[field])

    lead.updated_by = _actor_id()
    log_lead_action(lead.id, "lead_updated", _actor_id(), data)
    try:
        from services.leads_crm.scoring_service import refresh_lead_score
        refresh_lead_score(lead.id)
    except Exception:
        pass
    db.session.commit()
    return lead, {"ok": True}


def soft_delete_lead(lead_id: int) -> bool:
    lead = BusinessLead.query.get(lead_id)
    if not lead:
        return False
    lead.deleted_at = datetime.utcnow()
    lead.is_active = False
    log_lead_action(lead.id, "lead_deleted", _actor_id())
    db.session.commit()
    return True


def get_status_labels() -> dict[str, str]:
    rows = LeadStatusConfig.query.filter_by(is_active=True).order_by(LeadStatusConfig.sort_order).all()
    return {r.code: r.label_ar for r in rows}


def activity_stats() -> list[dict[str, Any]]:
    activities = BusinessActivity.query.filter_by(is_active=True).order_by(BusinessActivity.sort_order).all()
    result = []
    for act in activities:
        base = BusinessLead.query.filter(
            BusinessLead.activity_id == act.id,
            BusinessLead.deleted_at.is_(None),
            BusinessLead.merged_into_lead_id.is_(None),
        )
        total = base.count()
        with_phone = base.filter(BusinessLead.phones.any()).count()
        contacted = base.filter(BusinessLead.status.in_(["CONTACTED", "REPLIED", "INTERESTED", "TRIAL", "SUBSCRIBED"])).count()
        interested = base.filter(BusinessLead.status.in_(["INTERESTED", "DEMO_SCHEDULED", "TRIAL"])).count()
        trial = base.filter(BusinessLead.status == "TRIAL").count()
        subscribed = base.filter(BusinessLead.status == "SUBSCRIBED").count()
        result.append({
            "id": act.id,
            "name_ar": act.name_ar,
            "slug": act.slug,
            "icon": act.icon,
            "color": act.color,
            "total": total,
            "with_phone": with_phone,
            "contacted": contacted,
            "interested": interested,
            "trial": trial,
            "subscribed": subscribed,
        })
    return result
